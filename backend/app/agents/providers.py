"""
Smart Enroll — LLM Provider Abstraction (Increment 15, Task 15.3)

Provides a lightweight, HTTP-based LLM provider abstraction using existing httpx.
Features:
- Abstract LLMProvider interface and OpenAICompatibleProvider implementation.
- Universal support for OpenAI, Groq, local Ollama, vLLM, or LM Studio endpoints.
- Strict SSRF protection preventing arbitrary private network access unless configured.
- Zero credential leakage in repr, logs, or error exceptions.
- Graceful handling of timeouts, rate limits (429), and HTTP errors.
- Fully testable with httpx.MockTransport without live API calls.
"""

from abc import ABC, abstractmethod
import ipaddress
import logging
import socket
import threading
from typing import Any
import urllib.parse

import httpx

logger = logging.getLogger(__name__)


# =====================================================================
# Provider Exceptions
# =====================================================================

class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""
    pass


class LLMSSRFValidationError(LLMProviderError):
    """Raised when provider endpoint violates SSRF destination policies."""
    pass


class LLMProviderConfigurationError(LLMProviderError):
    """Raised when provider configuration is invalid or missing."""
    pass


class LLMProviderTimeoutError(LLMProviderError):
    """Raised when an HTTP request to the LLM provider times out."""
    pass


class LLMProviderHTTPError(LLMProviderError):
    """Raised when provider responds with an HTTP error code (4xx, 5xx)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class LLMProviderConnectionError(LLMProviderError):
    """Raised on network failure or unreachable provider host."""
    pass


class LLMProviderResponseError(LLMProviderError):
    """Raised when provider response format or JSON structure is invalid."""
    pass


# =====================================================================
# SSRF Validation Utility
# =====================================================================

def validate_endpoint_url(url: str, allow_local_endpoints: bool = False) -> str:
    """
    Validate an LLM endpoint URL against SSRF vulnerabilities.
    Enforces:
    - Scheme must be http or https.
    - If allow_local_endpoints is False:
      - Local loopback endpoints (localhost, 127.0.0.0/8, ::1) are strictly rejected.
    - If allow_local_endpoints is True:
      - ONLY unambiguous local loopback endpoints (e.g., localhost, 127.0.0.1, ::1) are permitted.
    - For all non-loopback destinations, regardless of allow_local_endpoints:
      - Hostnames like *.local, *.internal, *.arpa are strictly rejected.
      - Direct or DNS-resolved IP addresses cannot be private, link-local, unspecified (0.0.0.0, ::),
        reserved, or loopback.
    """
    if not url or not isinstance(url, str):
        raise LLMSSRFValidationError("Provider URL must be a non-empty string.")

    clean_url = url.strip()
    parsed = urllib.parse.urlparse(clean_url)
    if parsed.scheme not in ("http", "https"):
        raise LLMSSRFValidationError(
            f"Invalid URL scheme '{parsed.scheme}'. Only 'http' and 'https' are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise LLMSSRFValidationError("Invalid URL: missing hostname.")

    is_loopback = is_local_endpoint(clean_url)
    if not is_loopback and parsed.scheme != "https":
        raise LLMSSRFValidationError(
            f"Insecure scheme '{parsed.scheme}'. Remote endpoints must use 'https://'."
        )

    if is_loopback:
        if allow_local_endpoints:
            return clean_url
        raise LLMSSRFValidationError(
            f"SSRF violation: Endpoint host '{hostname}' is a local loopback address, which is forbidden unless allow_local_endpoints is enabled."
        )

    # For all non-loopback destinations, enforce strict SSRF validation regardless of allow_local_endpoints
    lower_host = hostname.lower()
    if lower_host in ("localhost", "127.0.0.1", "::1") or lower_host.endswith((".local", ".internal", ".arpa")):
        raise LLMSSRFValidationError(
            f"SSRF violation: Endpoint host '{hostname}' is a restricted local or private domain."
        )

    # Check if host is direct IP address
    try:
        ip = ipaddress.ip_address(lower_host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise LLMSSRFValidationError(
                f"SSRF violation: Direct IP '{lower_host}' is in a private, loopback, or restricted network range."
            )
        return clean_url
    except ValueError:
        pass

    # Resolve hostname to check destination IPs
    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        for res in addr_info:
            ip_str = res[4][0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
                raise LLMSSRFValidationError(
                    f"SSRF violation: Hostname '{hostname}' resolves to restricted IP '{ip_str}'."
                )
    except socket.gaierror as e:
        raise LLMSSRFValidationError(
            f"SSRF violation: DNS resolution failed for endpoint hostname '{hostname}': {e}"
        ) from e

    return clean_url


def is_local_endpoint(url: str) -> bool:
    """
    Check if the URL destination targets an unambiguous loopback host
    (e.g., localhost, 127.0.0.1, ::1, or any 127.0.0.0/8 loopback IP).
    Does NOT classify arbitrary local network or private domain suffixes
    (.local, .internal, .arpa) as loopback.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return True
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_loopback
        except ValueError:
            pass
        return False
    except Exception:
        return False


# =====================================================================
# Abstract Provider Interface
# =====================================================================

