"""Single source of truth for action-dependent trading decision reasons.

Defines the versioned reason catalogue (`scn_reasons`), validation helpers,
legacy-to-new migration mappings, and DB table synchronization.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

CATALOGUE_VERSION = "v2.0.0"
LEGACY_CATALOGUE_VERSION = "v1.0.0"

VALID_ACTIONS: Tuple[str, ...] = ("buy", "hold", "sell")
VALID_KINDS: Tuple[str, ...] = ("plan", "mixed", "emotion", "external", "unsure")

KIND_LABELS: Dict[str, str] = {
    "plan": "Plan-based",
    "mixed": "Mixed",
    "emotion": "Emotion-driven",
    "external": "External / Tip",
    "unsure": "Unsure",
}


@dataclass(frozen=True)
class ReasonDef:
    """Immutable definition of a single decision reason."""

    code: str
    action: str
    label: str
    kind: str
    display_order: int
    catalogue_version: str = CATALOGUE_VERSION

    def to_dict(self) -> Dict[str, object]:
        return {
            "code": self.code,
            "action": self.action,
            "label": self.label,
            "kind": self.kind,
            "display_order": self.display_order,
            "catalogue_version": self.catalogue_version,
        }


REASON_CATALOGUE: Tuple[ReasonDef, ...] = (
    # BUY (8)
    ReasonDef("BUY_PLANNED", "buy", "Matched my entry plan", "plan", 1),
    ReasonDef("BUY_ADD_WINNER", "buy", "Adding to a winning trade", "plan", 2),
    ReasonDef("BUY_DIP_CHEAP", "buy", "Price dipped, looks cheap", "mixed", 3),
    ReasonDef("BUY_BALANCE_LOSS", "buy", "Average down to balance loss", "emotion", 4),
    ReasonDef("BUY_RECOVER_LOSS", "buy", "Recover a previous loss", "emotion", 5),
    ReasonDef("BUY_FOMO", "buy", "FOMO - price is running away", "emotion", 6),
    ReasonDef("BUY_TIP", "buy", "Tip / social media call", "external", 7),
    ReasonDef("BUY_UNSURE", "buy", "Not sure", "unsure", 8),
    # HOLD (8)
    ReasonDef("HOLD_PLAN_INTACT", "hold", "Plan intact, stop not hit", "plan", 1),
    ReasonDef("HOLD_LET_PROFIT_RUN", "hold", "Letting a winning trade run", "plan", 2),
    ReasonDef("HOLD_WAIT_CONFIRM", "hold", "Waiting for confirmation", "mixed", 3),
    ReasonDef("HOLD_WAIT_BREAKEVEN", "hold", "Waiting to get back to breakeven", "emotion", 4),
    ReasonDef("HOLD_AVOID_LOSS", "hold", "Don't want to book a loss", "emotion", 5),
    ReasonDef("HOLD_FROZEN", "hold", "Frozen / unsure what to do", "emotion", 6),
    ReasonDef("HOLD_TIP", "hold", "Tip / someone told me to hold", "external", 7),
    ReasonDef("HOLD_UNSURE", "hold", "Not sure", "unsure", 8),
    # SELL (8)
    ReasonDef("SELL_STOP_HIT", "sell", "My stop-loss was hit", "plan", 1),
    ReasonDef("SELL_TARGET", "sell", "My profit target was hit", "plan", 2),
    ReasonDef("SELL_PROTECT_CAPITAL", "sell", "Protecting capital per rule", "plan", 3),
    ReasonDef("SELL_PANIC", "sell", "Panic / fear of bigger drop", "emotion", 4),
    ReasonDef("SELL_EARLY_PROFIT", "sell", "Locking profit early out of fear", "emotion", 5),
    ReasonDef("SELL_FRUSTRATED", "sell", "Frustrated with this trade", "emotion", 6),
    ReasonDef("SELL_TIP", "sell", "Tip / news told me to exit", "external", 7),
    ReasonDef("SELL_UNSURE", "sell", "Not sure", "unsure", 8),
)

REASON_CODES: List[str] = [r.code for r in REASON_CATALOGUE]
REASON_BY_CODE: Dict[str, ReasonDef] = {r.code: r for r in REASON_CATALOGUE}
REASONS_BY_ACTION: Dict[str, List[ReasonDef]] = {
    act: [r for r in REASON_CATALOGUE if r.action == act]
    for act in VALID_ACTIONS
}

# Exact label lookup per action and across all actions
_LABEL_BY_ACTION: Dict[str, Dict[str, ReasonDef]] = {
    act: {r.label.lower(): r for r in reasons}
    for act, reasons in REASONS_BY_ACTION.items()
}
_ALL_LABELS: Dict[str, List[ReasonDef]] = {}
for _r in REASON_CATALOGUE:
    _ALL_LABELS.setdefault(_r.label.lower(), []).append(_r)

# Deterministic mapping from legacy v1.0.0 reasons to closest new code per action
LEGACY_REASON_MAP: Dict[str, Dict[str, str]] = {
    "followed my rule": {
        "buy": "BUY_PLANNED",
        "hold": "HOLD_PLAN_INTACT",
        "sell": "SELL_PROTECT_CAPITAL",
    },
    "followed rule": {
        "buy": "BUY_PLANNED",
        "hold": "HOLD_PLAN_INTACT",
        "sell": "SELL_PROTECT_CAPITAL",
    },
    "fear": {
        "buy": "BUY_FOMO",
        "hold": "HOLD_AVOID_LOSS",
        "sell": "SELL_PANIC",
    },
    "panic": {
        "buy": "BUY_FOMO",
        "hold": "HOLD_FROZEN",
        "sell": "SELL_PANIC",
    },
    "fomo": {
        "buy": "BUY_FOMO",
        "hold": "HOLD_WAIT_CONFIRM",
        "sell": "SELL_EARLY_PROFIT",
    },
    "wanted to recover loss": {
        "buy": "BUY_RECOVER_LOSS",
        "hold": "HOLD_WAIT_BREAKEVEN",
        "sell": "SELL_FRUSTRATED",
    },
    "recover loss": {
        "buy": "BUY_RECOVER_LOSS",
        "hold": "HOLD_WAIT_BREAKEVEN",
        "sell": "SELL_FRUSTRATED",
    },
    "social media tip": {
        "buy": "BUY_TIP",
        "hold": "HOLD_TIP",
        "sell": "SELL_TIP",
    },
    "tip": {
        "buy": "BUY_TIP",
        "hold": "HOLD_TIP",
        "sell": "SELL_TIP",
    },
    "did analysis": {
        "buy": "BUY_PLANNED",
        "hold": "HOLD_WAIT_CONFIRM",
        "sell": "SELL_PROTECT_CAPITAL",
    },
    "not sure": {
        "buy": "BUY_UNSURE",
        "hold": "HOLD_UNSURE",
        "sell": "SELL_UNSURE",
    },
}


def normalize_action(action: Optional[str]) -> str:
    """Normalizes and validates an action string."""
    act = (action or "").strip().lower()
    if act not in VALID_ACTIONS:
        raise ValueError(f"Invalid action '{action}'. Must be one of: buy, hold, sell.")
    return act


def get_reasons_for_action(action: str) -> List[ReasonDef]:
    """Returns the ordered list of valid ReasonDef objects for an action."""
    act = normalize_action(action)
    return list(REASONS_BY_ACTION[act])


def get_reason(code: Optional[str]) -> Optional[ReasonDef]:
    """Looks up a ReasonDef by code (case-insensitive)."""
    if not code:
        return None
    return REASON_BY_CODE.get(code.strip().upper())


def map_legacy_reason(old_reason: Optional[str], action: Optional[str]) -> ReasonDef:
    """Maps a legacy free-text reason to the closest new ReasonDef for the given action."""
    act = (action or "hold").strip().lower()
    if act not in VALID_ACTIONS:
        act = "hold"

    raw = (old_reason or "").strip().lower()
    if not raw:
        return REASON_BY_CODE[f"{act.upper()}_UNSURE"]

    # If the string already matches a valid code for this action
    upper = raw.upper()
    if upper in REASON_BY_CODE and REASON_BY_CODE[upper].action == act:
        return REASON_BY_CODE[upper]

    # Exact legacy label match (also handle "Label - optional note" prefix)
    base_part = raw.split(" - ", 1)[0].strip()
    if base_part in LEGACY_REASON_MAP:
        return REASON_BY_CODE[LEGACY_REASON_MAP[base_part][act]]

    # Exact new catalogue label match for this action
    if base_part in _LABEL_BY_ACTION[act]:
        return _LABEL_BY_ACTION[act][base_part]

    # Substring heuristics for legacy / free-text notes
    if any(k in raw for k in ("rule", "plan", "disciplined")):
        return REASON_BY_CODE[LEGACY_REASON_MAP["followed my rule"][act]]
    if "fomo" in raw or "chasing" in raw:
        return REASON_BY_CODE[LEGACY_REASON_MAP["fomo"][act]]
    if "balance" in raw and act == "buy":
        return REASON_BY_CODE["BUY_BALANCE_LOSS"]
    if any(k in raw for k in ("recover", "loss", "revenge", "breakeven")):
        return REASON_BY_CODE[LEGACY_REASON_MAP["recover loss"][act]]
    if any(k in raw for k in ("fear", "panic")):
        return REASON_BY_CODE[LEGACY_REASON_MAP["fear"][act]]
    if any(k in raw for k in ("social", "tip", "news")):
        return REASON_BY_CODE[LEGACY_REASON_MAP["social media tip"][act]]
    if any(k in raw for k in ("analysis", "technical", "confirm")):
        return REASON_BY_CODE[LEGACY_REASON_MAP["did analysis"][act]]

    return REASON_BY_CODE[f"{act.upper()}_UNSURE"]


def resolve_and_validate_reason(
    action: str,
    reason_code: Optional[str] = None,
    reason_text: Optional[str] = None,
) -> ReasonDef:
    """Validates an action-reason pair and returns the resolved ReasonDef.

    - If `reason_code` is provided: validates it exists and matches `action`.
    - If `reason_code` is omitted: inspects `reason_text`; rejects explicit catalogue
      codes or exclusive labels belonging to a different action, and maps legacy
      free-text reasons cleanly to the closest code for `action`.
    Raises ValueError with a user-friendly message on invalid pairs.
    """
    act = normalize_action(action)

    if reason_code is not None and str(reason_code).strip() != "":
        code = str(reason_code).strip().upper()
        rdef = REASON_BY_CODE.get(code)
        if not rdef:
            raise ValueError(
                f"Unknown reason code '{reason_code}'. Please select a valid reason for '{act}'."
            )
        if rdef.action != act:
            raise ValueError(
                f"Reason '{code}' ({rdef.label}) is only valid for '{rdef.action}' actions, not '{act}'."
            )
        return rdef

    if not reason_text or not str(reason_text).strip():
        raise ValueError(f"Please choose a reason for your '{act}' decision.")

    raw_text = str(reason_text).strip()
    upper_text = raw_text.upper()

    # Check if caller put a reason_code directly in the `reason` field
    if upper_text in REASON_BY_CODE:
        rdef = REASON_BY_CODE[upper_text]
        if rdef.action != act:
            raise ValueError(
                f"Reason '{upper_text}' ({rdef.label}) is only valid for '{rdef.action}' actions, not '{act}'."
            )
        return rdef

    # Check if caller put an exclusive label from another action in `reason`
    lower_base = raw_text.lower().split(" - ", 1)[0].strip()
    if lower_base in _ALL_LABELS:
        matching_for_act = _LABEL_BY_ACTION[act].get(lower_base)
        if matching_for_act is not None:
            return matching_for_act
        other = _ALL_LABELS[lower_base][0]
        raise ValueError(
            f"Reason '{raw_text}' is only valid for '{other.action}' actions, not '{act}'."
        )

    return map_legacy_reason(raw_text, act)


def sync_reasons_table(db: Session) -> int:
    """Idempotently seeds or updates the `scn_reasons` table from REASON_CATALOGUE."""
    from app.models.reason import ScnReason

    existing = {r.code: r for r in db.query(ScnReason).all()}
    changed = 0

    for rdef in REASON_CATALOGUE:
        row = existing.get(rdef.code)
        if row is None:
            db.add(
                ScnReason(
                    code=rdef.code,
                    action=rdef.action,
                    label=rdef.label,
                    kind=rdef.kind,
                    catalogue_version=rdef.catalogue_version,
                    display_order=rdef.display_order,
                    is_active=True,
                )
            )
            changed += 1
        else:
            if (
                row.action != rdef.action
                or row.label != rdef.label
                or row.kind != rdef.kind
                or row.catalogue_version != rdef.catalogue_version
                or row.display_order != rdef.display_order
                or not row.is_active
            ):
                row.action = rdef.action
                row.label = rdef.label
                row.kind = rdef.kind
                row.catalogue_version = rdef.catalogue_version
                row.display_order = rdef.display_order
                row.is_active = True
                changed += 1

    if changed:
        db.commit()
    return changed
