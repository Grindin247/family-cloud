from .builder import (
    build_event,
    make_privacy,
    new_correlation_id,
    new_event_id,
    validate_event_envelope,
)
from .payloads import diff_field_paths, snippet_fields, text_snippet
from .subjects import canonical_subjects, subject_for_domain


def emit_canonical_event(*args, **kwargs):
    from .emitter import emit_canonical_event as _emit_canonical_event

    return _emit_canonical_event(*args, **kwargs)


def publish_event(*args, **kwargs):
    from .publisher import publish_event as _publish_event

    return _publish_event(*args, **kwargs)

__all__ = [
    "build_event",
    "emit_canonical_event",
    "make_privacy",
    "new_correlation_id",
    "new_event_id",
    "publish_event",
    "canonical_subjects",
    "diff_field_paths",
    "snippet_fields",
    "subject_for_domain",
    "text_snippet",
    "validate_event_envelope",
]
