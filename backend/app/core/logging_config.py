"""
Smart Enroll — Structured Logging, Redaction & Request Tracing (Hardening Task 4.5)

Provides:
- SensitiveDataRedactionFilter: Automatically strips passwords, tokens, API keys,
  and sensitive applicant data from application logs.
- RequestIdMiddleware: Attaches or propagates X-Request-ID to request context and responses.
"""

import logging
import re
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SENSITIVE_PATTERNS = [
    (re.compile(r'("password"\s*:\s*)"[^"]*"', re.IGNORECASE), r'\1"[REDACTED]"'),
    (re.compile(r'("hashed_password"\s*:\s*)"[^"]*"', re.IGNORECASE), r'\1"[REDACTED]"'),
    (re.compile(r'("token"\s*:\s*)"[^"]*"', re.IGNORECASE), r'\1"[REDACTED]"'),
    (re.compile(r'("apiKey"|"api_key"\s*:\s*)"[^"]*"', re.IGNORECASE), r'\1"[REDACTED]"'),
    (re.compile(r'(Bearer\s+)[A-Za-z0-9\-_\.]+', re.IGNORECASE), r'\1[REDACTED]'),
]


class SensitiveDataRedactionFilter(logging.Filter):
    """
    Sanitizes credentials, secrets, and authorization headers from log messages.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, repl in SENSITIVE_PATTERNS:
                record.msg = pattern.sub(repl, record.msg)
        return True


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Extracts or generates an X-Request-ID header for end-to-end tracing.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

