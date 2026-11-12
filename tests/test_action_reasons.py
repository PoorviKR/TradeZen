"""Tests for action-dependent reasons, validation, consistency checks, migrations, bots, fallback ML, and analytics."""

import random
from types import SimpleNamespace
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.core.reasons import (
    CATALOGUE_VERSION,
    LEGACY_CATALOGUE_VERSION,
    REASON_CODES,
    REASONS_BY_ACTION,
    VALID_ACTIONS,
    VALID_KINDS,
)
from app.models.decision import Attempt, BotDecision
from app.models.reason import ScnReason
from app.models.rule import Rule
from app.models.scenario import Scenario
from app.services.bots import populate_bot_decisions, regenerate_bot_decisions
from app.services.features import FEATURE_COLUMNS, extract_feature_vector
from app.services.rule_checker import (
    CONSISTENCY_FLAG_NAMES,
    check_user_rules,
    compute_consistency_checks,
)
from app.ml.explainer import (
    UNKNOWN_REASON_FALLBACK,
    explain_reason_code,
    explain_text,
)
from app.ml.predictor import FeatureMismatchError, MLPredictor


def _create_scenario(db_session, **overrides) -> Scenario:
    defaults = {
        "symbol": "RELIANCE.NS",
        "event_type": "drop",
        "entry_price": 1000.0,
        "current_price": 970.0,
        "drop_pct": -3.0,
        "candles": [{"time": 1, "open": 1000, "high": 1005, "low": 995, "close": 1000}],
        "outcome_candles": [{"time": 2, "open": 970, "high": 980, "low": 965, "close": 975}],
        "outcome_2m": 0.5,
        "outcome_5m": 1.0,
        "outcome_10m": 1.5,
        "outcome_30m": 2.0,
        "trades_today": 1,
        "last_trade_was_loss": False,
        "active": True,
    }
    defaults.update(overrides)
    sc = Scenario(**defaults)
    db_session.add(sc)
    db_session.commit()
    db_session.refresh(sc)
    return sc


