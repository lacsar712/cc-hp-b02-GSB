import json
import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from rules import DEFAULT_ZONE, judge

SECRET = os.environ.get("JWT_SECRET", "herb-process-dev-secret")
DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54393/herb")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "processor": {"role": "writer", "password_hash": pwd.hash("herb123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class StepIn(BaseModel):
    name: str
    temp_c: float
    minutes: float


class BatchIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    month: int | None = Field(default=None, ge=1, le=12)
    steps: list[StepIn]


class ZoneIn(BaseModel):
    month: int = Field(ge=1, le=12)
    low_c: float = Field(gt=0, lt=500)
    high_c: float = Field(gt=0, lt=500)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅炮制员可写入")
    return user


def current_zone(conn, month: int) -> dict:
    """取该月当前生效的温区（季节流水中最新一行）。"""
    row = conn.execute(
        """SELECT month, low_c, high_c, changed_by, changed_at
           FROM season_zone_log
           WHERE month = %s
           ORDER BY id DESC
           LIMIT 1""",
        (month,),
    ).fetchone()
    if row is None:
        return {"month": month, **DEFAULT_ZONE}
    return row


app = FastAPI(title="饮片炮制记录台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batches (
                id serial PRIMARY KEY,
                herb text NOT NULL,
                doc jsonb NOT NULL,
                verdict text NOT NULL,
                reason text NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        # 季节流水：只追加，不改写。每月当前温区取该月最新一行。
        conn.execute(
            """CREATE TABLE IF NOT EXISTS season_zone_log (
                id serial PRIMARY KEY,
                month int NOT NULL CHECK (month BETWEEN 1 AND 12),
                low_c double precision NOT NULL,
                high_c double precision NOT NULL,
                changed_by text NOT NULL,
                changed_at timestamptz NOT NULL
            )"""
        )
        now = datetime.now(timezone.utc)
        zone_count = conn.execute("SELECT COUNT(*) AS n FROM season_zone_log").fetchone()["n"]
        if zone_count == 0:
            for month in range(1, 13):
                conn.execute(
                    """INSERT INTO season_zone_log (month, low_c, high_c, changed_by, changed_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (month, DEFAULT_ZONE["low_c"], DEFAULT_ZONE["high_c"], "系统", now),
                )
        batch_count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if batch_count == 0:
            samples = [
                ("甘草", {"month": 6, "steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", {"month": 6, "steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
            ]
            for herb, doc in samples:
                verdict, reason = judge(doc, current_zone(conn, doc["month"]))
                conn.execute(
                    """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
                       VALUES (%s, %s::jsonb, %s, %s, %s, %s)""",
                    (herb, json.dumps(doc, ensure_ascii=False), verdict, reason, "processor", now),
                )
        conn.commit()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "herb-process-record"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/batches")
def list_batches(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute("SELECT id, herb, doc, verdict, reason, created_by FROM batches ORDER BY id DESC").fetchall()
    return rows


@app.post("/api/batches", status_code=201)
def create_batch(body: BatchIn, user: dict = Depends(require_writer)):
    if body.month is None:
        raise HTTPException(status_code=400, detail="写入必须声明月份")
    doc = {"month": body.month, "steps": [s.model_dump() for s in body.steps]}
    with connect() as conn:
        verdict, reason = judge(doc, current_zone(conn, body.month))
        row = conn.execute(
            """INSERT INTO batches (herb, doc, verdict, reason, created_by, created_at)
               VALUES (%s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id, herb, doc, verdict, reason, created_by""",
            (body.herb.strip(), json.dumps(doc, ensure_ascii=False), verdict, reason, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


@app.get("/api/season-zones")
def list_season_zones(_user: dict = Depends(current_user)):
    """十二月当前温区表：每月取季节流水最新一行。"""
    with connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT ON (month) month, low_c, high_c, changed_by, changed_at
               FROM season_zone_log
               ORDER BY month, id DESC"""
        ).fetchall()
    by_month = {r["month"]: r for r in rows}
    return [by_month.get(m, {"month": m, **DEFAULT_ZONE}) for m in range(1, 13)]


@app.post("/api/season-zones", status_code=201)
def change_season_zone(body: ZoneIn, user: dict = Depends(require_writer)):
    """改某月温区：向季节流水追加一行，早先流水行不改写，仅约束之后的提交。"""
    if body.low_c >= body.high_c:
        raise HTTPException(status_code=400, detail="温度下限必须低于上限")
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO season_zone_log (month, low_c, high_c, changed_by, changed_at)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id, month, low_c, high_c, changed_by, changed_at""",
            (body.month, body.low_c, body.high_c, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


@app.get("/api/season-zones/log")
def season_zone_log(_user: dict = Depends(current_user)):
    """季节流水：全部改线记录，新的在前，只读不改写。"""
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, month, low_c, high_c, changed_by, changed_at
               FROM season_zone_log
               ORDER BY id DESC
               LIMIT 200"""
        ).fetchall()
    return rows
