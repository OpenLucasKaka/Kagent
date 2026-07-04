from __future__ import annotations

import json
import os
import re
import stat
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

DEFAULT_LLM_MODEL = "qwen3.5-122b-a10b"
PROVIDER_CONFIG_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class LLMProviderConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "LLMProviderConfig":
        source = env if env is not None else environ
        return cls(
            base_url=source.get("KAGENT_LLM_BASE_URL", cls.base_url),
            api_key=source.get("KAGENT_LLM_API_KEY", cls.api_key),
            model=source.get("KAGENT_LLM_MODEL", cls.model),
            timeout_seconds=_env_float(
                source,
                "KAGENT_LLM_TIMEOUT_SECONDS",
                cls.timeout_seconds,
            ),
            max_retries=_env_int(
                source,
                "KAGENT_LLM_MAX_RETRIES",
                cls.max_retries,
            ),
            retry_backoff_seconds=_env_float(
                source,
                "KAGENT_LLM_RETRY_BACKOFF_SECONDS",
                cls.retry_backoff_seconds,
            ),
        )

    @classmethod
    def from_sources(
        cls,
        env: Optional[Mapping[str, str]] = None,
        config_path: str = "",
    ) -> "LLMProviderConfig":
        source = env if env is not None else environ
        file_config = load_provider_config(config_path)
        merged = {
            "KAGENT_LLM_BASE_URL": file_config.base_url,
            "KAGENT_LLM_API_KEY": file_config.api_key,
            "KAGENT_LLM_MODEL": file_config.model,
            "KAGENT_LLM_TIMEOUT_SECONDS": str(file_config.timeout_seconds),
            "KAGENT_LLM_MAX_RETRIES": str(file_config.max_retries),
            "KAGENT_LLM_RETRY_BACKOFF_SECONDS": str(
                file_config.retry_backoff_seconds
            ),
        }
        for key, value in source.items():
            if key.startswith("KAGENT_LLM_") and value != "":
                merged[key] = value
        return cls.from_env(merged)

    def redacted_snapshot(self) -> Dict[str, str]:
        provider = "openai_compatible" if self.base_url and self.model else "unconfigured"
        return {
            "llm_provider": provider,
            "llm_base_url": self.base_url,
            "llm_model": self.model,
            "llm_api_key_configured": str(bool(self.api_key)).lower(),
            "llm_timeout_seconds": str(self.timeout_seconds),
            "llm_max_retries": str(self.max_retries),
            "llm_retry_backoff_seconds": str(self.retry_backoff_seconds),
        }

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")


def default_provider_config_path(env: Optional[Mapping[str, str]] = None) -> str:
    source = env if env is not None else environ
    if source.get("KAGENT_LLM_CONFIG_PATH"):
        return source["KAGENT_LLM_CONFIG_PATH"]
    config_home = source.get("XDG_CONFIG_HOME")
    if config_home:
        return str(Path(config_home) / "kagent" / "provider.json")
    return str(Path.home() / ".config" / "kagent" / "provider.json")


