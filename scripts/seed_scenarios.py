"""Seeds initial sample market scenarios into PostgreSQL database.

Usage:
    python scripts/seed_scenarios.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.session import SessionLocal
from app.models.scenario import Scenario


def seed_scenarios():
    """Seeds sample scenarios (drops, spikes, calm) into the database."""
    db = SessionLocal()
    try:
        existing_count = db.query(Scenario).count()
        if existing_count > 0:
            print(f"Database already contains {existing_count} scenarios. Skipping seeding.")
            return

        sample_scenarios = [
            # 1. Drop Scenario
            Scenario(
                symbol="RELIANCE",
                event_type="drop",
                entry_price=1000.0,
                current_price=990.0,
                drop_pct=1.0,
                candles=[
                    {"time": 1700000000, "open": 1000.0, "high": 1005.0, "low": 995.0, "close": 1002.0, "volume": 5000},
                    {"time": 1700000060, "open": 1002.0, "high": 1003.0, "low": 989.0, "close": 990.0, "volume": 8500},
                ],
                outcome_2m=-0.5,
                outcome_5m=-1.2,
                outcome_10m=0.3,
                outcome_30m=1.8,
                trades_today=1,
                last_trade_was_loss=False,
                active=True,
            ),
            # 2. Spike Scenario
            Scenario(
                symbol="TCS",
                event_type="spike",
                entry_price=3500.0,
                current_price=3570.0,
                drop_pct=0.0,
                candles=[
                    {"time": 1700000000, "open": 3500.0, "high": 3520.0, "low": 3495.0, "close": 3515.0, "volume": 3200},
                    {"time": 1700000060, "open": 3515.0, "high": 3575.0, "low": 3510.0, "close": 3570.0, "volume": 9400},
                ],
                outcome_2m=0.4,
                outcome_5m=0.8,
                outcome_10m=-0.6,
                outcome_30m=-1.4,
                trades_today=3,
                last_trade_was_loss=True,
                active=True,
            ),
            # 3. Calm Scenario
            Scenario(
                symbol="INFY",
                event_type="calm",
                entry_price=1500.0,
                current_price=1501.5,
                drop_pct=0.1,
                candles=[
                    {"time": 1700000000, "open": 1500.0, "high": 1502.0, "low": 1499.0, "close": 1501.0, "volume": 2100},
                    {"time": 1700000060, "open": 1501.0, "high": 1503.0, "low": 1500.0, "close": 1501.5, "volume": 2300},
                ],
                outcome_2m=0.1,
                outcome_5m=0.2,
                outcome_10m=0.3,
                outcome_30m=0.5,
                trades_today=1,
                last_trade_was_loss=False,
                active=True,
            ),
        ]

        db.add_all(sample_scenarios)
        db.commit()
        print(f"Successfully seeded {len(sample_scenarios)} initial market scenarios.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_scenarios()
