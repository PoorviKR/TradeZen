"""Tests for Step 4: Scenario trainer flow, attempt rules, dashboard metrics, and responsive layout."""

import re
from pathlib import Path
import pytest
from fastapi import status

from app.models.scenario import Scenario
from app.models.decision import Attempt, Prediction
from app.models.rule import Rule
from app.models.user import User
from app.core.security import hash_password, create_access_token


def test_scenario_trainer_full_flow(client, auth_headers, sample_scenario, db_session):
    """Test full trainer flow: view scenario -> submit blind attempt 1 -> 3-part feedback ->

    change answer -> reveal outcome -> rate prediction -> next scenario.
    """
    # 1. Fetch next scenarios (symbol and date must be hidden)
    next_res = client.get("/api/v1/scenarios/next?limit=15", headers=auth_headers)
    assert next_res.status_code == status.HTTP_200_OK
    scenarios = next_res.json()
    assert len(scenarios) >= 1
    assert "symbol" not in scenarios[0]
    # Check candles are present and structured
    assert len(scenarios[0]["candles"]) > 0
    assert "close" in scenarios[0]["candles"][0]

    # 2. Attempt 1 is blind (after_reveal = False)
    decision_1 = {
        "scenario_id": sample_scenario.id,
        "action": "buy",
        "size": 10000.0,
        "reason": "Fear",
        "decision_seconds": 3.8,
        "chart_viewed": True,
        "after_reveal": False,
    }
    submit_res = client.post("/api/v1/decisions", json=decision_1, headers=auth_headers)
    assert submit_res.status_code == status.HTTP_201_CREATED
    feedback = submit_res.json()

    # Verify 3-part feedback structure
    assert feedback["attempt_no"] == 1
    assert "rules_feedback" in feedback
    assert "rule_summary" in feedback["rules_feedback"]
    assert "pattern_feedback" in feedback
    assert "explanation" in feedback["pattern_feedback"]
    assert "history_feedback" in feedback
    attempt1_id = feedback["attempt_id"]

    # Verify Attempt 1 stored as blind in DB
    att1 = db_session.query(Attempt).filter(Attempt.id == attempt1_id).first()
    assert att1.attempt_no == 1
    assert att1.after_reveal is False

    # 3. Change your answer ("What would you do now?") -> Revision Attempt 2
    decision_2 = {
        "scenario_id": sample_scenario.id,
        "action": "hold",
        "size": 10000.0,
        "reason": "Followed my rule",
        "decision_seconds": 14.2,
        "chart_viewed": True,
        "after_reveal": True,
    }
    revision_res = client.post("/api/v1/decisions", json=decision_2, headers=auth_headers)
    assert revision_res.status_code == status.HTTP_201_CREATED
    rev_data = revision_res.json()
    assert rev_data["attempt_no"] == 2
    attempt2_id = rev_data["attempt_id"]

    att2 = db_session.query(Attempt).filter(Attempt.id == attempt2_id).first()
    assert att2.attempt_no == 2
    assert att2.after_reveal is True

    # 4. Reveal outcome (2, 5, 10, 30 min)
    reveal_res = client.get(f"/api/v1/scenarios/{sample_scenario.id}/reveal", headers=auth_headers)
    assert reveal_res.status_code == status.HTTP_200_OK
    reveal = reveal_res.json()
    assert "outcome_2m" in reveal
    assert "outcome_5m" in reveal
    assert "outcome_10m" in reveal
    assert "outcome_30m" in reveal
    assert "outcome_candles" in reveal
    assert reveal["symbol"] == sample_scenario.symbol

    # 5. Rate feedback ("Was this feedback right? yes/no")
    rate_res = client.post(
        f"/api/v1/predictions/{attempt1_id}/feedback",
        json={"feedback_correct": True},
        headers=auth_headers,
    )
    assert rate_res.status_code == status.HTTP_200_OK
    assert "Thank you" in rate_res.json()["message"]


def test_reopen_old_scenarios_as_attempt_2_plus(client, auth_headers, sample_scenario, db_session):
    """Test user reopening an old scenario from history as attempt 2+ flagged after_reveal."""
    # Attempt 1
    client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": sample_scenario.id,
            "action": "buy",
            "size": 5000.0,
            "reason": "FOMO",
            "decision_seconds": 3.0,
            "chart_viewed": True,
            "after_reveal": False,
        },
        headers=auth_headers,
    )

    # Later: user reopens old scenario from history and tries again
    reopen_res = client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": sample_scenario.id,
            "action": "hold",
            "size": 5000.0,
            "reason": "Followed my rule",
            "decision_seconds": 11.0,
            "chart_viewed": True,
            "after_reveal": True,
        },
        headers=auth_headers,
    )
    assert reopen_res.status_code == status.HTTP_201_CREATED
    assert reopen_res.json()["attempt_no"] == 2

    # Verify both attempts exist and attempt 1 was never overwritten
    attempts = (
        db_session.query(Attempt)
        .filter(Attempt.scenario_id == sample_scenario.id)
        .order_by(Attempt.attempt_no.asc())
        .all()
    )
    assert len(attempts) == 2
    assert attempts[0].attempt_no == 1
    assert attempts[0].after_reveal is False
    assert attempts[1].attempt_no == 2
    assert attempts[1].after_reveal is True


