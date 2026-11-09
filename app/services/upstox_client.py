"""Upstox API client for backend market data ingestion.

Backend only (never called or exposed to the browser).
Reads UPSTOX_ANALYTICS_TOKEN strictly from environment variables without logging it.
Fetches 1-minute candles with Historical Candle V3 and exchange trading calendar.
Implements retry with exponential backoff, respects rate limits, validates candles,
caches instrument mappings, and reports token health.
"""

import gzip
import json
import logging
import os
import random
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import httpx
import jwt

from app.core.config import settings, mask_token, PROJECT_ROOT

logger = logging.getLogger("tradezen.upstox")

# Cache directory for instruments
INSTRUMENTS_CACHE_DIR = PROJECT_ROOT / "data"
INSTRUMENTS_CACHE_FILE = INSTRUMENTS_CACHE_DIR / "instruments_cache.json"

# Standard fixed Indian exchange holidays (NSE/BSE)
# Used when exchange calendar API is unavailable or offline
KNOWN_EXCHANGE_HOLIDAYS = {
    # 2025
    date(2025, 1, 26),  # Republic Day
    date(2025, 2, 26),  # Mahashivratri
    date(2025, 3, 14),  # Holi
    date(2025, 3, 31),  # Id-Ul-Fitr
    date(2025, 4, 10),  # Mahavir Jayanti
    date(2025, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 1),   # Maharashtra Day
    date(2025, 8, 15),  # Independence Day
    date(2025, 8, 27),  # Ganesh Chaturthi
    date(2025, 10, 2),  # Mahatma Gandhi Jayanti
    date(2025, 10, 21), # Diwali Laxmi Pujan
    date(2025, 10, 22), # Diwali Balipratipada
    date(2025, 11, 5),  # Gurunanak Jayanti
    date(2025, 12, 25), # Christmas
    # 2026
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 3),   # Holi
    date(2026, 3, 20),  # Id-Ul-Fitr
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 27),  # Bakri Id
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 8),  # Diwali
    date(2026, 11, 24), # Guru Nanak Jayanti
    date(2026, 12, 25), # Christmas
}

# Standard liquid instrument mappings fallback
INSTRUMENT_KEYS = {
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "INFY": "NSE_EQ|INE009A01021",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "SBIN": "NSE_EQ|INE062A01020",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "ITC": "NSE_EQ|INE154A01025",
    "KOTAKBANK": "NSE_EQ|INE237A01028",
    "LT": "NSE_EQ|INE018A01030",
}

# Shared state across client instances
_global_last_successful_fetch: Optional[datetime] = None


class UpstoxAuthError(Exception):
    """Raised when the Upstox Analytics Token is missing, expired, or invalid."""
    pass


class UpstoxAPIError(Exception):
    """Base exception for Upstox API communication failures."""
    pass


