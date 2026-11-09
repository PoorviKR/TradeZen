"""Tests for scenarios serving, decision attempts, outcome reveals, and scenario pipeline."""

from datetime import date, datetime, timedelta, timezone
import pytest
from fastapi import status

from app.models.scenario import Scenario, RawCandle, PoolReport
from app.models.decision import Attempt
from app.models.user import User
from app.core.security import hash_password, create_access_token
from app.services.upstox_client import UpstoxClient, KNOWN_EXCHANGE_HOLIDAYS
from app.services.scenario_builder import ScenarioBuilder
from app.jobs.refresh_scenarios import refresh_scenarios


def test_get_next_scenarios_hides_symbol(client, auth_headers, sample_scenario):
    """Test scenario serving hides the actual symbol and date to avoid hindsight bias."""
    response = client.get("/api/v1/scenarios/next", headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    items = response.json()
    assert len(items) >= 1
    first_item = items[0]
    # Check that private identifiers are excluded from public schema
    assert "symbol" not in first_item
    assert first_item["event_type"] == "drop"
    assert first_item["entry_price"] == 1000.0


def test_reveal_forbidden_before_decision(client, auth_headers, sample_scenario):
    """Test outcome reveal is forbidden before user attempts the scenario."""
    response = client.get(f"/api/v1/scenarios/{sample_scenario.id}/reveal", headers=auth_headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_submit_decision_and_get_reveal(client, auth_headers, sample_scenario):
    """Test full decision flow: submit decision -> receive 3-part feedback -> access reveal."""
    decision_payload = {
        "scenario_id": sample_scenario.id,
        "action": "hold",
        "size": 15000.0,
        "reason": "Followed my rule",
        "decision_seconds": 6.5,
        "chart_viewed": True,
        "after_reveal": False,
    }
    decision_res = client.post("/api/v1/decisions", json=decision_payload, headers=auth_headers)
    assert decision_res.status_code == status.HTTP_201_CREATED
    feedback = decision_res.json()

    # Verify 3-part feedback structure
    assert "rules_feedback" in feedback
    assert "pattern_feedback" in feedback
    assert "history_feedback" in feedback
    assert feedback["rules_feedback"]["passed"] is True

    # Now reveal must succeed
    reveal_res = client.get(f"/api/v1/scenarios/{sample_scenario.id}/reveal", headers=auth_headers)
    assert reveal_res.status_code == status.HTTP_200_OK
    reveal_data = reveal_res.json()
    assert reveal_data["outcome_2m"] == -1.5
    assert reveal_data["outcome_30m"] == 1.0


def test_progress_restart_season(client, auth_headers):
    """Test progress restart increments season without deleting history."""
    res = client.post("/api/v1/progress/restart", headers=auth_headers)
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["new_season"] >= 2


def test_idempotency_scenario_pool_refresh(db_session):
    """Requirement 8.1: Test scenario pool refresh is safe to run twice (idempotent)."""
    target = date(2026, 11, 6)  # Friday trading session

    # First run: build the pool of 200 scenarios
    report1 = refresh_scenarios(target_date=target, db_session=db_session)
    assert report1["total_active_scenarios"] == 200
    assert report1["drop_count"] == 100
    assert report1["spike_count"] == 60
    assert report1["calm_count"] == 40

    active_count_after_first = (
        db_session.query(Scenario)
        .filter(Scenario.active.is_(True))
        .count()
    )
    assert active_count_after_first == 200

    # Second run: must detect pool is already full and remain at exactly 200 (no duplicate rows)
    report2 = refresh_scenarios(target_date=target, db_session=db_session)
    assert report2["total_active_scenarios"] == 200

    active_count_after_second = (
        db_session.query(Scenario)
        .filter(Scenario.active.is_(True))
        .count()
    )
    assert active_count_after_second == 200

    # Verify pool reports were stored
    reports = db_session.query(PoolReport).all()
    assert len(reports) >= 2


def test_exchange_holiday_and_weekend_skip(db_session):
    """Requirement 8.2: Test exchange holiday and weekend skipping."""
    client = UpstoxClient()

    # Fixed holiday: Republic Day 2026-01-26
    republic_day = date(2026, 1, 26)
    assert client.is_holiday(republic_day) is True
    assert client.is_trading_day(republic_day) is False

    # Weekend check: Saturday & Sunday
    saturday = date(2026, 1, 24)
    sunday = date(2026, 1, 25)
    assert client.is_holiday(saturday) is True
    assert client.is_holiday(sunday) is True

    # Regular trading day: Tuesday 2026-01-27
    tuesday = date(2026, 1, 27)
    assert client.is_holiday(tuesday) is False
    assert client.is_trading_day(tuesday) is True

    # Refresh job on a holiday must skip holiday and catch up to latest trading day
    report = refresh_scenarios(target_date=republic_day, db_session=db_session)
    assert report["holiday_skipped"] is True
    assert report["original_target_date"] == "2026-01-26"
    assert report["effective_trading_date"] == "2026-01-23"  # Previous Friday


def test_correct_15_trading_day_window(db_session):
    """Requirement 8.3: Test strictly 15 trading days window and aging deactivation."""
    client = UpstoxClient()
    target_dt = date(2026, 11, 6)

    # 1. Verify 15-trading-day calculation excludes all weekends and holidays
    window = client.get_trading_days(target_dt, 15)
    assert len(window) == 15
    for d in window:
        assert d.weekday() < 5, f"{d} is a weekend day"
        assert d not in KNOWN_EXCHANGE_HOLIDAYS, f"{d} is an exchange holiday"

    # 2. Verify window deactivation: an older scenario outside the window is deactivated, never deleted
    old_date = window[0] - timedelta(days=5)
    old_window_end = datetime(old_date.year, old_date.month, old_date.day, tzinfo=timezone.utc)
    old_scenario = Scenario(
        symbol="OLD_STOCK",
        event_type="drop",
        entry_price=500.0,
        current_price=490.0,
        drop_pct=2.0,
        candles=[{"time": 0, "open": 500.0, "high": 501.0, "low": 489.0, "close": 490.0, "volume": 100}],
        window_end=old_window_end,
        active=True,
    )
    db_session.add(old_scenario)
    db_session.commit()
    db_session.refresh(old_scenario)
    old_scenario_id = old_scenario.id

    # Running build_pool must deactivate old scenarios outside the 15-day window
    builder = ScenarioBuilder(db_session, client)
    builder.build_pool(target_dt)

    db_session.refresh(old_scenario)
    assert old_scenario.id == old_scenario_id
    assert old_scenario.active is False  # Marked inactive when leaving window


def test_unseen_scenario_selection_and_hiding(client, auth_headers, test_user, db_session):
    """Requirement 8.4: Test serving 10-20 active unseen scenarios, hiding symbol and date."""
    # Create two distinct active scenarios
    s1 = Scenario(
        symbol="SECRET_CO_1",
        event_type="drop",
        entry_price=1200.0,
        current_price=1185.0,
        drop_pct=1.25,
        candles=[
            {"time": 0, "open": 1200.0, "high": 1202.0, "low": 1184.0, "close": 1185.0, "volume": 500},
            {"time": 60, "open": 1185.0, "high": 1186.0, "low": 1180.0, "close": 1182.0, "volume": 600},
        ],
        active=True,
    )
    s2 = Scenario(
        symbol="SECRET_CO_2",
        event_type="spike",
        entry_price=2400.0,
        current_price=2440.0,
        drop_pct=-1.67,
        candles=[
            {"time": 0, "open": 2400.0, "high": 2445.0, "low": 2398.0, "close": 2440.0, "volume": 800},
        ],
        active=True,
    )
    # Inactive scenario
    s_inactive = Scenario(
        symbol="SECRET_CO_INACTIVE",
        event_type="calm",
        entry_price=100.0,
        current_price=100.1,
        drop_pct=-0.1,
        candles=[{"time": 0, "open": 100.0, "high": 100.2, "low": 99.9, "close": 100.1, "volume": 100}],
        active=False,
    )
    db_session.add_all([s1, s2, s_inactive])
    db_session.commit()

    # User 1 queries next scenarios
    res = client.get("/api/v1/scenarios/next?limit=15", headers=auth_headers)
    assert res.status_code == status.HTTP_200_OK
    items = res.json()
    item_ids = [item["id"] for item in items]

    # Inactive scenario must NEVER be returned
    assert s_inactive.id not in item_ids
    assert s1.id in item_ids
    assert s2.id in item_ids

    # Symbol and date must be hidden from public response
    for item in items:
        assert "symbol" not in item
        # Candles have relative times (0, 60...)
        assert item["candles"][0]["time"] == 0

    # User 1 submits a decision on s1
    client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": s1.id,
            "action": "buy",
            "size": 10000.0,
            "reason": "Recover loss",
            "decision_seconds": 4.2,
            "chart_viewed": True,
            "after_reveal": False,
        },
        headers=auth_headers,
    )

    # Next call for User 1 must NO LONGER return s1
    res_after = client.get("/api/v1/scenarios/next?limit=15", headers=auth_headers)
    assert res_after.status_code == status.HTTP_200_OK
    item_ids_after = [item["id"] for item in res_after.json()]
    assert s1.id not in item_ids_after
    assert s2.id in item_ids_after

    # Create User 2
    user2 = User(
        email="seconduser@tradezen.com",
        password_hash=hash_password("Password123!"),
        display_name="Second User",
        is_active=True,
    )
    db_session.add(user2)
    db_session.commit()
    user2_token = create_access_token(subject=str(user2.id))
    user2_headers = {"Authorization": f"Bearer {user2_token}"}

    # User 2 has NOT seen s1 yet, so s1 MUST be returned for User 2
    res_user2 = client.get("/api/v1/scenarios/next?limit=15", headers=user2_headers)
    assert res_user2.status_code == status.HTTP_200_OK
    user2_item_ids = [item["id"] for item in res_user2.json()]
    assert s1.id in user2_item_ids


