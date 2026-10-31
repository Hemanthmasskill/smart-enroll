import abc
import logging
from pathlib import Path

logger = logging.getLogger("smartenroll.scanner")


class BaseUploadScanner(abc.ABC):
    @abc.abstractmethod
    def scan_file(self, file_path: Path) -> tuple[bool, str]:
        """
        Scan an uploaded file for malware / security threats.
        Returns: (is_clean: bool, message: str)
        """
        pass


class NoopUploadScanner(BaseUploadScanner):
    """
    Default no-op upload scanner for development and test environments.
    """

    def scan_file(self, file_path: Path) -> tuple[bool, str]:
        if not file_path.exists():
            return False, "File does not exist on disk."
        return True, "No-op upload scan passed: file clean."


class ClamAVUploadScanner(BaseUploadScanner):
    """
    ClamAV antivirus upload scanner integrating with clamd via network socket or daemon.
    Production deployments should run clamd and install pyclamd.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        from app.core.config import settings

        self.host = host if host is not None else getattr(settings, "CLAMAV_HOST", "localhost")
        self.port = port if port is not None else getattr(settings, "CLAMAV_PORT", 3310)

    def scan_file(self, file_path: Path) -> tuple[bool, str]:
        if not file_path.exists():
            return False, "File does not exist on disk."
        try:
            import pyclamd  # type: ignore

            cd = pyclamd.ClamdNetworkSocket(self.host, self.port)
            if not cd.ping():
                logger.warning("ClamAV daemon unreachable at %s:%d", self.host, self.port)
                return False, "Virus scan service unavailable."
            scan_result = cd.scan_file(str(file_path))
            if scan_result is None:
                return True, "ClamAV scan passed: clean."
            virus_name = scan_result.get(str(file_path), ["UNKNOWN"])[1]
            logger.error("Malware detected in %s: %s", file_path, virus_name)
            return False, f"Malware detected: {virus_name}"
        except ImportError:
            logger.warning("pyclamd not installed; ClamAV scanner unavailable.")
            return False, "pyclamd library not installed for ClamAV scanning."
        except Exception as e:
            logger.error("ClamAV scan failed with error: %s", e)
            return False, f"Scan error: {str(e)}"


def validate_upload_scanner() -> None:
    """
    Validate that UPLOAD_SCANNER is properly configured and verify readiness on startup.
    In staging and production:
    - requires UPLOAD_SCANNER == 'clamav' (rejects noop, missing, or unrecognized).
    - verifies pyclamd is installed and importable (fails startup if missing).
    - verifies the ClamAV daemon responds to ping on (CLAMAV_HOST, CLAMAV_PORT) (fails startup if unreachable).
    In development and test:
    - preserves no-op scanning without attempting network connection to ClamAV daemon.
    """
    from app.core.config import settings

    env = settings.ENV.lower()
    scanner = (getattr(settings, "UPLOAD_SCANNER", "") or "").strip().lower()
    if not scanner:
        raise ValueError(f"UPLOAD_SCANNER is missing. Configured ENV is '{settings.ENV}'.")
    if scanner not in ("noop", "clamav"):
        raise ValueError(f"Unrecognized UPLOAD_SCANNER '{settings.UPLOAD_SCANNER}'. Valid options: noop, clamav.")
    if env in ("staging", "production"):
        if scanner == "noop":
            raise ValueError(f"UPLOAD_SCANNER 'noop' is strictly forbidden in {settings.ENV}. A real scanner is required.")

        # Live ClamAV readiness check for staging/production
        if scanner == "clamav":
            try:
                import pyclamd  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    f"ClamAV readiness check failed in {settings.ENV}: 'pyclamd' package is not installed."
                ) from e

            try:
                cd = pyclamd.ClamdNetworkSocket(settings.CLAMAV_HOST, settings.CLAMAV_PORT)
                if not cd.ping():
                    raise RuntimeError(
                        f"ClamAV daemon at {settings.CLAMAV_HOST}:{settings.CLAMAV_PORT} failed ping check in {settings.ENV}."
                    )
            except Exception as e:
                if isinstance(e, RuntimeError):
                    raise
                raise RuntimeError(
                    f"ClamAV daemon unreachable at {settings.CLAMAV_HOST}:{settings.CLAMAV_PORT} in {settings.ENV}: {e}"
                ) from e


def get_upload_scanner() -> BaseUploadScanner:
    """
    Factory resolving configured upload scanner instance.
    """
    from app.core.config import settings

    scanner_type = (getattr(settings, "UPLOAD_SCANNER", "noop") or "").strip().lower()
    if scanner_type == "clamav":
        return ClamAVUploadScanner()
    elif scanner_type == "noop":
        if settings.ENV.lower() in ("staging", "production"):
            raise ValueError(f"UPLOAD_SCANNER 'noop' is strictly forbidden in {settings.ENV}.")
        return NoopUploadScanner()
    raise ValueError(f"Unrecognized UPLOAD_SCANNER '{scanner_type}'. Valid options: noop, clamav.")
