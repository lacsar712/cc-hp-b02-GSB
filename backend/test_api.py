"""服务端验收：用内存假库跑 FastAPI 全流程（本地无 docker/Postgres 时用）。

覆盖验收点：
- 写入必须声明月份，缺月拒写（400）
- 服务端按当月温区判定放行
- 改某月温区追加季节流水，早先流水行不被改写
- 新线只约束改线之后的提交，旧记录判定不回改
- 质检员只读各月温区与流水（写接口 403）

运行：python3 test_api.py
"""
import json

from fastapi.testclient import TestClient

import app as app_module


class FakeCursor:
    def __init__(self, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeConn:
    """按 app.py 实际使用的 SQL 形态分发到内存表，模拟 jsonb 往返。"""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        sql_one = " ".join(sql.split())
        db = self.db
        if sql_one.startswith("CREATE TABLE"):
            return FakeCursor()
        if "COUNT(*) AS n FROM season_ledger" in sql_one:
            return FakeCursor(row={"n": len(db["ledger"])})
        if "COUNT(*) AS n FROM batches" in sql_one:
            return FakeCursor(row={"n": len(db["batches"])})
        if "DISTINCT ON (month)" in sql_one:
            latest = {}
            for row in db["ledger"]:  # id 递增，后写入的覆盖同月旧行
                latest[row["month"]] = row
            rows = [{"month": m, "low_c": r["low_c"], "high_c": r["high_c"]} for m, r in sorted(latest.items())]
            return FakeCursor(rows=rows)
        if sql_one.startswith("INSERT INTO season_ledger"):
            row = {
                "id": len(db["ledger"]) + 1,
                "month": params[0],
                "low_c": params[1],
                "high_c": params[2],
                "created_by": params[3],
                "created_at": params[4],
            }
            db["ledger"].append(row)
            return FakeCursor(row=dict(row) if "RETURNING" in sql_one else None)
        if sql_one.startswith("INSERT INTO batches"):
            row = {
                "id": len(db["batches"]) + 1,
                "herb": params[0],
                "doc": json.loads(params[1]),
                "verdict": params[2],
                "reason": params[3],
                "created_by": params[4],
                "created_at": params[5],
            }
            db["batches"].append(row)
            if "RETURNING" in sql_one:
                back = {k: row[k] for k in ("id", "herb", "doc", "verdict", "reason", "created_by")}
                return FakeCursor(row=back)
            return FakeCursor()
        if "FROM batches ORDER BY id DESC" in sql_one:
            rows = [
                {k: r[k] for k in ("id", "herb", "doc", "verdict", "reason", "created_by")}
                for r in reversed(db["batches"])
            ]
            return FakeCursor(rows=rows)
        if "FROM season_ledger ORDER BY id DESC" in sql_one:
            return FakeCursor(rows=[dict(r) for r in reversed(db["ledger"])])
        raise AssertionError(f"未识别的 SQL: {sql_one}")

    def commit(self):
        pass


def fry(temp, minutes=12):
    return [{"name": "清炒", "temp_c": temp, "minutes": minutes}]


def main():
    db = {"batches": [], "ledger": []}
    app_module.connect = lambda: FakeConn(db)
    client = TestClient(app_module.app)
    with client:  # 触发 startup：建表 + 十二月默认温区 + 样本批次
        w_login = client.post("/api/auth/login", json={"username": "processor", "password": "herb123456"})
        assert w_login.status_code == 200, w_login.text
        w = {"Authorization": f"Bearer {w_login.json()['access_token']}"}
        c_login = client.post("/api/auth/login", json={"username": "checker", "password": "check123456"})
        assert c_login.status_code == 200, c_login.text
        r = {"Authorization": f"Bearer {c_login.json()['access_token']}"}

        # 种子：十二月温区各 80~150，流水 12 行
        zones = client.get("/api/season-zones", headers=w).json()
        assert len(zones) == 12, zones
        assert all(z["low_c"] == 80 and z["high_c"] == 150 for z in zones), zones
        assert [z["month"] for z in zones] == list(range(1, 13))
        ledger0 = client.get("/api/season-ledger", headers=w).json()
        assert len(ledger0) == 12

        # 缺月拒写
        res = client.post("/api/batches", headers=w, json={"herb": "白芍", "steps": fry(90)})
        assert res.status_code == 400 and "月份" in res.json()["detail"], res.text
        # 月份越界拒写
        res = client.post("/api/batches", headers=w, json={"herb": "白芍", "month": 13, "steps": fry(90)})
        assert res.status_code == 400, res.text

        # 改线前：3 月 90℃/12分钟 放行
        res = client.post("/api/batches", headers=w, json={"herb": "白芍", "month": 3, "steps": fry(90)})
        assert res.status_code == 201 and res.json()["verdict"] == "放行", res.text

        # 3 月温区抬到 100~150：追加一条季节流水
        res = client.post("/api/season-zones", headers=w, json={"month": 3, "low_c": 100, "high_c": 150})
        assert res.status_code == 201, res.text
        ledger1 = client.get("/api/season-ledger", headers=w).json()
        assert len(ledger1) == 13, ledger1
        newest = ledger1[0]
        assert newest["month"] == 3 and newest["low_c"] == 100 and newest["high_c"] == 150
        # 早先流水行不被改写
        before = {row["id"]: row for row in ledger0}
        after = {row["id"]: row for row in ledger1 if row["id"] in before}
        assert before == after

        # 新线约束之后提交：3 月 90℃/12分钟 → 未放行
        res = client.post("/api/batches", headers=w, json={"herb": "白芍", "month": 3, "steps": fry(90)})
        assert res.status_code == 201 and res.json()["verdict"] == "未放行", res.text
        # 声明另一月（4 月仍 80~150）：90℃/12分钟 → 放行
        res = client.post("/api/batches", headers=w, json={"herb": "白芍", "month": 4, "steps": fry(90)})
        assert res.status_code == 201 and res.json()["verdict"] == "放行", res.text

        # 改线前写入的旧记录判定不回改
        batches = client.get("/api/batches", headers=w).json()
        old = next(b for b in batches if b["doc"]["month"] == 3 and b["doc"]["zone"]["low_c"] == 80)
        assert old["verdict"] == "放行", old

        # 质检员只读各月温区与流水
        assert client.get("/api/season-zones", headers=r).status_code == 200
        assert client.get("/api/season-ledger", headers=r).status_code == 200
        assert client.post("/api/season-zones", headers=r, json={"month": 5, "low_c": 90, "high_c": 160}).status_code == 403
        assert client.post("/api/batches", headers=r, json={"herb": "白芍", "month": 5, "steps": fry(90)}).status_code == 403

        # 温区下限须小于上限
        assert client.post("/api/season-zones", headers=w, json={"month": 5, "low_c": 160, "high_c": 150}).status_code == 400

        # 未登录不可读
        assert client.get("/api/season-zones").status_code == 401

        # 种子批次：甘草放行、黄芩未放行，doc 带月份与当时温区
        seeds = {b["herb"]: b for b in batches if b["herb"] in ("甘草", "黄芩")}
        assert seeds["甘草"]["verdict"] == "放行" and seeds["黄芩"]["verdict"] == "未放行"
        assert seeds["甘草"]["doc"]["month"] == 9 and seeds["甘草"]["doc"]["zone"] == {"low_c": 80.0, "high_c": 150.0}

    print("API 验收全部通过")


if __name__ == "__main__":
    main()
