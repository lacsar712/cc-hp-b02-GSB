DEFAULT_ZONE = (80.0, 150.0)


def judge(doc: dict, zone: tuple[float, float] | None = None) -> tuple[str, str]:
    low, high = zone or DEFAULT_ZONE
    steps = doc.get("steps") or []
    fry = next((s for s in steps if s.get("name") == "清炒"), None)
    if fry is None:
        return "未放行", "缺少清炒工序"
    temp = float(fry.get("temp_c", 0))
    minutes = float(fry.get("minutes", 0))
    if not low <= temp <= high:
        return "未放行", f"清炒温度不在当月温区 {low:g}~{high:g} 内"
    if not 5 <= minutes <= 30:
        return "未放行", "清炒时长不在范围内"
    return "放行", "清炒工序符合当月季节温区"
