DEFAULT_ZONE = {"low_c": 80.0, "high_c": 150.0}


def judge(doc: dict, zone: dict | None = None) -> tuple[str, str]:
    """按当月温区判定清炒工序是否放行。zone 为 {"low_c", "high_c"}，缺省用 80–150。"""
    steps = doc.get("steps") or []
    fry = next((s for s in steps if s.get("name") == "清炒"), None)
    if fry is None:
        return "未放行", "缺少清炒工序"
    low = float((zone or DEFAULT_ZONE).get("low_c", DEFAULT_ZONE["low_c"]))
    high = float((zone or DEFAULT_ZONE).get("high_c", DEFAULT_ZONE["high_c"]))
    temp = float(fry.get("temp_c", 0))
    minutes = float(fry.get("minutes", 0))
    if not low <= temp <= high:
        return "未放行", f"清炒温度不在当月温区（{low:g}–{high:g}℃）内"
    if not 5 <= minutes <= 30:
        return "未放行", "清炒时长不在范围内"
    return "放行", "清炒工序符合炮制要求"
