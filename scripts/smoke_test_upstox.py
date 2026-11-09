"""Smoke test script to verify real Upstox market data connectivity.

Fetches 1 day of 1-minute historical candles for a symbol and prints only counts and time range.
Never prints or leaks secrets.
"""

import sys
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings, mask_token
from app.services.upstox_client import UpstoxClient


def main():
    parser = argparse.ArgumentParser(
        description="TradeZen Upstox Market Data Smoke Test"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="RELIANCE",
        help="Trading symbol to query (default: RELIANCE)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Trading date in YYYY-MM-DD format (defaults to latest trading day)",
    )
    args = parser.parse_args()

    client = UpstoxClient(use_sample_data=False)

    # Health check
    health = client.token_health()
    if health.get("status") not in ("ok", "degraded"):
        print(f"Error: Upstox token health check failed: {health.get('status')}", file=sys.stderr)
        print(f"Details: {health.get('message')}", file=sys.stderr)
        sys.exit(1)

    # Determine trading date
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
        candles = client.fetch_historical_candles(args.symbol, target_date)
    else:
        # Default to latest trading day with available data
        trading_days = client.get_trading_days(date.today(), 5)
        candles = []
        target_date = None
        for candidate_date in reversed(trading_days):
            candles = client.fetch_historical_candles(args.symbol, candidate_date)
            if candles:
                target_date = candidate_date
                break

        if not target_date:
            target_date = trading_days[-1]
    if not candles:
        print(f"No candles returned for {args.symbol} on {target_date}.", file=sys.stderr)
        sys.exit(1)

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    first_dt = datetime.fromtimestamp(candles[0]["timestamp"], tz=ist_tz)
    last_dt = datetime.fromtimestamp(candles[-1]["timestamp"], tz=ist_tz)

    print("Upstox Market Data Smoke Test Successful:")
    print(f"  Symbol:          {args.symbol.upper()}")
    print(f"  Trading Date:    {target_date}")
    print(f"  Total Candles:   {len(candles)}")
    print(f"  Start Time (IST): {first_dt.strftime('%H:%M:%S')}")
    print(f"  End Time (IST):   {last_dt.strftime('%H:%M:%S')}")
    print(f"  Time Range:      {first_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} to {last_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")


if __name__ == "__main__":
    main()
