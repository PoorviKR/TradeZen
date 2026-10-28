"""Tests for scenarios serving, decision attempts, and outcome reveals."""

import pytest
from fastapi import status


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