def test_attempt_rules_and_immutability(client, auth_headers, sample_scenario, db_session):
    """Requirement 8.5: Test attempt rules (attempt 1 is blind, revisions increment attempt_no, immutable)."""
    # 1. Attempt 1: blind first try
    res1 = client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": sample_scenario.id,
            "action": "hold",
            "size": 10000.0,
            "reason": "Followed my rule",
            "decision_seconds": 5.5,
            "chart_viewed": True,
            "after_reveal": False,
        },
        headers=auth_headers,
    )
    assert res1.status_code == status.HTTP_201_CREATED
    data1 = res1.json()
    assert data1["attempt_no"] == 1
    attempt1_id = data1["attempt_id"]

    # Verify attempt 1 in DB
    att1 = db_session.query(Attempt).filter(Attempt.id == attempt1_id).first()
    assert att1.attempt_no == 1
    assert att1.after_reveal is False
    assert att1.actor_type == "human"

    # 2. View outcome reveal
    reveal_res = client.get(f"/api/v1/scenarios/{sample_scenario.id}/reveal", headers=auth_headers)
    assert reveal_res.status_code == status.HTTP_200_OK
    assert "outcome_2m" in reveal_res.json()

    # 3. Attempt 2: revision after reveal
    res2 = client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": sample_scenario.id,
            "action": "buy",
            "size": 12000.0,
            "reason": "Changed my mind after seeing chart",
            "decision_seconds": 12.0,
            "chart_viewed": True,
            "after_reveal": True,
        },
        headers=auth_headers,
    )
    assert res2.status_code == status.HTTP_201_CREATED
    data2 = res2.json()
    assert data2["attempt_no"] == 2
    attempt2_id = data2["attempt_id"]

    # Verify attempt 2 in DB
    att2 = db_session.query(Attempt).filter(Attempt.id == attempt2_id).first()
    assert att2.attempt_no == 2
    assert att2.after_reveal is True

    # 4. Immutability check: Attempt 1 was never overwritten
    db_session.refresh(att1)
    assert att1.id == attempt1_id
    assert att1.attempt_no == 1
    assert att1.action == "hold"
    assert att1.size == 10000.0
    assert att1.after_reveal is False

    # Both attempts coexist in DB
    all_attempts = (
        db_session.query(Attempt)
        .filter(Attempt.scenario_id == sample_scenario.id)
        .order_by(Attempt.attempt_no.asc())
        .all()
    )
    assert len(all_attempts) == 2
    assert all_attempts[0].attempt_no == 1
    assert all_attempts[1].attempt_no == 2
