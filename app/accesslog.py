"""Mask secrets in uvicorn's access log.

From the platform template: bibliotekarien-platform/edge/templates/accesslog.py
(see LOGGNING.md there). Only _PATTERNS is app-specific.

Members' secret link tokens are in the path (GET /svara/<token>). uvicorn logs
every request's full path to stdout, which Alloy ships to Loki. The access log
used to be turned off for that reason (--no-access-log); it is on again — it
is needed for incidents and puts the request line next to a traceback — and
the token is replaced before the line is formatted.
"""

import logging
import re

# (pattern, replacement) — the only part that differs between apps.
# Tokens are 43 chars (secrets.token_urlsafe(32), app/auth/token.py); {32,}
# leaves /svara/roadmap, /svara/vaxla and /svara/<funktion_id>/svar readable.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(/svara/)[A-Za-z0-9_-]{32,}"), r"\1_token_"),
]


def mask(value: str) -> str:
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


class MaskSecretsFilter(logging.Filter):
    """Rewrites request paths in uvicorn.access records.

    The access line is formatted lazily ('%s - "%s %s HTTP/%s" %d', path is
    args[2]), so the filter rewrites record.args. It walks every arg rather than
    trusting args[2], so a change in uvicorn's tuple keeps the protection; only
    strings that look like a request path ("/…") are touched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple):
            return True
        masked = tuple(
            mask(a) if isinstance(a, str) and a.startswith("/") else a for a in args
        )
        if masked != args:
            record.args = masked
        return True


def install() -> None:
    """Idempotent: the app may be created more than once per process (tests)."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, MaskSecretsFilter) for f in logger.filters):
        logger.addFilter(MaskSecretsFilter())
