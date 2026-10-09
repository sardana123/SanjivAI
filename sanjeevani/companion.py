"""Orchestrator: the Scheduler + Voice agents. Owns all dose state transitions."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import insights, nlu
from .escalation import EscalationAgent
from .responses import join_names, lang_of, t
from .timeutil import day_bounds, fmt, now_local, parse, spoken_time

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
WARM_INTENTS = {"taken", "next", "snooze"}  # routine replies the LLM may soften


class Companion:
    def __init__(self, db, settings, escalation: EscalationAgent, llm=None) -> None:
        self.db, self.settings, self.escalation, self.llm = db, settings, escalation, llm

    # ------------------------------------------------------------------ patients
    def create_patient(self, name: str, language: str = "en", caregiver_name: str = "",
                       caregiver_contact: str = "", now: datetime | None = None) -> dict:
        name = (name or "").strip()
        if not name or len(name) > 80:
            raise ValueError("name is required (max 80 characters)")
        pid = self.db.execute(
            "INSERT INTO patients(name, language, caregiver_name, caregiver_contact, created_at) VALUES (?,?,?,?,?)",
            (name, lang_of(language), caregiver_name.strip()[:80], caregiver_contact.strip()[:120],
             fmt(now or now_local())))
        return self.get_patient(pid)

    def get_patient(self, pid: int) -> dict:
        p = self.db.one("SELECT * FROM patients WHERE id=?", (pid,))
        if not p:
            raise LookupError("patient not found")
        return p

    def list_patients(self) -> list[dict]:
        return self.db.query("SELECT * FROM patients ORDER BY id")

    def update_patient(self, pid: int, **fields) -> dict:
        self.get_patient(pid)
        allowed = {"name", "language", "caregiver_name", "caregiver_contact"}
        for k, v in fields.items():
            if k in allowed and isinstance(v, str):
                v = lang_of(v) if k == "language" else v.strip()[:120]
                if k == "name" and not v:
                    raise ValueError("name cannot be empty")
                self.db.execute(f"UPDATE patients SET {k}=? WHERE id=?", (v, pid))
        return self.get_patient(pid)

    # --------------------------------------------------------------- medications
    def add_medication(self, pid: int, name: str, times: list[str], dose: str = "",
                       instructions: str = "", min_gap_hours: float | None = None,
                       now: datetime | None = None) -> dict:
        self.get_patient(pid)
        name = (name or "").strip()
        if not name or len(name) > 80:
            raise ValueError("medicine name is required (max 80 characters)")
        times = sorted({str(x).strip() for x in (times or [])})
        if not times or len(times) > 12 or not all(HHMM.match(x) for x in times):
            raise ValueError("times must be 1-12 values in 24h HH:MM format")
        if min_gap_hours is None:
            min_gap_hours = self._default_gap(times)
        if not 0 <= float(min_gap_hours) <= 24:
            raise ValueError("min_gap_hours must be between 0 and 24")
        mid = self.db.execute(
            "INSERT INTO medications(patient_id, name, dose, instructions, times, min_gap_hours, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (pid, name, dose.strip()[:40], instructions.strip()[:200], ",".join(times),
             float(min_gap_hours), fmt(now or now_local())))
        self.ensure_events(pid, (now or now_local()).date())
        return self._med(mid)

    def _default_gap(self, times: list[str]) -> float:
        """Half the shortest interval between doses (incl. overnight wrap), capped by the global default."""
        mins = sorted(int(x[:2]) * 60 + int(x[3:]) for x in times)
        if len(mins) == 1:
            return self.settings.default_min_gap_hours
        gaps = [b - a for a, b in zip(mins, mins[1:])] + [mins[0] + 1440 - mins[-1]]
        return round(min(self.settings.default_min_gap_hours, min(gaps) / 120), 2)

    def _med(self, mid: int) -> dict:
        m = self.db.one("SELECT * FROM medications WHERE id=?", (mid,))
        if not m:
            raise LookupError("medication not found")
        m["times"] = m["times"].split(",")
        return m

    def list_medications(self, pid: int, active_only: bool = True) -> list[dict]:
        rows = self.db.query("SELECT * FROM medications WHERE patient_id=?" +
                             (" AND active=1" if active_only else "") + " ORDER BY id", (pid,))
        for m in rows:
            m["times"] = m["times"].split(",")
        return rows

    def remove_medication(self, mid: int, now: datetime | None = None) -> None:
        self._med(mid)
        self.db.execute("UPDATE medications SET active=0 WHERE id=?", (mid,))
        self.db.execute("DELETE FROM dose_events WHERE medication_id=? AND status='pending' AND scheduled_for>=?",
                        (mid, fmt(now or now_local())))

    # ------------------------------------------------------------------ schedule
    def ensure_events(self, pid: int, day: date) -> None:
        for m in self.list_medications(pid):
            created = parse(m["created_at"])
            for hhmm in m["times"]:
                sched = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
                if sched < created:
                    continue  # never invent doses from before the medicine was added
                self.db.execute(
                    "INSERT OR IGNORE INTO dose_events(patient_id, medication_id, scheduled_for) VALUES (?,?,?)",
                    (pid, m["id"], fmt(sched)))

    _EVENT_SQL = ("SELECT d.*, m.name AS med_name, m.dose, m.instructions, m.min_gap_hours "
                  "FROM dose_events d JOIN medications m ON m.id = d.medication_id ")

    def _event(self, eid: int) -> dict:
        ev = self.db.one(self._EVENT_SQL + "WHERE d.id=?", (eid,))
        if not ev:
            raise LookupError("dose not found")
        return ev

    def _decorate(self, ev: dict, now: datetime) -> dict:
        sched = parse(ev["scheduled_for"])
        snoozed = bool(ev["snooze_until"] and parse(ev["snooze_until"]) > now)
        ev["time_label"] = spoken_time(sched)
        ev["due"] = (ev["status"] == "pending" and sched <= now + timedelta(minutes=self.settings.due_lead_min)
                     and not snoozed)
        ev["overdue_min"] = max(0, int((now - sched).total_seconds() // 60)) if ev["status"] == "pending" else 0
        return ev

    def today(self, pid: int, now: datetime | None = None) -> dict:
        now = now or now_local()
        patient = self.get_patient(pid)
        self.ensure_events(pid, now.date())
        lo, hi = day_bounds(now.date())
        doses = [self._decorate(e, now) for e in
                 self.db.query(self._EVENT_SQL + "WHERE d.patient_id=? AND d.scheduled_for>=? AND d.scheduled_for<? "
                               "ORDER BY d.scheduled_for, d.id", (pid, lo, hi))]
        due = [d for d in doses if d["due"]]
        nxt = self.next_dose(pid, now)
        return {"patient": patient, "now": fmt(now), "doses": doses, "due_count": len(due),
                "reminder": self.reminder_text(patient, due) if due else "",
                "next": self._decorate(nxt, now) if nxt else None}

    def due_doses(self, pid: int, now: datetime, include_snoozed: bool = False) -> list[dict]:
        """Pending doses inside their window. Snoozed ones are hidden from reminders but still
        actionable when the patient speaks ("I took it")."""
        self.ensure_events(pid, now.date())
        rows = self.db.query(self._EVENT_SQL + "WHERE d.patient_id=? AND d.status='pending' AND d.scheduled_for<=? "
                             "ORDER BY d.scheduled_for, d.id",
                             (pid, fmt(now + timedelta(minutes=self.settings.due_lead_min))))
        decorated = [self._decorate(r, now) for r in rows]
        return decorated if include_snoozed else [d for d in decorated if d["due"]]

    def next_dose(self, pid: int, now: datetime) -> dict | None:
        for day in (now.date(), now.date() + timedelta(days=1)):
            self.ensure_events(pid, day)
        return self.db.one(self._EVENT_SQL + "WHERE d.patient_id=? AND d.status='pending' AND d.scheduled_for>=? "
                           "ORDER BY d.scheduled_for, d.id LIMIT 1",
                           (pid, fmt(now - timedelta(minutes=self.settings.miss_after_min))))

    def reminder_text(self, patient: dict, due: list[dict]) -> str:
        lang = patient["language"]
        meds = join_names(lang, [f"{d['med_name']} {d['dose']}".strip() for d in due])
        notes = sorted({d["instructions"].strip() for d in due if d["instructions"].strip()})
        instr = " ".join(n[0].upper() + n[1:] + ("" if n.endswith((".", "।")) else ".") for n in notes)
        return t(lang, "reminder", name=patient["name"], meds=meds, instr=(" " + instr) if instr else "")

    # --------------------------------------------------------------- transitions
    def take(self, eid: int, now: datetime | None = None, force: bool = False) -> dict:
        now = now or now_local()
        ev = self._event(eid)
        if ev["status"] == "taken":
            return {"ok": True, "already": True, "dose": ev}
        sched = parse(ev["scheduled_for"])
        last = self.db.one("SELECT responded_at FROM dose_events WHERE medication_id=? AND status='taken' "
                           "AND id<>? ORDER BY responded_at DESC LIMIT 1", (ev["medication_id"], eid))
        if not force:
            if last and now - parse(last["responded_at"]) < timedelta(hours=ev["min_gap_hours"]):
                return {"ok": False, "reason": "too_soon", "last_taken": last["responded_at"], "dose": ev}
            if sched > now + timedelta(minutes=2 * self.settings.due_lead_min):
                return {"ok": False, "reason": "too_early", "dose": ev}
        late = now > sched + timedelta(minutes=self.settings.alert_after_min)
        self.db.execute("UPDATE dose_events SET status='taken', responded_at=?, note=?, snooze_until=NULL WHERE id=?",
                        (fmt(now), "late" if late else "", eid))
        return {"ok": True, "dose": self._event(eid)}

    def skip(self, eid: int, now: datetime | None = None) -> dict:
        now = now or now_local()
        ev = self._event(eid)
        if ev["status"] == "taken":
            return {"ok": False, "reason": "already_taken", "dose": ev}
        self.db.execute("UPDATE dose_events SET status='skipped', responded_at=? WHERE id=?", (fmt(now), eid))
        patient = self.get_patient(ev["patient_id"])
        self.escalation.raise_alert(
            ev["patient_id"], "skipped_dose",
            f"{patient['name']} chose to skip {ev['med_name']} {ev['dose']} "
            f"scheduled for {spoken_time(parse(ev['scheduled_for']))}.".replace("  ", " "),
            now, ev["medication_id"])
        return {"ok": True, "dose": self._event(eid)}

    def snooze(self, eid: int, minutes: int = 15, now: datetime | None = None) -> dict:
        now = now or now_local()
        minutes = max(5, min(120, int(minutes)))
        self._event(eid)
        self.db.execute("UPDATE dose_events SET snooze_until=? WHERE id=? AND status='pending'",
                        (fmt(now + timedelta(minutes=minutes)), eid))
        return {"ok": True, "minutes": minutes, "dose": self._event(eid)}

    def tick(self, now: datetime | None = None) -> dict:
        """Background heartbeat: materialise schedules, escalate, deliver alerts."""
        now = now or now_local()
        for p in self.list_patients():
            for day in (now.date(), now.date() + timedelta(days=1)):
                self.ensure_events(p["id"], day)
        raised = self.escalation.scan(now)
        delivered = self.escalation.deliver_pending()
        return {"raised": raised, "delivered": delivered}

    # -------------------------------------------------------------------- voice
    def handle_utterance(self, pid: int, text: str, now: datetime | None = None, lang: str | None = None) -> dict:
        now = now or now_local()
        patient = self.get_patient(pid)
        lang = lang_of(lang or patient["language"])
        meds = self.list_medications(pid)
        names = [m["name"] for m in meds]
        intent = nlu.parse(text, names)
        caregiver = patient["caregiver_name"] or t(lang, "caregiver_default")
        who = patient["name"]
        due = self.due_doses(pid, now, include_snoozed=True)
        if intent.med_hint:
            due = [d for d in due if d["med_name"].lower() == intent.med_hint.lower()]
        actions: list[dict] = []

        if intent.name == "emergency":
            self.escalation.raise_alert(pid, "emergency", f"{who} said: \"{text.strip()[:200]}\". Call them now.", now)
            reply = t(lang, "emergency", name=who, number=self.settings.emergency_number, caregiver=caregiver)
            actions.append({"type": "alert", "kind": "emergency"})

        elif intent.name == "taken":
            done: list[str] = []
            blocked: dict | None = None
            for d in due:
                r = self.take(d["id"], now)
                if r["ok"]:
                    done.append(f"{d['med_name']} {d['dose']}".strip())
                    actions.append({"type": "taken", "dose_id": d["id"]})
                elif r["reason"] == "too_soon" and not blocked:
                    blocked = r
            if not due and intent.med_hint:
                blocked = self._recent_dose_guard(pid, intent.med_hint, now)
            if blocked:
                last = parse(blocked["last_taken"])
                reply = t(lang, "too_soon", name=who, med=blocked["dose"]["med_name"],
                          time=spoken_time(last, lang), caregiver=caregiver)
                actions.append({"type": "guard", "reason": "too_soon"})
                intent.name = "guard"
            elif done:
                reply = t(lang, "taken", name=who, meds=join_names(lang, done), next=self._next_suffix(pid, now, lang))
            else:
                reply = t(lang, "nothing_due", next=self._next_suffix(pid, now, lang))

        elif intent.name == "skip":
            if due:
                for d in due:
                    self.skip(d["id"], now)
                    actions.append({"type": "skipped", "dose_id": d["id"]})
                reply = t(lang, "skip", meds=join_names(lang, [d["med_name"] for d in due]), caregiver=caregiver)
            else:
                reply = t(lang, "nothing_due", next=self._next_suffix(pid, now, lang))

        elif intent.name == "snooze":
            minutes = intent.minutes or 15
            for d in due:
                self.snooze(d["id"], minutes, now)
                actions.append({"type": "snoozed", "dose_id": d["id"]})
            reply = t(lang, "snooze", name=who, minutes=minutes)

        elif intent.name == "next":
            nxt = self.next_dose(pid, now)
            reply = (t(lang, "next", med=nxt["med_name"], dose=nxt["dose"],
                       time=spoken_time(parse(nxt["scheduled_for"]), lang)).replace("  ", " ")
                     if nxt else t(lang, "nothing_next", name=who))

        elif intent.name == "add_med":
            p = intent.payload
            m = self.add_medication(pid, p["name"], p["times"], p["dose"], now=now)
            reply = t(lang, "med_added", med=m["name"], dose=m["dose"],
                      times=join_names(lang, [spoken_time(datetime.strptime(x, "%H:%M"), lang) for x in m["times"]])
                      ).replace("  ", " ")
            actions.append({"type": "medication_added", "medication_id": m["id"]})

        else:
            reply = t(lang, "unknown")

        if self.llm and self.llm.enabled and intent.name in WARM_INTENTS:
            reply = self.llm.warm(reply, tuple(names))
        return {"intent": intent.name, "reply": reply, "actions": actions, "lang": lang}

    def _recent_dose_guard(self, pid: int, med_name: str, now: datetime) -> dict | None:
        """'I took Metformin' with nothing due: block if it was taken very recently (accidental double dose)."""
        row = self.db.one(
            "SELECT d.responded_at AS last_taken, m.name AS med_name, m.min_gap_hours FROM dose_events d "
            "JOIN medications m ON m.id = d.medication_id WHERE d.patient_id=? AND lower(m.name)=lower(?) "
            "AND d.status='taken' ORDER BY d.responded_at DESC LIMIT 1", (pid, med_name))
        if row and now - parse(row["last_taken"]) < timedelta(hours=row["min_gap_hours"]):
            return {"ok": False, "reason": "too_soon", "last_taken": row["last_taken"], "dose": row}
        return None

    def _next_suffix(self, pid: int, now: datetime, lang: str) -> str:
        nxt = self.next_dose(pid, now)
        if not nxt:
            return ""
        return t(lang, "next_suffix", med=nxt["med_name"], time=spoken_time(parse(nxt["scheduled_for"]), lang))

    # ------------------------------------------------------------------ insights
    def insights(self, pid: int, days: int = 14, now: datetime | None = None) -> dict:
        self.get_patient(pid)
        return insights.adherence(self.db, pid, now or now_local(), days, self.settings.miss_after_min)

    def alerts(self, pid: int, limit: int = 50) -> list[dict]:
        self.get_patient(pid)
        return self.db.query("SELECT * FROM alerts WHERE patient_id=? ORDER BY id DESC LIMIT ?", (pid, limit))

    def ack_alert(self, aid: int) -> None:
        if not self.db.one("SELECT id FROM alerts WHERE id=?", (aid,)):
            raise LookupError("alert not found")
        self.db.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (aid,))
