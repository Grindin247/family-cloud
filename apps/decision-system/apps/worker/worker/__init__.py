from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

API_DIR = Path(os.environ.get("DECISION_API_APP_DIR", "/app_api"))
if API_DIR.exists():
    sys.path.insert(0, str(API_DIR))
