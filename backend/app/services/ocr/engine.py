from abc import ABC, abstractmethod
import os
from pathlib import Path
import shutil
from typing import Any
from PIL import Image
import pytesseract

from app.core.config import settings


class OCREngineUnavailableError(RuntimeError):
    """Raised when native OCR engine executable is missing or cannot be executed."""
    pass


class OCRProcessingError(RuntimeError):
    """Raised when OCR processing encounters an unexpected parser or engine failure."""
    pass


class OCREngine(ABC):
    """Abstract OCR engine interface for replaceable OCR adapters."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether OCR engine executable and libraries are available."""
        pass

    @abstractmethod
    def get_engine_name(self) -> str:
        """Return identifier string for engine and version."""
        pass

    @abstractmethod
    def extract_text_from_image(self, image: Image.Image, timeout_seconds: int = 15) -> str:
        """Extract text from a PIL Image instance with bounded execution time."""
        pass


class TesseractOCREngine(OCREngine):
    """
    Adapter for native Tesseract OCR executable via pytesseract.
    Checks environment variable, config setting, and standard Windows paths.
    Fails with actionable error if executable is unavailable.
    """

    def __init__(self, custom_cmd: str | None = None, languages: str | None = None):
        self._custom_cmd = custom_cmd or settings.TESSERACT_CMD
        self._languages = languages or getattr(settings, "OCR_LANGUAGES", "eng+tam+hin")
        self._resolved_cmd: str | None = None
        self._checked = False

    @property
    def languages(self) -> str:
        return self._languages

    def _discover_executable(self) -> str | None:
        if self._checked:
            return self._resolved_cmd

        self._checked = True

        # 1. Custom configured command / env var
        if self._custom_cmd and os.path.exists(self._custom_cmd):
            self._resolved_cmd = str(Path(self._custom_cmd).resolve())
            pytesseract.pytesseract.tesseract_cmd = self._resolved_cmd
            return self._resolved_cmd

        # 2. Check system PATH via shutil.which
        path_which = shutil.which("tesseract")
        if path_which and os.path.exists(path_which):
            self._resolved_cmd = str(Path(path_which).resolve())
            pytesseract.pytesseract.tesseract_cmd = self._resolved_cmd
            return self._resolved_cmd

        # 3. Check common Windows installation paths
        common_windows_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for p in common_windows_paths:
            if p and os.path.exists(p):
                self._resolved_cmd = str(Path(p).resolve())
                pytesseract.pytesseract.tesseract_cmd = self._resolved_cmd
                return self._resolved_cmd

        self._resolved_cmd = None
        return None

    def is_available(self) -> bool:
        cmd = self._discover_executable()
        if not cmd:
            return False
        try:
            # Check version
            _ = pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def get_engine_name(self) -> str:
        if self.is_available():
            try:
                ver = pytesseract.get_tesseract_version()
                return f"tesseract-ocr-{ver}"
            except Exception:
                return "tesseract-ocr"
        return "tesseract-ocr-unavailable"

    def extract_text_from_image(self, image: Image.Image, timeout_seconds: int = 15) -> str:
        if not self.is_available():
            raise OCREngineUnavailableError(
                "Tesseract OCR engine is not installed or discoverable on this host. "
                "Install Tesseract OCR for Windows (e.g. from https://github.com/UB-Mannheim/tesseract/wiki) "
                "and set TESSERACT_CMD in backend/.env or your system PATH."
            )

        try:
            text = pytesseract.image_to_string(
                image,
                lang=self._languages,
                timeout=timeout_seconds,
            )
            return text or ""
        except pytesseract.TesseractTimeoutError:
            raise OCRProcessingError(f"OCR execution timed out after {timeout_seconds} seconds.")
        except pytesseract.TesseractError as e:
            raise OCRProcessingError(f"Tesseract OCR engine error: {str(e)}")
        except Exception as e:
            raise OCRProcessingError(f"Unexpected error during OCR text extraction: {str(e)}")


class MockOCREngine(OCREngine):
    """
    Deterministic mock OCR engine adapter for automated unit and integration tests.
    Does not require external binaries.
    """

    def __init__(self, mock_text: str = "", is_available: bool = True):
        self.mock_text = mock_text
        self._is_available = is_available
        self.call_count = 0

    def is_available(self) -> bool:
        return self._is_available

    def get_engine_name(self) -> str:
        return "mock-ocr-engine-1.0"

    def extract_text_from_image(self, image: Image.Image, timeout_seconds: int = 15) -> str:
        self.call_count += 1
        if not self._is_available:
            raise OCREngineUnavailableError("Mock OCR engine configured as unavailable.")
        return self.mock_text


_default_engine: OCREngine | None = None


def get_ocr_engine() -> OCREngine:
    """Return configured singleton or standard Tesseract engine adapter."""
    global _default_engine
    if _default_engine is None:
        _default_engine = TesseractOCREngine()
    return _default_engine


def set_ocr_engine(engine: OCREngine | None) -> None:
    """Override engine (e.g. for testing with MockOCREngine)."""
    global _default_engine
    _default_engine = engine
