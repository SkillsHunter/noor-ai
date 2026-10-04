"""Step 6: deliver the SMS to Noor's basic phone, and read her replies.

Gateways share `send(to, text) -> dict`. Pick one with NOOR_SMS:
  console        - prints the SMS (demo, tests)
  twilio         - Twilio Programmable Messaging REST API
  africastalking - Africa's Talking SMS API (use username "sandbox" to test)
For Indonesia or elsewhere, a local SMS aggregator usually costs less; add a
class with the same `send` method.
"""
import requests

from .config import Settings


class ConsoleGateway:
    def __init__(self):
        self.outbox = []

    def send(self, to: str, text: str) -> dict:
        self.outbox.append({"to": to, "text": text})
        print(f"\n--- SMS to {to} ---\n{text}\n-------------------")
        return {"status": "printed", "to": to}


class TwilioGateway:
    def __init__(self, sid, token, sender):
        self.sid, self.token, self.sender = sid, token, sender

    def send(self, to: str, text: str) -> dict:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
            data={"To": to, "From": self.sender, "Body": text},
            auth=(self.sid, self.token), timeout=20)
        r.raise_for_status()
        return {"status": "sent", "id": r.json().get("sid")}


class AfricasTalkingGateway:
    def __init__(self, username, api_key, sender=""):
        self.username, self.api_key, self.sender = username, api_key, sender
        host = "api.sandbox.africastalking.com" if username == "sandbox" else "api.africastalking.com"
        self.url = f"https://{host}/version1/messaging"

    def send(self, to: str, text: str) -> dict:
        data = {"username": self.username, "to": to, "message": text}
        if self.sender:
            data["from"] = self.sender
        r = requests.post(self.url, data=data, timeout=20,
                          headers={"apiKey": self.api_key, "Accept": "application/json"})
        r.raise_for_status()
        return {"status": "sent", "response": r.json()}


def gateway_from(settings: Settings):
    if settings.sms_backend == "twilio":
        return TwilioGateway(settings.twilio_sid, settings.twilio_token, settings.twilio_from)
    if settings.sms_backend == "africastalking":
        return AfricasTalkingGateway(settings.at_username, settings.at_api_key, settings.at_sender)
    return ConsoleGateway()


REPLY_CODES = {"1": "seen", "2": "call_requested", "3": "full_text"}


def parse_reply(text: str) -> str:
    """Noor replies with a digit; anything else is kept as a note for the team."""
    t = (text or "").strip()
    return REPLY_CODES.get(t[:1], "note") if t else "empty"


def reply_feedback_no(text: str):
    """'3 12' -> 12 (which feedback Noor means); '3' -> None (the latest)."""
    parts = (text or "").split()
    if len(parts) > 1 and parts[1].lstrip("#").isdigit():
        return int(parts[1].lstrip("#"))
    return None
