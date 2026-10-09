"""Insights agent: turns raw dose history into adherence numbers a caregiver can act on."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from .timeutil import fmt, parse


def adherence(db, patient_id: int, now, days: int = 14, miss_after_min: int = 180) -> dict:
    days = max(1, min(days, 90))
    first_day = now.date() - timedelta(days=days - 1)
    rows = db.query(
        "SELECT d.scheduled_for, d.status, m.name FROM dose_events d "
        "JOIN medications m ON m.id = d.medication_id "
        "WHERE d.patient_id=? AND d.scheduled_for >= ? AND d.scheduled_for <= ? ORDER BY d.scheduled_for",
        (patient_id, fmt(parse(f"{first_day.isoformat()}T00:00")), fmt(now)),
    )
    daily = {(first_day + timedelta(days=i)).isoformat(): Counter() for i in range(days)}
    by_med: dict[str, Counter] = {}
    missed_slots: Counter = Counter()
    for r in rows:
        sched = parse(r["scheduled_for"])
        status = r["status"]
        if status == "pending":
            if now - sched < timedelta(minutes=miss_after_min):
                continue  # still within its window: not yet judged
            status = "missed"
        daily[sched.date().isoformat()][status] += 1
        by_med.setdefault(r["name"], Counter())[status] += 1
        if status in ("missed", "skipped"):
            missed_slots[sched.strftime("%H:%M")] += 1

    def rate(c: Counter) -> float | None:
        total = c["taken"] + c["missed"] + c["skipped"]
        return round(c["taken"] / total, 3) if total else None

    series = [{"date": d, "taken": c["taken"], "missed": c["missed"], "skipped": c["skipped"], "rate": rate(c)}
              for d, c in daily.items()]
    overall = Counter()
    for c in daily.values():
        overall.update(c)
    streak = 0
    for item in reversed(series):
        if item["rate"] is None:
            if item["date"] == now.date().isoformat():
                continue  # today has nothing judged yet
            break
        if item["rate"] < 1.0:
            break
        streak += 1
    worst = missed_slots.most_common(1)
    result = {
        "days": days,
        "overall_rate": rate(overall),
        "taken": overall["taken"], "missed": overall["missed"], "skipped": overall["skipped"],
        "streak_days": streak,
        "daily": series,
        "by_medication": {n: {"rate": rate(c), "taken": c["taken"], "missed": c["missed"] + c["skipped"]}
                          for n, c in by_med.items()},
        "worst_slot": worst[0][0] if worst else None,
    }
    result["summary"] = _summary(result)
    return result


def _summary(r: dict) -> str:
    if r["overall_rate"] is None:
        return "Not enough history yet. Insights appear after the first scheduled doses."
    pct = round(r["overall_rate"] * 100)
    parts = [f"{pct}% of doses were taken over the last {r['days']} days "
             f"({r['taken']} taken, {r['missed'] + r['skipped']} missed or skipped)."]
    if r["streak_days"] >= 2:
        parts.append(f"Current perfect streak: {r['streak_days']} days.")
    if r["worst_slot"] and r["missed"] + r["skipped"] >= 2:
        parts.append(f"Most missed time slot: {r['worst_slot']}. Consider moving it or adding a caregiver check-in.")
    weakest = [(n, v["rate"]) for n, v in r["by_medication"].items() if v["rate"] is not None and v["rate"] < 0.8]
    if weakest:
        n, v = min(weakest, key=lambda x: x[1])
        parts.append(f"{n} needs attention ({round(v * 100)}% taken).")
    if pct < 70:
        parts.append("Adherence is low - worth a call to the patient or their doctor.")
    return " ".join(parts)