def test_reason_catalogue_and_api(client, db_session):
    """Single source of truth contains 24 codes (8 per action) and API filters strictly by action."""
    assert CATALOGUE_VERSION == "v2.0.0"
    assert len(REASON_CODES) == 24
    for action in VALID_ACTIONS:
        assert len(REASONS_BY_ACTION[action]) == 8
        resp = client.get(f"/api/v1/reasons?action={action}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == action
        assert data["catalogue_version"] == CATALOGUE_VERSION
        assert len(data["reasons"]) == 8
        assert all(r["action"] == action for r in data["reasons"])
        assert all(r["kind"] in VALID_KINDS for r in data["reasons"])

    bad_resp = client.get("/api/v1/reasons?action=short")
    assert bad_resp.status_code == 422

    db_reasons = db_session.query(ScnReason).all()
    assert len(db_reasons) == 24


def test_valid_and_invalid_action_reason_pairs(client, db_session, auth_headers, sample_scenario):
    """Valid pairs succeed and store metadata; invalid pairs return friendly 422 and never 500."""
    valid_payload = {
        "scenario_id": sample_scenario.id,
        "action": "buy",
        "size": 10.0,
        "reason_code": "BUY_PLANNED",
        "note": "Entered per support plan",
        "decision_seconds": 12.0,
        "chart_viewed": True,
    }
    ok = client.post("/api/v1/decisions", json=valid_payload, headers=auth_headers)
    assert ok.status_code == 201
    body = ok.json()
    assert body["reason_code"] == "BUY_PLANNED"
    assert body["reason_kind"] == "plan"
    assert body["catalogue_version"] == CATALOGUE_VERSION

    attempt = db_session.query(Attempt).filter(Attempt.id == body["attempt_id"]).first()
    assert attempt is not None
    assert attempt.reason_code == "BUY_PLANNED"
    assert attempt.reason_kind == "plan"
    assert attempt.catalogue_version == CATALOGUE_VERSION
    assert attempt.migrated is False
    assert attempt.note == "Entered per support plan"
    assert attempt.rule_version == 1

    # Invalid action-reason pairs must return 422
    invalid_cases = [
        {"action": "buy", "reason_code": "SELL_PANIC"},
        {"action": "sell", "reason_code": "BUY_FOMO"},
        {"action": "hold", "reason_code": "SELL_TARGET"},
        {"action": "buy", "reason_code": "UNKNOWN_CODE_999"},
        {"action": "buy", "reason": "My stop-loss was hit"},
        {"action": "sell", "reason": "Price dipped, looks cheap"},
    ]
    for bad in invalid_cases:
        payload = {
            "scenario_id": sample_scenario.id,
            "size": 10.0,
            "decision_seconds": 8.0,
            "chart_viewed": True,
            **bad,
        }
        resp = client.post("/api/v1/decisions", json=payload, headers=auth_headers)
        assert resp.status_code == 422, f"Expected 422 for {bad}, got {resp.status_code}"


def test_alembic_single_head_and_migration_up_down(tmp_path, monkeypatch):
    """Migration 0003 upgrades legacy rows cleanly and downgrades reversibly with one head."""
    cfg = Config("alembic.ini")
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert heads == ["0003_action_reasons"]

    db_file = tmp_path / "migration_test.db"
    sqlite_url = f"sqlite:///{db_file.as_posix()}"

    from app.core import config as app_config

    monkeypatch.setattr(app_config.settings, "DATABASE_URL", sqlite_url)
    cfg.set_main_option("sqlalchemy.url", sqlite_url)

    # Upgrade to 0001_initial, add 0002's username column, and stamp 0002_username
    # (0002 itself uses non-batch ALTER COLUMN which SQLite disallows, while 0003 uses batch mode)
    command.upgrade(cfg, "0001_initial")

    engine = create_engine(sqlite_url)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(100)"))
    command.stamp(cfg, "0002_username")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, username, password_hash, display_name, is_active, current_season) "
                "VALUES (1, 'mig@example.com', 'miguser', 'hash', 'Mig User', 1, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO scenarios (id, symbol, event_type, entry_price, current_price, drop_pct, "
                "candles, outcome_candles, trades_today, last_trade_was_loss, active, created_on) "
                "VALUES (1, 'INFY.NS', 'drop', 1000.0, 960.0, -4.0, '[]', '[]', 1, 0, 1, '2026-01-01 00:00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO attempts (id, scenario_id, user_id, actor_type, attempt_no, season_no, "
                "action, size, reason, decision_seconds, chart_viewed) VALUES "
                "(1, 1, 1, 'human', 1, 1, 'sell', 10.0, 'Fear', 5.0, 1), "
                "(2, 1, 1, 'human', 2, 1, 'buy', 10.0, 'Followed my rule', 9.0, 1), "
                "(3, 1, 1, 'human', 3, 1, 'hold', 10.0, 'Wanted to recover loss', 11.0, 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO bot_decisions (id, scenario_id, bot_name, true_label, action, size, "
                "reason, decision_seconds, features) VALUES "
                "(1, 1, 'Panic', 'panic_sell', 'sell', 50.0, 'Panic', 2.0, '{}'), "
                "(2, 1, 'Disciplined', 'disciplined', 'hold', 10.0, 'Followed my rule', 14.0, '{}')"
            )
        )

    # Upgrade to head (0003)
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        insp = inspect(conn)
        assert "scn_reasons" in insp.get_table_names()
        reason_count = conn.execute(text("SELECT COUNT(*) FROM scn_reasons")).scalar()
        assert reason_count == 24

        att_rows = conn.execute(
            text("SELECT id, action, reason, reason_code, reason_kind, catalogue_version, migrated FROM attempts ORDER BY id")
        ).fetchall()
        assert len(att_rows) == 3
        assert att_rows[0][2] == "Fear"
        assert att_rows[0][3] == "SELL_PANIC"
        assert att_rows[0][4] == "emotion"
        assert att_rows[0][5] == LEGACY_CATALOGUE_VERSION
        assert bool(att_rows[0][6]) is True

        assert att_rows[1][3] == "BUY_PLANNED"
        assert att_rows[1][4] == "plan"
        assert att_rows[2][3] == "HOLD_WAIT_BREAKEVEN"
        assert att_rows[2][4] == "emotion"

        bot_rows = conn.execute(
            text("SELECT id, reason_code, catalogue_version, migrated FROM bot_decisions ORDER BY id")
        ).fetchall()
        assert bot_rows[0][1] == "SELL_PANIC"
        assert bot_rows[0][2] == LEGACY_CATALOGUE_VERSION
        assert bool(bot_rows[0][3]) is True
        assert bot_rows[1][1] == "HOLD_PLAN_INTACT"

    # Downgrade back to 0002 cleanly
    command.downgrade(cfg, "0002_username")

    with engine.connect() as conn:
        insp = inspect(conn)
        assert "scn_reasons" not in insp.get_table_names()
        att_cols = {c["name"] for c in insp.get_columns("attempts")}
        assert "reason_code" not in att_cols
        assert "migrated" not in att_cols
        old_reasons = conn.execute(text("SELECT reason FROM attempts ORDER BY id")).fetchall()
        assert [r[0] for r in old_reasons] == ["Fear", "Followed my rule", "Wanted to recover loss"]

    engine.dispose()


