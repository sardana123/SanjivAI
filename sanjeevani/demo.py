"""Seeds a realistic demo patient with two weeks of history (some misses) for screenshots and demos."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from .companion import Companion
from .timeutil import fmt


def seed(c: Companion, now: datetime, days: int = 14, seed_value: int = 7) -> int:
    rnd = random.Random(seed_value)
    start = (now - timedelta(days=days)).replace(hour=0, minute=1)
    p = c.create_patient("Ramesh", "en", "Anita (daughter)", "+91-90000-00000", now=start)
    c.add_medication(p["id"], "Metformin", ["08:00", "20:00"], "500 mg", "take after food", now=start)
    c.add_medication(p["id"], "Amlodipine", ["09:00"], "5 mg", "for blood pressure", now=start)
    c.add_medication(p["id"], "Vitamin D", ["13:00"], "60000 IU", "once a day with lunch", now=start)
    for i in range(days, -1, -1):
        day = (now - timedelta(days=i)).date()
        c.ensure_events(p["id"], day)
    rows = c.db.query("SELECT id, scheduled_for FROM dose_events WHERE patient_id=? AND scheduled_for<?",
                      (p["id"], fmt(now - timedelta(minutes=c.settings.miss_after_min))))
    for r in rows:
        sched = datetime.strptime(r["scheduled_for"], "%Y-%m-%dT%H:%M")
        evening = sched.hour >= 19
        roll = rnd.random()
        miss_p = 0.28 if evening else 0.08  # evening doses are forgotten more often: a realistic pattern
        if roll < miss_p:
            c.db.execute("UPDATE dose_events SET status='missed', alerted=2 WHERE id=?", (r["id"],))
        else:
            when = sched + timedelta(minutes=rnd.randint(0, 40))
            c.db.execute("UPDATE dose_events SET status='taken', responded_at=? WHERE id=?", (fmt(when), r["id"]))
    return p["id"]
