from __future__ import annotations

import logging

from .tracing import correlation_id_var


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.correlation_id = correlation_id_var.get() or "-"
        return True

