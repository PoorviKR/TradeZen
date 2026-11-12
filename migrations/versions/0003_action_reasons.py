"""Add action-dependent reason catalogue (`scn_reasons`) and backfill attempts & bot_decisions.

Revision ID: 0003_action_reasons
Revises: 0002_username
Create Date: 2026-11-12 00:00:00.000000

Legacy Reason -> New Reason Code Mapping (by action):
- "Followed my rule" / "Followed rule":
    - buy  -> BUY_PLANNED (kind: plan)
    - hold -> HOLD_PLAN_INTACT (kind: plan)
    - sell -> SELL_PROTECT_CAPITAL (kind: plan)
- "Fear":
    - buy  -> BUY_FOMO (kind: emotion)
    - hold -> HOLD_AVOID_LOSS (kind: emotion)
    - sell -> SELL_PANIC (kind: emotion)
- "Panic":
    - buy  -> BUY_FOMO (kind: emotion)
    - hold -> HOLD_FROZEN (kind: emotion)
    - sell -> SELL_PANIC (kind: emotion)
- "FOMO":
    - buy  -> BUY_FOMO (kind: emotion)
    - hold -> HOLD_WAIT_CONFIRM (kind: mixed)
    - sell -> SELL_EARLY_PROFIT (kind: emotion)
- "Wanted to recover loss" / "Recover loss":
    - buy  -> BUY_RECOVER_LOSS (kind: emotion)
    - hold -> HOLD_WAIT_BREAKEVEN (kind: emotion)
    - sell -> SELL_FRUSTRATED (kind: emotion)
- "Social media tip" / "Tip":
    - buy  -> BUY_TIP (kind: external)
    - hold -> HOLD_TIP (kind: external)
    - sell -> SELL_TIP (kind: external)
- "Did analysis":
    - buy  -> BUY_PLANNED (kind: plan)
    - hold -> HOLD_WAIT_CONFIRM (kind: mixed)
    - sell -> SELL_PROTECT_CAPITAL (kind: plan)
- "Not sure" / any unrecognized legacy text:
    - buy  -> BUY_UNSURE (kind: unsure)
    - hold -> HOLD_UNSURE (kind: unsure)
    - sell -> SELL_UNSURE (kind: unsure)

All backfilled legacy rows receive `catalogue_version='v1.0.0'` and `migrated=true`.
Original `reason` strings are preserved untouched so old rows remain readable.
"""

from typing import Dict, List, Sequence, Tuple, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0003_action_reasons"
down_revision: Union[str, None] = "0002_username"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATALOGUE_VERSION = "v2.0.0"
LEGACY_CATALOGUE_VERSION = "v1.0.0"

REASON_ROWS: List[Tuple[str, str, str, str, int]] = [
    # BUY (8)
    ("BUY_PLANNED", "buy", "Matched my entry plan", "plan", 1),
    ("BUY_ADD_WINNER", "buy", "Adding to a winning trade", "plan", 2),
    ("BUY_DIP_CHEAP", "buy", "Price dipped, looks cheap", "mixed", 3),
    ("BUY_BALANCE_LOSS", "buy", "Average down to balance loss", "emotion", 4),
    ("BUY_RECOVER_LOSS", "buy", "Recover a previous loss", "emotion", 5),
    ("BUY_FOMO", "buy", "FOMO - price is running away", "emotion", 6),
    ("BUY_TIP", "buy", "Tip / social media call", "external", 7),
    ("BUY_UNSURE", "buy", "Not sure", "unsure", 8),
    # HOLD (8)
    ("HOLD_PLAN_INTACT", "hold", "Plan intact, stop not hit", "plan", 1),
    ("HOLD_LET_PROFIT_RUN", "hold", "Letting a winning trade run", "plan", 2),
    ("HOLD_WAIT_CONFIRM", "hold", "Waiting for confirmation", "mixed", 3),
    ("HOLD_WAIT_BREAKEVEN", "hold", "Waiting to get back to breakeven", "emotion", 4),
    ("HOLD_AVOID_LOSS", "hold", "Don't want to book a loss", "emotion", 5),
    ("HOLD_FROZEN", "hold", "Frozen / unsure what to do", "emotion", 6),
    ("HOLD_TIP", "hold", "Tip / someone told me to hold", "external", 7),
    ("HOLD_UNSURE", "hold", "Not sure", "unsure", 8),
    # SELL (8)
    ("SELL_STOP_HIT", "sell", "My stop-loss was hit", "plan", 1),
    ("SELL_TARGET", "sell", "My profit target was hit", "plan", 2),
    ("SELL_PROTECT_CAPITAL", "sell", "Protecting capital per rule", "plan", 3),
    ("SELL_PANIC", "sell", "Panic / fear of bigger drop", "emotion", 4),
    ("SELL_EARLY_PROFIT", "sell", "Locking profit early out of fear", "emotion", 5),
    ("SELL_FRUSTRATED", "sell", "Frustrated with this trade", "emotion", 6),
    ("SELL_TIP", "sell", "Tip / news told me to exit", "external", 7),
    ("SELL_UNSURE", "sell", "Not sure", "unsure", 8),
]

