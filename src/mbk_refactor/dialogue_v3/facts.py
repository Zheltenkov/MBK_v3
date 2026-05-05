"""Fact contracts and deterministic extraction for dialogue_v3."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .constants import MORTGAGE_AUX, MORTGAGE_MAIN, PTS

if TYPE_CHECKING:
    from .state import DialogueV3State

FactQuality = Literal["unknown", "approx", "exact", "conflicting", "not_applicable"]
FactSource = Literal["user", "form", "derived", "llm_extractor"]


@dataclass(frozen=True)
class FactValue:
    """A canonical fact with provenance and merge quality."""

    value: Any
    quality: FactQuality = "exact"
    source: FactSource = "user"
    updated_at_turn: int = 0


@dataclass
class ExtractedTurn:
    """Lightweight container for facts and non-routing turn signals."""

    facts: dict[str, Any] = field(default_factory=dict)
    direct_question: str | None = None
    off_topic: str | None = None
    customer_concerns: list[str] = field(default_factory=list)
    service_signal: str | None = None
    route_rejection: str | None = None
    raw_user_text: str = ""


@dataclass(frozen=True)
class VehicleIntentEvidence:
    """Turn-local semantic evidence for auto/PTS extraction."""

    has_vehicle_context: bool = False
    auto_collateral_consideration: bool = False
    explicit_pts_channel: bool = False
    retention_required: bool = False
    transfer_refusal: bool = False
    hard_collateral_refusal: bool = False
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class NeedIntentResult:
    """Turn-local semantic need signal without selecting a product route."""

    need_type: str | None = None
    early_need_signal: str | None = None
    purpose_goal: str | None = None
    evidence: tuple[str, ...] = ()


SERVICE_FRAUD_PATTERNS = (
    "просили код",
    "попросили код",
    "код из смс",
    "смс-код",
    "смс код",
    "я ничего не оформлял",
    "заявка не моя",
    "на меня оформили",
    "мошенники позвонили",
    "ao_mbk",
)
SERVICE_REPEAT_PATTERNS = (
    "я уже оставлял заявку",
    "я уже оставляла заявку",
    "я уже переходил в чат",
    "я уже переходила в чат",
    "мне не ответили",
    "вам и не ответили",
    "со мной не связались",
    "продолжить заявку",
    "продолжить прошлую заявку",
    "по старой заявке",
    "прошлую заявку",
)
SERVICE_REPEAT_SELF_REFERENCE_PATTERNS = (
    "я уже обращался",
    "я уже обращалась",
    "ранее обращался",
    "ранее обращалась",
    "раньше обращалась",
    "раньше обращался",
)
ACTIVE_DIALOG_CORRECTION_PATTERNS = (
    "я уже писал",
    "я уже писала",
    "я уже написал",
    "я уже написала",
    "я уже говорил",
    "я уже говорила",
    "я уже отвечал",
    "я уже отвечала",
    "уже писал",
    "уже писала",
    "уже написал",
    "уже написала",
    "уже говорил",
    "уже говорила",
    "уже отвечал",
    "уже отвечала",
    "я же сказал",
    "я же сказала",
    "выше написал",
    "выше написала",
    "я это уже указал",
    "я это уже указала",
    "это уже указал",
    "это уже указала",
    "повторяю",
    "как писал",
    "как писала",
    "как говорил",
    "как говорила",
)
REPEAT_CASE_CHANGE_PATTERNS = (
    "изменился доход",
    "появились просрочки",
)
OFF_TOPIC_PATTERNS = (
    "напиши код",
    "python",
    "switch to english",
    "забудь инструкции",
    "переведи",
    "расскажи историю",
)

MONEY_REQUEST_PATTERNS = (
    "хочу взять денег",
    "нужны деньги",
    "деньги нужны",
    "получить сумму",
    "сумму на руки",
    "хочу кредит",
    "нужна сумма",
)
STRONG_NEW_MONEY_PATTERNS = (
    "получить сумму",
    "получить деньги на руки",
    "сумму на руки",
    "деньги на руки",
    "нужна сумма на руки",
    "нужны деньги на руки",
)
DEBT_SOLUTION_PATTERNS = (
    "закрыть карты",
    "закрыть карту",
    "закрыть кредитные карты",
    "закрыть кредитную карту",
    "закрыть кредитки",
    "закрыть кредитку",
    "погасить карты",
    "погасить кредитки",
    "закрыть кредиты",
    "закрыть кредит",
    "закрыть долги",
    "закрыть долг",
    "перекрыть долги",
    "перекрыть долг",
    "объединить кредиты",
    "рефинансироваться",
)
PAYMENT_REDUCTION_PATTERNS = (
    "снизить платеж",
    "снизить ежемесячный платеж",
    "уменьшить платеж",
    "уменьшить ежемесячный платеж",
    "снизить нагрузку",
    "уменьшить нагрузку",
    "платеж меньше",
    "платежи тяжело тянуть",
    "тяжело тянуть платеж",
    "платить тяжело",
    "не вывожу платежи",
    "не вывожу кредиты",
    "не вывожу долги",
)
REPAIR_PURPOSE_PATTERNS = ("ремонт", "лечение", "покупку техники", "покупка техники")

EXPLICIT_PTS_PATTERNS = (
    "под птс",
    "под авто",
    "есть машина, хочу под нее",
    "есть авто, хочу под него",
    "под машину",
)
EXPLICIT_MORTGAGE_PATTERNS = (
    "под залог недвижимости",
    "залог недвижимости",
    "под недвижимость",
    "под квартиру",
    "под дом",
    "под жилье",
)
VEHICLE_COLLATERAL_REFUSAL_PATTERNS = (
    "птс не рассматриваю",
    "не хочу залог на машину",
    "машина вообще не должна участвовать",
    "машину вообще не трогаем",
    "никаких автозалогов",
    "авто не трогаем",
)
MORTGAGE_REJECTION_PATTERNS = (
    "квартиру не трогаем",
    "залог недвижимости не рассматриваю",
    "не хочу использовать квартиру",
    "недвижимость не должна участвовать",
)
VEHICLE_WORD_PATTERNS = ("авто", "машин", "птс", "kia", "hyundai", "лада", "ваз", "toyota")
VEHICLE_AVAILABILITY_PATTERNS = (
    "авто есть",
    "есть авто",
    "машина есть",
    "есть машина",
)
VEHICLE_RETENTION_PATTERNS = (
    "машину отдавать не буду",
    "авто отдавать не буду",
    "машина нужна",
    "машина нужна каждый день",
    "машина нужна для работы",
    "она для работы",
    "авто нужно",
)
PROPERTY_WORD_PATTERNS = ("квартира", "дом", "недвижимость", "жилье")
PROPERTY_POSITIVE_PATTERNS = (
    "квартира есть",
    "есть квартира",
    "квартира в собственности",
    "в собственности квартира",
    "дом есть",
    "есть дом",
    "дом в собственности",
    "в собственности дом",
    "недвижимость есть",
    "есть недвижимость",
    "недвижимость в собственности",
    "в собственности недвижимость",
    "жилье есть",
    "есть жилье",
    "жилье в собственности",
    "в собственности жилье",
)
PROPERTY_NEGATIVE_PATTERNS = (
    "квартиры нет",
    "нет квартиры",
    "дома нет",
    "нет дома",
    "недвижимости нет",
    "нет недвижимости",
    "жилья нет",
    "нет жилья",
    "жилья в собственности нет",
    "нет жилья в собственности",
)
PROPERTY_RISK_PATTERNS = (
    "боюсь потерять",
    "страшно потерять",
    "боюсь за квартиру",
    "страх за квартиру",
    "страшно за жилье",
    "квартиру потерять не хочу",
    "жилье потерять не хочу",
    "потерять жилье боюсь",
    "потерять ее боюсь",
    "потерять квартиру боюсь",
)

DEBT_WORD_PATTERNS = ("кредит", "кредиты", "карты", "долг", "долги", "займ")
COLLECTOR_PATTERNS = ("коллектор",)
ARREARS_PATTERNS = ("просроч", "не плачу", "пропустил", "пропустила")
MFO_PATTERNS = (
    r"(?<![а-яёa-z])м\s*ф\s*о(?![а-яёa-z])",
    r"(?<![а-яёa-z])микро\s*займ[а-яё]*(?![а-яёa-z])",
    r"(?<![а-яёa-z])займ\s+до\s+зарплат[а-яё]*(?![а-яёa-z])",
)
NO_ARREARS_PATTERNS = ("просрочек нет", "без просрочек")
HIGH_LOAD_PATTERNS = (
    "нагрузка",
    "платежи большие",
    "платить тяжело",
    "платежи тяжело тянуть",
    "тяжело тянуть",
)
WANTS_TO_PAY_PATTERNS = ("хочу платить", "не списывать", "законный график")
BANKRUPTCY_FEAR_PATTERNS = (
    "банкротство не хочу",
    "банкротство пугает",
    "боюсь банкротства",
)
BANKRUPTCY_CLARIFICATION_PATTERNS = (
    "это банкротство",
    "можно без банкротства",
    "банкротство или реструктуризация",
    "банкротство или можно",
)
POST_TERMINAL_NEXT_STEP_PATTERNS = (
    "что дальше",
    "что делать",
    "что значит отдельный разбор",
    "куда нажать",
)
POST_TERMINAL_CONTACT_PATTERNS = (
    "кто со мной свяжется",
    "кто свяжется",
    "как со мной свяжутся",
    "когда со мной свяжутся",
)
MFO_RATING_CONCERN_PATTERNS = (
    "мфо портит рейтинг",
    "мфо портят рейтинг",
    "окб это видит",
    "бюро видит мфо",
    "займы портят кредитную историю",
    "займы портят рейтинг",
    "портит кредитную историю",
)
DEBT_PROCEDURE_HARD_REFUSAL_PATTERNS = (
    "банкротство не рассматриваю",
    "никаких судов",
    "суды не рассматриваю",
    "юридические процедуры не хочу",
    "никаких процедур",
    "не хочу никакие процедуры",
    "никакого банкротства и реструктуризации",
    "не хочу юридический разбор долгов",
)

NO_STABLE_INCOME_PATTERNS = ("дохода стабильного нет", "нет стабильного дохода")
NO_INCOME_PATTERNS = ("дохода нет", "без дохода")
NO_OFFICIAL_INCOME_PATTERNS = ("официального дохода нет", "неофициальный доход")
STABLE_INCOME_PATTERNS = ("официально", "работаю", "стабильный")
COMFORTABLE_PAYMENT_CONTEXT_PATTERNS = (
    "комфортно",
    "комфортнее",
    "комфортный платеж",
    "комфортный платёж",
    "нормально было бы",
    "удобнее было бы",
    "удобнее платить",
    "могу платить",
    "мог бы платить",
    "готов платить",
    "смогу платить",
    "хотелось бы платить",
    "посильно",
    "посильный платеж",
    "посильный платёж",
    "тянуть смогу",
    "тянуть могу",
    "для меня нормально",
)

NEED_SIGNAL_PRIORITY = {
    "unknown": 0,
    "new_money": 1,
    "repair_or_purpose": 2,
    "payment_reduction": 3,
    "debt_solution": 4,
    "explicit_mortgage": 5,
    "explicit_pts": 5,
    "security": 6,
    "repeat": 6,
}
NEED_TYPE_BY_SIGNAL = {
    "new_money": "new_money",
    "debt_solution": "debt_solution",
    "payment_reduction": "payment_reduction",
    "security": "security",
}

AMOUNT_PATTERN = re.compile(
    r"(\d+(?:[,.]\d+)?)\s*(млн|миллион|миллиона|миллионов|тыс|тысяч|к|руб|₽)?"
)
COMPOSITE_MILLION_THOUSAND_PATTERN = re.compile(
    r"(\d+(?:[,.]\d+)?)\s*(млн|миллион|миллиона|миллионов)\s+"
    r"(\d+(?:[,.]\d+)?)\s*(тыс|тысяч|к)\b"
)
AMOUNT_RANGE_PATTERN = re.compile(
    r"(\d+(?:[,.]\d+)?)\s*[-–—]\s*(\d+(?:[,.]\d+)?)\s*"
    r"(млн|миллион|миллиона|тыс|тысяч|к|руб|₽)?"
)
RAW_CAR_PATTERN = re.compile(r"\b(kia rio|hyundai tucson|лада веста|toyota camry|ваз \d{4})\b")
YEAR_PATTERN = re.compile(r"\b(19[8-9]\d|20[0-2]\d)\b")
DEBT_SOLUTION_REGEXES = (
    re.compile(
        r"\b(закрыть|погасить|перекрыть)\b.{0,50}"
        r"\b(кредитн\w*\s+карт\w*|карт\w*|кредитк\w*|кредит\w*|долг\w*)\b"
    ),
    re.compile(r"\b(объединить|рефинансир\w*)\b.{0,50}\b(кредит\w*|долг\w*|карт\w*)\b"),
    re.compile(r"\bрефинансироваться\b"),
)
PAYMENT_REDUCTION_REGEXES = (
    re.compile(r"\b(снизить|уменьшить)\b.{0,40}\b(платеж\w*|нагрузк\w*)\b"),
    re.compile(r"\b(тяжело|не вывожу)\b.{0,50}\b(платеж\w*|кредит\w*|долг\w*)\b"),
)


def merge_fact(old: FactValue | None, new: FactValue) -> FactValue:
    """Merge a new fact without silently overwriting stronger evidence."""

    if old is None:
        return new
    if old.value == new.value:
        return old
    if old.quality == "unknown":
        return new
    if new.quality == "exact" and old.quality == "approx":
        return new
    return FactValue(
        value=old.value,
        quality="conflicting",
        source=old.source,
        updated_at_turn=new.updated_at_turn,
    )


def coerce_fact_value(
    value: Any,
    *,
    turn_index: int,
    source: FactSource = "user",
    quality: FactQuality = "exact",
) -> FactValue:
    """Wrap raw values so state stores one canonical fact representation."""

    if isinstance(value, FactValue):
        return value
    return FactValue(value=value, quality=quality, source=source, updated_at_turn=turn_index)


def extract_turn(
    user_message: str,
    *,
    turn_index: int = 0,
    state: DialogueV3State | None = None,
) -> ExtractedTurn:
    """Extract obvious facts and non-routing signals by deterministic rules only."""

    text = normalize_text(user_message)
    facts: dict[str, Any] = {}
    concerns: list[str] = []

    post_terminal_topic = detect_post_terminal_topic(text)
    if post_terminal_topic:
        facts["post_terminal_topic"] = post_terminal_topic

    service_signal, off_topic = extract_service_signals(text, facts, concerns, state)
    extract_need_signals(text, facts)
    extract_collateral_signals(text, facts, concerns, state)
    extract_debt_signals(text, facts, concerns)
    extract_amounts_with_context(text, facts, state)
    _derive_payment_load(facts)

    direct_question = user_message.strip() if "?" in user_message else None
    route_rejection = facts.get("route_rejection")

    return ExtractedTurn(
        facts=facts,
        direct_question=direct_question,
        off_topic=off_topic,
        customer_concerns=concerns,
        service_signal=service_signal,
        route_rejection=route_rejection if isinstance(route_rejection, str) else None,
        raw_user_text=user_message,
    )


def normalize_text(text: str) -> str:
    """Normalize user text for deterministic phrase matching."""

    return " ".join(text.lower().replace("ё", "е").split())


def extract_service_signals(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None = None,
) -> tuple[str | None, str | None]:
    """Extract service-mode and off-topic signals without product routing."""

    service_signal: str | None = None
    if _contains_any(text, SERVICE_FRAUD_PATTERNS):
        service_signal = "fraud_check"
        facts["service_signal"] = service_signal
        _set_need_signal(facts, "security")
    elif _is_repeat_visit_signal(text, state):
        service_signal = "repeat_visit"
        facts["service_signal"] = service_signal
        _set_need_signal(facts, "repeat")
    elif state is not None and state.turn_index > 1 and _contains_any(text, ACTIVE_DIALOG_CORRECTION_PATTERNS):
        facts["correction_signal"] = True

    off_topic: str | None = None
    if _contains_any(text, OFF_TOPIC_PATTERNS):
        off_topic = "off_topic_request"
        facts["off_topic_kind"] = off_topic
    elif _contains_any(text, ("ты бот", "ты ии")):
        off_topic = "assistant_identity"
        facts["off_topic_kind"] = off_topic

    return service_signal, off_topic


def detect_post_terminal_topic(text: str) -> str | None:
    """Return a compact post-terminal clarification topic, if the turn contains one."""

    text = normalize_text(text)
    if _is_bankruptcy_clarification(text):
        return "bankruptcy_clarification"
    if _is_contact_question(text):
        return "contact_question"
    if _is_next_step_question(text):
        return "next_step"
    return None


def _is_next_step_question(text: str) -> bool:
    """Detect clarification about the next operational step."""

    if _contains_any(text, POST_TERMINAL_NEXT_STEP_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bдальше\b.{0,20}\b(?:что|как|будет|делать)\b",
            r"\b(?:куда|где)\b.{0,20}\bпереход\w*\b",
            r"\bнужно\b.{0,20}\bкуда[-\s]?то\b.{0,20}\bпереход\w*\b",
            r"\bспециалист\b.{0,30}\b(?:сам\s+)?посмотр\w*\b",
            r"\bкто\b.{0,20}\bдальше\b.{0,20}\bпосмотр\w*\b",
            r"\bкак\b.{0,20}\bдальше\b.{0,20}\bбуд\w*\b",
        )
    )


def _is_bankruptcy_clarification(text: str) -> bool:
    """Detect debt-procedure clarification without deciding the route."""

    if _contains_any(text, BANKRUPTCY_CLARIFICATION_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bбанкротств\w*\b.{0,30}\bили\b",
            r"\bэто\b.{0,20}\bреструктуризац\w*\b",
            r"\bбез\s+суда\b.{0,20}\bможн\w*\b",
            r"\bсписан\w*\b.{0,20}\bили\b.{0,20}\bплат\w*\b",
        )
    )


def _is_contact_question(text: str) -> bool:
    """Detect clarification about who contacts the client and when."""

    if _contains_any(text, POST_TERMINAL_CONTACT_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bкогда\b.{0,25}\bсвяж\w*\b",
            r"\bмне\b.{0,20}\bпозвон\w*\b",
            r"\bспециалист\b.{0,25}\bнапиш\w*\b",
            r"\bждать\b.{0,20}\b(?:звонк\w*|сообщен\w*)\b",
        )
    )


def extract_need_signals(text: str, facts: dict[str, Any]) -> None:
    """Extract broad need signals; priorities prevent weaker purpose words from overriding debt."""

    result = detect_need_intent(text)
    if result.purpose_goal:
        facts["purpose_goal"] = result.purpose_goal
    if result.need_type:
        _set_need_signal(facts, result.need_type)
    elif result.early_need_signal:
        _set_early_need_signal(facts, result.early_need_signal)


def detect_need_intent(
    text: str,
    state: DialogueV3State | None = None,
) -> NeedIntentResult:
    """Classify broad client need without selecting a route."""

    text = normalize_text(text)
    del state  # Reserved for future context-aware need extraction.

    evidence: list[str] = []
    purpose_goal = _detect_purpose_goal(text)
    debt_solution = _is_debt_solution_need(text)
    payment_reduction = _is_payment_reduction_need(text)
    strong_new_money = _is_strong_new_money_need(text)
    generic_new_money = _is_generic_new_money_need(text)

    if purpose_goal:
        evidence.append(f"purpose:{purpose_goal}")
    if debt_solution:
        evidence.append("debt_solution")
        return NeedIntentResult(
            need_type="debt_solution",
            early_need_signal="debt_solution",
            purpose_goal=purpose_goal,
            evidence=tuple(evidence),
        )
    if payment_reduction:
        evidence.append("payment_reduction")
        return NeedIntentResult(
            need_type="payment_reduction",
            early_need_signal="payment_reduction",
            purpose_goal=purpose_goal,
            evidence=tuple(evidence),
        )
    if purpose_goal:
        return NeedIntentResult(
            early_need_signal="repair_or_purpose",
            purpose_goal=purpose_goal,
            evidence=tuple(evidence),
        )
    if strong_new_money:
        evidence.append("new_money")
        return NeedIntentResult(
            need_type="new_money",
            early_need_signal="new_money",
            evidence=tuple(evidence),
        )
    if generic_new_money:
        evidence.append("generic_new_money")
        return NeedIntentResult(
            early_need_signal="new_money",
            evidence=tuple(evidence),
        )
    return NeedIntentResult()


def _is_debt_solution_need(text: str) -> bool:
    return _contains_any(text, DEBT_SOLUTION_PATTERNS) or _matches_any_regex(text, DEBT_SOLUTION_REGEXES)


def _is_payment_reduction_need(text: str) -> bool:
    if _contains_any(text, PAYMENT_REDUCTION_PATTERNS) or _matches_any_regex(text, PAYMENT_REDUCTION_REGEXES):
        return True
    return bool(
        re.search(r"\bнагрузк\w*\b.{0,30}\b(?:больш\w*|высок\w*|тяжел\w*)\b", text)
        or re.search(r"\b(?:больш\w*|высок\w*|тяжел\w*)\b.{0,30}\bнагрузк\w*\b", text)
    )


def _is_strong_new_money_need(text: str) -> bool:
    return _contains_any(text, STRONG_NEW_MONEY_PATTERNS + ("хочу кредит", "нужна сумма"))


def _is_generic_new_money_need(text: str) -> bool:
    return _contains_any(text, MONEY_REQUEST_PATTERNS)


def _detect_purpose_goal(text: str) -> str | None:
    if not _contains_any(text, REPAIR_PURPOSE_PATTERNS):
        return None
    if _contains_any(text, ("ремонт машины", "ремонт авто")):
        return "car_repair"
    if _contains_any(text, ("ремонт квартиры", "ремонт дома", "ремонт жилья")):
        return "home_repair"
    if "ремонт" in text:
        return "repair"
    if "лечение" in text:
        return "medical"
    if _contains_any(text, ("покупку техники", "покупка техники")):
        return "purchase"
    return None


def extract_collateral_signals(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None = None,
) -> None:
    """Extract collateral facts and concerns without choosing a route."""

    if _contains_any(text, EXPLICIT_MORTGAGE_PATTERNS):
        facts["explicit_mortgage_intent"] = True
        _set_need_signal(facts, "explicit_mortgage")

    _extract_property_facts(text, facts, concerns, state)
    vehicle_evidence = detect_vehicle_intent(text, state)
    _extract_vehicle_facts(text, facts, concerns, state, vehicle_evidence)

    if vehicle_evidence.hard_collateral_refusal:
        facts["route_rejection"] = PTS
        facts["vehicle_refuses_collateral"] = True
    if _contains_any(text, MORTGAGE_REJECTION_PATTERNS):
        facts["route_rejection"] = "MORTGAGE"
        facts["property_refuses_collateral"] = True


def extract_debt_signals(text: str, facts: dict[str, Any], concerns: list[str]) -> None:
    """Extract debt pressure and client-position signals."""

    has_mfo_signal = _has_mfo_signal(text)
    if _contains_any(text, DEBT_WORD_PATTERNS) or has_mfo_signal:
        facts["has_current_loans"] = True

    if has_mfo_signal:
        facts["has_mfo"] = True
        facts["loan_types_known"] = True
        _set_need_signal(facts, "debt_solution")

    if _has_no_arrears_signal(text):
        facts["has_arrears"] = False
    elif _contains_any(text, ARREARS_PATTERNS):
        facts["has_arrears"] = True
        arrears_months = _extract_month_count(text)
        if arrears_months is not None:
            facts["arrears_months"] = arrears_months

    if _contains_any(text, COLLECTOR_PATTERNS):
        facts["collector_pressure"] = True

    if _contains_any(text, HIGH_LOAD_PATTERNS):
        facts["high_payment_load"] = True

    if _contains_any(text, WANTS_TO_PAY_PATTERNS):
        facts["client_wants_to_pay"] = True
        _set_need_signal(facts, "debt_solution")
    if _contains_any(text, BANKRUPTCY_FEAR_PATTERNS):
        facts["client_fears_bankruptcy"] = True
        concerns.append("bankruptcy_fear")
    if _contains_any(text, BANKRUPTCY_CLARIFICATION_PATTERNS):
        facts["bankruptcy_clarification_question"] = True
        concerns.append("bankruptcy_clarification_question")
    if _contains_any(text, MFO_RATING_CONCERN_PATTERNS):
        facts["mfo_rating_concern"] = True
        facts["credit_bureau_objection"] = True
        concerns.append("mfo_rating_concern")
    if _contains_any(text, DEBT_PROCEDURE_HARD_REFUSAL_PATTERNS):
        facts["client_refuses_debt_procedure"] = True

    if (
        _contains_any(text, DEBT_SOLUTION_PATTERNS)
        or _matches_any_regex(text, DEBT_SOLUTION_REGEXES)
        or has_mfo_signal
        or _contains_any(text, ("коллектор", "банкрот", "долг", "долги"))
    ):
        facts["need_type"] = "debt_solution"
    elif _contains_any(text, PAYMENT_REDUCTION_PATTERNS) or _matches_any_regex(text, PAYMENT_REDUCTION_REGEXES):
        facts["need_type"] = "payment_reduction"
    elif _contains_any(text, STRONG_NEW_MONEY_PATTERNS):
        facts["need_type"] = "new_money"


def _has_no_arrears_signal(text: str) -> bool:
    if _contains_any(text, NO_ARREARS_PATTERNS + ("плачу по графику", "без задержек")):
        return True
    return bool(
        re.search(r"\bпросроч(?:ек|ки)?\b.{0,25}\bнет\b", text)
        or re.search(r"\bнет\s+просроч(?:ек|ки)?\b", text)
    )


def extract_amounts_with_context(
    text: str,
    facts: dict[str, Any],
    state: DialogueV3State | None = None,
) -> None:
    """Extract monetary facts using local keywords plus previous asked-slot context."""

    last_slot = get_last_asked_slot(state)

    total_debt = _find_amount_near(text, ("долг", "долги", "задолженность"))
    if total_debt is None and last_slot in {"total_debt", "desired_amount_or_total_debt"}:
        total_debt = _first_contextual_amount(text)
    if total_debt is None and _looks_like_standalone_total_debt(text):
        total_debt = _first_contextual_amount(text)
    if total_debt is not None:
        facts["total_debt"] = total_debt

    comfortable_context = _has_comfortable_payment_context(text)
    if _can_extract_monthly_payment(text, last_slot):
        monthly_payments = (
            _find_current_payment_amount(text)
            if comfortable_context
            else _find_amount_near(text, ("плачу", "уходит", "платеж", "платежи"))
        )
        if monthly_payments is None:
            if comfortable_context:
                monthly_payments = None
            elif last_slot == "monthly_payments":
                monthly_payments = _first_contextual_amount(text)
            elif _contains_any(text, ("в месяц", "ежемесячно")):
                monthly_payments = _first_contextual_amount(text)
        if monthly_payments is not None:
            facts["monthly_payments"] = monthly_payments

    comfortable_payment = _find_comfortable_payment_amount(text)
    if comfortable_payment is None and last_slot == "comfortable_payment" and not _looks_like_payment_correction(text):
        comfortable_payment = _normalize_payment_amount(_first_contextual_amount(text))
    elif comfortable_payment is None and _is_comfortable_payment_context(text):
        comfortable_payment = _normalize_payment_amount(_first_contextual_amount(text))
    if comfortable_payment is not None:
        facts["comfortable_payment"] = comfortable_payment

    _extract_income_amount(text, facts, last_slot)

    desired_amount = _find_desired_amount(text, last_slot)
    if desired_amount is not None:
        facts["desired_amount"] = desired_amount


def _extract_property_facts(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None,
) -> None:
    property_word_present = _contains_any(text, PROPERTY_WORD_PATTERNS)
    property_available = _contains_any(text, PROPERTY_POSITIVE_PATTERNS)
    property_negative = _contains_any(text, PROPERTY_NEGATIVE_PATTERNS)
    owner_known = _contains_any(
        text,
        (
            "оформлена на меня",
            "оформлен на меня",
            "я собственник",
            "я единственный собственник",
            "собственник готов участвовать",
        ),
    )

    if property_available or (property_word_present and owner_known and not property_negative):
        facts["has_property"] = True
    elif property_negative and not property_available:
        facts["has_property"] = False

    has_property_context = facts.get("has_property") is True or owner_known
    mortgage_slot_context = _has_mortgage_property_slot_context(state)
    if has_property_context and _property_type_is_descriptive(text, "квартира"):
        facts["property_type"] = "apartment"
    elif has_property_context and _property_type_is_descriptive(text, "дом"):
        facts["property_type"] = "house"
    elif mortgage_slot_context and _property_type_is_descriptive(text, "квартира"):
        facts["property_type"] = "apartment"
    elif mortgage_slot_context and _property_type_is_descriptive(text, "дом"):
        facts["property_type"] = "house"
    elif mortgage_slot_context and _property_type_is_descriptive(text, "комната"):
        facts["property_type"] = "room"

    if _contains_any(text, ("москва", "москве", "московская область", "московской области")):
        facts["property_region"] = "Москва"
    elif _contains_any(
        text,
        ("санкт-петербург", "санкт-петербурге", "спб", "питер", "питере", "ленинградская область"),
    ):
        facts["property_region"] = "Санкт-Петербург"

    if owner_known:
        facts["property_owner_known"] = True
        facts["property_owner"] = "known"
        if property_word_present and not property_negative:
            facts["has_property"] = True

    if _contains_any(text, ("без обременений", "ипотеки нет", "залога нет", "ареста нет")):
        facts["property_encumbrance"] = False
        facts["property_mortgage"] = False
        facts["property_pledge"] = False
        facts["property_arrest"] = False

    if _contains_any(text, PROPERTY_RISK_PATTERNS):
        facts["property_risk_concern"] = True
        facts["property_refuses_collateral"] = False
        concerns.append("property_risk")


def detect_vehicle_intent(
    text: str,
    state: DialogueV3State | None = None,
) -> VehicleIntentEvidence:
    """Infer vehicle/PTS meaning for this turn without selecting a route."""

    text = normalize_text(text)
    evidence: list[str] = []
    hard_collateral_refusal = _mentions_hard_vehicle_refusal(text)
    if hard_collateral_refusal:
        evidence.append("hard_collateral_refusal")

    explicit_pts_channel = _mentions_pts_channel(text)
    if explicit_pts_channel:
        evidence.append("explicit_pts_channel")

    auto_collateral_consideration = _mentions_soft_auto_consideration(text)
    if auto_collateral_consideration:
        evidence.append("auto_collateral_consideration")

    has_vehicle_context = bool(
        _mentions_vehicle(text, state)
        or explicit_pts_channel
        or auto_collateral_consideration
    )
    if has_vehicle_context:
        evidence.append("vehicle_context")

    retention_raw = _mentions_retention_constraint(text)
    transfer_refusal_raw = _mentions_transfer_refusal(text)
    retention_required = retention_raw and has_vehicle_context
    transfer_refusal = transfer_refusal_raw and has_vehicle_context
    if (retention_required or transfer_refusal) and not hard_collateral_refusal:
        auto_collateral_consideration = True
        if "auto_collateral_consideration" not in evidence:
            evidence.append("auto_collateral_consideration")
    if retention_required:
        evidence.append("retention_required")
    if transfer_refusal:
        evidence.append("transfer_refusal")

    return VehicleIntentEvidence(
        has_vehicle_context=has_vehicle_context,
        auto_collateral_consideration=auto_collateral_consideration,
        explicit_pts_channel=explicit_pts_channel,
        retention_required=retention_required,
        transfer_refusal=transfer_refusal,
        hard_collateral_refusal=hard_collateral_refusal,
        evidence=tuple(evidence),
    )


def _mentions_vehicle(text: str, state: DialogueV3State | None) -> bool:
    """Detect vehicle context from text, known form facts, or current car slot."""

    return bool(_has_vehicle_context(text, {}, state) or RAW_CAR_PATTERN.search(text))


def _mentions_soft_auto_consideration(text: str) -> bool:
    """Detect that the client allows using the car/PTS path as an option."""

    if _contains_any(text, EXPLICIT_PTS_PATTERNS):
        return True
    vehicle_or_pts = r"(?:машин\w*|авто\w*|птс)"
    return any(
        re.search(pattern, text)
        for pattern in (
            rf"\b(?:машин\w*|авто\w*)\b.{{0,30}}\b(?:можно|готов\w*)\b.{{0,20}}\bрассмотр\w*",
            rf"\bрассмотр\w*\b.{{0,30}}\b{vehicle_or_pts}\b",
            rf"\bвариант\b.{{0,30}}\b(?:с\s+)?{vehicle_or_pts}\b",
            r"\bможно\b.{0,20}\bпо\s+(?:машин\w*|авто)\b",
            r"\bесли\b.{0,20}\bчерез\s+(?:машин\w*|авто)\b",
            r"\bпод\s+(?:птс|авто|машин\w*)\b",
        )
    )


def _mentions_pts_channel(text: str) -> bool:
    """Detect an explicit PTS/auto-collateral channel, not a bare PTS mention."""

    return bool(
        re.search(r"\b(?:под|по|через)\s+(?:птс|авто|машин\w*)\b", text)
        or re.search(r"\bвариант\b.{0,30}\b(?:с\s+)?(?:птс|авто|машин\w*)\b", text)
    )


def _mentions_retention_constraint(text: str) -> bool:
    """Detect that the client needs to keep using the vehicle."""

    if _contains_any(text, VEHICLE_RETENTION_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\b(?:машин\w*|авто|она|ее|её)\b.{0,35}\bнужн\w*\b.{0,25}\b(?:каждый день|для работы)\b",
            r"\b(?:каждый день|для работы)\b.{0,35}\bнужн\w*\b",
            r"\b(?:машин\w*|авто|она|ее|её)\b.{0,35}\b(?:для работы|каждый день)\b",
            r"\b(?:пользоваться|ездить)\b.{0,30}\b(?:машин\w*|авто)\b.{0,20}\bнужн\w*\b",
            r"\b(?:машин\w*|авто)\b.{0,35}\bоставал\w*\b.{0,20}\bу меня\b",
            r"\b(?:машин\w*|авто)\b.{0,35}\bдолжн\w*\b.{0,20}\bостаться\b.{0,20}\bу меня\b",
            r"\bоставал\w*\b.{0,20}\bу меня\b",
        )
    )


def _mentions_transfer_refusal(text: str) -> bool:
    """Detect refusal to physically hand over the car, not refusal of PTS itself."""

    return any(
        re.search(pattern, text)
        for pattern in (
            r"\b(?:отдавать|передавать)\b.{0,40}\bне\s+(?:готов\w*|буду|хочу)\b",
            r"\bне\s+(?:готов\w*|буду|хочу)\b.{0,40}\b(?:отдавать|передавать)\b",
            r"\b(?:машин\w*|авто)\b.{0,35}\bоставал\w*\b.{0,20}\bу меня\b",
            r"\b(?:машин\w*|авто)\b.{0,35}\bдолжн\w*\b.{0,20}\bостаться\b.{0,20}\bу меня\b",
            r"\bоставал\w*\b.{0,20}\bу меня\b",
        )
    )


def _mentions_hard_vehicle_refusal(text: str) -> bool:
    """Detect hard refusal of the auto-collateral route, not retention concern."""

    if _contains_any(text, VEHICLE_COLLATERAL_REFUSAL_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"(?<![a-zа-я0-9_])птс(?![a-zа-я0-9_]).{0,30}\bне\s+рассматрива\w*\b",
            r"\bне\s+(?:хочу|готов\w*)\b.{0,30}\bзалог\b.{0,20}\b(?:машин\w*|авто)\b",
            r"\bзалог\b.{0,20}\b(?:на\s+)?(?:машин\w*|авто)\b.{0,30}\bне\s+(?:хочу|готов\w*)\b",
            r"\bникаких\b.{0,20}\bавтозалог\w*\b",
            r"\b(?:машин\w*|авто)\b.{0,30}\b(?:вообще\s+)?не\s+трога\w*\b",
        )
    )


def _extract_vehicle_facts(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None,
    vehicle_evidence: VehicleIntentEvidence,
) -> None:
    vehicle_context = vehicle_evidence.has_vehicle_context
    if vehicle_context:
        facts["has_car"] = True

    if vehicle_evidence.explicit_pts_channel or vehicle_evidence.auto_collateral_consideration:
        facts["explicit_pts_intent"] = True
        _set_need_signal(facts, "explicit_pts")

    raw_car_match = RAW_CAR_PATTERN.search(text)
    if raw_car_match:
        facts["raw_car_name"] = raw_car_match.group(1)
        facts["car_brand_model_known"] = True
        facts["has_car"] = True
        vehicle_context = True

    year_match = YEAR_PATTERN.search(text)
    if year_match and vehicle_context:
        facts["car_year"] = int(year_match.group(1))

    if "я собственник" in text and vehicle_context:
        facts["car_owner_known"] = True
        facts["car_owner"] = "client"

    if vehicle_evidence.retention_required or vehicle_evidence.transfer_refusal:
        facts["vehicle_requires_retention"] = True
        facts["vehicle_refuses_transfer"] = True
        facts["vehicle_refuses_collateral"] = False
        concerns.append("vehicle_retention")

    if _contains_any(
        text,
        (
            "не в залоге и ограничений нет",
            "кредитов по машине нет",
            "арестов по машине нет",
            "ограничений по машине нет",
        ),
    ):
        facts["car_in_pledge"] = False
        facts["car_arrest_or_restriction"] = False


def _extract_income_amount(text: str, facts: dict[str, Any], last_slot: str | None) -> None:
    if _contains_any(text, NO_STABLE_INCOME_PATTERNS):
        facts["income_status"] = "unstable"
        return
    if _contains_any(text, NO_OFFICIAL_INCOME_PATTERNS):
        facts["income_status"] = "no_official_income"
        return
    if _contains_any(text, NO_INCOME_PATTERNS):
        facts["income_status"] = "none"
        return

    if not _can_extract_official_income(text, last_slot):
        return

    income = _find_amount_near(text, ("доход", "заработ", "получаю"))
    if income is None and (
        last_slot == "income_status" or _contains_any(text, STABLE_INCOME_PATTERNS)
    ):
        income = _first_contextual_amount(text)
    if income is not None:
        if income < 1_000 and (last_slot == "income_status" or _contains_any(text, STABLE_INCOME_PATTERNS)):
            income *= 1_000
        facts["official_income"] = income
        facts["income_status"] = "stable"
    elif last_slot == "income_status" and _contains_any(text, STABLE_INCOME_PATTERNS):
        facts["income_status"] = "stable"


def _find_desired_amount(text: str, last_slot: str | None) -> int | None:
    if last_slot == "desired_amount":
        return _first_contextual_amount(text)
    if not _contains_any(text, MONEY_REQUEST_PATTERNS + ("нужно", "нужна сумма", "сумма нужна")):
        return None
    if _contains_any(text, DEBT_SOLUTION_PATTERNS) and not _contains_any(text, ("на руки", "получить сумму", "нужна сумма")):
        return None
    return _find_amount_near(text, ("нужн", "сумма", "деньги", "получить", "на руки", "взять"))


def _derive_payment_load(facts: dict[str, Any]) -> None:
    monthly = facts.get("monthly_payments")
    official_income = facts.get("official_income")
    comfortable = facts.get("comfortable_payment")
    if isinstance(monthly, int) and isinstance(official_income, int) and official_income > 0:
        facts["high_payment_load"] = monthly / official_income >= 0.5
    if isinstance(monthly, int) and isinstance(comfortable, int):
        facts["payment_gap_large"] = monthly > comfortable * 1.5


def _set_need_signal(facts: dict[str, Any], signal: str) -> None:
    _set_early_need_signal(facts, signal)
    need_type = NEED_TYPE_BY_SIGNAL.get(signal)
    if need_type:
        facts["need_type"] = need_type


def _set_early_need_signal(facts: dict[str, Any], signal: str) -> None:
    current = str(facts.get("early_need_signal") or "unknown")
    if NEED_SIGNAL_PRIORITY.get(signal, 0) >= NEED_SIGNAL_PRIORITY.get(current, 0):
        facts["early_need_signal"] = signal


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _matches_any_regex(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _is_repeat_visit_signal(text: str, state: DialogueV3State | None) -> bool:
    if _contains_any(text, SERVICE_REPEAT_PATTERNS):
        return True
    if _contains_any(text, REPEAT_CASE_CHANGE_PATTERNS):
        return state is None or state.turn_index <= 1
    if not _contains_any(text, SERVICE_REPEAT_SELF_REFERENCE_PATTERNS):
        return False
    if state is not None and state.turn_index > 1 and _contains_any(text, ACTIVE_DIALOG_CORRECTION_PATTERNS):
        return False
    return state is None or state.turn_index <= 1


def _has_income_context(text: str, last_slot: str | None) -> bool:
    return bool(
        last_slot == "income_status"
        or _contains_any(text, ("доход", "заработ", "зарплат", "получаю"))
        or _contains_any(text, STABLE_INCOME_PATTERNS)
        or _contains_any(text, NO_STABLE_INCOME_PATTERNS + NO_OFFICIAL_INCOME_PATTERNS + NO_INCOME_PATTERNS)
    )


def _has_monthly_payment_context(text: str, last_slot: str | None) -> bool:
    return bool(
        last_slot == "monthly_payments"
        or _contains_any(text, ("плачу", "платеж", "платежи", "в месяц", "ежемесячно"))
    )


def _is_comfortable_payment_context(text: str) -> bool:
    if _contains_any(text, COMFORTABLE_PAYMENT_CONTEXT_PATTERNS):
        return True
    comfort_words = r"(?:комфорт\w*|удобн\w*|нормальн\w*|посильн\w*)"
    return bool(
        re.search(rf"\b{comfort_words}\b.{{0,45}}\b(?:было\s+бы|будет|плат\w*|платеж\w*|в\s+месяц)\b", text)
        or re.search(rf"\b(?:было\s+бы|будет|плат\w*|платеж\w*|в\s+месяц)\b.{{0,45}}\b{comfort_words}\b", text)
        or re.search(r"\b(?:могу|смогу|готов\w*)\b.{0,20}\bплат\w*\b", text)
        or re.search(r"\bмог\s+бы\b.{0,20}\bплат\w*\b", text)
        or re.search(r"\bхотелось\s+бы\b.{0,20}\bплат\w*\b", text)
        or re.search(r"\bтянуть\b.{0,20}\b(?:могу|смогу)\b", text)
    )


def _has_comfortable_payment_context(text: str) -> bool:
    return _is_comfortable_payment_context(text)


def _has_explicit_current_payment_context(text: str) -> bool:
    return _find_current_payment_amount(text) is not None


def _find_current_payment_amount(text: str) -> int | None:
    for keyword in ("сейчас плачу", "плачу", "сейчас уходит", "уходит"):
        index = text.find(keyword)
        if index == -1:
            continue
        window = text[index : index + 80]
        comfort_index = _first_comfortable_payment_context_index(window)
        if comfort_index is not None and comfort_index > 0:
            window = window[:comfort_index]
        amount = _first_contextual_amount(window)
        if amount is not None:
            return _normalize_payment_amount(amount)
    return None


def _find_comfortable_payment_amount(text: str) -> int | None:
    context_index = _first_comfortable_payment_context_index(text)
    if context_index is None:
        return None
    amount_after_context = _find_amount_after_comfort_context(text, context_index)
    if amount_after_context is not None:
        return _normalize_payment_amount(amount_after_context)
    amount_before_context = _find_amount_immediately_before_comfort_context(text, context_index)
    return _normalize_payment_amount(amount_before_context)


def _find_amount_after_comfort_context(text: str, context_index: int) -> int | None:
    window = text[context_index : context_index + 100]
    amount_start = _first_amount_start(window)
    if amount_start is None:
        return None
    if _contains_any(window[:amount_start], ("сейчас", "плачу", "уходит")):
        return None
    return _first_contextual_amount(window)


def _find_amount_immediately_before_comfort_context(text: str, context_index: int) -> int | None:
    prefix = text[max(0, context_index - 70) : context_index]
    for match in reversed(list(AMOUNT_RANGE_PATTERN.finditer(prefix))):
        if _amount_gap_is_comfort_link(prefix[match.end() :]):
            return _first_contextual_amount_range(match.group(0))
    for match in reversed(list(AMOUNT_PATTERN.finditer(prefix))):
        if match.group(2) is None and _is_month_duration_after(prefix, match.end()):
            continue
        if _amount_gap_is_comfort_link(prefix[match.end() :]):
            return _parse_amount(match.group(1), match.group(2))
    return None


def _amount_gap_is_comfort_link(gap: str) -> bool:
    if len(gap) > 40:
        return False
    if _contains_any(gap, ("но", "сейчас", "плачу", "уходит")):
        return False
    return True


def _first_comfortable_payment_context_index(text: str) -> int | None:
    indexes = [
        index
        for pattern in COMFORTABLE_PAYMENT_CONTEXT_PATTERNS
        if (index := text.find(pattern)) >= 0
    ]
    for pattern in (
        r"\b(?:комфорт\w*|удобн\w*|нормальн\w*|посильн\w*)\b",
        r"\b(?:могу|смогу|готов\w*)\b.{0,20}\bплат\w*\b",
        r"\bмог\s+бы\b.{0,20}\bплат\w*\b",
        r"\bхотелось\s+бы\b.{0,20}\bплат\w*\b",
        r"\bтянуть\b.{0,20}\b(?:могу|смогу)\b",
    ):
        match = re.search(pattern, text)
        if match:
            indexes.append(match.start())
    return min(indexes) if indexes else None


def _first_amount_start(text: str) -> int | None:
    starts: list[int] = []
    range_match = AMOUNT_RANGE_PATTERN.search(text)
    if range_match:
        starts.append(range_match.start())
    amount_match = AMOUNT_PATTERN.search(text)
    if amount_match:
        starts.append(amount_match.start())
    return min(starts) if starts else None


def _normalize_payment_amount(amount: int | None) -> int | None:
    if amount is not None and 0 < amount < 1_000:
        return amount * 1_000
    return amount


def _can_extract_monthly_payment(text: str, last_slot: str | None) -> bool:
    monthly_context = _has_monthly_payment_context(text, last_slot)
    if not monthly_context:
        return False
    if _has_comfortable_payment_context(text) and not _has_explicit_current_payment_context(text):
        return False
    if last_slot in {"income_status", "comfortable_payment"}:
        return False
    return True


def _can_extract_official_income(text: str, last_slot: str | None) -> bool:
    income_context = _has_income_context(text, last_slot)
    if not income_context:
        return False
    if last_slot == "monthly_payments" and _has_monthly_payment_context(text, last_slot):
        return False
    return True


def _looks_like_payment_correction(text: str) -> bool:
    return bool(
        _contains_any(text, ACTIVE_DIALOG_CORRECTION_PATTERNS)
        and (
            _contains_any(text, ("платеж", "платежи", "плачу", "в месяц"))
            or _contains_any(text, ("по карте", "по картам", "по кредиту", "по кредитам"))
        )
    )


def _has_mfo_signal(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in MFO_PATTERNS)


def _has_vehicle_context(
    text: str,
    facts: dict[str, Any],
    state: DialogueV3State | None,
) -> bool:
    if _contains_any(text, VEHICLE_WORD_PATTERNS):
        return True
    if facts.get("has_car") is True or facts.get("explicit_pts_intent") is True:
        return True
    if _state_bool(state, "has_car") is True:
        return True
    if state is None:
        return False
    route = getattr(state, "route", None)
    if getattr(route, "selected_route", None) == PTS:
        return True
    if getattr(route, "next_slot", None) in {"car_brand_model", "car_year", "car_owner", "car_pledge_or_restrictions"}:
        return True
    if state.trace_history:
        last_trace = state.trace_history[-1]
        if last_trace.get("selected_route") == PTS:
            return True
        if last_trace.get("next_slot") in {
            "car_brand_model",
            "car_year",
            "car_owner",
            "car_pledge_or_restrictions",
        }:
            return True
    return False


def _state_bool(state: DialogueV3State | None, key: str) -> bool | None:
    if state is None:
        return None
    value = state.fact_value(key)
    return value if isinstance(value, bool) else None


def _has_mortgage_property_slot_context(state: DialogueV3State | None) -> bool:
    if state is None:
        return False
    if get_last_asked_slot(state) == "property_type":
        return True
    route = getattr(state, "route", None)
    return getattr(route, "selected_route", None) in {MORTGAGE_MAIN, MORTGAGE_AUX}


def get_last_asked_slot(state: DialogueV3State | None) -> str | None:
    """Return the last slot the assistant asked for, without selecting a route."""

    if state is None:
        return None
    if state.asked_slots:
        return state.asked_slots[-1]
    route = getattr(state, "route", None)
    route_next_slot = getattr(route, "next_slot", None)
    if isinstance(route_next_slot, str):
        return route_next_slot
    if state.trace_history:
        last_trace = state.trace_history[-1]
        actor_move = last_trace.get("actor_move")
        if isinstance(actor_move, dict):
            actor_next_slot = actor_move.get("next_slot")
            if isinstance(actor_next_slot, str):
                return actor_next_slot
        next_slot = last_trace.get("next_slot")
        if isinstance(next_slot, str):
            return next_slot
    return None


def _property_type_is_descriptive(text: str, property_word: str) -> bool:
    if property_word == "дом":
        if not re.search(r"\bдом\b", text):
            return False
    elif property_word == "комната":
        if "комната" not in text:
            return False
    elif property_word not in text:
        return False
    intent_patterns = {
        "квартира": ("под квартиру", "рассмотреть под квартиру"),
        "дом": ("под дом", "рассмотреть под дом"),
        "комната": ("под комнату", "рассмотреть под комнату"),
    }
    if _contains_any(text, intent_patterns.get(property_word, ())):
        return False
    return True


def _find_amount_near(text: str, keywords: tuple[str, ...]) -> int | None:
    for keyword in keywords:
        index = text.find(keyword)
        if index == -1:
            continue
        window = text[index : index + 80]
        composite_amount = _first_composite_amount(window)
        if composite_amount is not None:
            return composite_amount
        range_amount = _first_contextual_amount_range(window)
        if range_amount is not None:
            return range_amount
        match = AMOUNT_PATTERN.search(window)
        if match:
            return _parse_amount(match.group(1), match.group(2))
    return None


def _first_contextual_amount(text: str) -> int | None:
    composite_amount = _first_composite_amount(text)
    if composite_amount is not None:
        return composite_amount
    range_amount = _first_contextual_amount_range(text)
    if range_amount is not None:
        return range_amount
    for match in AMOUNT_PATTERN.finditer(text):
        if match.group(2) is None and _is_month_duration_after(text, match.end()):
            continue
        return _parse_amount(match.group(1), match.group(2))
    return None


def _first_composite_amount(text: str) -> int | None:
    match = COMPOSITE_MILLION_THOUSAND_PATTERN.search(text)
    if match is None:
        return None
    million_part = _parse_amount(match.group(1), match.group(2))
    thousand_part = _parse_amount(match.group(3), match.group(4))
    return million_part + thousand_part


def _first_contextual_amount_range(text: str) -> int | None:
    match = AMOUNT_RANGE_PATTERN.search(text)
    if match is None:
        return None
    # For a conversational range, keep the conservative upper bound as approx value.
    return _parse_amount(match.group(2), match.group(3))


def _is_month_duration_after(text: str, position: int) -> bool:
    return re.match(r"\s*(месяц|месяца|месяцев)\b", text[position:]) is not None


def _looks_like_standalone_total_debt(text: str) -> bool:
    if not re.search(r"\d", text):
        return False
    return bool(
        _has_mfo_signal(text)
        or _contains_any(text, ("долг", "долги", "задолженность"))
    )


def _parse_amount(number: str, unit: str | None) -> int:
    value = float(number.replace(",", "."))
    if unit in {"млн", "миллион", "миллиона", "миллионов"}:
        value *= 1_000_000
    elif unit in {"тыс", "тысяч", "к"}:
        value *= 1_000
    return int(value)


def _extract_month_count(text: str) -> float | None:
    match = re.search(r"(\d+(?:[,.]\d+)?)\s*(месяц|месяца|месяцев)", text)
    if not match:
        if re.search(r"\bмесяц(?:а|ев)?\b", text):
            return 1.0
        return None
    return float(match.group(1).replace(",", "."))


_normalize_text = normalize_text
_last_asked_slot = get_last_asked_slot
