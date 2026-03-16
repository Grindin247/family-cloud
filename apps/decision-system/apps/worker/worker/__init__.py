from __future__ import annotations

import os
import sys
from pathlib import Path

API_DIR = Path(os.environ.get("DECISION_API_APP_DIR", "/app_api"))
if API_DIR.exists():
    sys.path.insert(0, str(API_DIR))