def test_consistency_checks_and_historic_rule_version(client, db_session, test_user, auth_headers):
    """All plain-code consistency checks trigger accurately and follow the historic rule version."""
    # 1. SELL_STOP_HIT when stop was NOT reached
    flags, warnings = compute_consistency_checks(
        action="sell",
        size=10.0,
        reason_code="SELL_STOP_HIT",
        reason_kind="plan",
        entry_price=1000.0,
        current_price=990.0,
        drop_pct=-1.0,
        user_trades_today=0,
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        max_position_pct=25.0,
        no_averaging_down=True,
        practice_capital=100000.0,
    )
    assert flags["consistency_sell_stop_not_hit"] is True
    assert flags["consistency_has_contradiction"] is True
    assert any("SELL_STOP_HIT" in w for w in warnings)

    # 2. HOLD_PLAN_INTACT when loss already passed stop
    flags2, warnings2 = compute_consistency_checks(
        action="hold",
        size=10.0,
        reason_code="HOLD_PLAN_INTACT",
        reason_kind="plan",
        entry_price=1000.0,
        current_price=965.0,
        drop_pct=-3.5,
        user_trades_today=0,
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        max_position_pct=25.0,
        no_averaging_down=True,
        practice_capital=100000.0,
    )
    assert flags2["consistency_hold_past_stop"] is True
    assert flags2["consistency_has_contradiction"] is True
    assert any("HOLD_PLAN_INTACT" in w for w in warnings2)

    # 3. BUY_ADD_WINNER when position is in loss
    flags3, _ = compute_consistency_checks(
        action="buy",
        size=10.0,
        reason_code="BUY_ADD_WINNER",
        reason_kind="plan",
        entry_price=1000.0,
        current_price=980.0,
        drop_pct=-2.0,
        user_trades_today=0,
        stop_loss_pct=5.0,
        max_trades_per_day=5,
        max_position_pct=25.0,
        no_averaging_down=False,
        practice_capital=100000.0,
    )
    assert flags3["consistency_add_winner_in_loss"] is True
    assert flags3["consistency_has_contradiction"] is True

    # 4. BUY_BALANCE_LOSS / BUY_RECOVER_LOSS when no_averaging_down is enabled
    for code in ("BUY_BALANCE_LOSS", "BUY_RECOVER_LOSS"):
        flags4, _ = compute_consistency_checks(
            action="buy",
            size=10.0,
            reason_code=code,
            reason_kind="emotion",
            entry_price=1000.0,
            current_price=960.0,
            drop_pct=-4.0,
            user_trades_today=0,
            stop_loss_pct=2.0,
            max_trades_per_day=5,
            max_position_pct=25.0,
            no_averaging_down=True,
            practice_capital=100000.0,
        )
        assert flags4["consistency_averaging_against_rule"] is True
        assert flags4["consistency_has_contradiction"] is True

    # 5. Any plan-kind contradiction against scenario numbers (e.g. SELL_TARGET in loss)
    flags5, _ = compute_consistency_checks(
        action="sell",
        size=10.0,
        reason_code="SELL_TARGET",
        reason_kind="plan",
        entry_price=1000.0,
        current_price=985.0,
        drop_pct=-1.5,
        user_trades_today=0,
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        max_position_pct=25.0,
        no_averaging_down=True,
        practice_capital=100000.0,
    )
    assert flags5["consistency_plan_contradicts_numbers"] is True
    assert flags5["consistency_has_contradiction"] is True

    # 6. End-to-end historic rule version judgment on /decisions
    rule_v1 = Rule(
        user_id=test_user.id,
        version=1,
        stop_loss_pct=5.0,
        max_trades_per_day=5,
        no_averaging_down=False,
        max_position_pct=25.0,
        practice_capital=100000.0,
        is_current=True,
    )
    db_session.add(rule_v1)
    db_session.commit()

    sc = _create_scenario(db_session, drop_pct=-3.0, current_price=970.0)

    # Under v1 (stop=5.0%), -3.0% has NOT hit stop -> SELL_STOP_HIT triggers consistency warning
    res_v1 = client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": sc.id,
            "action": "sell",
            "size": 10.0,
            "reason_code": "SELL_STOP_HIT",
            "decision_seconds": 10.0,
        },
        headers=auth_headers,
    )
    assert res_v1.status_code == 201
    d1 = res_v1.json()
    assert d1["rules_feedback"]["rule_version"] == 1
    assert d1["rules_feedback"]["consistency_flags"]["consistency_sell_stop_not_hit"] is True
    assert d1["rules_feedback"]["passed"] is False

    # Update user rule to v2 (stop=2.0%)
    rule_v1.is_current = False
    rule_v2 = Rule(
        user_id=test_user.id,
        version=2,
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        no_averaging_down=True,
        max_position_pct=25.0,
        practice_capital=100000.0,
        is_current=True,
    )
    db_session.add(rule_v2)
    db_session.commit()

    sc2 = _create_scenario(db_session, drop_pct=-3.0, current_price=970.0)
    res_v2 = client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": sc2.id,
            "action": "sell",
            "size": 10.0,
            "reason_code": "SELL_STOP_HIT",
            "decision_seconds": 10.0,
        },
        headers=auth_headers,
    )
    assert res_v2.status_code == 201
    d2 = res_v2.json()
    assert d2["rules_feedback"]["rule_version"] == 2
    assert d2["rules_feedback"]["consistency_flags"]["consistency_sell_stop_not_hit"] is False

    # Check historic attempt still records rule_version=1
    att1 = db_session.query(Attempt).filter(Attempt.id == d1["attempt_id"]).first()
    assert att1.rule_version == 1
    check_historic = check_user_rules(
        rule_v1,
        sc,
        SimpleNamespace(action="sell", size=10.0, reason="My stop-loss was hit"),
        user_trades_today=0,
        resolved_reason_code="SELL_STOP_HIT",
        resolved_reason_kind="plan",
    )
    assert check_historic.rule_version == 1
    assert check_historic.consistency_flags["consistency_sell_stop_not_hit"] is True


