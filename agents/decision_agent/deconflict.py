from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class DeconflictAdvisor:
    def detect_collisions(self, target: date | None, roadmap_items: list[dict]) -> list[str]:
        if target is None:
            return []
        notes: list[str] = []
        window_start = target - timedelta(days=2)
        window_end = target + timedelta(days=2)
        for item in roadmap_items:
            due = item.get("due_date")
            if not due:
                continue
            try:
                due_d = date.fromisoformat(due)
            except Exception:
                continue
            if window_start <= due_d <= window_end:
                notes.append(f"Roadmap collision: '{item.get('title', 'item')}' due {due_d.isoformat()} is within +/-2 days.")
        return notes

