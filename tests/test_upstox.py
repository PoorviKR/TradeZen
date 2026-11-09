"""Comprehensive tests for Upstox market data integration.

Never calls the real API in tests; uses recorded/mocked fixtures.
Validates:
1. Token alias handling and missing-token failure
2. Token never appears in logs or responses
3. Retry/backoff on 429 and 5xx, and the 401 error message
4. Candle validation and upsert idempotency
5. Holiday skip and 15-trading-day window with calendar fixtures
6. Refresh twice changes nothing (idempotency)
7. Stock universe configuration and widening
8. /admin/data-health endpoint schema and secrecy
"""

import io
import logging
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, mask_token
from app.models.scenario import Scenario, RawCandle, PoolReport
from app.services.upstox_client import (
    UpstoxClient,
    UpstoxAuthError,
    UpstoxAPIError,
    KNOWN_EXCHANGE_HOLIDAYS,
)
from app.services.scenario_builder import ScenarioBuilder
from app.jobs.refresh_scenarios import refresh_scenarios
from app.core.universe import get_primary_symbols, get_extended_symbols, get_full_universe
from app.services.data_health import check_data_health, set_startup_error


# -----------------------------------------------------------------------------
# 1. Token alias handling and missing-token failure
# -----------------------------------------------------------------------------

def test_token_alias_handling_and_missing_failure(monkeypatch):
    """Verify settings accepts UPSTOX_ANALYTICS_TOKEN or fallback ANALYTICS_TOKEN, and fails if missing."""
    # 1. Canonical name via kwargs
    s1 = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
        JWT_SECRET="valid_jwt_secret_12345",
        UPSTOX_ANALYTICS_TOKEN="canonical_token_xyz_123",
    )
    assert s1.UPSTOX_ANALYTICS_TOKEN == "canonical_token_xyz_123"

    # 2. Fallback alias via kwargs
    s2 = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
        JWT_SECRET="valid_jwt_secret_12345",
        ANALYTICS_TOKEN="fallback_alias_token_abc_789",
    )
    assert s2.UPSTOX_ANALYTICS_TOKEN == "fallback_alias_token_abc_789"

    # 3. Fallback alias via environment variable
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    monkeypatch.setenv("ANALYTICS_TOKEN", "env_alias_token_456")
    s3 = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
        JWT_SECRET="valid_jwt_secret_12345",
    )
    assert s3.UPSTOX_ANALYTICS_TOKEN == "env_alias_token_456"

    # 4. Missing token raises clear validation error
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    monkeypatch.delenv("ANALYTICS_TOKEN", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
            JWT_SECRET="valid_jwt_secret_12345",
            UPSTOX_ANALYTICS_TOKEN="",
        )
    assert "UPSTOX_ANALYTICS_TOKEN is missing" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 2. Token never appears in logs or responses
# -----------------------------------------------------------------------------

