"""Shared dialogue_v3 route and action identifiers."""

from __future__ import annotations

DISCOVERY = "DISCOVERY"
MORTGAGE_MAIN = "MORTGAGE_MAIN"
MORTGAGE_AUX = "MORTGAGE_AUX"
PTS = "PTS"
# Registered for the auxiliary car-collateral scenario; select_route does not
# return it until the product rule is finalized.
AUTO_AUX = "AUTO_AUX"
UNSECURED = "UNSECURED"
MICRO = "MICRO"
BFL_RI = "BFL_RI"
BFL_RD = "BFL_RD"
OTHER = "OTHER"
FRAUD_CHECK = "FRAUD_CHECK"
REPEAT_VISIT = "REPEAT_VISIT"

TECHNICAL_ROUTES = frozenset({DISCOVERY})
PRODUCT_ROUTES = frozenset(
    {
        MORTGAGE_MAIN,
        MORTGAGE_AUX,
        PTS,
        AUTO_AUX,
        UNSECURED,
        MICRO,
        BFL_RI,
        BFL_RD,
        OTHER,
    }
)
SERVICE_ROUTES = frozenset({FRAUD_CHECK, REPEAT_VISIT})
DEBT_ROUTES = frozenset({BFL_RI, BFL_RD})
COLLATERAL_ROUTES = frozenset({MORTGAGE_MAIN, MORTGAGE_AUX, PTS, AUTO_AUX})
SELF_SERVE_ROUTES = frozenset({MORTGAGE_AUX, AUTO_AUX, UNSECURED, MICRO})

HANDOFF_EXPERT = "HANDOFF_EXPERT"
HANDOFF_BFL_SPECIALIST = "HANDOFF_BFL_SPECIALIST"
MANUAL_REVIEW = "MANUAL_REVIEW"
SECURITY_FLOW = "SECURITY_FLOW"
REPEAT_HANDOFF = "REPEAT_HANDOFF"
SELF_SERVE_LINKS_3 = "SELF_SERVE_LINKS_3"
SELF_SERVE_LINKS_7 = "SELF_SERVE_LINKS_7"

ACTION_SCOPE_BY_ACTION_ID = {
    HANDOFF_EXPERT: "handoff_expert",
    HANDOFF_BFL_SPECIALIST: "bfl_handoff",
    MANUAL_REVIEW: "manual_review",
    SECURITY_FLOW: "security_check",
    REPEAT_HANDOFF: "repeat_handoff",
    SELF_SERVE_LINKS_3: "self_serve_links",
    SELF_SERVE_LINKS_7: "self_serve_links",
}
