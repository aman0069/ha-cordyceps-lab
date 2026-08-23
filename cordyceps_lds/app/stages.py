"""Closed stage vocabulary and legal state transitions."""
from __future__ import annotations

from dataclasses import dataclass

STAGES = frozenset({
    "autoclaved", "inoculated", "dark_incubation", "transferred_to_light",
    "primordia_observed", "fruiting", "harvested", "dried", "packaged",
    "discarded", "contaminated",
})
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "autoclaved": frozenset({"inoculated", "discarded", "contaminated"}),
    "inoculated": frozenset({"dark_incubation", "contaminated", "discarded"}),
    "dark_incubation": frozenset({"transferred_to_light", "contaminated", "discarded"}),
    "transferred_to_light": frozenset({"primordia_observed", "contaminated", "discarded"}),
    "primordia_observed": frozenset({"fruiting", "contaminated", "discarded"}),
    "fruiting": frozenset({"harvested", "contaminated", "discarded"}),
    "harvested": frozenset({"dried", "discarded"}),
    "dried": frozenset({"packaged", "discarded"}),
    "packaged": frozenset(),
    "discarded": frozenset(),
    "contaminated": frozenset({"discarded"}),
}
ACTION_BY_DESTINATION = {
    "inoculated": "inoculation", "transferred_to_light": "transfer_dark_to_light",
    "contaminated": "contamination", "harvested": "harvest", "discarded": "discard",
}


class IllegalTransition(ValueError):
    """Raised where a requested stage edge is not legal and not forced."""


@dataclass(frozen=True)
class TransitionResult:
    from_stage: str
    to_stage: str
    forced: int


def transition(current_stage: str, to_stage: str, *, force: bool = False) -> TransitionResult:
    """Validate a stage edge, allowing a clearly marked forced override."""
    if current_stage not in STAGES or to_stage not in STAGES:
        raise IllegalTransition("stage is outside the closed vocabulary")
    if to_stage not in LEGAL_TRANSITIONS[current_stage] and not force:
        allowed = ", ".join(sorted(LEGAL_TRANSITIONS[current_stage])) or "none (terminal)"
        raise IllegalTransition(f"{current_stage} -> {to_stage} is not legal; allowed: {allowed}")
    # A caller that explicitly chooses force has requested an audited override,
    # even where the requested edge happens to be legal.
    return TransitionResult(current_stage, to_stage, int(force))


def allowed_actions(stage: str) -> list[str]:
    """Return scan-loggable actions relevant to the current stage."""
    if stage not in STAGES or stage in {"packaged", "discarded"}:
        return []
    actions = ["visual_inspection", "cleaning"]
    for destination in LEGAL_TRANSITIONS[stage]:
        action = ACTION_BY_DESTINATION.get(destination)
        if action:
            actions.append(action)
    if stage in {"harvested", "dried"}:
        actions.append("final_yield")
    return sorted(set(actions))
