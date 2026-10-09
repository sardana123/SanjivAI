"""Deterministic, offline intent parsing for English, Hindi and Hinglish.

The safety-critical path (what counts as "I took it", "skip", "emergency") is
intentionally rule-based so it is predictable, testable and works with no
internet. An LLM is only ever used afterwards, to soften the *wording* of
routine replies (see llm.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EMERGENCY = (
    "chest pain", "can't breathe", "cannot breathe", "cant breathe", "difficulty breathing",
    "short of breath", "fainted", "passed out", "unconscious", "severe bleeding",
    "heart attack", "stroke", "seizure", "overdose", "took too many", "taken too many",
    "suicid", "सीने में दर्द", "सीने मे दर्द", "सांस नहीं", "साँस नहीं", "सांस लेने में",
    "बेहोश", "चक्कर आ रहा", "दौरा", "ज्यादा दवा", "ज़्यादा दवा", "seene mein dard",
    "sine me dard", "saans nahi", "behosh",
)
SKIP = (
    "skip", "don't want", "dont want", "won't take", "wont take", "will not take",
    "not going to take", "refuse", "नहीं लूंगा", "नहीं लूँगा", "नहीं लूंगी", "नहीं लूँगी",
    "मन नहीं", "नहीं खाऊंगा", "नहीं खाऊँगी", "nahi lunga", "nahi lungi",
    "nahi khaunga", "nahi khaungi", "man nahi",
)
TAKEN = (
    "taken", "took", "have had", "had it", "had my", "finished", "done", "swallowed",
    "kha li", "kha liya", "le li", "le liya", "li hai", "khali", "khayi", "khai hai",
    "ले ली", "ले लिया", "खा ली", "खा लिया", "ले चुका", "ले चुकी", "ली है", "खा चुका",
    "खा चुकी", "खाई है",
)
SNOOZE = (
    "later", "remind me", "in a while", "not yet", "baad mein", "baad me", "thodi der",
    "abhi nahi", "nahi li", "nahi liya", "nahi khai", "बाद में", "बाद मे", "थोड़ी देर",
    "अभी नहीं", "नहीं ली", "नहीं लिया", "नहीं खाई",
)
NEXT = (
    "what's next", "whats next", "what is next", "next medicine", "next dose", "next tablet",
    "which medicine", "what medicine", "what should i take", "when is my", "kaun si",
    "kaunsi", "konsi", "dawai kab", "dawa kab", "davai kab", "कौन सी", "कौनसी",
    "अगली दवा", "अगली दवाई", "दवा कब", "दवाई कब", "कब लेनी",
)
NEGATION = re.compile(
    r"\b(not|no|never|haven't|havent|hasn't|hasnt|didn't|didnt|don't|dont|won't|wont|"
    r"nahi|nahin|nhi|mat)\b|नहीं|नही|नहि|मत"
)

ADD_RE = re.compile(
    r"^(?:please\s+)?(?:add|new medicine|new medication)\s+"
    r"(?P<name>[a-z][a-z0-9\- ]{1,40}?)"
    r"(?:\s+(?P<dose>\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?|tablets?|tabs?)))?"
    r"\s+(?:at|@|every)\s+(?P<times>.+)$"
)
TIME_WORDS = {
    "morning": "08:00", "noon": "12:00", "afternoon": "14:00",
    "evening": "18:00", "night": "21:00", "bedtime": "22:00",
}
TIME_RE = re.compile(r"(?<![\d:.])(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?(?![\d:])")


@dataclass
class Intent:
    name: str  # emergency|taken|skip|snooze|next|add_med|unknown
    med_hint: str | None = None
    minutes: int | None = None
    payload: dict = field(default_factory=dict)


def normalize(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", t).strip()


def _has(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def parse_times(text: str) -> list[str]:
    """'8 am and 8:30 pm', 'morning and night' -> ['08:00', '20:30'] (sorted, unique)."""
    out: set[str] = set()
    t = normalize(text)
    for word, hhmm in TIME_WORDS.items():
        if re.search(rf"\b{word}\b", t):
            out.add(hhmm)
    for m in TIME_RE.finditer(t):
        hour, minute, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if minute > 59:
            continue
        if ap:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if ap.startswith("p") else 0)
        elif hour > 23:
            continue
        out.add(f"{hour:02d}:{minute:02d}")
    return sorted(out)


def find_med(text: str, med_names: list[str]) -> str | None:
    hits = [n for n in med_names if n and n.lower() in text]
    return max(hits, key=len) if hits else None


def parse(text: str, med_names: list[str] | None = None) -> Intent:
    t = normalize(text)
    hint = find_med(t, med_names or [])
    if not t:
        return Intent("unknown")
    if _has(t, EMERGENCY):
        return Intent("emergency", hint)
    if _has(t, SKIP):
        return Intent("skip", hint)
    if _has(t, TAKEN):
        if NEGATION.search(t):  # "I have not taken it yet"
            return Intent("snooze", hint, _minutes(t))
        return Intent("taken", hint)
    if _has(t, SNOOZE):
        return Intent("snooze", hint, _minutes(t))
    if _has(t, NEXT):
        return Intent("next", hint)
    m = ADD_RE.match(t)
    if m:
        times = parse_times(m.group("times"))
        if times:
            return Intent(
                "add_med",
                payload={
                    "name": m.group("name").strip().title(),
                    "dose": (m.group("dose") or "").strip(),
                    "times": times,
                },
            )
    return Intent("unknown", hint)


def _minutes(t: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:min|mins|minute|minutes|मिनट)", t)
    return max(5, min(120, int(m.group(1)))) if m else None
