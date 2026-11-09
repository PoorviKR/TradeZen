"""Scenario builder service for generating the rolling 200 market scenarios.

Builds scenarios from the last 15 TRADING days:
- 100 drops (>= 0.7% in 2 min, relaxed in steps if short)
- 60 spikes (>= 1.5% in 5 min, relaxed in steps if short)
- 40 calm (volatility <= 0.3% in 15 min, relaxed in steps if short)
Excludes split, bonus, circuit-limit anomalies, and data gaps.
Retains raw candles strictly for the last 20 trading days.
Generates immutable snapshots and records a pool_report.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.scenario import Scenario, RawCandle, PoolReport
from app.services.upstox_client import UpstoxClient, INSTRUMENT_KEYS

logger = logging.getLogger("tradezen.scenario_builder")

SYMBOLS_UNIVERSE = list(INSTRUMENT_KEYS.keys())

# Stepwise relaxation definitions
DROP_THRESHOLDS = [
    {"drop_pct_min": 0.7, "window_minutes": 2, "name": "0.7% in 2 min"},
    {"drop_pct_min": 0.5, "window_minutes": 2, "name": "0.5% in 2 min"},
    {"drop_pct_min": 0.5, "window_minutes": 5, "name": "0.5% in 5 min"},
    {"drop_pct_min": 0.4, "window_minutes": 5, "name": "0.4% in 5 min"},
]

SPIKE_THRESHOLDS = [
    {"spike_pct_min": 1.5, "window_minutes": 5, "name": "1.5% in 5 min"},
    {"spike_pct_min": 1.2, "window_minutes": 5, "name": "1.2% in 5 min"},
    {"spike_pct_min": 1.0, "window_minutes": 5, "name": "1.0% in 5 min"},
    {"spike_pct_min": 0.8, "window_minutes": 5, "name": "0.8% in 5 min"},
]

CALM_THRESHOLDS = [
    {"max_range_pct": 0.3, "window_minutes": 15, "name": "<=0.3% in 15 min"},
    {"max_range_pct": 0.4, "window_minutes": 15, "name": "<=0.4% in 15 min"},
    {"max_range_pct": 0.5, "window_minutes": 15, "name": "<=0.5% in 15 min"},
    {"max_range_pct": 0.7, "window_minutes": 15, "name": "<=0.7% in 15 min"},
]


class ScenarioBuilder:
    """Orchestrates market candle ingestion, cleaning, scenario mining, and pool management."""

    def __init__(self, db: Session, client: Optional[UpstoxClient] = None):
        self.db = db
        self.client = client or UpstoxClient()

    def sync_raw_candles(self, target_date: date) -> int:
        """Fetches raw 1-minute candles for the last 20 trading days and purges older data."""
        # 1. Determine last 20 trading days
        trading_days = self.client.get_trading_days(target_date, 20)
        oldest_trading_date_str = trading_days[0].strftime("%Y-%m-%d")

        # 2. Fetch candles for any missing trading days
        inserted_total = 0
        for t_date in trading_days:
            date_str = t_date.strftime("%Y-%m-%d")
            # Check if we already have candles for this date
            existing_count = (
                self.db.query(func.count(RawCandle.id))
                .filter(RawCandle.trading_date == date_str)
                .scalar()
                or 0
            )
            if existing_count >= 1000:
                continue  # Already ingested for this trading day

            for symbol in SYMBOLS_UNIVERSE:
                candles = self.client.fetch_historical_candles(symbol, t_date)
                raw_entries = [
                    RawCandle(
                        symbol=symbol,
                        trading_date=date_str,
                        timestamp=c["timestamp"],
                        open=c["open"],
                        high=c["high"],
                        low=c["low"],
                        close=c["close"],
                        volume=c.get("volume", 0.0),
                    )
                    for c in candles
                ]
                self.db.add_all(raw_entries)
                inserted_total += len(raw_entries)

            self.db.commit()

        # 3. Purge raw candles older than 20 trading days
        deleted = (
            self.db.query(RawCandle)
            .filter(RawCandle.trading_date < oldest_trading_date_str)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        if deleted > 0:
            logger.info("Purged %d raw candles older than 20 trading days (< %s)", deleted, oldest_trading_date_str)

        return inserted_total

    def build_pool(self, target_date: date) -> Dict[str, Any]:
        """Builds and refreshes the rolling 200 scenario pool for the last 15 TRADING days.

        Safe to run twice (idempotent).
        Target mix: 100 drops, 60 spikes, 40 calm moments.
        """
        # Ensure raw candles are available for at least 20 trading days
        self.sync_raw_candles(target_date)

        # 1. 15-trading-day window
        window_days = self.client.get_trading_days(target_date, 15)
        window_start_str = window_days[0].strftime("%Y-%m-%d")
        window_end_str = window_days[-1].strftime("%Y-%m-%d")
        window_start_dt = datetime(window_days[0].year, window_days[0].month, window_days[0].day, tzinfo=timezone.utc)
        window_end_dt = datetime(window_days[-1].year, window_days[-1].month, window_days[-1].day, 23, 59, 59, tzinfo=timezone.utc)

        # 2. Deactivate scenarios older than the 15-trading-day window (Never delete)
        deactivated = (
            self.db.query(Scenario)
            .filter(Scenario.active.is_(True), Scenario.window_end < window_start_dt)
            .update({"active": False}, synchronize_session=False)
        )
        self.db.commit()
        if deactivated > 0:
            logger.info("Deactivated %d scenarios that left the 15-trading-day window", deactivated)

        # 3. Check existing active scenarios in current window
        active_scenarios = (
            self.db.query(Scenario)
            .filter(
                Scenario.active.is_(True),
                Scenario.window_end >= window_start_dt,
                Scenario.window_end <= window_end_dt,
            )
            .all()
        )

        existing_drops = [s for s in active_scenarios if s.event_type == "drop"]
        existing_spikes = [s for s in active_scenarios if s.event_type == "spike"]
        existing_calm = [s for s in active_scenarios if s.event_type == "calm"]

        needed_drops = max(0, 100 - len(existing_drops))
        needed_spikes = max(0, 60 - len(existing_spikes))
        needed_calm = max(0, 40 - len(existing_calm))

        thresholds_recorded: Dict[str, Any] = {}

        if needed_drops > 0 or needed_spikes > 0 or needed_calm > 0:
            logger.info(
                "Scenario pool needs replenish: %d drops, %d spikes, %d calm needed",
                needed_drops,
                needed_spikes,
                needed_calm,
            )
            # Mine new candidates from raw candles
            new_drops, drop_thresh = self._mine_scenarios(
                event_type="drop",
                target_count=needed_drops,
                window_days=window_days,
                threshold_steps=DROP_THRESHOLDS,
            )
            thresholds_recorded["drops"] = drop_thresh

            new_spikes, spike_thresh = self._mine_scenarios(
                event_type="spike",
                target_count=needed_spikes,
                window_days=window_days,
                threshold_steps=SPIKE_THRESHOLDS,
            )
            thresholds_recorded["spikes"] = spike_thresh

            new_calm, calm_thresh = self._mine_scenarios(
                event_type="calm",
                target_count=needed_calm,
                window_days=window_days,
                threshold_steps=CALM_THRESHOLDS,
            )
            thresholds_recorded["calm"] = calm_thresh

            all_new = new_drops + new_spikes + new_calm
            if all_new:
                self.db.add_all(all_new)
                self.db.commit()
                logger.info("Added %d new scenarios to active pool", len(all_new))
        else:
            thresholds_recorded = {
                "drops": DROP_THRESHOLDS[0]["name"],
                "spikes": SPIKE_THRESHOLDS[0]["name"],
                "calm": CALM_THRESHOLDS[0]["name"],
            }
            logger.info("Scenario pool is already fully populated with 200 scenarios. No new scenarios needed.")

        # Recount current active pool
        current_active = (
            self.db.query(Scenario)
            .filter(
                Scenario.active.is_(True),
                Scenario.window_end >= window_start_dt,
                Scenario.window_end <= window_end_dt,
            )
            .all()
        )
        drop_cnt = sum(1 for s in current_active if s.event_type == "drop")
        spike_cnt = sum(1 for s in current_active if s.event_type == "spike")
        calm_cnt = sum(1 for s in current_active if s.event_type == "calm")

        # 4. Generate and store pool report
        report_record = PoolReport(
            report_date=target_date.strftime("%Y-%m-%d"),
            window_start=window_start_str,
            window_end=window_end_str,
            total_scenarios=len(current_active),
            drop_count=drop_cnt,
            spike_count=spike_cnt,
            calm_count=calm_cnt,
            thresholds_used=thresholds_recorded,
        )
        self.db.add(report_record)
        self.db.commit()

        report = {
            "report_date": target_date.strftime("%Y-%m-%d"),
            "window_start": window_start_str,
            "window_end": window_end_str,
            "total_active_scenarios": len(current_active),
            "drop_count": drop_cnt,
            "spike_count": spike_cnt,
            "calm_count": calm_cnt,
            "thresholds_used": thresholds_recorded,
        }
        logger.info("Pool report generated: %s", report)
        return report

    def _mine_scenarios(
        self,
        event_type: str,
        target_count: int,
        window_days: List[date],
        threshold_steps: List[Dict[str, Any]],
    ) -> Tuple[List[Scenario], str]:
        """Scans raw candles to extract scenario candidates using stepwise threshold relaxation."""
        found: List[Scenario] = []
        threshold_used_name = threshold_steps[0]["name"]

        for step in threshold_steps:
            threshold_used_name = step["name"]
            for d in reversed(window_days):
                date_str = d.strftime("%Y-%m-%d")
                d_end_dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)

                for symbol in SYMBOLS_UNIVERSE:
                    if len(found) >= target_count:
                        break

                    raw = (
                        self.db.query(RawCandle)
                        .filter(RawCandle.symbol == symbol, RawCandle.trading_date == date_str)
                        .order_by(RawCandle.timestamp.asc())
                        .all()
                    )

                    # Exclude data gaps (< 300 candles) and anomalies/circuit bars (> 10% move in 1 bar)
                    if len(raw) < 300:
                        continue
                    if any(abs((c.close - c.open) / c.open) > 0.10 for c in raw if c.open > 0):
                        continue

                    scenarios = self._extract_from_day(raw, symbol, d_end_dt, event_type, step)
                    for sc in scenarios:
                        if len(found) < target_count:
                            found.append(sc)
                        else:
                            break

                if len(found) >= target_count:
                    break

            if len(found) >= target_count:
                break

        return found, threshold_used_name

    def _extract_from_day(
        self,
        raw_candles: List[RawCandle],
        symbol: str,
        window_end_dt: datetime,
        event_type: str,
        step: Dict[str, Any],
    ) -> List[Scenario]:
        """Extracts immutable scenario snapshots from a single trading day's raw candles."""
        results: List[Scenario] = []
        n = len(raw_candles)
        # We need at least 30 candles prior to decision, and 30 candles outcome
        # Decision point index i between 30 and n - 31
        step_idx = 10  # spacing between detected events to avoid overlapping candles

        for i in range(30, n - 31, step_idx):
            decision_candle = raw_candles[i]
            prior_candles = raw_candles[i - 29 : i + 1]  # 30 candles up to decision
            outcome_candles = raw_candles[i + 1 : i + 31]  # 30 candles after decision

            entry_candle = prior_candles[0]
            entry_p = entry_candle.open
            curr_p = decision_candle.close
            if entry_p <= 0 or curr_p <= 0:
                continue

            # Check event criteria based on step parameters
            is_match = False
            drop_pct = 0.0

            if event_type == "drop":
                w_min = step.get("window_minutes", 2)
                ref_candle = prior_candles[-w_min] if len(prior_candles) >= w_min else prior_candles[0]
                if ref_candle.close > 0:
                    pct = (ref_candle.close - curr_p) / ref_candle.close * 100
                    if pct >= step.get("drop_pct_min", 0.7):
                        is_match = True
                        drop_pct = round(pct, 2)

            elif event_type == "spike":
                w_min = step.get("window_minutes", 5)
                ref_candle = prior_candles[-w_min] if len(prior_candles) >= w_min else prior_candles[0]
                if ref_candle.close > 0:
                    pct = (curr_p - ref_candle.close) / ref_candle.close * 100
                    if pct >= step.get("spike_pct_min", 1.5):
                        is_match = True
                        drop_pct = round(-pct, 2)  # negative drop = gain

            elif event_type == "calm":
                w_min = step.get("window_minutes", 15)
                recent = prior_candles[-w_min:] if len(prior_candles) >= w_min else prior_candles
                highs = [c.high for c in recent]
                lows = [c.low for c in recent]
                if lows and min(lows) > 0:
                    vol_pct = (max(highs) - min(lows)) / min(lows) * 100
                    if vol_pct <= step.get("max_range_pct", 0.3):
                        is_match = True
                        drop_pct = round((entry_p - curr_p) / entry_p * 100, 2)

            if not is_match:
                continue

            # Compute outcomes at 2, 5, 10, 30 minutes after decision point
            p2 = outcome_candles[1].close if len(outcome_candles) >= 2 else curr_p
            p5 = outcome_candles[4].close if len(outcome_candles) >= 5 else curr_p
            p10 = outcome_candles[9].close if len(outcome_candles) >= 10 else curr_p
            p30 = outcome_candles[29].close if len(outcome_candles) >= 30 else curr_p

            out_2m = round((p2 - curr_p) / curr_p * 100, 2)
            out_5m = round((p5 - curr_p) / curr_p * 100, 2)
            out_10m = round((p10 - curr_p) / curr_p * 100, 2)
            out_30m = round((p30 - curr_p) / curr_p * 100, 2)

            # Anonymize candles for public serving: use relative integer index instead of real timestamps
            # This conceals symbol and calendar dates, eliminating hindsight bias
            anonymized_candles = [
                {
                    "time": idx * 60,  # 0, 60, 120... relative seconds
                    "open": round(c.open, 2),
                    "high": round(c.high, 2),
                    "low": round(c.low, 2),
                    "close": round(c.close, 2),
                    "volume": float(c.volume),
                }
                for idx, c in enumerate(prior_candles)
            ]

            anonymized_outcome_candles = [
                {
                    "time": (30 + idx) * 60,
                    "open": round(c.open, 2),
                    "high": round(c.high, 2),
                    "low": round(c.low, 2),
                    "close": round(c.close, 2),
                    "volume": float(c.volume),
                }
                for idx, c in enumerate(outcome_candles)
            ]

            scenario = Scenario(
                symbol=symbol,
                event_type=event_type,
                entry_price=round(entry_p, 2),
                current_price=round(curr_p, 2),
                drop_pct=drop_pct,
                candles=anonymized_candles,
                outcome_candles=anonymized_outcome_candles,
                outcome_2m=out_2m,
                outcome_5m=out_5m,
                outcome_10m=out_10m,
                outcome_30m=out_30m,
                trades_today=(i % 4) + 1,
                last_trade_was_loss=(i % 2 == 1),
                thresholds=step,
                active=True,
                window_end=window_end_dt,
            )
            results.append(scenario)

        return results
