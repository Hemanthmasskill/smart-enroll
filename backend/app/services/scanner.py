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

    def __init__(self, host: str = "localhost", port: int = 3310):
        self.host = host
        self.port = port

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


def get_upload_scanner() -> BaseUploadScanner:
    """
    Factory resolving configured upload scanner instance.
    """
    from app.core.config import settings

    scanner_type = getattr(settings, "UPLOAD_SCANNER", "noop").strip().lower()
    if scanner_type == "clamav":
        return ClamAVUploadScanner()
    return NoopUploadScanner()