class LLMProvider(ABC):
    """
    Abstract interface for LLM planning providers.
    """

    @abstractmethod
    def generate_plan_proposal(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send system and user prompts to model and return the raw text response.
        Raises an LLMProviderError subclass on failure.
        """
        pass

    def close(self) -> None:
        """Clean up underlying network resources."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# =====================================================================
# OpenAI-Compatible HTTP Provider
# =====================================================================

class OpenAICompatibleProvider(LLMProvider):
    """
    HTTP-based LLM provider adhering to the OpenAI Chat Completions API standard.
    Built strictly with existing httpx dependency.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        api_base: str = "https://api.openai.com/v1",
        timeout_seconds: float = 15.0,
        temperature: float = 0.0,
        max_tokens: int = 512,
        allow_local_endpoints: bool = False,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key.strip() if api_key else None
        self.model = model.strip() if model else "gpt-4o-mini"
        self.api_base = validate_endpoint_url(api_base, allow_local_endpoints=allow_local_endpoints)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.temperature = max(0.0, min(1.0, float(temperature)))
        self.max_tokens = max(1, int(max_tokens))
        self.allow_local_endpoints = allow_local_endpoints

        self._client = httpx.Client(
            timeout=self.timeout_seconds,
            transport=transport,
        )

    def __repr__(self) -> str:
        masked_key = f"sk-...{self.api_key[-4:]}" if self.api_key and len(self.api_key) > 6 else ("present" if self.api_key else "none")
        return (
            f"OpenAICompatibleProvider(model='{self.model}', api_base='{self.api_base}', "
            f"api_key='{masked_key}', timeout={self.timeout_seconds}s)"
        )

    def generate_plan_proposal(self, system_prompt: str, user_prompt: str) -> str:
        """
        Submit planning prompts to the provider and return the response content.
        """
        endpoint = f"{self.api_base.rstrip('/')}/chat/completions"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            response = self._client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.TimeoutException as e:
            logger.warning("LLM provider call timed out after %s seconds: %s", self.timeout_seconds, e)
            raise LLMProviderTimeoutError(f"LLM provider request timed out after {self.timeout_seconds}s.") from e
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            logger.warning("LLM provider returned HTTP error %d", status_code)
            raise LLMProviderHTTPError(
                status_code=status_code,
                message=f"LLM provider returned HTTP error {status_code}.",
            ) from e
        except httpx.RequestError as e:
            logger.warning("LLM provider request failed: %s", e.__class__.__name__)
            raise LLMProviderConnectionError(
                f"LLM provider connection failed: {e.__class__.__name__}."
            ) from e

        try:
            data = response.json()
            choices = data.get("choices")
            if not choices or not isinstance(choices, list):
                raise LLMProviderResponseError("LLM provider response missing 'choices' array.")

            message = choices[0].get("message", {})
            content = message.get("content", "")
            if not content or not isinstance(content, str):
                raise LLMProviderResponseError("LLM provider returned empty message content.")

            return content
        except Exception as e:
            if isinstance(e, LLMProviderError):
                raise
            raise LLMProviderResponseError(f"Failed to parse LLM provider response JSON: {e}") from e

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


# =====================================================================
# Cached Singleton Provider Lifecycle
# =====================================================================

_CACHED_PROVIDER: LLMProvider | None = None
_CACHED_PROVIDER_CONFIG: dict[str, Any] | None = None
_PROVIDER_LOCK = threading.Lock()


def get_llm_provider() -> LLMProvider | None:
    """
    Get or initialize the cached singleton LLMProvider instance based on current settings.
    Avoids re-instantiating HTTP client and socket connection pools across requests.
    """
    global _CACHED_PROVIDER, _CACHED_PROVIDER_CONFIG
    from app.core.config import settings

    if settings.LLM_PROVIDER not in ("openai_compatible", "openai"):
        return None

    is_local = is_local_endpoint(settings.LLM_API_BASE)
    has_valid_credentials = bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip())
    can_initialize = (is_local and settings.LLM_ALLOW_LOCAL_ENDPOINTS) or (
        not is_local and has_valid_credentials
    )
    if not can_initialize:
        return None

    current_config = {
        "provider": settings.LLM_PROVIDER,
        "api_key": settings.LLM_API_KEY,
        "model": settings.LLM_MODEL,
        "api_base": settings.LLM_API_BASE,
        "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        "temperature": settings.LLM_TEMPERATURE,
        "allow_local_endpoints": settings.LLM_ALLOW_LOCAL_ENDPOINTS,
    }

    with _PROVIDER_LOCK:
        if _CACHED_PROVIDER is not None and _CACHED_PROVIDER_CONFIG == current_config:
            return _CACHED_PROVIDER

        if _CACHED_PROVIDER is not None:
            try:
                _CACHED_PROVIDER.close()
            except Exception:
                pass
            _CACHED_PROVIDER = None
            _CACHED_PROVIDER_CONFIG = None

        try:
            _CACHED_PROVIDER = OpenAICompatibleProvider(
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL,
                api_base=settings.LLM_API_BASE,
                timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=512,
                allow_local_endpoints=settings.LLM_ALLOW_LOCAL_ENDPOINTS,
            )
            _CACHED_PROVIDER_CONFIG = current_config
            return _CACHED_PROVIDER
        except (LLMSSRFValidationError, LLMProviderError) as exc:
            logger.warning("Cannot initialize LLM provider due to validation error: %s", exc)
            return None


def close_llm_provider() -> None:
    """Close and reset the cached singleton LLMProvider instance."""
    global _CACHED_PROVIDER, _CACHED_PROVIDER_CONFIG
    with _PROVIDER_LOCK:
        if _CACHED_PROVIDER is not None:
            try:
                _CACHED_PROVIDER.close()
            except Exception:
                pass
            _CACHED_PROVIDER = None
            _CACHED_PROVIDER_CONFIG = None
