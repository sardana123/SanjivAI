from datetime import datetime

from sanjeevani.app import build_companion
from sanjeevani.config import Settings
from sanjeevani.notify import ConsoleNotifier

T0 = datetime(2026, 10, 8, 7, 0)


class RecordingNotifier:
    def __init__(self, ok: bool = True) -> None:
        self.sent, self.ok = [], ok

    def send(self, alert, patient) -> bool:
        self.sent.append((alert, patient))
        return self.ok


def make(notifier=None, **overrides):
    s = Settings(db_path=":memory:", **overrides)
    c = build_companion(s)
    c.escalation.notifier = notifier or ConsoleNotifier()
    p = c.create_patient("Ramesh", "en", "Anita", "+91-90000", now=T0)
    c.add_medication(p["id"], "Metformin", ["08:00", "20:00"], "500 mg", "after food", now=T0)
    c.add_medication(p["id"], "Aspirin", ["08:00"], "75 mg", now=T0)
    return c, p["id"]