def test_bot_reason_overlap_idempotency_and_versioning(db_session):
    """Bots pick valid overlapping reasons, keep old versions, and regenerate idempotently."""
    random.seed(42)
    scenarios = []
    for i in range(18):
        event = ("drop", "spike", "calm")[i % 3]
        drop_val = -3.5 if event == "drop" else (2.5 if event == "spike" else -0.4)
        scenarios.append(
            _create_scenario(
                db_session,
                event_type=event,
                drop_pct=drop_val,
                current_price=round(1000.0 * (1.0 + drop_val / 100.0), 2),
                last_trade_was_loss=(i % 2 == 0),
                trades_today=i % 4,
            )
        )

    # Seed an old legacy v1.0.0 bot row to ensure version preservation
    legacy_bot = BotDecision(
        scenario_id=scenarios[0].id,
        bot_name="Panic",
        true_label="panic_sell",
        action="sell",
        size=20.0,
        reason="Panic",
        reason_code="SELL_PANIC",
        reason_kind="emotion",
        catalogue_version=LEGACY_CATALOGUE_VERSION,
        migrated=True,
        decision_seconds=2.0,
        features={},
    )
    db_session.add(legacy_bot)
    db_session.commit()

    inserted = populate_bot_decisions(db_session, scenarios=scenarios, target_per_scenario=5)
    assert inserted == len(scenarios) * 5

    # Idempotent re-run adds 0 new v2 rows
    inserted_again = populate_bot_decisions(db_session, scenarios=scenarios, target_per_scenario=5)
    assert inserted_again == 0

    # Legacy v1.0.0 row is still preserved
    v1_rows = db_session.query(BotDecision).filter(BotDecision.catalogue_version == LEGACY_CATALOGUE_VERSION).all()
    assert len(v1_rows) == 1

    v2_rows = db_session.query(BotDecision).filter(BotDecision.catalogue_version == CATALOGUE_VERSION).all()
    assert len(v2_rows) == len(scenarios) * 5

    # Every bot row uses a valid reason_code for its action
    labels_by_code = {}
    for row in v2_rows:
        valid_codes = {r.code for r in REASONS_BY_ACTION[row.action]}
        assert row.reason_code in valid_codes
        labels_by_code.setdefault(row.reason_code, set()).add(row.true_label)

        # Disciplined bot only picks SELL_STOP_HIT when stop was actually hit (drop_pct <= -2.0)
        if row.bot_name == "Disciplined" and row.reason_code == "SELL_STOP_HIT":
            sc_map = {s.id: s for s in scenarios}
            assert sc_map[row.scenario_id].drop_pct <= -2.0

    # Overlap check: multiple codes map to >= 2 labels (no trivial 1-to-1 reason->label mapping)
    multi_label_codes = [c for c, lbls in labels_by_code.items() if len(lbls) >= 2]
    assert len(multi_label_codes) >= 3, f"Expected overlapping reason codes across labels, got: {labels_by_code}"

    # Idempotent regeneration under same version inserts 0 duplicate rows; adding inactive scenario populates it too
    assert regenerate_bot_decisions(db_session, catalogue_version=CATALOGUE_VERSION) == 0

    inactive_sc = _create_scenario(db_session, event_type="drop", drop_pct=-4.0, active=False)
    scenarios.append(inactive_sc)
    assert regenerate_bot_decisions(db_session, catalogue_version=CATALOGUE_VERSION) == 5

    # Versioned regeneration under a newer catalogue_version populates all active+inactive scenarios while keeping older versions
    regen_new_ver = regenerate_bot_decisions(db_session, catalogue_version="v2.1.0-test")
    assert regen_new_ver == len(scenarios) * 5
    assert db_session.query(BotDecision).filter(BotDecision.catalogue_version == LEGACY_CATALOGUE_VERSION).count() == 1
    assert db_session.query(BotDecision).filter(BotDecision.catalogue_version == CATALOGUE_VERSION).count() == len(scenarios) * 5