def test_token_never_appears_in_logs_or_responses(client, auth_headers, caplog):
    """Verify the real secret token is masked and never exposed in logs or API responses."""
    secret_token = "secret_live_bearer_token_xyz_9876543210"
    masked = mask_token(secret_token)
    assert secret_token not in masked
    assert "..." in masked

    # Ensure repr/str of Settings does not expose the token
    s = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/tradezen",
        JWT_SECRET="valid_jwt_secret_12345",
        UPSTOX_ANALYTICS_TOKEN=secret_token,
    )
    repr_str = repr(s)
    str_val = str(s)
    assert secret_token not in repr_str
    assert secret_token not in str_val

    # Verify logs do not leak token when 401 occurs
    caplog.clear()
    caplog.set_level(logging.DEBUG)

    upstox = UpstoxClient(token=secret_token, use_sample_data=False)
    with patch("httpx.Client.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_req.return_value = mock_resp

        with pytest.raises(UpstoxAuthError) as exc_info:
            upstox._execute_request_with_retry("GET", "https://api.upstox.com/v2/market/status/NSE")

        # Exception message must not contain secret
        assert secret_token not in str(exc_info.value)

    # Check logs captured
    logged_text = caplog.text
    assert secret_token not in logged_text

    # Test /admin/data-health and /api/v1/admin/data-health endpoints
    res1 = client.get("/admin/data-health")
    assert res1.status_code == 200
    res1_text = res1.text
    assert secret_token not in res1_text

    res2 = client.get("/api/v1/admin/data-health")
    assert res2.status_code == 200
    res2_text = res2.text
    assert secret_token not in res2_text


# -----------------------------------------------------------------------------
# 3. Retry/backoff on 429 and 5xx, and the 401 message
# -----------------------------------------------------------------------------

def test_retry_backoff_on_429_and_5xx_and_401():
    """Verify HTTP retry with backoff on 429/5xx, and specific error message on 401."""
    client = UpstoxClient(token="mock_token_for_retry_tests_12345678", use_sample_data=False)
    client._rate_limit_delay = 0.001  # fast test

    # Case A: 429 once, then 200 OK
    resp_429 = MagicMock()
    resp_429.status_code = 429

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"status": "success"}

    with patch("httpx.Client.request", side_effect=[resp_429, resp_200]) as mock_call:
        with patch("time.sleep") as mock_sleep:
            res = client._execute_request_with_retry("GET", "https://api.upstox.com/v2/market/status/NSE")
            assert res.status_code == 200
            assert mock_call.call_count == 2
            assert mock_sleep.called

    # Case B: 502 Bad Gateway twice, then 200 OK
    resp_502 = MagicMock()
    resp_502.status_code = 502

    with patch("httpx.Client.request", side_effect=[resp_502, resp_502, resp_200]) as mock_call:
        with patch("time.sleep"):
            res = client._execute_request_with_retry("GET", "https://api.upstox.com/v2/market/status/NSE")
            assert res.status_code == 200
            assert mock_call.call_count == 3

    # Case C: 401 Unauthorized raises clear message
    resp_401 = MagicMock()
    resp_401.status_code = 401

    with patch("httpx.Client.request", return_value=resp_401):
        with pytest.raises(UpstoxAuthError) as exc_info:
            client._execute_request_with_retry("GET", "https://api.upstox.com/v2/market/status/NSE")
        err_msg = str(exc_info.value)
        assert "Upstox Analytics Token is expired or invalid" in err_msg
        assert "generate a new Analytics Token in the Upstox Developer Console" in err_msg
        assert "update UPSTOX_ANALYTICS_TOKEN in your .env file" in err_msg


# -----------------------------------------------------------------------------
# 4. Candle validation and upsert idempotency
# -----------------------------------------------------------------------------

