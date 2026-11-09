"""Data health tracking service for Upstox integration and scenario pool.

Reports status, last successful fetch time, pool date window, and token expiry.
Exposes zero credentials, secrets, or sensitive details.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.scenario import Scenario, PoolReport
from app.services.upstox_client import UpstoxClient

logger = logging.getLogger("tradezen.data_health")

_startup_error: Optional[str] = None
_startup_time: Optional[datetime] = None


def set_startup_error(error_msg: Optional[str]) -> None:
    """Records any failure during startup refresh without logging secrets."""
    global _startup_error, _startup_time
    _startup_error = error_msg
    _startup_time = datetime.now(timezone.utc)


def get_startup_error() -> Optional[str]:
    """Retrieves the last recorded startup error."""
    return _startup_error


def check_data_health(db: Session, client: Optional[UpstoxClient] = None) -> Dict[str, Any]:
    """Evaluates the market data pipeline health.

    Returns:
        status: 'ok', 'degraded', 'invalid', or 'expired'
        last_successful_fetch: ISO 8601 string or None
        pool_date_window: {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'} or None
        days_until_expiry: int or None
        total_active_scenarios: int
        is_stale: bool
        message: human readable status string
    """
    client = client or UpstoxClient()

    # 1. Check Upstox token health
    upstox_health = client.token_health()
    token_status = upstox_health.get("status", "degraded")
    days_until_expiry = upstox_health.get("days_until_expiry")

    # 2. Query pool information from database
    total_active = 0
    pool_window = None
    last_report_date = None
    try:
        total_active = (
            db.query(func.count(Scenario.id))
            .filter(Scenario.active.is_(True))
            .scalar()
            or 0
        )
        latest_report = (
            db.query(PoolReport)
            .order_by(PoolReport.id.desc())
            .first()
        )
        if latest_report:
            pool_window = {
                "start": latest_report.window_start,
                "end": latest_report.window_end,
            }
            last_report_date = latest_report.report_date
    except Exception as exc:
        logger.warning("Could not read scenario pool metadata from database: %s", exc)

    # 3. Determine fetch time
    last_fetch_dt = client.last_successful_fetch
    last_successful_fetch_str = last_fetch_dt.isoformat() if last_fetch_dt else None

    # 4. Check staleness
    today = date.today()
    recent_trading_days = client.get_trading_days(today, 1)
    latest_trading_day_str = recent_trading_days[-1].strftime("%Y-%m-%d")

    is_stale = False
    if total_active < 200:
        is_stale = True
    elif pool_window and pool_window.get("end") and pool_window["end"] < latest_trading_day_str:
        is_stale = True

    # 5. Determine overall health status
    if token_status in ("invalid", "expired"):
        overall_status = token_status
        message = upstox_health.get("message", "Upstox token invalid or expired.")
    elif _startup_error:
        overall_status = "degraded"
        message = f"Startup refresh encountered an issue: {_startup_error}"
    elif is_stale:
        overall_status = "degraded"
        message = (
            f"Scenario pool is currently behind ({total_active}/200 scenarios active). "
            f"Last updated for window ending {pool_window.get('end') if pool_window else 'unknown'}."
        )
    elif token_status == "ok":
        overall_status = "ok"
        message = f"Scenario pool is up to date with {total_active} active scenarios."
    else:
        overall_status = token_status
        message = upstox_health.get("message", "Market data status degraded.")

    return {
        "status": overall_status,
        "last_successful_fetch": last_successful_fetch_str,
        "pool_date_window": pool_window,
        "days_until_expiry": days_until_expiry,
        "total_active_scenarios": total_active,
        "is_stale": is_stale,
        "message": message,
    }
