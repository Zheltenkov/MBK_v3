from __future__ import annotations

import inspect

import app_v3


def test_start_chat_from_form_creates_assistant_opening_message() -> None:
    state, facts = app_v3.start_chat_from_form(
        {
            "Сумма": 645_467,
            "ФИО": "Соколов Виктор Семенович",
            "Есть текущие кредиты или займы?": True,
            "Есть ли в собственности авто?": True,
            "Тип актива": "Недвижимость",
        },
        session_id="opening-test",
    )

    assert facts["desired_amount"] == 645_467
    assert len(state.messages) == 1
    assert state.messages[0].role == "assistant"
    assert state.messages[0].turn_index == 0


def test_render_chat_no_longer_uses_system_instruction_after_form_submit() -> None:
    source = inspect.getsource(app_v3._render_chat)

    assert "Анкета применена. Напишите первое сообщение клиента." not in source


def test_auth_enabled_defaults_to_credentials_presence(monkeypatch) -> None:
    monkeypatch.delenv("MBK_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("MBK_AUTH_USERNAME", raising=False)
    monkeypatch.delenv("MBK_AUTH_PASSWORD", raising=False)

    assert app_v3._auth_enabled() is False

    monkeypatch.setenv("MBK_AUTH_USERNAME", "operator")
    monkeypatch.setenv("MBK_AUTH_PASSWORD", "secret")

    assert app_v3._auth_enabled() is True


def test_auth_enabled_env_switch_can_disable_auth(monkeypatch) -> None:
    monkeypatch.setenv("MBK_AUTH_ENABLED", "false")
    monkeypatch.setenv("MBK_AUTH_USERNAME", "operator")
    monkeypatch.setenv("MBK_AUTH_PASSWORD", "secret")

    assert app_v3._auth_enabled() is False


def test_opening_message_is_actor_like_and_top_level() -> None:
    state, _ = app_v3.start_chat_from_form(
        {
            "Сумма": 645_467,
            "ФИО": "Соколов Виктор Семенович",
            "Есть текущие кредиты или займы?": True,
            "Есть ли в собственности авто?": True,
            "Тип актива": "Недвижимость",
            "Тип занятости": "найм",
        },
        session_id="opening-copy-test",
    )
    opening = state.messages[0].content
    lowered = opening.lower()

    assert "виктор семенович, добрый день" in lowered
    assert "заявку вижу" in lowered
    assert "645 467 ₽" in opening
    assert "есть текущие кредиты" in lowered
    assert "указали авто и недвижимость" in lowered
    assert "актив - недвижимость" not in lowered
    assert "актив" not in lowered
    assert "\n\n" in opening
    assert "чтобы подобрать нормальный вариант" in lowered
    assert "закрыть/объединить долги" in lowered
    assert "снизить ежемесячный платёж" in lowered
    assert "получить сумму на руки" in lowered
    assert "это квартира, дом или другой объект" not in lowered
    assert "тип объекта" not in lowered
    assert "марка" not in lowered
    assert "модель" not in lowered
    assert "какая у вас машина" not in lowered
    assert "какого года" not in lowered
    assert "виды активных кредитов" not in lowered
    assert state.route is None
    assert state.pending_route is None
    assert state.pending_terminal_action is None
    assert state.asked_slots == []
    assert state.trace_history == []