CODE_TO_KIND: Dict[str, str] = {code: kind for code, _, _, kind, _ in REASON_ROWS}

LEGACY_MAP: Dict[str, Dict[str, str]] = {
    "followed my rule": {"buy": "BUY_PLANNED", "hold": "HOLD_PLAN_INTACT", "sell": "SELL_PROTECT_CAPITAL"},
    "followed rule": {"buy": "BUY_PLANNED", "hold": "HOLD_PLAN_INTACT", "sell": "SELL_PROTECT_CAPITAL"},
    "fear": {"buy": "BUY_FOMO", "hold": "HOLD_AVOID_LOSS", "sell": "SELL_PANIC"},
    "panic": {"buy": "BUY_FOMO", "hold": "HOLD_FROZEN", "sell": "SELL_PANIC"},
    "fomo": {"buy": "BUY_FOMO", "hold": "HOLD_WAIT_CONFIRM", "sell": "SELL_EARLY_PROFIT"},
    "wanted to recover loss": {"buy": "BUY_RECOVER_LOSS", "hold": "HOLD_WAIT_BREAKEVEN", "sell": "SELL_FRUSTRATED"},
    "recover loss": {"buy": "BUY_RECOVER_LOSS", "hold": "HOLD_WAIT_BREAKEVEN", "sell": "SELL_FRUSTRATED"},
    "social media tip": {"buy": "BUY_TIP", "hold": "HOLD_TIP", "sell": "SELL_TIP"},
    "tip": {"buy": "BUY_TIP", "hold": "HOLD_TIP", "sell": "SELL_TIP"},
    "did analysis": {"buy": "BUY_PLANNED", "hold": "HOLD_WAIT_CONFIRM", "sell": "SELL_PROTECT_CAPITAL"},
    "not sure": {"buy": "BUY_UNSURE", "hold": "HOLD_UNSURE", "sell": "SELL_UNSURE"},
}


def _map_old_reason(reason_text: str, action: str) -> Tuple[str, str]:
    act = (action or "hold").strip().lower()
    if act not in ("buy", "hold", "sell"):
        act = "hold"

    raw = (reason_text or "").strip().lower()
    base = raw.split(" - ", 1)[0].strip()

    if base.upper() in CODE_TO_KIND:
        code = base.upper()
        return code, CODE_TO_KIND[code]

    if base in LEGACY_MAP:
        code = LEGACY_MAP[base][act]
        return code, CODE_TO_KIND[code]

    if any(k in raw for k in ("rule", "plan", "disciplined")):
        code = LEGACY_MAP["followed my rule"][act]
    elif "fomo" in raw or "chasing" in raw:
        code = LEGACY_MAP["fomo"][act]
    elif "balance" in raw and act == "buy":
        code = "BUY_BALANCE_LOSS"
    elif any(k in raw for k in ("recover", "loss", "revenge", "breakeven")):
        code = LEGACY_MAP["recover loss"][act]
    elif any(k in raw for k in ("fear", "panic")):
        code = LEGACY_MAP["fear"][act]
    elif any(k in raw for k in ("social", "tip", "news")):
        code = LEGACY_MAP["social media tip"][act]
    elif any(k in raw for k in ("analysis", "technical", "confirm")):
        code = LEGACY_MAP["did analysis"][act]
    else:
        code = f"{act.upper()}_UNSURE"

    return code, CODE_TO_KIND[code]


def _backfill_table(bind, table_name: str) -> None:
    tbl = sa.table(
        table_name,
        sa.column("id", sa.Integer),
        sa.column("action", sa.String),
        sa.column("reason", sa.String),
        sa.column("reason_code", sa.String),
        sa.column("reason_kind", sa.String),
        sa.column("catalogue_version", sa.String),
        sa.column("migrated", sa.Boolean),
    )
    rows = bind.execute(sa.select(tbl.c.id, tbl.c.action, tbl.c.reason)).fetchall()
    for row_id, action, reason_text in rows:
        code, kind = _map_old_reason(reason_text, action)
        bind.execute(
            tbl.update()
            .where(tbl.c.id == row_id)
            .values(
                reason_code=code,
                reason_kind=kind,
                catalogue_version=LEGACY_CATALOGUE_VERSION,
                migrated=True,
            )
        )


