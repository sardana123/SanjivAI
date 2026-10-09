"""Optional Claude integration - used ONLY to make routine replies warmer.

Safety-critical decisions (dose recording, double-dose guard, emergencies, escalation)
never pass through an LLM. A rewrite is accepted only if every number, time and
medicine name from the original survives; otherwise the deterministic text is used.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request

log = logging.getLogger("sanjeevani.llm")
SYSTEM = (
    "You rewrite short replies of a medication-reminder voice assistant for an elderly user. "
    "Keep the exact meaning. Never change, add or remove any medicine name, dose, number or time. "
    "Never give medical advice. Be warm and brief (at most 2 short sentences). "
    "Reply in the same language as the input. Output only the rewritten reply."
)


def facts_preserved(original: str, rewritten: str, names: tuple[str, ...] = ()) -> bool:
    """Every number, clock time, AM/PM marker and medicine name must survive the rewrite."""
    tokens = re.findall(r"\d+(?::\d+)?|\b(?:am|pm)\b", original.lower())
    tokens += [n.lower() for n in names if n and n.lower() in original.lower()]
    low = rewritten.lower()
    return all(tok in low for tok in tokens)


class LLMClient:
    def __init__(self, api_key: str = "", model: str = "claude-sonnet-5-5", timeout: float = 6.0) -> None:
        self.api_key, self.model, self.timeout = api_key, model, timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _complete(self, text: str) -> str:
        body = json.dumps({
            "model": self.model, "max_tokens": 200, "system": SYSTEM,
            "messages": [{"role": "user", "content": text}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"content-type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
            data = json.load(r)
        return "".join(b.get("text", "") for b in data.get("content", [])).strip()

    def warm(self, text: str, names: tuple[str, ...] = ()) -> str:
        if not self.enabled:
            return text
        try:
            out = self._complete(text)
        except Exception as exc:
            log.warning("LLM unavailable, using template reply: %s", exc)
            return text
        return out if out and facts_preserved(text, out, names) else text
