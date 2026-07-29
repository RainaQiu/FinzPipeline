"""Logging controls that keep OAuth callback secrets out of access logs."""

from __future__ import annotations

import logging


class OAuthQueryRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            arguments = list(record.args)
            request_target = str(arguments[2])
            if request_target.startswith("/api/v1/integrations/qbo/callback"):
                arguments[2] = request_target.split("?", 1)[0]
                record.args = tuple(arguments)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthQueryRedactionFilter) for item in logger.filters):
        logger.addFilter(OAuthQueryRedactionFilter())

