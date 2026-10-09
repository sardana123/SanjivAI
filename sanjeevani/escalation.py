"""Escalation agent: watches overdue doses and makes sure a human finds out."""
from __future__ import annotations

from datetime import timedelta

from .timeutil import fmt, parse, spoken_time

MAX_DELIVERY_ATTEMPTS = 5


class EscalationAgent:
    def __init__(self, db, settings, notifier) -> None:
        self.db, self.settings, self.notifier = db, settings, notifier

    def raise_alert(self, patient_id: int, kind: str, message: str, now, medication_id: int | None = None) -> int:
        return self.db.execute(
            "INSERT INTO alerts(patient_id, medication_id, kind, message, created_at) VALUES (?,?,?,?,?)",
            (patient_id, medication_id, kind, message, fmt(now)),
        )

    def scan(self, now) -> int:
        """Level 1: late dose alert. Level 2: dose recorded as missed. Idempotent per dose."""
        s = self.settings
        pending = self.db.query(
            "SELECT d.*, m.name AS med_name, m.dose, p.name AS patient_name "
            "FROM dose_events d JOIN medications m ON m.id = d.medication_id "
            "JOIN patients p ON p.id = d.patient_id "
            "WHERE d.status = 'pending' AND d.scheduled_for <= ?",
            (fmt(now - timedelta(minutes=s.alert_after_min)),),
        )
        raised = 0
        for d in pending:
            sched = parse(d["scheduled_for"])
            overdue = int((now - sched).total_seconds() // 60)
            label = f"{d['med_name']} {d['dose']}".strip()
            if overdue >= s.miss_after_min:
                self.db.execute("UPDATE dose_events SET status='missed' WHERE id=?", (d["id"],))
                if d["alerted"] < 2:
                    self.raise_alert(
                        d["patient_id"], "missed_dose",
                        f"{d['patient_name']} missed {label} scheduled for {spoken_time(sched)} "
                        f"({overdue} min overdue). Please check in.", now, d["medication_id"])
                    raised += 1
                self.db.execute("UPDATE dose_events SET alerted=2 WHERE id=?", (d["id"],))
            elif d["alerted"] < 1:
                self.raise_alert(
                    d["patient_id"], "late_dose",
                    f"{d['patient_name']} has not taken {label} scheduled for {spoken_time(sched)} "
                    f"({overdue} min overdue).", now, d["medication_id"])
                self.db.execute("UPDATE dose_events SET alerted=1 WHERE id=?", (d["id"],))
                raised += 1
        return raised

    def deliver_pending(self) -> int:
        sent = 0
        rows = self.db.query(
            "SELECT a.*, p.name AS p_name FROM alerts a JOIN patients p ON p.id = a.patient_id "
            "WHERE a.delivered = 0 AND a.attempts < ?", (MAX_DELIVERY_ATTEMPTS,))
        for a in rows:
            patient = self.db.one("SELECT * FROM patients WHERE id=?", (a["patient_id"],))
            ok = False
            try:
                ok = self.notifier.send(a, patient)
            finally:
                self.db.execute("UPDATE alerts SET attempts = attempts + 1, delivered = ? WHERE id=?",
                                (1 if ok else 0, a["id"]))
            sent += 1 if ok else 0
        return sent
