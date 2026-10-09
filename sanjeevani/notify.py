"""Alert delivery channels. Add your own by implementing `send(alert, patient) -> bool`."""
from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger("sanjeevani.notify")


class ConsoleNotifier:
    def send(self, alert: dict, patient: dict) -> bool:
        log.warning("ALERT [%s] for %s -> %s: %s", alert["kind"], patient["name"],
                    patient.get("caregiver_contact") or "no contact", alert["message"])
        return True


class WebhookNotifier:
    """POSTs JSON to any URL: n8n, Zapier, Make, a Twilio/WhatsApp bridge, Slack, ntfy..."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url, self.timeout = url, timeout

    def send(self, alert: dict, patient: dict) -> bool:
        body = json.dumps({
            "title": f"Sanjeevani: {alert['kind'].replace('_', ' ')} - {patient['name']}",
            "message": alert["message"],
            "kind": alert["kind"],
            "patient": patient["name"],
            "caregiver_name": patient.get("caregiver_name", ""),
            "caregiver_contact": patient.get("caregiver_contact", ""),
            "created_at": alert["created_at"],
        }).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 (operator-set URL)
                return 200 <= r.status < 300
        except Exception as exc:  # network errors must never crash the scheduler
            log.error("webhook delivery failed: %s", exc)
            return False


class CompositeNotifier:
    def __init__(self, *notifiers) -> None:
        self.notifiers = notifiers

    def send(self, alert: dict, patient: dict) -> bool:
        return all([n.send(alert, patient) for n in self.notifiers])


def build_notifier(settings) -> CompositeNotifier:
    chans = [ConsoleNotifier()]
    if settings.webhook_url:
        chans.append(WebhookNotifier(settings.webhook_url))
    return CompositeNotifier(*chans)