def test_no_bot_name_leakage():
    """Neither bot_name nor outcome fields leak into FEATURE_COLUMNS or generated feature dicts."""
    forbidden = {"bot_name", "true_label", "actor_type", "outcome_2m", "outcome_5m", "outcome_10m", "outcome_30m"}
    assert not (forbidden & set(FEATURE_COLUMNS))
    for flag in CONSISTENCY_FLAG_NAMES:
        assert flag in FEATURE_COLUMNS

    vec = extract_feature_vector(
        action="buy",
        size=10.0,
        reason="Matched my entry plan",
        reason_code="BUY_PLANNED",
        reason_kind="plan",
        decision_seconds=12.0,
        chart_viewed=True,
        scenario_drop_pct=-1.0,
        scenario_current_price=990.0,
        scenario_entry_price=1000.0,
        scenario_trades_today=1,
        scenario_last_trade_was_loss=False,
        scenario_event_type="drop",
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        max_position_pct=25.0,
        no_averaging_down=True,
        practice_capital=100000.0,
    )
    assert list(vec.keys()) == FEATURE_COLUMNS
    assert not (forbidden & set(vec.keys()))


def test_missing_and_mismatched_model_fallback(client, sample_scenario, auth_headers, monkeypatch):
    """Missing or feature-mismatched models never crash and cleanly fall back to rules-only feedback."""
    payload = {
        "scenario_id": sample_scenario.id,
        "action": "buy",
        "size": 10.0,
        "reason_code": "BUY_PLANNED",
        "decision_seconds": 10.0,
    }

    # Case 1: Missing model raises FileNotFoundError
    def raise_missing(cls):
        raise FileNotFoundError("No active model file")

    monkeypatch.setattr(MLPredictor, "get_instance", classmethod(raise_missing))
    resp_missing = client.post("/api/v1/decisions", json=payload, headers=auth_headers)
    assert resp_missing.status_code == 201
    data_missing = resp_missing.json()
    assert data_missing["pattern_feedback"]["available"] is False
    assert data_missing["pattern_feedback"]["label"] == "rules_only"
    assert data_missing["pattern_feedback"]["explanation"] == "pattern feedback not available yet"

    # Case 2: Mismatched feature list
    stale_predictor = MLPredictor.__new__(MLPredictor)
    stale_predictor.model = None
    stale_predictor.model_version = "v0.9.0"
    stale_predictor.feature_names = ["legacy_feature_only"]
    stale_predictor.explainer = None

    assert stale_predictor.is_feature_compatible() is False
    with pytest.raises(FeatureMismatchError):
        stale_predictor.predict({"legacy_feature_only": 1.0})

    monkeypatch.setattr(MLPredictor, "get_instance", classmethod(lambda cls: stale_predictor))
    resp_mismatch = client.post("/api/v1/decisions", json=payload, headers=auth_headers)
    assert resp_mismatch.status_code == 201
    data_mismatch = resp_mismatch.json()
    assert data_mismatch["pattern_feedback"]["available"] is False
    assert data_mismatch["pattern_feedback"]["label"] == "rules_only"
    assert data_mismatch["pattern_feedback"]["explanation"] == "pattern feedback not available yet"