def test_candle_validation_rules():
    """Verify candle integrity validation rules."""
    client = UpstoxClient(token="test_mock_token_12345678901234567890")
    t_date = date(2026, 11, 6)
    ist_tz = timezone(timedelta(hours=5, minutes=30))

    base_time = int(datetime(2026, 11, 6, 9, 15, tzinfo=ist_tz).timestamp())

    # 1. Valid candle
    valid_candles = [
        {
            "timestamp": base_time,
            "open": 100.0,
            "high": 102.0,
            "low": 99.5,
            "close": 101.0,
            "volume": 500.0,
        },
        {
            "timestamp": base_time + 60,
            "open": 101.0,
            "high": 103.0,
            "low": 100.5,
            "close": 102.5,
            "volume": 600.0,
        },
    ]
    ok, reason = client.validate_candles("RELIANCE", t_date, valid_candles)
    assert ok is True
    assert reason is None

    # 2. Negative price
    bad_price = [
        {"timestamp": base_time, "open": -10.0, "high": 102.0, "low": 99.5, "close": 101.0, "volume": 100.0}
    ]
    ok, reason = client.validate_candles("RELIANCE", t_date, bad_price)
    assert ok is False
    assert "Non-positive price" in reason

    # 3. High < Low
    bad_high_low = [
        {"timestamp": base_time, "open": 100.0, "high": 98.0, "low": 99.0, "close": 98.5, "volume": 100.0}
    ]
    ok, reason = client.validate_candles("RELIANCE", t_date, bad_high_low)
    assert ok is False
    assert "High price" in reason and "less than" in reason

    # 4. Duplicate minutes
    duplicate_minutes = [
        {"timestamp": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 100.0},
        {"timestamp": base_time, "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 150.0},
    ]
    ok, reason = client.validate_candles("RELIANCE", t_date, duplicate_minutes)
    assert ok is False
    assert "Duplicate minute" in reason


def test_candle_upsert_idempotency(db_session):
    """Verify sync_raw_candles is idempotent and never creates duplicate rows."""
    client = UpstoxClient(token="test_mock_token_12345678901234567890", use_sample_data=True)
    builder = ScenarioBuilder(db=db_session, client=client)
    target_dt = date(2026, 11, 6)

    # First sync: populates raw candles
    count1 = builder.sync_raw_candles(target_dt, symbols=["RELIANCE", "TCS"])
    assert count1 > 0

    total_rows1 = db_session.query(RawCandle).count()
    assert total_rows1 > 0

    # Second sync on the same date: must be idempotent and not create duplicates
    count2 = builder.sync_raw_candles(target_dt, symbols=["RELIANCE", "TCS"])
    total_rows2 = db_session.query(RawCandle).count()

    assert total_rows2 == total_rows1


# -----------------------------------------------------------------------------
# 5. Holiday skip and 15-trading-day window with real calendar fixtures
# -----------------------------------------------------------------------------

def test_holiday_skip_and_15_trading_day_window():
    """Verify holiday skipping and rolling 15 trading day window."""
    client = UpstoxClient(token="test_mock_token_12345678901234567890", use_sample_data=True)

    # 2026-01-26 is Republic Day (Monday)
    republic_day = date(2026, 1, 26)
    assert client.is_holiday(republic_day) is True
    assert client.is_trading_day(republic_day) is False

    # Saturday/Sunday checks
    assert client.is_holiday(date(2026, 1, 24)) is True
    assert client.is_holiday(date(2026, 1, 25)) is True

    # 15 trading days ending on 2026-01-30
    days = client.get_trading_days(date(2026, 1, 30), 15)
    assert len(days) == 15
    assert republic_day not in days
    for d in days:
        assert d.weekday() < 5
        assert d not in KNOWN_EXCHANGE_HOLIDAYS


# -----------------------------------------------------------------------------
# 6. Refresh twice changes nothing (idempotency)
# -----------------------------------------------------------------------------

def test_refresh_twice_changes_nothing(db_session):
    """Verify running refresh_scenarios twice produces exactly 200 scenarios and changes nothing."""
    client = UpstoxClient(token="test_mock_token_12345678901234567890", use_sample_data=True)
    target_dt = date(2026, 11, 6)

    report1 = refresh_scenarios(target_date=target_dt, db_session=db_session, client=client)
    assert report1["total_active_scenarios"] == 200
    assert report1["drop_count"] == 100
    assert report1["spike_count"] == 60
    assert report1["calm_count"] == 40

    active_ids_first = [s.id for s in db_session.query(Scenario).filter(Scenario.active.is_(True)).all()]
    assert len(active_ids_first) == 200

    # Second run
    report2 = refresh_scenarios(target_date=target_dt, db_session=db_session, client=client)
    assert report2["total_active_scenarios"] == 200
    assert report2["drop_count"] == 100
    assert report2["spike_count"] == 60
    assert report2["calm_count"] == 40

    active_ids_second = [s.id for s in db_session.query(Scenario).filter(Scenario.active.is_(True)).all()]
    assert active_ids_second == active_ids_first


# -----------------------------------------------------------------------------
# 7. Universe configuration and widening
# -----------------------------------------------------------------------------

def test_stock_universe_configuration():
    """Verify stock universe loading and primary NIFTY 50 + extended constituents."""
    primary = get_primary_symbols()
    extended = get_extended_symbols()
    full = get_full_universe()

    assert len(primary) >= 50
    assert "RELIANCE" in primary
    assert "TCS" in primary
    assert "HDFCBANK" in primary

    assert len(extended) >= 15
    assert "DLF" in extended or "HAL" in extended

    assert len(full) >= len(primary) + len(extended) - 5


# -----------------------------------------------------------------------------
# 8. /admin/data-health endpoint schema and secrecy
# -----------------------------------------------------------------------------

def test_admin_data_health_endpoint(client, db_session):
    """Verify /admin/data-health returns status, date window, expiry, and zero secrets."""
    res = client.get("/admin/data-health")
    assert res.status_code == 200
    data = res.json()

    assert "status" in data
    assert data["status"] in ("ok", "degraded", "invalid", "expired")
    assert "pool_date_window" in data
    assert "days_until_expiry" in data
    assert "total_active_scenarios" in data
    assert "is_stale" in data

    # Secrecy check
    for key in ("token", "authorization", "password", "secret", "UPSTOX_ANALYTICS_TOKEN"):
        assert key not in data