def load_provider_config(path: str = "") -> LLMProviderConfig:
    config_path = Path(path or default_provider_config_path())
    if not config_path.exists():
        return LLMProviderConfig()
    _validate_provider_config_path_for_read(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider config must be a JSON object")
    if str(payload.get("schema_version", "")) != PROVIDER_CONFIG_SCHEMA_VERSION:
        raise ValueError("provider config schema_version is unsupported")
    provider = str(payload.get("provider", "openai_compatible"))
    if provider != "openai_compatible":
        raise ValueError("provider config provider is unsupported")
    return LLMProviderConfig(
        base_url=str(payload.get("base_url", "")),
        api_key=str(payload.get("api_key", "")),
        model=str(payload.get("model", "")),
        timeout_seconds=float(
            payload.get("timeout_seconds", LLMProviderConfig.timeout_seconds)
        ),
        max_retries=int(payload.get("max_retries", LLMProviderConfig.max_retries)),
        retry_backoff_seconds=float(
            payload.get(
                "retry_backoff_seconds",
                LLMProviderConfig.retry_backoff_seconds,
            )
        ),
    )


def save_provider_config(config: LLMProviderConfig, path: str = "") -> str:
    config_path = Path(path or default_provider_config_path())
    _validate_provider_config_path_for_write(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(config_path.parent, 0o700)
    payload = {
        "schema_version": PROVIDER_CONFIG_SCHEMA_VERSION,
        "provider": "openai_compatible",
        "base_url": config.base_url,
        "api_key": config.api_key,
        "model": config.model,
        "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries,
        "retry_backoff_seconds": config.retry_backoff_seconds,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(config_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(config_path, 0o600)
    return str(config_path)


def _validate_provider_config_path_for_read(path: Path) -> None:
    _reject_symlink_path(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ValueError("provider config file must be owner-only")


def _validate_provider_config_path_for_write(path: Path) -> None:
    _reject_symlink_path(path)
    if path.parent.exists():
        _reject_symlink_path(path.parent)
        os.chmod(path.parent, 0o700)
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise ValueError("provider config file must be owner-only")


def _reject_symlink_path(path: Path) -> None:
    current = Path(path.anchor or ".")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("provider config path must not contain symlinks")


class FakeLLMProvider:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: List[Dict[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response_text


class SequentialFakeLLMProvider:
    def __init__(self, response_texts: List[str]) -> None:
        if not response_texts:
            raise ValueError("response_texts must be non-empty")
        self.response_texts = list(response_texts)
        self.calls: List[Dict[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if len(self.calls) <= len(self.response_texts):
            return self.response_texts[len(self.calls) - 1]
        return self.response_texts[-1]


class OpenAICompatibleProvider:
    def __init__(
        self,
        config: LLMProviderConfig,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.base_url:
            raise ValueError("base_url is required")
        if not config.model:
            raise ValueError("model is required")
        self.config = config
        self._urlopen = urlopen
        self._sleep = sleep

    def complete(self, system: str, user: str) -> str:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        body = self._request_json_with_retries(request)
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("llm provider response missing message content") from exc

    def _request_json_with_retries(self, request: urllib.request.Request) -> Dict[str, Any]:
        max_attempts = self.config.max_retries + 1
        for attempt in range(max_attempts):
            try:
                with self._urlopen(
                    request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = _read_http_error_body(exc)
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(
                    exc,
                    body,
                ):
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key, body)
                    ) from exc
                retry_delay = _provider_retry_delay_seconds(exc, self.config)
                if retry_delay:
                    self._sleep(retry_delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(exc):
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key)
                    ) from exc
                if self.config.retry_backoff_seconds:
                    self._sleep(self.config.retry_backoff_seconds)
        raise RuntimeError("llm provider request failed")


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _is_retryable_provider_error(exc: BaseException, body: str = "") -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return (
            exc.code == 429
            or 500 <= exc.code <= 599
            or (exc.code == 400 and "model unloaded" in body.lower())
        )
    return isinstance(exc, (urllib.error.URLError, TimeoutError))


def _provider_retry_delay_seconds(
    exc: BaseException,
    config: LLMProviderConfig,
) -> float:
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = _numeric_retry_after_seconds(exc)
        if retry_after is not None:
            return retry_after
    return config.retry_backoff_seconds


def _numeric_retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after is None:
        return None
    try:
        seconds = float(str(retry_after).strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


def _provider_failure_message(
    exc: BaseException,
    api_key: str,
    body: str = "",
) -> str:
    message = "llm provider request failed"
    if isinstance(exc, urllib.error.HTTPError):
        redacted_body = _redact_provider_text(body, api_key)
        if redacted_body:
            return f"{message}: http_status={exc.code} body={redacted_body}"
        return f"{message}: http_status={exc.code} reason={exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        reason = _redact_provider_text(str(exc.reason), api_key)
        if reason:
            return f"{message}: reason={reason}"
    if isinstance(exc, TimeoutError):
        return f"{message}: reason=timeout"
    return message


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read()
    except OSError:
        return ""
    if not body:
        return ""
    return body.decode("utf-8", errors="replace")[:500]


def _redact_provider_text(text: str, api_key: str) -> str:
    redacted = text
    if api_key:
        redacted = redacted.replace(api_key, "[redacted]")
    return re.sub(r"sk-[A-Za-z0-9:_-]{8,}", "[redacted]", redacted)
