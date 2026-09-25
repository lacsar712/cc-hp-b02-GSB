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


def fetch_zones(conn) -> dict:
    """每月当前温区 = 该月最新一条季节流水。"""
    rows = conn.execute(
        """SELECT DISTINCT ON (month) month, low_c, high_c
           FROM season_ledger ORDER BY month, id DESC"""
    ).fetchall()
    return {r["month"]: (float(r["low_c"]), float(r["high_c"])) for r in rows}


class LoginIn(BaseModel):
    username: str
    password: str


class StepIn(BaseModel):
    name: str
    temp_c: float
    minutes: float


class BatchIn(BaseModel):
    herb: str = Field(min_length=1, max_length=80)
    month: int | None = None
    steps: list[StepIn]


class ZoneIn(BaseModel):
    month: int
    low_c: float
    high_c: float


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
        raise HTTPException(status_code=403, detail="仅炮制员可写入记录")
    return user


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
        conn.execute(
            """CREATE TABLE IF NOT EXISTS season_ledger (
                id serial PRIMARY KEY,
                month int NOT NULL CHECK (month BETWEEN 1 AND 12),
                low_c double precision NOT NULL,
                high_c double precision NOT NULL,
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        # 季节流水只增不改：为空时铺十二个月默认温区 80~150
        zone_count = conn.execute("SELECT COUNT(*) AS n FROM season_ledger").fetchone()["n"]
        now = datetime.now(timezone.utc)
        if zone_count == 0:
            for month in range(1, 13):
                conn.execute(
                    """INSERT INTO season_ledger (month, low_c, high_c, created_by, created_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (month, DEFAULT_ZONE[0], DEFAULT_ZONE[1], "system", now),
                )
        count = conn.execute("SELECT COUNT(*) AS n FROM batches").fetchone()["n"]
        if count == 0:
            zones = fetch_zones(conn)
            samples = [
                ("甘草", 9, {"steps": [{"name": "清炒", "temp_c": 120, "minutes": 12}]}),
                ("黄芩", 9, {"steps": [{"name": "清炒", "temp_c": 40, "minutes": 12}]}),
            ]
            for herb, month, doc in samples:
                zone = zones.get(month, DEFAULT_ZONE)
                doc = {"month": month, "zone": {"low_c": zone[0], "high_c": zone[1]}, **doc}
                verdict, reason = judge(doc, zone)
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
    if not 1 <= body.month <= 12:
        raise HTTPException(status_code=400, detail="月份须在 1 到 12")
    with connect() as conn:
        zone = fetch_zones(conn).get(body.month, DEFAULT_ZONE)
        doc = {
            "month": body.month,
            "zone": {"low_c": zone[0], "high_c": zone[1]},
            "steps": [s.model_dump() for s in body.steps],
        }
        verdict, reason = judge(doc, zone)
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
    with connect() as conn:
        zones = fetch_zones(conn)
    return [
        {"month": m, "low_c": zones.get(m, DEFAULT_ZONE)[0], "high_c": zones.get(m, DEFAULT_ZONE)[1]}
        for m in range(1, 13)
    ]


@app.get("/api/season-ledger")
def list_season_ledger(_user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, month, low_c, high_c, created_by, created_at
               FROM season_ledger ORDER BY id DESC"""
        ).fetchall()
    return rows


@app.post("/api/season-zones", status_code=201)
def change_season_zone(body: ZoneIn, user: dict = Depends(require_writer)):
    if not 1 <= body.month <= 12:
        raise HTTPException(status_code=400, detail="月份须在 1 到 12")
    if not 0 <= body.low_c < body.high_c:
        raise HTTPException(status_code=400, detail="温区下限须小于上限")
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO season_ledger (month, low_c, high_c, created_by, created_at)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id, month, low_c, high_c, created_by, created_at""",
            (body.month, body.low_c, body.high_c, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row
