"""季节温区判定验收（rules.judge 层，无外部依赖）。

场景：某月温区抬到 100~150 后，声明该月递交 90℃/12分钟 应未放行；
另一月仍为 80~150 则同样 90℃/12分钟 可通过；时长规则不变。
"""
from rules import DEFAULT_ZONE, judge


def fry(temp, minutes=12):
    return {"steps": [{"name": "清炒", "temp_c": temp, "minutes": minutes}]}


def main():
    # 默认温区 80~150
    assert DEFAULT_ZONE == (80.0, 150.0)

    # 3 月改线到 100~150（新线只约束改线之后的提交）
    zones = {m: DEFAULT_ZONE for m in range(1, 13)}
    zones[3] = (100.0, 150.0)

    # 声明 3 月，90℃/12分钟 → 未放行
    verdict, reason = judge(fry(90), zones[3])
    assert verdict == "未放行", (verdict, reason)
    assert "100" in reason and "150" in reason, reason

    # 声明 4 月（仍 80~150），90℃/12分钟 → 放行
    verdict, reason = judge(fry(90), zones[4])
    assert verdict == "放行", (verdict, reason)

    # 边界：3 月 100℃ 与 150℃ 均放行；99.9 与 150.1 未放行
    assert judge(fry(100), zones[3])[0] == "放行"
    assert judge(fry(150), zones[3])[0] == "放行"
    assert judge(fry(99.9), zones[3])[0] == "未放行"
    assert judge(fry(150.1), zones[3])[0] == "未放行"

    # 时长规则不受温区影响
    assert judge(fry(120, 4), zones[4])[0] == "未放行"
    assert judge(fry(120, 31), zones[4])[0] == "未放行"
    assert judge(fry(120, 30), zones[4])[0] == "放行"

    # 缺清炒工序
    assert judge({"steps": []}, zones[4])[0] == "未放行"

    # 不传温区时回退默认 80~150（兼容旧调用）
    assert judge(fry(90))[0] == "放行"
    assert judge(fry(40))[0] == "未放行"

    print("judge 验收全部通过")


if __name__ == "__main__":
    main()