def test_explainer_templates_variants_try_instead_and_fallback():
    """Explainer has 2 wording variants per new code, safe unknown fallback, and try-this-instead guidance."""
    for code in REASON_CODES:
        v0 = explain_reason_code(code, variant_idx=0)
        v1 = explain_reason_code(code, variant_idx=1)
        assert isinstance(v0, str) and len(v0) > 10
        assert isinstance(v1, str) and len(v1) > 10
        assert v0 != v1, f"Expected 2 distinct variants for {code}"

    assert explain_reason_code("TOTALLY_UNKNOWN_CODE") == UNKNOWN_REASON_FALLBACK

    base_row = extract_feature_vector(
        action="sell",
        size=10.0,
        reason="Panic / fear of bigger drop",
        reason_code="SELL_PANIC",
        reason_kind="emotion",
        decision_seconds=2.5,
        chart_viewed=False,
        scenario_drop_pct=-1.0,
        scenario_current_price=990.0,
        scenario_entry_price=1000.0,
        scenario_trades_today=1,
        scenario_last_trade_was_loss=True,
        scenario_event_type="drop",
        stop_loss_pct=2.0,
        max_trades_per_day=5,
        max_position_pct=25.0,
        no_averaging_down=True,
        practice_capital=100000.0,
    )
    reasons = [
        {"feature": "reason_code_SELL_PANIC", "value": 1.0, "impact": 0.4},
        {"feature": "decision_seconds", "value": 2.5, "impact": 0.3},
    ]
    for mistake in ("panic_sell", "averaging_down", "fomo_buy", "revenge_trade"):
        txt = explain_text(base_row, reasons, predicted_label=mistake)
        assert "Try this instead:" in txt