def upgrade() -> None:
    # 1. Create scn_reasons catalogue table
    op.create_table(
        "scn_reasons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("catalogue_version", sa.String(length=20), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scn_reasons_id"), "scn_reasons", ["id"], unique=False)
    op.create_index(op.f("ix_scn_reasons_code"), "scn_reasons", ["code"], unique=True)
    op.create_index(op.f("ix_scn_reasons_action"), "scn_reasons", ["action"], unique=False)
    op.create_index(op.f("ix_scn_reasons_kind"), "scn_reasons", ["kind"], unique=False)
    op.create_index(op.f("ix_scn_reasons_catalogue_version"), "scn_reasons", ["catalogue_version"], unique=False)

    reasons_tbl = sa.table(
        "scn_reasons",
        sa.column("code", sa.String),
        sa.column("action", sa.String),
        sa.column("label", sa.String),
        sa.column("kind", sa.String),
        sa.column("catalogue_version", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        reasons_tbl,
        [
            {
                "code": code,
                "action": action,
                "label": label,
                "kind": kind,
                "catalogue_version": CATALOGUE_VERSION,
                "display_order": order,
                "is_active": True,
            }
            for code, action, label, kind, order in REASON_ROWS
        ],
    )

    # 2. Additive columns on attempts
    with op.batch_alter_table("attempts") as batch_op:
        batch_op.alter_column(
            "reason",
            existing_type=sa.String(length=50),
            type_=sa.String(length=200),
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("reason_code", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("reason_kind", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("catalogue_version", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("migrated", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("note", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("rule_version", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_attempts_reason_code"), ["reason_code"], unique=False)
        batch_op.create_index(op.f("ix_attempts_reason_kind"), ["reason_kind"], unique=False)
        batch_op.create_index(op.f("ix_attempts_catalogue_version"), ["catalogue_version"], unique=False)

    # 3. Additive columns on bot_decisions
    with op.batch_alter_table("bot_decisions") as batch_op:
        batch_op.alter_column(
            "reason",
            existing_type=sa.String(length=50),
            type_=sa.String(length=120),
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("reason_code", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("reason_kind", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("catalogue_version", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("migrated", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.create_index(op.f("ix_bot_decisions_reason_code"), ["reason_code"], unique=False)
        batch_op.create_index(op.f("ix_bot_decisions_reason_kind"), ["reason_kind"], unique=False)
        batch_op.create_index(op.f("ix_bot_decisions_catalogue_version"), ["catalogue_version"], unique=False)

    # 4. Backfill existing attempts & bot_decisions rows
    bind = op.get_bind()
    _backfill_table(bind, "attempts")
    _backfill_table(bind, "bot_decisions")


def downgrade() -> None:
    with op.batch_alter_table("bot_decisions") as batch_op:
        batch_op.drop_index(op.f("ix_bot_decisions_catalogue_version"))
        batch_op.drop_index(op.f("ix_bot_decisions_reason_kind"))
        batch_op.drop_index(op.f("ix_bot_decisions_reason_code"))
        batch_op.drop_column("migrated")
        batch_op.drop_column("catalogue_version")
        batch_op.drop_column("reason_kind")
        batch_op.drop_column("reason_code")
        batch_op.alter_column(
            "reason",
            existing_type=sa.String(length=120),
            type_=sa.String(length=50),
            existing_nullable=False,
        )

    with op.batch_alter_table("attempts") as batch_op:
        batch_op.drop_index(op.f("ix_attempts_catalogue_version"))
        batch_op.drop_index(op.f("ix_attempts_reason_kind"))
        batch_op.drop_index(op.f("ix_attempts_reason_code"))
        batch_op.drop_column("rule_version")
        batch_op.drop_column("note")
        batch_op.drop_column("migrated")
        batch_op.drop_column("catalogue_version")
        batch_op.drop_column("reason_kind")
        batch_op.drop_column("reason_code")
        batch_op.alter_column(
            "reason",
            existing_type=sa.String(length=200),
            type_=sa.String(length=50),
            existing_nullable=False,
        )

    op.drop_index(op.f("ix_scn_reasons_catalogue_version"), table_name="scn_reasons")
    op.drop_index(op.f("ix_scn_reasons_kind"), table_name="scn_reasons")
    op.drop_index(op.f("ix_scn_reasons_action"), table_name="scn_reasons")
    op.drop_index(op.f("ix_scn_reasons_code"), table_name="scn_reasons")
    op.drop_index(op.f("ix_scn_reasons_id"), table_name="scn_reasons")
    op.drop_table("scn_reasons")
