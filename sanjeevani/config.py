"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: str = "sanjeevani.db"
    host: str = "127.0.0.1"
    port: int = 8000
    # A pending dose triggers a caregiver alert this many minutes after its time...
    alert_after_min: int = 45
    # ...and is recorded as missed (second-level alert) after this many.
    miss_after_min: int = 180
    # A dose counts as "due" this many minutes before its scheduled time.
    due_lead_min: int = 30
    default_min_gap_hours: float = 3.0
    emergency_number: str = "112"
    webhook_url: str = ""
    api_token: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    tick_seconds: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            db_path=e("SANJEEVANI_DB", cls.db_path),
            host=e("SANJEEVANI_HOST", cls.host),
            port=_int("SANJEEVANI_PORT", cls.port),
            alert_after_min=_int("SANJEEVANI_ALERT_AFTER_MIN", cls.alert_after_min),
            miss_after_min=_int("SANJEEVANI_MISS_AFTER_MIN", cls.miss_after_min),
            due_lead_min=_int("SANJEEVANI_DUE_LEAD_MIN", cls.due_lead_min),
            emergency_number=e("SANJEEVANI_EMERGENCY_NUMBER", cls.emergency_number),
            webhook_url=e("SANJEEVANI_WEBHOOK_URL", ""),
            api_token=e("SANJEEVANI_TOKEN", ""),
            anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
            anthropic_model=e("SANJEEVANI_MODEL", cls.anthropic_model),
            tick_seconds=_int("SANJEEVANI_TICK_SECONDS", cls.tick_seconds),
        )
