#!/usr/bin/env python3
"""Regenerate data/dashboard.html from the sent-jobs history without
running the full scout pipeline. Open the file directly in a browser.

    python scripts/dashboard.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scout import DASHBOARD_PATH, generate_dashboard, load_sent  # noqa: E402

if __name__ == "__main__":
    sent = load_sent()
    generate_dashboard(sent)
    print(f"{len(sent)} jobs · open file://{DASHBOARD_PATH}")
