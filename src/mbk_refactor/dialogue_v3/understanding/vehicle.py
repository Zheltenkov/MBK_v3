"""Vehicle and PTS semantic extraction for dialogue_v3 turns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..constants import PTS
from .need import set_need_signal
from .text import contains_any, normalize_text

if TYPE_CHECKING:
    from ..state import DialogueV3State


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


EXPLICIT_PTS_PATTERNS = (
    "под птс",
    "под авто",
    "есть машина, хочу под нее",
    "есть авто, хочу под него",
    "под машину",
)
VEHICLE_COLLATERAL_REFUSAL_PATTERNS = (
    "птс не рассматриваю",
    "под машину не хочу",
    "никакого варианта с авто",
    "никакого варианта с машиной",
    "авто в залог не дам",
    "машину в залог не дам",
    "машину как обеспечение не рассматриваю",
    "авто как обеспечение не рассматриваю",
    "не хочу залог на машину",
    "машина вообще не должна участвовать",
    "машину вообще не трогаем",
    "никаких автозалогов",
    "авто не трогаем",
)
VEHICLE_WORD_PATTERNS = ("авто", "машин", "птс", "kia", "hyundai", "лада", "ваз", "toyota")
VEHICLE_AVAILABILITY_PATTERNS = (
    "авто есть",
    "есть авто",
    "машина есть",
    "есть машина",
)
VEHICLE_ABSENCE_PATTERNS = (
    "авто нет",
    "нет авто",
    "машины нет",
    "нет машины",
)
VEHICLE_RETENTION_PATTERNS = (
    "машину отдавать не буду",
    "авто отдавать не буду",
    "машина нужна",
    "машина нужна каждый день",
    "машина нужна для работы",
    "она для работы",
    "авто нужно",
    "авто нужно каждый день",
    "машина для работы",
    "авто для работы",
    "оставалась у меня",
    "оставить машину у меня",
    "только если машину не забирают",
    "без варианта где машину забирают",
    "без варианта, где машину забирают",
    "машину не забирают",
    "машину не забираем",
    "без изъятия",
    "нужно пользоваться машиной",
    "продолжаю пользоваться машиной",
    "нужно ездить",
)

RAW_CAR_PATTERN = re.compile(r"\b(kia rio|hyundai tucson|лада веста|toyota camry|ваз \d{4})\b")
YEAR_PATTERN = re.compile(r"\b(19[8-9]\d|20[0-2]\d)\b")
OLD_CAR_YEAR_THRESHOLD = 2010
PTS_SLOT_NAMES = {
    "car_brand_model",
    "car_year",
    "car_owner",
    "car_pledge_or_restrictions",
}
BFL_VEHICLE_SLOT_NAMES = {"bfl_vehicle_context"}
YES_NO_OR_REFUSAL_PATTERN = re.compile(
    r"^(?:да|нет|не\s+знаю|не\s+помню|без\s+понятия|не\s+готов\w*|не\s+хочу)\.?$"
)


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


def extract_vehicle_facts(
    text: str,
    facts: dict[str, Any],
    concerns: list[str],
    state: DialogueV3State | None,
    vehicle_evidence: VehicleIntentEvidence,
) -> None:
    _extract_slot_local_vehicle_answer(text, facts, state)

    if _mentions_vehicle_absence(text):
        facts["has_car"] = False
        facts["vehicle_hard_blocker"] = True
        facts["vehicle_no_car_red_flag"] = True
        return

    vehicle_context = vehicle_evidence.has_vehicle_context
    if vehicle_context:
        facts["has_car"] = True

    if vehicle_evidence.explicit_pts_channel or vehicle_evidence.auto_collateral_consideration:
        facts["explicit_pts_intent"] = True
        set_need_signal(facts, "explicit_pts")

    raw_car_match = RAW_CAR_PATTERN.search(text)
    if raw_car_match:
        facts["raw_car_name"] = raw_car_match.group(1)
        facts["car_brand_model_known"] = True
        facts["has_car"] = True
        vehicle_context = True

    year_match = YEAR_PATTERN.search(text)
    if year_match and vehicle_context:
        _set_car_year_fact(facts, int(year_match.group(1)))

    if "я собственник" in text and vehicle_context:
        facts["car_owner_known"] = True
        facts["car_owner"] = "client"
    elif vehicle_context:
        _extract_car_owner_red_flags(text, facts)

    if vehicle_evidence.retention_required or vehicle_evidence.transfer_refusal:
        facts["vehicle_requires_retention"] = True
        facts["vehicle_refuses_transfer"] = True
        facts["vehicle_refuses_collateral"] = False
        concerns.append("vehicle_retention")

    if contains_any(
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

    if vehicle_context:
        _extract_car_restriction_flags(text, facts)


def _extract_slot_local_vehicle_answer(
    text: str,
    facts: dict[str, Any],
    state: DialogueV3State | None,
) -> None:
    """Parse concise answers to the last asked PTS slot before global patterns."""

    asked_slot = _last_vehicle_asked_slot(state)
    if asked_slot is None:
        return

    if asked_slot == "car_brand_model":
        if _mentions_vehicle_absence(text):
            facts["has_car"] = False
            facts["vehicle_hard_blocker"] = True
            facts["vehicle_no_car_red_flag"] = True
            return
        car_name = _slot_local_car_brand_model(text)
        if car_name is not None:
            facts["raw_car_name"] = car_name
            facts["car_brand_model_known"] = True
            facts["has_car"] = True
        return

    if asked_slot == "car_year":
        year_match = YEAR_PATTERN.search(text)
        if year_match:
            _set_car_year_fact(facts, int(year_match.group(1)))
            facts["has_car"] = True
        return

    if asked_slot == "car_owner":
        if _slot_local_client_is_car_owner(text):
            facts["car_owner_known"] = True
            facts["car_owner"] = "client"
            facts["has_car"] = True
            return
        if _extract_car_owner_red_flags(text, facts):
            facts["has_car"] = True
            return
        return

    if asked_slot == "car_pledge_or_restrictions":
        _extract_slot_local_car_restrictions(text, facts)
        _extract_car_restriction_flags(text, facts)

    if asked_slot == "bfl_vehicle_context":
        if _mentions_vehicle_absence(text):
            facts["has_car"] = False
            facts["bfl_vehicle_context_known"] = True
            return
        car_name = _slot_local_bfl_car_brand_model(text)
        if car_name is not None:
            facts["raw_car_name"] = car_name
            facts["car_brand_model_known"] = True
            facts["has_car"] = True
        year_match = YEAR_PATTERN.search(text)
        if year_match:
            _set_car_year_fact(facts, int(year_match.group(1)))
            facts["has_car"] = True
        if car_name is not None and year_match:
            facts["bfl_vehicle_context_known"] = True


def _slot_local_car_brand_model(text: str) -> str | None:
    """Accept short free-text brand/model answers without a car dictionary."""

    cleaned = text.strip(" .,!?:;\"'«»()")
    if not cleaned:
        return None
    if YEAR_PATTERN.fullmatch(cleaned):
        return None
    if YES_NO_OR_REFUSAL_PATTERN.match(cleaned):
        return None
    if len(cleaned) > 50:
        return None
    if re.fullmatch(r"[\d\s.,-]+", cleaned):
        return None
    if not re.search(r"[a-zа-яё]", cleaned):
        return None
    return _readable_vehicle_name(cleaned)


def _readable_vehicle_name(value: str) -> str:
    """Keep a readable model name after normalized text lowercasing."""

    parts: list[str] = []
    for token in value.split():
        stripped = token.strip()
        if stripped in {"bmw"}:
            parts.append(stripped.upper())
        elif re.fullmatch(r"[a-z]\d+", stripped):
            parts.append(stripped.upper())
        else:
            parts.append(stripped[:1].upper() + stripped[1:])
    return " ".join(parts)


def _slot_local_bfl_car_brand_model(text: str) -> str | None:
    """Parse a short car asset answer in BFL risk context without implying PTS intent."""

    without_year = YEAR_PATTERN.sub("", text)
    cleaned = re.sub(r"\b(?:машина|авто|автомобиль)\b", "", without_year)
    cleaned = re.sub(r"\b(?:год|года|выпуска)\b", "", cleaned)
    cleaned = cleaned.strip(" .,!?:;\"'«»()-")
    if not cleaned or YES_NO_OR_REFUSAL_PATTERN.match(cleaned):
        return None
    if len(cleaned) > 50:
        return None
    if not re.search(r"[a-zа-яё]", cleaned):
        return None
    return _readable_vehicle_name(cleaned)


def _slot_local_client_is_car_owner(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "на мне",
                "оформлена на меня",
                "оформлен на меня",
                "я собственник",
                "я собственница",
                "моя",
                "мой автомобиль",
                "моя машина",
            ),
        )
    )


def _extract_car_owner_red_flags(text: str, facts: dict[str, Any]) -> bool:
    if contains_any(
        text,
        (
            "не собственник",
            "я не собственник",
            "не на мне",
            "на жене",
            "на супруге",
            "на муже",
            "на маме",
            "на отце",
            "на папе",
            "на родител",
        ),
    ):
        facts["car_owner_known"] = True
        facts["car_owner"] = "third_party"
        facts["third_party_car_owner"] = True
        facts["car_owner_red_flag"] = True
        return True
    return False


def _extract_slot_local_car_restrictions(text: str, facts: dict[str, Any]) -> None:
    if _extract_car_restriction_flags(text, facts):
        facts["has_car"] = True


def _extract_car_restriction_flags(text: str, facts: dict[str, Any]) -> bool:
    """Extract pledge/restriction polarity without treating mentioned words as red flags."""

    loan_negative = _car_loan_negative(text)
    pledge_negative = _car_pledge_negative(text)
    arrest_negative = _car_arrest_negative(text)
    restriction_negative = _car_restriction_negative(text)
    all_clear = _car_restrictions_all_clear(text)

    loan_positive = _car_loan_positive(text) and not loan_negative
    pledge_positive = _car_pledge_positive(text) and not pledge_negative
    arrest_positive = _car_arrest_positive(text) and not arrest_negative
    restriction_positive = _car_restriction_positive(text) and not restriction_negative

    if all_clear:
        loan_negative = True
        pledge_negative = True
        arrest_negative = True
        restriction_negative = True

    found_signal = any(
        (
            loan_negative,
            pledge_negative,
            arrest_negative,
            restriction_negative,
            loan_positive,
            pledge_positive,
            arrest_positive,
            restriction_positive,
        )
    )
    if not found_signal:
        return False

    if loan_positive:
        facts["car_in_pledge"] = True
        facts["car_loan_red_flag"] = True
    elif loan_negative:
        facts["car_loan_red_flag"] = False

    if pledge_positive:
        facts["car_in_pledge"] = True
        facts["car_pledge_red_flag"] = True
    elif pledge_negative:
        facts["car_pledge_red_flag"] = False

    if (loan_negative or pledge_negative) and not (loan_positive or pledge_positive):
        facts["car_in_pledge"] = False

    if arrest_positive:
        facts["car_arrest_or_restriction"] = True
        facts["car_arrest_red_flag"] = True
    elif arrest_negative:
        facts["car_arrest_red_flag"] = False

    if restriction_positive:
        facts["car_arrest_or_restriction"] = True
        facts["car_restriction_red_flag"] = True
    elif restriction_negative:
        facts["car_restriction_red_flag"] = False

    if (arrest_negative or restriction_negative) and not (arrest_positive or restriction_positive):
        facts["car_arrest_or_restriction"] = False

    return True


def _car_loan_negative(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "автокредита нет",
                "автокредитов нет",
                "кредита на машину нет",
                "кредитов по машине нет",
                "без автокредита",
            ),
        )
    )


def _car_pledge_negative(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "в залоге не была",
                "в залоге не был",
                "не в залоге",
                "залога нет",
                "залогов нет",
                "без залога",
                "без залогов",
            ),
        )
        or re.search(r"\bзалог\w*.{0,40}\bнет\b", text)
    )


def _car_arrest_negative(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "арестов нет",
                "ареста нет",
                "без арестов",
                "без ареста",
            ),
        )
        or re.search(r"\bарест\w*.{0,40}\b(?:нет|тоже нет|не было)\b", text)
    )


def _car_restriction_negative(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "ограничений нет",
                "ограничения нет",
                "ограничений тоже нет",
                "без ограничений",
            ),
        )
        or re.search(r"\bогранич\w*.{0,40}\b(?:нет|тоже нет|не было)\b", text)
    )


def _car_restrictions_all_clear(text: str) -> bool:
    return contains_any(
        text,
        (
            "ничего такого нет",
            "ничего нет",
            "без обременений",
            "залогов, арестов и ограничений нет",
        ),
    )


def _car_loan_positive(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "есть автокредит",
                "автокредит есть",
                "машина в кредите",
                "авто в кредите",
            ),
        )
    )


def _car_pledge_positive(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "есть залог",
                "залог есть",
                "машина в залоге",
                "авто в залоге",
                "автомобиль в залоге",
            ),
        )
        or re.search(r"\bв\s+залоге\b", text)
    )


def _car_arrest_positive(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "есть арест",
                "арест есть",
                "на машине арест",
                "на авто арест",
                "на автомобиле арест",
            ),
        )
    )


def _car_restriction_positive(text: str) -> bool:
    return bool(
        contains_any(
            text,
            (
                "есть ограничения",
                "ограничения есть",
                "на машине ограничения",
                "на авто ограничения",
                "на автомобиле ограничения",
                "запрет на регистрационные действия",
                "запрет рег действий",
            ),
        )
    )


def _set_car_year_fact(facts: dict[str, Any], year: int) -> None:
    facts["car_year"] = year
    if year < OLD_CAR_YEAR_THRESHOLD:
        facts["car_old_year"] = True
        facts["car_year_red_flag"] = True


def _mentions_vehicle_absence(text: str) -> bool:
    return contains_any(text, VEHICLE_ABSENCE_PATTERNS)



def _last_vehicle_asked_slot(state: DialogueV3State | None) -> str | None:
    if state is None:
        return None
    slot_names = PTS_SLOT_NAMES | BFL_VEHICLE_SLOT_NAMES
    if state.asked_slots and state.asked_slots[-1] in slot_names:
        return state.asked_slots[-1]
    route = getattr(state, "route", None)
    route_next_slot = getattr(route, "next_slot", None)
    if route_next_slot in slot_names:
        return route_next_slot
    if state.trace_history:
        last_trace = state.trace_history[-1]
        next_slot = last_trace.get("next_slot")
        if next_slot in slot_names:
            return str(next_slot)
        actor_move = last_trace.get("actor_move")
        if isinstance(actor_move, dict) and actor_move.get("next_slot") in slot_names:
            return str(actor_move["next_slot"])
    return None


def _mentions_vehicle(text: str, state: DialogueV3State | None) -> bool:
    """Detect vehicle context from text, known form facts, or current car slot."""

    return bool(_mentions_vehicle_availability(text) or _has_vehicle_context(text, {}, state) or RAW_CAR_PATTERN.search(text))


def _mentions_vehicle_availability(text: str) -> bool:
    """Detect explicit vehicle availability without inferring a PTS channel."""

    return contains_any(text, VEHICLE_AVAILABILITY_PATTERNS)


def _mentions_soft_auto_consideration(text: str) -> bool:
    """Detect that the client allows using the car/PTS path as an option."""

    if contains_any(text, EXPLICIT_PTS_PATTERNS):
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

    if contains_any(text, VEHICLE_RETENTION_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\b(?:машин\w*|авто|она|ее|её)\b.{0,35}\bнужн\w*\b.{0,25}\b(?:каждый день|для работы)\b",
            r"\b(?:каждый день|для работы)\b.{0,35}\bнужн\w*\b",
            r"\b(?:машин\w*|авто|она|ее|её)\b.{0,35}\b(?:для работы|каждый день)\b",
            r"\b(?:пользоваться|ездить)\b.{0,30}\b(?:машин\w*|авто)\b.{0,20}\bнужн\w*\b",
            r"\bпродолжа\w*\b.{0,25}\bпользоват\w*\b.{0,25}\b(?:машин\w*|авто)\b",
            r"\b(?:машин\w*|авто)\b.{0,25}\bне\s+забира\w*\b",
            r"\bбез\s+вариант\w*\b.{0,35}\b(?:машин\w*|авто)\b.{0,25}\bзабира\w*\b",
            r"\bбез\s+изъятия\b",
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
            r"\b(?:машин\w*|авто)\b.{0,35}\bне\s+забира\w*\b",
            r"\bне\s+забира\w*\b.{0,35}\b(?:машин\w*|авто)\b",
            r"\bбез\s+вариант\w*\b.{0,35}\b(?:машин\w*|авто)\b.{0,25}\bзабира\w*\b",
            r"\bбез\s+изъятия\b",
            r"\b(?:машин\w*|авто)\b.{0,35}\bоставал\w*\b.{0,20}\bу меня\b",
            r"\b(?:машин\w*|авто)\b.{0,35}\bдолжн\w*\b.{0,20}\bостаться\b.{0,20}\bу меня\b",
            r"\bоставал\w*\b.{0,20}\bу меня\b",
        )
    )


def _mentions_hard_vehicle_refusal(text: str) -> bool:
    """Detect hard refusal of the auto-collateral route, not retention concern."""

    if contains_any(text, VEHICLE_COLLATERAL_REFUSAL_PATTERNS):
        return True
    return any(
        re.search(pattern, text)
        for pattern in (
            r"(?<![a-zа-я0-9_])птс(?![a-zа-я0-9_]).{0,30}\bне\s+рассматрива\w*\b",
            r"\bне\s+(?:хочу|готов\w*)\b.{0,30}\bзалог\b.{0,20}\b(?:машин\w*|авто)\b",
            r"\bзалог\b.{0,20}\b(?:на\s+)?(?:машин\w*|авто)\b.{0,30}\bне\s+(?:хочу|готов\w*)\b",
            r"\bпод\s+(?:машин\w*|авто)\b.{0,30}\bне\s+хочу\b",
            r"\bникак\w*\b.{0,20}\bвариант\w*\b.{0,20}\b(?:с\s+)?(?:машин\w*|авто)\b",
            r"\b(?:машин\w*|авто)\b.{0,20}\bв\s+залог\b.{0,20}\bне\s+дам\b",
            r"\b(?:машин\w*|авто)\b.{0,25}\bкак\s+обеспечен\w*\b.{0,30}\bне\s+рассматрива\w*\b",
            r"\bникаких\b.{0,20}\bавтозалог\w*\b",
            r"\b(?:машин\w*|авто)\b.{0,30}\b(?:вообще\s+)?не\s+трога\w*\b",
        )
    )


def _has_vehicle_context(
    text: str,
    facts: dict[str, Any],
    state: DialogueV3State | None,
) -> bool:
    if contains_any(text, VEHICLE_WORD_PATTERNS):
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
        if last_trace.get("next_slot") in {"car_brand_model", "car_year", "car_owner", "car_pledge_or_restrictions"}:
            return True
        actor_move = last_trace.get("actor_move")
        if isinstance(actor_move, dict) and actor_move.get("next_slot") in {
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