class UpstoxClient:
    """Backend client to interact with Upstox API V3."""

    def __init__(
        self,
        token: Optional[str] = None,
        use_sample_data: Optional[bool] = None,
        base_url: str = "https://api.upstox.com",
    ):
        # Never hard-code or log the raw token
        self._token = token or settings.UPSTOX_ANALYTICS_TOKEN
        self._base_url = base_url.rstrip("/")
        # Rate limit delay: at most 10 requests/s -> 0.12s spacing
        self._rate_limit_delay = 0.12
        self._last_request_time = 0.0
        self._rate_limiter_lock = threading.Lock()

        # Configurable flag for sample data (for explicit tests)
        if use_sample_data is not None:
            self._use_sample_data = use_sample_data
        else:
            self._use_sample_data = getattr(settings, "USE_SAMPLE_DATA", False)

        # In-memory instruments mapping
        self._instruments_map: Dict[str, str] = {}
        self._instruments_loaded = False
        self._client_timeout = 15.0

    @property
    def last_successful_fetch(self) -> Optional[datetime]:
        global _global_last_successful_fetch
        return _global_last_successful_fetch

    @last_successful_fetch.setter
    def last_successful_fetch(self, dt: datetime):
        global _global_last_successful_fetch
        _global_last_successful_fetch = dt

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def _is_mock_token(self) -> bool:
        if not self._token:
            return True
        t = self._token.strip().lower()
        return (
            t.startswith("test_")
            or t.startswith("replace_")
            or t.startswith("dev_")
            or "placeholder" in t
            or len(t) < 32
        )

    def _rate_limit_wait(self) -> None:
        """Enforces rate limits across threads."""
        with self._rate_limiter_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self._rate_limit_delay:
                time.sleep(self._rate_limit_delay - elapsed)
            self._last_request_time = time.time()

    def _execute_request_with_retry(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> httpx.Response:
        """Executes HTTP request with exponential backoff for 429 and 5xx errors.

        Fails fast with clear error on 401 Unauthorized.
        """
        req_headers = headers or self._get_headers()
        backoff_sec = 1.0

        for attempt in range(max_retries):
            self._rate_limit_wait()
            try:
                with httpx.Client(timeout=self._client_timeout) as client:
                    resp = client.request(method, url, headers=req_headers, params=params)

                    if resp.status_code == 200:
                        self.last_successful_fetch = datetime.now(timezone.utc)
                        return resp

                    if resp.status_code == 401:
                        masked = mask_token(self._token)
                        logger.error(
                            "Upstox 401 Unauthorized received for token %s. Token expired or invalid.",
                            masked,
                        )
                        raise UpstoxAuthError(
                            "Upstox Analytics Token is expired or invalid. Please generate a new "
                            "Analytics Token in the Upstox Developer Console and update "
                            "UPSTOX_ANALYTICS_TOKEN in your .env file."
                        )

                    if resp.status_code == 429 or 500 <= resp.status_code < 600:
                        if attempt == max_retries - 1:
                            logger.warning(
                                "Upstox request failed with status %d after %d attempts: %s",
                                resp.status_code,
                                max_retries,
                                url,
                            )
                            return resp
                        jitter = random.uniform(0.05, 0.25)
                        sleep_time = backoff_sec + jitter
                        logger.info(
                            "Upstox returned status %d. Backing off for %.2fs (attempt %d/%d)",
                            resp.status_code,
                            sleep_time,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(sleep_time)
                        backoff_sec *= 2.0
                        continue

                    # Other 4xx client errors
                    logger.warning("Upstox returned unexpected status %d for %s", resp.status_code, url)
                    return resp

            except UpstoxAuthError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == max_retries - 1:
                    logger.warning("Upstox request failed with network error after %d attempts: %s", max_retries, exc)
                    raise UpstoxAPIError(f"Network error contacting Upstox: {exc}") from exc
                sleep_time = backoff_sec + random.uniform(0.05, 0.2)
                time.sleep(sleep_time)
                backoff_sec *= 2.0

        raise UpstoxAPIError(f"Failed to execute request to {url} after {max_retries} attempts.")

    # -------------------------------------------------------------------------
    # Instrument Master Lookup (Daily Cached)
    # -------------------------------------------------------------------------

    def load_instruments(self, force_refresh: bool = False) -> Dict[str, str]:
        """Loads symbol-to-instrument_key mapping using local cache or remote instruments file.

        Cached locally in data/instruments_cache.json and refreshed daily (every 24h).
        """
        if self._instruments_loaded and not force_refresh:
            return self._instruments_map

        INSTRUMENTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        now_ts = time.time()

        # Check local cache freshness (< 24 hours = 86400 seconds)
        if not force_refresh and INSTRUMENTS_CACHE_FILE.exists():
            try:
                mtime = INSTRUMENTS_CACHE_FILE.stat().st_mtime
                if (now_ts - mtime) < 86400:
                    with open(INSTRUMENTS_CACHE_FILE, "r", encoding="utf-8") as f:
                        self._instruments_map = json.load(f)
                        self._instruments_loaded = True
                        logger.debug("Loaded %d instruments from local cache.", len(self._instruments_map))
                        return self._instruments_map
            except Exception as exc:
                logger.warning("Failed to read instruments cache (%s), re-fetching...", exc)

        # Download from Upstox assets
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    raw_data = json.loads(gzip.decompress(resp.content).decode("utf-8"))
                    mapping: Dict[str, str] = {}
                    for item in raw_data:
                        seg = item.get("segment")
                        symbol = item.get("trading_symbol")
                        key = item.get("instrument_key")
                        if seg == "NSE_EQ" and symbol and key:
                            mapping[symbol.upper()] = key

                    if mapping:
                        self._instruments_map = mapping
                        self._instruments_loaded = True
                        with open(INSTRUMENTS_CACHE_FILE, "w", encoding="utf-8") as f:
                            json.dump(mapping, f)
                        logger.info("Successfully refreshed and cached %d NSE instruments.", len(mapping))
                        return self._instruments_map
        except Exception as exc:
            logger.warning("Could not download Upstox instruments file (%s). Falling back.", exc)

        # Fallback 1: Use expired cache if available
        if INSTRUMENTS_CACHE_FILE.exists():
            try:
                with open(INSTRUMENTS_CACHE_FILE, "r", encoding="utf-8") as f:
                    self._instruments_map = json.load(f)
                    self._instruments_loaded = True
                    return self._instruments_map
            except Exception:
                pass

        # Fallback 2: Static dictionary
        self._instruments_map = dict(INSTRUMENT_KEYS)
        self._instruments_loaded = True
        return self._instruments_map

    def get_instrument_key(self, symbol: str) -> str:
        """Looks up the Upstox instrument_key for a trading symbol (e.g. RELIANCE -> NSE_EQ|INE002A01018)."""
        sym = symbol.strip().upper()
        if not self._instruments_loaded:
            self.load_instruments()

        if sym in self._instruments_map:
            return self._instruments_map[sym]
        if sym in INSTRUMENT_KEYS:
            return INSTRUMENT_KEYS[sym]

        # Standard fallback format
        return f"NSE_EQ|{sym}"

    # -------------------------------------------------------------------------
    # Market Status & Timings
    # -------------------------------------------------------------------------

    def get_market_status(self, exchange: str = "NSE") -> Dict[str, Any]:
        """Fetches the operational market status from Upstox for an exchange."""
        if self._is_mock_token() or self._use_sample_data:
            return {
                "status": "success",
                "data": {
                    "exchange": exchange,
                    "status": "NORMAL_OPEN",
                    "last_updated": int(time.time() * 1000),
                },
            }

        url = f"{self._base_url}/v2/market/status/{exchange}"
        resp = self._execute_request_with_retry("GET", url)
        if resp.status_code == 200:
            return resp.json()
        return {"status": "error", "code": resp.status_code}

    # -------------------------------------------------------------------------
    # Exchange Calendar & Holidays
    # -------------------------------------------------------------------------

    def is_holiday(self, target_date: date) -> bool:
        """Determines if a given date is an exchange holiday or weekend."""
        # Weekend check: Saturday=5, Sunday=6
        if target_date.weekday() >= 5:
            return True
        return target_date in KNOWN_EXCHANGE_HOLIDAYS

    def is_trading_day(self, target_date: date) -> bool:
        """Checks if a date is an active trading session."""
        return not self.is_holiday(target_date)

    def get_trading_days(self, end_date: date, count: int) -> List[date]:
        """Calculates the last `count` trading days ending on or before `end_date`."""
        trading_days: List[date] = []
        curr = end_date
        while len(trading_days) < count:
            if self.is_trading_day(curr):
                trading_days.append(curr)
            curr -= timedelta(days=1)
        trading_days.reverse()
        return trading_days

    def fetch_exchange_holidays(self) -> Set[date]:
        """Fetches the exchange holiday calendar from Upstox or returns standard calendar."""
        if self._is_mock_token() or self._use_sample_data:
            return set(KNOWN_EXCHANGE_HOLIDAYS)

        url = f"{self._base_url}/v2/market/holidays"
        holidays = set(KNOWN_EXCHANGE_HOLIDAYS)
        try:
            resp = self._execute_request_with_retry("GET", url)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for item in data:
                    h_date_str = item.get("date")
                    if h_date_str:
                        try:
                            holidays.add(datetime.strptime(h_date_str, "%Y-%m-%d").date())
                        except ValueError:
                            pass
        except Exception as exc:
            logger.warning("Could not fetch remote holidays from Upstox API (%s), using exchange defaults", exc)

        return holidays

    # -------------------------------------------------------------------------
    # Token Health Check
    # -------------------------------------------------------------------------

    def token_health(self) -> Dict[str, Any]:
        """Performs a lightweight token health check.

        Makes one cheap call and verifies token expiration.
        Returns ONLY non-sensitive health metadata (status, days_until_expiry, etc).
        Never exposes secrets.
        """
        if not self._token or not self._token.strip():
            return {
                "status": "invalid",
                "days_until_expiry": None,
                "message": "UPSTOX_ANALYTICS_TOKEN is missing.",
            }

        # Calculate days until 1-year expiry from JWT claims if present
        days_until_expiry: Optional[int] = None
        try:
            unverified = jwt.decode(self._token, options={"verify_signature": False})
            exp_ts = unverified.get("exp")
            if exp_ts:
                exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                days_until_expiry = max(0, (exp_dt.date() - now_dt.date()).days)
                if days_until_expiry <= 0:
                    return {
                        "status": "expired",
                        "days_until_expiry": 0,
                        "message": "Upstox Analytics Token has expired.",
                    }
        except Exception:
            pass

        # Cheap live call to check status
        if self._is_mock_token():
            return {
                "status": "ok",
                "days_until_expiry": days_until_expiry or 365,
                "message": "Token health verified (mock environment).",
            }

        try:
            url = f"{self._base_url}/v2/market/status/NSE"
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=self._get_headers())
                if resp.status_code == 200:
                    self.last_successful_fetch = datetime.now(timezone.utc)
                    return {
                        "status": "ok",
                        "days_until_expiry": days_until_expiry,
                        "message": "Upstox Analytics Token is valid and connected.",
                    }
                elif resp.status_code == 401:
                    return {
                        "status": "invalid" if (days_until_expiry is None or days_until_expiry > 0) else "expired",
                        "days_until_expiry": days_until_expiry,
                        "message": "Upstox Analytics Token is invalid or expired. Please generate a new token.",
                    }
                else:
                    return {
                        "status": "degraded",
                        "days_until_expiry": days_until_expiry,
                        "message": f"Upstox returned status code {resp.status_code}.",
                    }
        except Exception as exc:
            return {
                "status": "degraded",
                "days_until_expiry": days_until_expiry,
                "message": f"Could not connect to Upstox API: {exc}",
            }

    # -------------------------------------------------------------------------
    # Candle Validation
    # -------------------------------------------------------------------------

    def validate_candles(
        self,
        symbol: str,
        trading_date: date,
        candles: List[Dict[str, Any]],
    ) -> Tuple[bool, Optional[str]]:
        """Validates candles for integrity.

        Checks:
        - Timestamps in IST within trading session
        - No negative or zero prices
        - high >= low, high >= open, high >= close, low <= open, low <= close
        - No duplicate minutes
        """
        if not candles:
            return False, f"No candles returned for {symbol} on {trading_date}"

        seen_timestamps: Set[int] = set()

        for idx, c in enumerate(candles):
            ts = c.get("timestamp")
            if ts is None:
                return False, f"Missing timestamp at candle index {idx}"

            if ts in seen_timestamps:
                return False, f"Duplicate minute timestamp {ts} detected"
            seen_timestamps.add(ts)

            # Check timestamp in IST (UTC+5:30)
            ist_dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=5, minutes=30)))
            if ist_dt.date() != trading_date:
                return False, f"Candle date {ist_dt.date()} does not match trading date {trading_date}"

            # Trading hours check: 09:15 to 15:30
            c_minutes = ist_dt.hour * 60 + ist_dt.minute
            if c_minutes < (9 * 60 + 15) or c_minutes > (15 * 60 + 30):
                return False, f"Candle time {ist_dt.strftime('%H:%M')} is outside trading hours (09:15-15:30)"

            o = c.get("open", 0.0)
            h = c.get("high", 0.0)
            l = c.get("low", 0.0)
            cl = c.get("close", 0.0)
            vol = c.get("volume", 0.0)

            # Price positivity
            if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
                return False, f"Non-positive price encountered (O:{o}, H:{h}, L:{l}, C:{cl})"
            if vol < 0:
                return False, f"Negative volume encountered ({vol})"

            # Candle envelope check
            if h < l:
                return False, f"High price ({h}) is less than low price ({l})"
            if h < o or h < cl:
                return False, f"High price ({h}) is less than open ({o}) or close ({cl})"
            if l > o or l > cl:
                return False, f"Low price ({l}) is greater than open ({o}) or close ({cl})"

        return True, None

    # -------------------------------------------------------------------------
    # Historical Candle V3
    # -------------------------------------------------------------------------

    def fetch_historical_candles(
        self,
        symbol: str,
        trading_date: date,
        interval: str = "1minute",
    ) -> List[Dict[str, Any]]:
        """Fetches 1-minute candles for a specific symbol on a trading date using Upstox V3.

        Validates each candle and returns chronological candle series.
        """
        # If explicitly requested or mock token in test without real API, use simulated generator
        if self._use_sample_data or self._is_mock_token():
            return self._generate_simulated_candles(symbol, trading_date)

        if not self.is_trading_day(trading_date):
            return []

        instrument_key = self.get_instrument_key(symbol)
        date_str = trading_date.strftime("%Y-%m-%d")

        # Upstox Historical Candle V3: /v3/historical-candle/{instrument_key}/minutes/1/{to_date}/{from_date}
        endpoint = f"{self._base_url}/v3/historical-candle/{instrument_key}/minutes/1/{date_str}/{date_str}"

        try:
            resp = self._execute_request_with_retry("GET", endpoint)
            if resp.status_code == 200:
                data = resp.json()
                raw_candles = data.get("data", {}).get("candles", [])
                if not raw_candles:
                    logger.info("No candles returned from Upstox for %s on %s", symbol, date_str)
                    return []

                # Upstox returns: [timestamp_iso_string, open, high, low, close, volume, open_interest]
                # Candles are returned in reverse chronological order (newest first).
                formatted: List[Dict[str, Any]] = []
                for c in raw_candles:
                    ts_raw = c[0]
                    if isinstance(ts_raw, str):
                        # ISO 8601 string, e.g. '2026-11-06T15:29:00+05:30'
                        dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                        ts = int(dt.timestamp())
                    else:
                        ts = int(ts_raw)

                    formatted.append({
                        "timestamp": ts,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]) if len(c) > 5 else 0.0,
                    })

                # Sort chronologically (oldest to newest: 09:15 to 15:30)
                formatted.sort(key=lambda x: x["timestamp"])

                # Validate candles
                is_valid, reason = self.validate_candles(symbol, trading_date, formatted)
                if not is_valid:
                    logger.warning("Candle validation failed for %s on %s: %s. Skipping symbol.", symbol, date_str, reason)
                    return []

                return formatted
            else:
                logger.warning(
                    "Upstox historical candle returned status %d for %s on %s",
                    resp.status_code,
                    symbol,
                    date_str,
                )
                return []
        except UpstoxAuthError:
            raise
        except Exception as exc:
            logger.warning("Failed to fetch Upstox candles for %s on %s: %s", symbol, date_str, exc)
            return []

    # -------------------------------------------------------------------------
    # Deterministic Generator (Kept behind USE_SAMPLE_DATA for tests)
    # -------------------------------------------------------------------------

    def _generate_simulated_candles(self, symbol: str, trading_date: date) -> List[Dict[str, Any]]:
        """Generates realistic 1-minute intraday candles for a full trading session (09:15 - 15:30).

        Used strictly when USE_SAMPLE_DATA=True or in mock test fixtures.
        Deterministic seed ensures idempotency.
        """
        seed_val = int(trading_date.strftime("%Y%m%d")) + sum(ord(c) for c in symbol)
        rng = random.Random(seed_val)

        base_prices = {
            "RELIANCE": 2850.0,
            "TCS": 3950.0,
            "INFY": 1820.0,
            "HDFCBANK": 1680.0,
            "ICICIBANK": 1240.0,
            "SBIN": 810.0,
            "BHARTIARTL": 1580.0,
            "ITC": 490.0,
            "KOTAKBANK": 1780.0,
            "LT": 3620.0,
        }
        current_price = base_prices.get(symbol.upper(), 1000.0) * (1.0 + rng.uniform(-0.03, 0.03))

        ist_tz = timezone(timedelta(hours=5, minutes=30))
        start_dt = datetime(trading_date.year, trading_date.month, trading_date.day, 9, 15, tzinfo=ist_tz)
        candles: List[Dict[str, Any]] = []
        total_minutes = 375  # 09:15 to 15:30 = 375 minutes

        for i in range(total_minutes):
            minute_dt = start_dt + timedelta(minutes=i)
            ts = int(minute_dt.timestamp())

            if i in (45, 120, 210, 310):
                change_pct = rng.uniform(-0.014, -0.008)
            elif i in (80, 160, 260):
                change_pct = rng.uniform(0.016, 0.025)
            elif 130 <= i <= 175:
                change_pct = rng.uniform(-0.0004, 0.0004)
            else:
                change_pct = rng.gauss(0.0, 0.0015)

            open_p = current_price
            close_p = open_p * (1.0 + change_pct)
            high_p = max(open_p, close_p) * (1.0 + rng.uniform(0.0001, 0.0008))
            low_p = min(open_p, close_p) * (1.0 - rng.uniform(0.0001, 0.0008))
            vol = round(rng.uniform(1000, 15000))

            candles.append({
                "timestamp": ts,
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": float(vol),
            })
            current_price = close_p

        return candles
