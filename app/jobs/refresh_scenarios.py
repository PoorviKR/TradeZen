"""Scenario pool refresh job.

Safe to run twice (idempotent), skips holidays/weekends, and catches up on missed days.
CLI usage:
    python -m app.jobs.refresh_scenarios
    python -m app.jobs.refresh_scenarios --date 2026-11-09
"""

import sys
import argparse
import logging
from datetime import date, datetime
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.upstox_client import UpstoxClient
from app.services.scenario_builder import ScenarioBuilder

logger = logging.getLogger("tradezen.jobs.refresh_scenarios")


def refresh_scenarios(
    target_date: Optional[date] = None,
    db_session: Optional[Session] = None,
    client: Optional[UpstoxClient] = None,
) -> Dict[str, Any]:
    """Refreshes the scenario pool for target_date (defaults to today).

    - Skips exchange holidays and weekends, resolving to the latest completed trading day.
    - Catches up on missed days to guarantee 200 active scenarios (100 drops, 60 spikes, 40 calm).
    - Idempotent: safe to run multiple times without duplicating scenarios.
    """
    client = client or UpstoxClient()
    current_date = target_date or date.today()

    # 1. Holiday & weekend check
    is_holiday = client.is_holiday(current_date)
    if is_holiday:
        recent_trading_days = client.get_trading_days(current_date, 1)
        effective_date = recent_trading_days[-1]
        logger.info(
            "Date %s is an exchange holiday or weekend. Skipping holiday ingestion. "
            "Catching up to latest trading day: %s",
            current_date,
            effective_date,
        )
    else:
        effective_date = current_date

    owns_session = False
    if db_session is None:
        db = SessionLocal()
        owns_session = True
    else:
        db = db_session

    try:
        builder = ScenarioBuilder(db=db, client=client)
        report = builder.build_pool(target_date=effective_date)
        report["holiday_skipped"] = is_holiday
        report["original_target_date"] = current_date.strftime("%Y-%m-%d")
        report["effective_trading_date"] = effective_date.strftime("%Y-%m-%d")
        return report
    finally:
        if owns_session:
            db.close()


from app.models.scenario import PoolReport


def get_latest_pool_report(db_session: Optional[Session] = None) -> Optional[Dict[str, Any]]:
    """Fetches the most recently recorded PoolReport from the database."""
    owns_session = False
    if db_session is None:
        db = SessionLocal()
        owns_session = True
    else:
        db = db_session

    try:
        report = db.query(PoolReport).order_by(PoolReport.id.desc()).first()
        if not report:
            return None
        return {
            "id": report.id,
            "report_date": report.report_date,
            "window_start": report.window_start,
            "window_end": report.window_end,
            "total_scenarios": report.total_scenarios,
            "drop_count": report.drop_count,
            "spike_count": report.spike_count,
            "calm_count": report.calm_count,
            "thresholds_used": report.thresholds_used,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        }
    finally:
        if owns_session:
            db.close()


def main():
    """CLI entrypoint for python -m app.jobs.refresh_scenarios."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="TradeZen Scenario Refresh Job: Refreshes 15-trading-day scenario pool."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date in YYYY-MM-DD format (defaults to current date)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print the latest stored pool_report without executing a refresh run",
    )
    args = parser.parse_args()

    if args.report_only:
        try:
            report = get_latest_pool_report()
            if not report:
                print("No pool_report found in database. Run the refresh job first.")
                sys.exit(0)
            print("Latest Pool Report:")
            print(f"  Report Date:     {report['report_date']}")
            print(f"  Window:          {report['window_start']} to {report['window_end']}")
            print(f"  Total Scenarios: {report['total_scenarios']}")
            print(f"  - Drops:         {report['drop_count']}")
            print(f"  - Spikes:        {report['spike_count']}")
            print(f"  - Calm:          {report['calm_count']}")
            print(f"  Thresholds:      {report['thresholds_used']}")
            sys.exit(0)
        except Exception as exc:
            print(f"Error fetching pool report: {exc}", file=sys.stderr)
            sys.exit(1)

    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    print(f"Starting scenario pool refresh for date: {target_date or date.today()}...")
    try:
        report = refresh_scenarios(target_date=target_date)
    except Exception as exc:
        print(f"Error executing scenario refresh: {exc}", file=sys.stderr)
        print("Please ensure PostgreSQL is running (e.g. 'docker compose up -d').", file=sys.stderr)
        sys.exit(1)

    print("Scenario pool refresh completed successfully:")
    print(f"  Effective Trading Date: {report['effective_trading_date']}")
    print(f"  Window Range:          {report['window_start']} to {report['window_end']}")
    print(f"  Total Active Pool:     {report['total_active_scenarios']}")
    print(f"  - Drops:               {report['drop_count']}")
    print(f"  - Spikes:              {report['spike_count']}")
    print(f"  - Calm:                {report['calm_count']}")
    print(f"  - Bot Decisions:       {report.get('bot_decisions_added', 0)}")
    print(f"  Holiday Skipped:       {report['holiday_skipped']}")
    print(f"  Thresholds Used:       {report['thresholds_used']}")


if __name__ == "__main__":
    main()