def test_dashboard_reason_analytics_empty_and_min_samples(client, db_session, test_user, auth_headers):
    """Dashboard enforces min sample sizes for reason-kind breakdown and reason-vs-outcome."""
    # Empty state
    empty_resp = client.get("/api/v1/progress/dashboard", headers=auth_headers)
    assert empty_resp.status_code == 200
    assert empty_resp.json()["status"] == "empty"
    assert empty_resp.json()["reason_kind_breakdown"]["has_enough_data"] is False
    assert empty_resp.json()["reason_vs_outcome"]["has_enough_data"] is False

    # Submit 2 attempts -> below min_sample_size (5 for kind, 3 for reason)
    sc = _create_scenario(db_session, drop_pct=1.0, current_price=1010.0, outcome_10m=1.2, outcome_30m=2.1)
    for _ in range(2):
        r = client.post(
            "/api/v1/decisions",
            json={
                "scenario_id": sc.id,
                "action": "buy",
                "size": 10.0,
                "reason_code": "BUY_PLANNED",
                "decision_seconds": 10.0,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201

    small_dash = client.get("/api/v1/progress/dashboard", headers=auth_headers).json()
    assert small_dash["reason_kind_breakdown"]["has_enough_data"] is False
    assert small_dash["reason_kind_breakdown"]["min_sample_size"] == 5
    assert small_dash["reason_vs_outcome"]["has_enough_data"] is False
    assert small_dash["reason_vs_outcome"]["items"][0]["meets_min_sample"] is False
    assert small_dash["reason_vs_outcome"]["items"][0]["disciplined_pct"] is None

    # Add 2 more BUY_PLANNED + 1 legacy attempt without reason_code (total = 5)
    for _ in range(2):
        client.post(
            "/api/v1/decisions",
            json={
                "scenario_id": sc.id,
                "action": "buy",
                "size": 10.0,
                "reason_code": "BUY_PLANNED",
                "decision_seconds": 11.0,
            },
            headers=auth_headers,
        )
    legacy_att = Attempt(
        scenario_id=sc.id,
        user_id=test_user.id,
        actor_type="human",
        attempt_no=1,
        season_no=test_user.current_season,
        action="sell",
        size=10.0,
        reason="Fear",
        reason_code=None,
        reason_kind=None,
        catalogue_version=None,
        decision_seconds=3.0,
        chart_viewed=True,
    )
    db_session.add(legacy_att)
    db_session.commit()

    full_dash = client.get("/api/v1/progress/dashboard", headers=auth_headers).json()
    rkb = full_dash["reason_kind_breakdown"]
    assert rkb["total_decisions"] == 5
    assert rkb["has_enough_data"] is True
    by_kind = {item["kind"]: item for item in rkb["items"]}
    assert by_kind["plan"]["count"] == 4
    assert by_kind["emotion"]["count"] == 1

    rvo = full_dash["reason_vs_outcome"]
    assert rvo["has_enough_data"] is True
    by_code = {item["reason_code"]: item for item in rvo["items"]}
    assert by_code["BUY_PLANNED"]["count"] == 4
    assert by_code["BUY_PLANNED"]["meets_min_sample"] is True
    assert by_code["BUY_PLANNED"]["avg_outcome_10m"] == 1.2
    assert by_code["SELL_PANIC"]["count"] == 1
    assert by_code["SELL_PANIC"]["meets_min_sample"] is False
