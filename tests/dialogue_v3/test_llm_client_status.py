from __future__ import annotations

import app_v3

from mbk_refactor.dialogue_v3 import llm_client
from mbk_refactor.dialogue_v3.llm_client import (
    LLMClientStatus,
    build_optional_llm_client,
    mark_llm_status_failed,
    mark_llm_status_verified,
)


def test_llm_status_missing_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MBK_OPENAI_API_KEY", raising=False)

    client, status = build_optional_llm_client("gpt-5.4-mini")

    assert client is None
    assert status.configured is False
    assert status.verified is False
    assert status.available is False
    assert status.reason == "missing_api_key"
    assert status.last_error is None


def test_llm_status_configured_but_unverified_without_sanity_call(monkeypatch) -> None:
    class FakeOpenAIClient:
        def __init__(self, *, model_name: str, api_key: str | None = None):
            self.model_name = model_name
            self.api_key = api_key

        def verify(self) -> None:
            raise AssertionError("verify should not run without explicit request")

        def __call__(self, messages: list[dict[str, str]]) -> str:
            return '{"body":"","followup_question":""}'

    monkeypatch.setenv("OPENAI_API_KEY", "configured-key")
    monkeypatch.delenv("MBK_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "OpenAIChatLLMClient", FakeOpenAIClient)

    client, status = build_optional_llm_client("gpt-5.4-mini")

    assert client is not None
    assert status.configured is True
    assert status.verified is False
    assert status.available is False
    assert status.reason == "openai_client_configured_unverified"


def test_llm_status_invalid_key_after_explicit_check(monkeypatch) -> None:
    class AuthenticationError(Exception):
        pass

    class FakeOpenAIClient:
        def __init__(self, *, model_name: str, api_key: str | None = None):
            self.model_name = model_name

        def verify(self) -> None:
            raise AuthenticationError("Incorrect API key")

    monkeypatch.setenv("OPENAI_API_KEY", "bad-key")
    monkeypatch.delenv("MBK_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "OpenAIChatLLMClient", FakeOpenAIClient)

    client, status = build_optional_llm_client("gpt-5.4-mini", verify=True)

    assert client is None
    assert status.configured is True
    assert status.verified is False
    assert status.available is False
    assert status.reason == "invalid_api_key"
    assert status.last_error == "AuthenticationError: Incorrect API key"


def test_llm_status_successful_lightweight_check(monkeypatch) -> None:
    class FakeOpenAIClient:
        def __init__(self, *, model_name: str, api_key: str | None = None):
            self.model_name = model_name
            self.verified = False

        def verify(self) -> None:
            self.verified = True

    monkeypatch.setenv("OPENAI_API_KEY", "valid-key")
    monkeypatch.delenv("MBK_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "OpenAIChatLLMClient", FakeOpenAIClient)

    client, status = build_optional_llm_client("gpt-5.4-mini", verify=True)

    assert client is not None
    assert status.configured is True
    assert status.verified is True
    assert status.available is True
    assert status.reason == "openai client verified"
    assert status.model_name == "gpt-5.4-mini"
    assert status.last_error is None


def test_llm_status_marked_failed_after_writer_auth_error() -> None:
    status = LLMClientStatus(
        configured=True,
        verified=True,
        available=True,
        reason="openai client verified",
        model_name="gpt-5.4-mini",
    )

    failed = mark_llm_status_failed(status, "AuthenticationError: Incorrect API key")

    assert failed.configured is True
    assert failed.verified is False
    assert failed.available is False
    assert failed.reason == "invalid_api_key"
    assert failed.last_error == "AuthenticationError: Incorrect API key"


def test_llm_status_marked_verified_after_successful_writer_call() -> None:
    status = LLMClientStatus(
        configured=True,
        verified=False,
        available=False,
        reason="openai_client_configured_unverified",
        model_name="gpt-5.4-mini",
    )

    verified = mark_llm_status_verified(status)

    assert verified.configured is True
    assert verified.verified is True
    assert verified.available is True
    assert verified.reason == "openai client verified"
    assert verified.last_error is None


def test_debug_export_includes_configured_verified_available_llm_status(monkeypatch) -> None:
    status = LLMClientStatus(
        configured=True,
        verified=False,
        available=False,
        reason="invalid_api_key",
        model_name="gpt-5.4-mini",
        last_error="AuthenticationError: Incorrect API key",
    )
    fake_streamlit = type(
        "FakeStreamlit",
        (),
        {
            "session_state": {
                "v3_state": None,
                "last_result": None,
                "last_llm_status": status,
                "last_error": "AuthenticationError: Incorrect API key",
                "model_name": "gpt-5.4-mini",
                "applied_form": {},
                "applied_facts": {},
                "turn_records": [],
            }
        },
    )()
    monkeypatch.setattr(app_v3, "st", fake_streamlit)

    payload = app_v3._current_debug_payload()

    assert payload["llm_status"] == {
        "configured": True,
        "verified": False,
        "available": False,
        "reason": "invalid_api_key",
        "model_name": "gpt-5.4-mini",
        "last_error": "AuthenticationError: Incorrect API key",
    }
