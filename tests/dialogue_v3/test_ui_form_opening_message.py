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
    assert "указали авто" in lowered
    assert "актив - недвижимость" in lowered
    assert "\n\n" in opening
    assert "чтобы подобрать нормальный вариант" in lowered
    assert "закрыть/объединить долги" in lowered
    assert "снизить ежемесячный платёж" in lowered
    assert "получить сумму на руки" in lowered
    assert "это квартира, дом или другой объект" not in lowered
    assert "какого года" not in lowered
    assert "виды активных кредитов" not in lowered
