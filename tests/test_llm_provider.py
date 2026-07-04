import io
import stat
import urllib.error

from kagent.providers.llm import (
    DEFAULT_LLM_MODEL,
    FakeLLMProvider,
    LLMProviderConfig,
    OpenAICompatibleProvider,
    SequentialFakeLLMProvider,
    default_provider_config_path,
    load_provider_config,
    save_provider_config,
)


def test_provider_config_reads_openai_compatible_environment_without_exposing_key():
    config = LLMProviderConfig.from_env(
        {
            "KAGENT_LLM_BASE_URL": "https://llm.example/v1",
            "KAGENT_LLM_API_KEY": "redactme",
            "KAGENT_LLM_MODEL": "agent-model",
            "KAGENT_LLM_TIMEOUT_SECONDS": "12.5",
            "KAGENT_LLM_MAX_RETRIES": "2",
            "KAGENT_LLM_RETRY_BACKOFF_SECONDS": "0.25",
        }
    )

    assert config.base_url == "https://llm.example/v1"
    assert config.model == "agent-model"
    assert config.timeout_seconds == 12.5
    assert config.max_retries == 2
    assert config.retry_backoff_seconds == 0.25
    assert config.redacted_snapshot() == {
        "llm_provider": "openai_compatible",
        "llm_base_url": "https://llm.example/v1",
        "llm_model": "agent-model",
        "llm_api_key_configured": "true",
        "llm_timeout_seconds": "12.5",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
    }
    assert "redactme" not in str(config.redacted_snapshot())


def test_provider_config_defaults_to_unconfigured_runtime():
    config = LLMProviderConfig.from_env({})

    assert config.redacted_snapshot() == {
        "llm_provider": "unconfigured",
        "llm_base_url": "",
        "llm_model": "",
        "llm_api_key_configured": "false",
        "llm_timeout_seconds": "30.0",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
    }


def test_provider_config_can_be_saved_loaded_and_overridden_by_env(tmp_path):
    config_path = tmp_path / "provider.json"

    saved_path = save_provider_config(
        LLMProviderConfig(
            base_url="https://stored.example/v1",
            api_key="stored-key",
            model=DEFAULT_LLM_MODEL,
        ),
        str(config_path),
    )

    loaded = load_provider_config(str(config_path))
    merged = LLMProviderConfig.from_sources(
        {
            "KAGENT_LLM_BASE_URL": "https://env.example/v1",
            "KAGENT_LLM_MODEL": "env-model",
        },
        config_path=str(config_path),
    )

    assert saved_path == str(config_path)
    assert loaded.base_url == "https://stored.example/v1"
    assert loaded.api_key == "stored-key"
    assert loaded.model == DEFAULT_LLM_MODEL
    assert merged.base_url == "https://env.example/v1"
    assert merged.api_key == "stored-key"
    assert merged.model == "env-model"
    assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_default_provider_config_path_respects_xdg_and_explicit_override(tmp_path):
    explicit = tmp_path / "explicit.json"

    assert default_provider_config_path({"KAGENT_LLM_CONFIG_PATH": str(explicit)}) == str(
        explicit
    )
    assert default_provider_config_path({"XDG_CONFIG_HOME": str(tmp_path)}) == str(
        tmp_path / "kagent" / "provider.json"
    )


def test_provider_config_rejects_symlink_paths(tmp_path):
    target = tmp_path / "target.json"
    link = tmp_path / "provider-link.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    link.symlink_to(target)

    try:
        save_provider_config(
            LLMProviderConfig(base_url="https://llm.example/v1", model="agent"),
            str(link),
        )
    except ValueError as exc:
        assert "provider config path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("provider config was saved through a symlink")


def test_fake_llm_provider_returns_configured_text_response():
    provider = FakeLLMProvider('{"actions": []}')

    assert provider.complete("system", "user") == '{"actions": []}'
    assert provider.calls == [{"system": "system", "user": "user"}]


def test_sequential_fake_llm_provider_returns_configured_responses_in_order():
    provider = SequentialFakeLLMProvider(
        ['{"actions": []}', '{"actions": [], "final_answer": "ok"}']
    )

    assert provider.complete("system-1", "user-1") == '{"actions": []}'
    assert provider.complete("system-2", "user-2") == '{"actions": [], "final_answer": "ok"}'
    assert provider.complete("system-3", "user-3") == '{"actions": [], "final_answer": "ok"}'
    assert provider.calls == [
        {"system": "system-1", "user": "user-1"},
        {"system": "system-2", "user": "user-2"},
        {"system": "system-3", "user": "user-3"},
    ]


def test_openai_compatible_provider_retries_transient_http_errors():
    calls = []
    responses = [
        urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=503,
            msg="temporarily unavailable",
            hdrs={},
            fp=io.BytesIO(b"temporary"),
        ),
        _FakeHTTPResponse(
            b'{"choices":[{"message":{"content":"{\\"actions\\":[]}"}}]}'
        ),
    ]

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=1,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2


def test_openai_compatible_provider_does_not_retry_non_transient_http_errors():
    calls = []

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        raise urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=400,
            msg="bad request",
            hdrs={},
            fp=io.BytesIO(b"bad request"),
        )

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=3,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    try:
        provider.complete("system", "user")
    except RuntimeError as exc:
        assert str(exc) == "llm provider request failed: http_status=400 body=bad request"
    else:
        raise AssertionError("expected non-transient provider error")
    assert len(calls) == 1


def test_openai_compatible_provider_retries_model_unloaded_http_errors():
    calls = []
    responses = [
        urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=400,
            msg="bad request",
            hdrs={},
            fp=io.BytesIO(b'{"error":"Model unloaded."}'),
        ),
        _FakeHTTPResponse(
            b'{"choices":[{"message":{"content":"{\\"actions\\":[]}"}}]}'
        ),
    ]

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=1,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2


def test_openai_compatible_provider_uses_numeric_retry_after_header():
    calls = []
    sleeps = []
    responses = [
        urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=429,
            msg="rate limited",
            hdrs={"Retry-After": "1.5"},
            fp=io.BytesIO(b"rate limited"),
        ),
        _FakeHTTPResponse(
            b'{"choices":[{"message":{"content":"{\\"actions\\":[]}"}}]}'
        ),
    ]

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=1,
            retry_backoff_seconds=0.25,
        ),
        urlopen=open_url,
        sleep=sleeps.append,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2
    assert sleeps == [1.5]


def test_openai_compatible_provider_redacts_secret_like_error_body_values():
    api_key = "sk-" + "test-redaction-token"

    def open_url(request, *, timeout):
        raise urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=401,
            msg="unauthorized",
            hdrs={},
            fp=io.BytesIO(
                f'{{"error":"invalid api key {api_key} for request"}}'.encode()
            ),
        )

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key=api_key,
            model="agent-model",
        ),
        urlopen=open_url,
    )

    try:
        provider.complete("system", "user")
    except RuntimeError as exc:
        message = str(exc)
        assert "http_status=401" in message
        assert api_key not in message
        assert "[redacted]" in message
    else:
        raise AssertionError("expected provider error")


class _FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body
