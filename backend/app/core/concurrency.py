"""
Smart Enroll — Concurrency Limiter & Worker Semaphore (Hardening Task 4.2)

Restricts concurrent CPU-intensive workloads (OCR, PDF extraction, document verification)
to prevent event loop starvation and resource exhaustion.
"""

from contextlib import contextmanager
import threading
from fastapi import HTTPException, status

from app.core.config import settings

_ocr_semaphore = threading.Semaphore(getattr(settings, "MAX_CONCURRENT_OCR_WORKERS", 4))


@contextmanager
def acquire_ocr_worker(timeout: float = 0.5):
    """
    Context manager to acquire an OCR execution slot.
    Returns HTTP 503 Service Unavailable if worker pool is saturated.
    """
    acquired = _ocr_semaphore.acquire(blocking=True, timeout=timeout)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document processing capacity is currently saturated. Please retry shortly.",
            headers={"Retry-After": "5"},
        )
    try:
        yield
    finally:
        _ocr_semaphore.release()

