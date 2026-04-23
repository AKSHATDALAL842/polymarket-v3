"""
Kalshi Markets — fetches active binary markets from Kalshi's REST API v2
and maps them to the shared Market dataclass (source='kalshi').

Authentication (pick one):
  Option A — email + password: set KALSHI_EMAIL + KALSHI_PASSWORD
             Token cached in memory, refreshed every 55 minutes.
  Option B — RSA API key: set KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH
             Each request is signed with your RSA private key.

Kalshi prices are in cents (1–99); we normalise to [0,1] floats.
Kalshi volumes are in contracts; we convert to USD (contracts × avg_price).
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

import httpx

import config
from ingestion.markets import Market, _infer_category, filter_by_categories

log = logging.getLogger(__name__)

# ── Token cache (option A) ─────────────────────────────────────────────────────

@dataclass
class _TokenCache:
    token: str
    member_id: str
    expires_at: float   # monotonic time

_token_cache: _TokenCache | None = None
_TOKEN_TTL = 55 * 60   # refresh 5 min before the 1-hour expiry


def _get_auth_headers(method: str = "GET", path: str = "/trade-api/v2/markets") -> dict:
    """
    Return auth headers.  Tries RSA key first; falls back to email/password.
    Returns an empty dict if no credentials are configured.

    For RSA auth, `method` and `path` must match the actual request being signed
    (Kalshi verifies the signature against the incoming request path).
    """
    # Option B: RSA key signing
    if config.KALSHI_API_KEY_ID and config.KALSHI_PRIVATE_KEY_PATH:
        return _rsa_headers(method, path)

    # Option A: email/password JWT
    if config.KALSHI_EMAIL and config.KALSHI_PASSWORD:
        token = _ensure_token()
        if token:
            return {"Authorization": f"Bearer {token}"}

    return {}


def _ensure_token() -> str | None:
    """Return a valid JWT, refreshing if expired."""
    global _token_cache
    now = time.monotonic()
    if _token_cache and _token_cache.expires_at > now:
        return _token_cache.token

    try:
        resp = httpx.post(
            f"{config.KALSHI_HOST}/login",
            json={"email": config.KALSHI_EMAIL, "password": config.KALSHI_PASSWORD},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token", "")
        if not token:
            log.warning("[kalshi] Login returned no token")
            return None
        _token_cache = _TokenCache(
            token=token,
            member_id=data.get("member_id", ""),
            expires_at=now + _TOKEN_TTL,
        )
        log.info("[kalshi] Token refreshed")
        return token
    except Exception as e:
        log.warning(f"[kalshi] Login failed: {e}")
        return None


def _rsa_headers(method: str, path: str) -> dict:
    """
    Build RSA-signed request headers for Kalshi API key auth.
    Requires cryptography package: pip install cryptography

    Kalshi signature message: timestamp_ms + HTTP_METHOD + url_path
    (path is the URL path only, e.g. "/trade-api/v2/markets")
    """
    try:
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        with open(config.KALSHI_PRIVATE_KEY_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)

        ts = str(int(time.time() * 1000))
        msg = (ts + method.upper() + path).encode()
        sig = private_key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.b64encode(sig).decode()

        return {
            "KALSHI-ACCESS-KEY": config.KALSHI_API_KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    except Exception as e:
        log.warning(f"[kalshi] RSA header build failed: {e}")
        return {}


# ── Market fetching ────────────────────────────────────────────────────────────

# Kalshi → our category mapping
_KALSHI_CATEGORY_MAP: dict[str, str] = {
    "Economics":    "politics",   # macro/fed/CPI → treated as politics
    "Politics":     "politics",
    "Science":      "science",
    "Technology":   "technology",
    "Crypto":       "crypto",
    "Climate":      "science",
    "Health":       "science",
    "Sports":       "other",
    "Finance":      "politics",
    "Entertainment":"other",
}


def _map_category(kalshi_cat: str, question: str) -> str:
    """Map Kalshi category string → our internal category."""
    mapped = _KALSHI_CATEGORY_MAP.get(kalshi_cat, "")
    if mapped:
        return mapped
    # Fall back to keyword inference
    return _infer_category(question, [kalshi_cat])


def _cents_to_prob(cents: int | float | None, fallback: float = 0.5) -> float:
    """Convert Kalshi cent price (0–100) to probability float (0–1)."""
    if cents is None:
        return fallback
    return max(0.01, min(0.99, float(cents) / 100.0))


def _volume_to_usd(volume_contracts: int | float, avg_price: float) -> float:
    """Rough USD conversion: contracts × average price per contract."""
    return float(volume_contracts) * max(0.01, avg_price)


def fetch_kalshi_markets(limit: int = 200) -> list[Market]:
    """
    Fetch open binary markets from Kalshi and return as Market objects.
    Returns [] if Kalshi is disabled or credentials are missing.
    """
    if not config.KALSHI_ENABLED:
        return []

    headers = _get_auth_headers()
    # Auth is optional for public market data on Kalshi
    # (order placement always requires auth)

    markets: list[Market] = []
    cursor = ""

    try:
        with httpx.Client(timeout=15) as client:
            while True:
                params: dict = {"status": "open", "limit": min(limit, 200)}
                if cursor:
                    params["cursor"] = cursor

                resp = client.get(
                    f"{config.KALSHI_HOST}/markets",
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

                batch = data.get("markets", [])
                if not batch:
                    break

                for m in batch:
                    market = _parse_kalshi_market(m)
                    if market:
                        markets.append(market)

                cursor = data.get("cursor", "")
                if not cursor or len(markets) >= limit:
                    break

    except Exception as e:
        log.warning(f"[kalshi] Market fetch error: {e}")

    log.info(f"[kalshi] Fetched {len(markets)} open markets")
    return markets


def _parse_kalshi_market(m: dict) -> Market | None:
    """Parse one Kalshi market dict into a Market dataclass."""
    try:
        ticker = m.get("ticker", "")
        if not ticker:
            return None

        status = m.get("status", "")
        if status not in ("open", "active"):
            return None

        title = m.get("title", m.get("subtitle", ticker))
        kalshi_cat = m.get("category", "")

        # Prices — Kalshi returns in cents (0–100)
        yes_bid = m.get("yes_bid", 50)
        yes_ask = m.get("yes_ask", 50)
        # Mid-price for YES
        yes_price = _cents_to_prob((yes_bid + yes_ask) / 2)
        no_price  = round(1.0 - yes_price, 4)

        # Volume — Kalshi reports in contracts; convert to rough USD
        volume_contracts = float(m.get("volume", 0) or 0)
        avg_price = yes_price * 0.5 + 0.5 * 0.5   # rough blend
        volume_usd = _volume_to_usd(volume_contracts, avg_price)

        # End date
        end_date = m.get("close_time", m.get("expiration_time", ""))

        # Skip fully resolved or zero-volume markets
        if yes_price in (0.0, 1.0) and volume_usd == 0:
            return None

        category = _map_category(kalshi_cat, title)

        # Build a stable condition_id from the ticker
        # (Kalshi tickers like "FED-25-MAY-T" are already unique strings)
        condition_id = f"kalshi:{ticker}"

        return Market(
            condition_id=condition_id,
            question=title,
            category=category,
            yes_price=yes_price,
            no_price=no_price,
            volume=volume_usd,
            end_date=end_date,
            active=True,
            tokens=[],          # Kalshi has no token model
            source="kalshi",
        )

    except (KeyError, ValueError, TypeError) as e:
        log.debug(f"[kalshi] Parse error for {m.get('ticker','?')}: {e}")
        return None


def get_kalshi_ticker(market: Market) -> str:
    """Extract raw Kalshi ticker from our condition_id (strips 'kalshi:' prefix)."""
    return market.condition_id.replace("kalshi:", "")