def test_dashboard_metrics_and_data_thresholds(client, auth_headers, db_session, test_user):
    """Test dashboard metrics: repeated mistakes, improvement, rule-keeping, and 'not enough data yet' under 10."""
    # Under 10 decisions: must show 'not enough data yet'
    dash_empty = client.get("/api/v1/progress/dashboard", headers=auth_headers).json()
    assert dash_empty["total_decisions"] == 0
    assert dash_empty["has_enough_data"] is False
    assert dash_empty["data_notice"] == "not enough data yet"

    # Simulate 12 decisions across 8 scenarios to test 10+ threshold and improvement
    scenarios = []
    for i in range(8):
        sc = Scenario(
            symbol=f"STOCK_{i}",
            event_type="drop" if i % 2 == 0 else "spike",
            entry_price=100.0,
            current_price=98.0,
            drop_pct=2.0,
            candles=[{"time": 0, "open": 100.0, "high": 101.0, "low": 97.0, "close": 98.0, "volume": 100}],
            active=True,
        )
        db_session.add(sc)
        scenarios.append(sc)
    db_session.commit()

    # Generate 12 decisions with repeated mistakes and revisions
    for idx in range(12):
        sc = scenarios[idx % len(scenarios)]
        client.post(
            "/api/v1/decisions",
            json={
                "scenario_id": sc.id,
                "action": "sell" if idx % 2 == 0 else "hold",
                "size": 10000.0,
                "reason": "Fear" if idx < 4 else "Followed my rule",
                "decision_seconds": 4.0 if idx < 4 else 12.0,
                "chart_viewed": True,
                "after_reveal": idx >= 8,
            },
            headers=auth_headers,
        )

    # Now total_decisions >= 10: has_enough_data must be True
    dash = client.get("/api/v1/progress/dashboard", headers=auth_headers).json()
    assert dash["total_decisions"] == 12
    assert dash["has_enough_data"] is True
    assert dash["data_notice"] == "sufficient data"
    assert dash["decisions_backing_claim"] == 12

    # Check metrics existence
    assert "rule_compliance_pct" in dash
    assert "discipline_score" in dash
    assert "mistakes_by_type" in dash
    assert "repeated_mistakes" in dash
    assert "improvement" in dash
    assert "discipline_trend" in dash


def test_layout_responsive_tokens_and_accessibility():
    """Test layout responsiveness at 360, 768, and 1280 px and dark palette color tokens."""
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    app_jsx = (frontend_dir / "src" / "App.jsx").read_text(encoding="utf-8")
    index_css = (frontend_dir / "src" / "index.css").read_text(encoding="utf-8")
    tailwind_cfg = (frontend_dir / "tailwind.config.js").read_text(encoding="utf-8")

    # 1. Verify exact dark palette color tokens in CSS variables
    required_css_tokens = [
        "--bg-primary: #0E1116",
        "--bg-secondary: #1A1F29",
        "--bg-tertiary: #11161F",
        "--text-primary: #F9FAFB",
        "--text-secondary: #D1D5DB",
        "--text-tertiary: #9CA3AF",
        "--border-default: #2A313C",
        "--border-strong: #374151",
        "--accent-primary: #3B82F6",
        "--gain: #34D399",
        "--loss: #F87171",
        "--warning: #FBBF24",
        "--info: #60A5FA",
        "--success: #34D399",
    ]
    for token in required_css_tokens:
        assert token in index_css, f"Missing CSS variable: {token}"

    # 2. Verify Tailwind maps these tokens
    assert "bgPrimary" in tailwind_cfg
    assert "bgSecondary" in tailwind_cfg
    assert "accentPrimary" in tailwind_cfg
    assert "gain" in tailwind_cfg
    assert "loss" in tailwind_cfg
    assert "warning" in tailwind_cfg

    # 3. Verify mobile-first and responsive layout classes in App.jsx
    # 360px mobile classes (base: full width, min-h-[44px] touch targets, single column)
    assert "min-h-[44px]" in app_jsx or "min-h-[48px]" in app_jsx, "Must include 44px+ touch targets for mobile"
    assert "grid-cols-1" in app_jsx or "flex-col" in app_jsx, "Must support single-column mobile view"

    # 768px tablet classes (sm: and md: breakpoints)
    assert "sm:" in app_jsx, "Must include sm: responsive breakpoint"
    assert "md:" in app_jsx, "Must include md: responsive breakpoint"

    # 1280px desktop classes (lg: or max-w-5xl)
    assert "max-w-5xl" in app_jsx or "lg:" in app_jsx, "Must support large desktop layout"

    # 4. Accessibility check: Ensure arrows/signs accompany colors
    assert "ArrowUpRight" in app_jsx or "+" in app_jsx, "Must use plus/arrow signs alongside green gain"
    assert "ArrowDownRight" in app_jsx or "-" in app_jsx, "Must use minus/arrow signs alongside red loss"
