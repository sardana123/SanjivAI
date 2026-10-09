"""Dependency wiring."""
from __future__ import annotations

from .companion import Companion
from .config import Settings
from .db import Database
from .escalation import EscalationAgent
from .llm import LLMClient
from .notify import build_notifier


def build_companion(settings: Settings) -> Companion:
    db = Database(settings.db_path)
    escalation = EscalationAgent(db, settings, build_notifier(settings))
    llm = LLMClient(settings.anthropic_api_key, settings.anthropic_model)
    return Companion(db, settings, escalation, llm)
