#!/usr/bin/env python
"""Daily job: surface predictions whose timing window is now active (Part 17).

Push delivery is a stub (prints) until a provider (FCM/APNs/web-push) is chosen —
deferred per Part 18 until the core pipeline is stable.

Schedule with cron, e.g.:  30 1 * * *  python jobs/surface_predictions.py
"""
import os
import sys
from datetime import date, datetime

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project src/ root
sys.path.insert(0, SRC)

from db import store   # noqa: E402


def send_push_notification(user_id, message):
    # TODO: wire FCM/APNs/web-push. Stub prints for now.
    print(f"[PUSH → {user_id}] {message}")


def _window_active(pred, today_):
    """True if today falls in the window. Prefers structured start/end; tolerates strings."""
    timing = pred.get("timing")
    if isinstance(timing, dict) and timing.get("start") and timing.get("end"):
        try:
            s = datetime.strptime(timing["start"], "%Y-%m-%d").date()
            e = datetime.strptime(timing["end"], "%Y-%m-%d").date()
            return s <= today_ <= e
        except ValueError:
            return False
    return False        # plain-string windows can't be reliably parsed (bug #23)


def run(today_=None):
    today_ = today_ or date.today()
    store.init_db()

    surfaced = 0
    for user_id, domain in store.all_ledger_keys():
        ledger = store.get_ledger_from_db(user_id, domain)
        changed = False
        for pred in ledger.get("predictions_made", []):
            if not pred.get("surfaced") and _window_active(pred, today_):
                send_push_notification(
                    user_id,           # user_id lives on the ledger row, not the prediction record
                    f"StarSage identified this period as significant for your {pred['domain']}. "
                    f"You are now in it. Ask StarSage what to watch for.",
                )
                pred["surfaced"] = True
                changed = True
                surfaced += 1
        if changed:
            store.save_ledger(user_id, domain, ledger)
    print(f"Surfaced {surfaced} prediction(s) for {today_}")


if __name__ == "__main__":
    run()
