#!/usr/bin/env python
"""Daily job: recompute the `transits` block for every stored chart.

Schedule with cron, e.g.:  0 1 * * *  python jobs/recalc_transits.py
"""
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from astro.transits import current_transits   # noqa: E402
from db import store                            # noqa: E402


def run(target=None):
    target = target or datetime.utcnow()
    store.init_db()
    with sqlite3.connect(store.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT user_id FROM user_charts").fetchall()
    updated = 0
    for r in rows:
        chart = store.get_user_chart(r["user_id"])
        if not chart:
            continue
        chart["transits"] = current_transits(
            target, chart["lagna"]["sign"], chart["planets"]["Moon"]["sign"]
        )
        store.save_chart(r["user_id"], chart)
        updated += 1
    print(f"Recalculated transits for {updated} chart(s) as of {target.date()}")


if __name__ == "__main__":
    run()
