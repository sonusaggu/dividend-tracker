"""
Broker API integration services for Wealthsimple and Questrade.

Encryption helpers use Django's SECRET_KEY via Fernet (cryptography library).
HTTP calls use the requests library only — no broker SDKs required.
"""

import base64
import logging

import requests
from django.conf import settings
from django.utils import timezone
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    """Derive a Fernet key from Django's SECRET_KEY."""
    secret = settings.SECRET_KEY
    # Encode to bytes and take exactly 32 bytes (pad or truncate)
    key_bytes = secret.encode("utf-8")[:32].ljust(32, b"\x00")
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_token(text: str) -> str:
    """Encrypt *text* and return a URL-safe base64 string."""
    f = _get_fernet()
    return f.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_token(text: str) -> str:
    """Decrypt a value produced by :func:`encrypt_token`."""
    f = _get_fernet()
    return f.decrypt(text.encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# Wealthsimple
# ---------------------------------------------------------------------------

class WealthsimpleService:
    """
    Client for the unofficial Wealthsimple Trade API.

    All methods return plain dicts and never raise — exceptions are caught
    and surfaced as ``{"status": "error", "message": "..."}``.
    """

    _AUTH_URL = "https://auth.wealthsimple.com/auth/login/v2"
    _TOKEN_URL = "https://auth.wealthsimple.com/auth/token/v2"
    _TRADE_BASE = "https://trade-service.wealthsimple.com"

    _BASE_HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, email: str, password: str) -> dict:
        """
        Authenticate with email + password.

        Returns one of:
          - ``{"status": "success", "access_token": ..., "refresh_token": ..., "expires_in": ...}``
          - ``{"status": "otp_required", "otp_claim": ...}``
          - ``{"status": "error", "message": ...}``
        """
        payload = {
            "email": email,
            "password": password,
            "timeoutMs": 300000,
        }
        try:
            resp = requests.post(
                self._AUTH_URL,
                json=payload,
                headers=self._BASE_HEADERS,
                timeout=30,
            )
            data = resp.json() if resp.content else {}

            # --- Success path ---
            if resp.status_code == 200 and data.get("access_token"):
                return {
                    "status": "success",
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", ""),
                    "expires_in": data.get("expires_in", 1800),
                }

            # --- OTP required (200 with two_factor flag) ---
            if resp.status_code == 200 and (
                data.get("two_factor_required") or data.get("otp_claim")
            ):
                otp_claim = data.get("otp_claim") or data.get("two_factor_claim", "")
                return {"status": "otp_required", "otp_claim": otp_claim}

            # --- OTP required (401 with OTP header) ---
            if resp.status_code == 401:
                otp_header = resp.headers.get("x-wealthsimple-otp", "")
                if otp_header:
                    # Header format is typically "required;method=<method>;claim=<claim>"
                    otp_claim = ""
                    for part in otp_header.split(";"):
                        if part.startswith("claim="):
                            otp_claim = part.split("=", 1)[1]
                    return {"status": "otp_required", "otp_claim": otp_claim or otp_header}

            # --- Generic error ---
            message = data.get("message") or data.get("error") or resp.text or "Authentication failed"
            return {"status": "error", "message": message}

        except Exception as exc:
            logger.exception("WealthsimpleService.authenticate error")
            return {"status": "error", "message": str(exc)}

    def authenticate_otp(self, otp_claim: str, otp_code: str) -> dict:
        """
        Complete authentication with a one-time password.

        *otp_claim* is returned by :meth:`authenticate` when OTP is required.
        Returns the same shape as :meth:`authenticate`.
        """
        payload = {
            "otp_claim": otp_claim,
        }
        headers = {
            **self._BASE_HEADERS,
            "X-Wealthsimple-OTP": f"{otp_code};remember=true",
        }
        try:
            resp = requests.post(
                self._AUTH_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            data = resp.json() if resp.content else {}

            if resp.status_code == 200 and data.get("access_token"):
                return {
                    "status": "success",
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", ""),
                    "expires_in": data.get("expires_in", 1800),
                }

            message = data.get("message") or data.get("error") or resp.text or "OTP authentication failed"
            return {"status": "error", "message": message}

        except Exception as exc:
            logger.exception("WealthsimpleService.authenticate_otp error")
            return {"status": "error", "message": str(exc)}

    def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Exchange a refresh token for a new access token.

        Returns ``{"status": "success", ...}`` or ``{"status": "error", "message": ...}``.
        """
        payload = {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            resp = requests.post(
                self._TOKEN_URL,
                json=payload,
                headers=self._BASE_HEADERS,
                timeout=30,
            )
            data = resp.json() if resp.content else {}

            if resp.status_code == 200 and data.get("access_token"):
                return {
                    "status": "success",
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", refresh_token),
                    "expires_in": data.get("expires_in", 1800),
                }

            message = data.get("message") or data.get("error") or resp.text or "Token refresh failed"
            return {"status": "error", "message": message}

        except Exception as exc:
            logger.exception("WealthsimpleService.refresh_access_token error")
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Account & position data
    # ------------------------------------------------------------------

    def get_accounts(self, access_token: str) -> list:
        """
        Fetch the list of brokerage accounts for the authenticated user.

        Returns a list of dicts: ``[{"id": ..., "number": ..., "type": ..., "currency": ...}]``.
        Returns an empty list on any error.
        """
        url = f"{self._TRADE_BASE}/account/list"
        headers = {
            **self._BASE_HEADERS,
            "Authorization": f"Bearer {access_token}",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            accounts = []
            for acct in data.get("results", data if isinstance(data, list) else []):
                accounts.append({
                    "id": acct.get("id", ""),
                    "number": acct.get("number", acct.get("account_number", "")),
                    "type": acct.get("account_type", acct.get("type", "")),
                    "currency": acct.get("base_currency", acct.get("currency", "CAD")),
                })
            return accounts
        except Exception as exc:
            logger.exception("WealthsimpleService.get_accounts error")
            return []

    def get_positions(self, access_token: str, account_id: str) -> list:
        """
        Fetch open positions for a given account.

        Returns a list of dicts:
        ``[{"symbol": ..., "quantity": ..., "average_cost": ..., "market_value": ...}]``.
        Returns an empty list on any error.
        """
        url = f"{self._TRADE_BASE}/account/positions"
        headers = {
            **self._BASE_HEADERS,
            "Authorization": f"Bearer {access_token}",
        }
        params = {"account_id": account_id}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            positions = []
            for item in data.get("results", []):
                stock_info = item.get("stock", {})
                symbol = stock_info.get("symbol", item.get("symbol", ""))
                quantity = float(item.get("quantity", 0) or 0)

                # Compute average cost: prefer book_value / quantity, fall back to average_book_price
                book_value = item.get("book_value")
                avg_cost_raw = item.get("average_book_price")
                if book_value is not None and quantity:
                    try:
                        average_cost = float(book_value) / quantity
                    except (TypeError, ZeroDivisionError):
                        average_cost = float(avg_cost_raw or 0)
                else:
                    average_cost = float(avg_cost_raw or 0)

                market_value = float(item.get("market_value", 0) or 0)

                if symbol:
                    positions.append({
                        "symbol": symbol,
                        "quantity": quantity,
                        "average_cost": average_cost,
                        "market_value": market_value,
                    })
            return positions
        except Exception as exc:
            logger.exception("WealthsimpleService.get_positions error")
            return []


# ---------------------------------------------------------------------------
# Questrade
# ---------------------------------------------------------------------------

class QuestradeService:
    """
    Client for the official Questrade API.

    All methods return plain dicts / lists and never raise.
    """

    _TOKEN_URL = "https://login.questrade.com/oauth2/token"

    # ------------------------------------------------------------------
    # Token exchange
    # ------------------------------------------------------------------

    def exchange_token(self, refresh_token: str) -> dict:
        """
        Exchange a Questrade refresh token for a new access token + API server URL.

        Returns:
          ``{"status": "success", "access_token": ..., "refresh_token": ...,
             "api_server": ..., "expires_in": ...}``
          or ``{"status": "error", "message": ...}``.
        """
        payload = f"grant_type=refresh_token&refresh_token={refresh_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            resp = requests.post(
                self._TOKEN_URL,
                data=payload,
                headers=headers,
                timeout=30,
            )
            data = resp.json() if resp.content else {}

            if resp.status_code == 200 and data.get("access_token"):
                return {
                    "status": "success",
                    "access_token": data["access_token"],
                    "refresh_token": data.get("refresh_token", refresh_token),
                    "api_server": data.get("api_server", ""),
                    "expires_in": data.get("expires_in", 1800),
                }

            message = data.get("error_description") or data.get("error") or resp.text or "Token exchange failed"
            return {"status": "error", "message": message}

        except Exception as exc:
            logger.exception("QuestradeService.exchange_token error")
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Account & position data
    # ------------------------------------------------------------------

    def get_accounts(self, access_token: str, api_server: str) -> list:
        """
        Fetch brokerage accounts from Questrade.

        Returns a list of dicts: ``[{"id": ..., "number": ..., "type": ...}]``.
        Returns an empty list on any error.
        """
        # Ensure api_server ends with a slash
        base = api_server.rstrip("/") + "/"
        url = f"{base}v1/accounts"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            accounts = []
            for acct in data.get("accounts", []):
                accounts.append({
                    "id": str(acct.get("number", acct.get("id", ""))),
                    "number": acct.get("number", ""),
                    "type": acct.get("type", ""),
                })
            return accounts
        except Exception as exc:
            logger.exception("QuestradeService.get_accounts error")
            return []

    def get_positions(self, access_token: str, api_server: str, account_id: str) -> list:
        """
        Fetch open positions for a given Questrade account.

        Returns a list of dicts:
        ``[{"symbol": ..., "quantity": ..., "average_cost": ..., "market_value": ...}]``.
        Returns an empty list on any error.
        """
        base = api_server.rstrip("/") + "/"
        url = f"{base}v1/accounts/{account_id}/positions"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            positions = []
            for pos in data.get("positions", []):
                symbol = pos.get("symbol", "")
                quantity = float(pos.get("openQuantity", 0) or 0)
                average_cost = float(pos.get("averageEntryPrice", 0) or 0)
                market_value = float(pos.get("currentMarketValue", 0) or 0)
                if symbol:
                    positions.append({
                        "symbol": symbol,
                        "quantity": quantity,
                        "average_cost": average_cost,
                        "market_value": market_value,
                    })
            return positions
        except Exception as exc:
            logger.exception("QuestradeService.get_positions error")
            return []


# ---------------------------------------------------------------------------
# Sync service
# ---------------------------------------------------------------------------

class SyncService:
    """Synchronise broker holdings into the local UserPortfolio table."""

    def sync_broker_holdings(self, broker_connection) -> dict:
        """
        Pull live positions from the broker and upsert them into UserPortfolio.

        Parameters
        ----------
        broker_connection:
            A ``BrokerConnection`` model instance.  Expected fields:
            ``user``, ``broker`` (str, 'wealthsimple' | 'questrade'),
            ``account_id``, ``access_token`` (encrypted), ``refresh_token``
            (encrypted, optional), ``api_server`` (Questrade only),
            ``token_expiry`` (datetime, nullable), ``last_sync``,
            ``status``, ``sync_error``.

        Returns
        -------
        dict
            ``{"synced": N, "skipped": M, "errors": [...]}``
        """
        from portfolio.models import UserPortfolio, Stock  # local import to avoid circular refs

        conn = broker_connection
        synced = 0
        skipped = 0
        errors = []

        try:
            # ------------------------------------------------------------------
            # 1. Resolve a valid access token
            # ------------------------------------------------------------------
            raw_access_token = decrypt_token(conn.access_token)
            broker_name = (conn.broker or "").lower()

            # Check expiry and refresh if needed
            token_expiry = getattr(conn, "token_expiry", None)
            if token_expiry and timezone.now() >= token_expiry:
                raw_refresh_token = decrypt_token(conn.refresh_token)

                if broker_name == "wealthsimple":
                    result = WealthsimpleService().refresh_access_token(raw_refresh_token)
                    if result["status"] == "success":
                        raw_access_token = result["access_token"]
                        conn.access_token = encrypt_token(raw_access_token)
                        if result.get("refresh_token"):
                            conn.refresh_token = encrypt_token(result["refresh_token"])
                        if result.get("expires_in"):
                            conn.token_expiry = timezone.now() + timezone.timedelta(
                                seconds=int(result["expires_in"])
                            )
                    else:
                        raise RuntimeError(
                            f"Token refresh failed: {result.get('message', 'unknown error')}"
                        )

                elif broker_name == "questrade":
                    result = QuestradeService().exchange_token(raw_refresh_token)
                    if result["status"] == "success":
                        raw_access_token = result["access_token"]
                        conn.access_token = encrypt_token(raw_access_token)
                        if result.get("refresh_token"):
                            conn.refresh_token = encrypt_token(result["refresh_token"])
                        if result.get("api_server"):
                            conn.api_server = result["api_server"]
                        if result.get("expires_in"):
                            conn.token_expiry = timezone.now() + timezone.timedelta(
                                seconds=int(result["expires_in"])
                            )
                    else:
                        raise RuntimeError(
                            f"Token exchange failed: {result.get('message', 'unknown error')}"
                        )

            # ------------------------------------------------------------------
            # 2. Fetch positions from the broker
            # ------------------------------------------------------------------
            account_id = conn.account_id

            if broker_name == "wealthsimple":
                positions = WealthsimpleService().get_positions(raw_access_token, account_id)
            elif broker_name == "questrade":
                api_server = getattr(conn, "api_server", "")
                positions = QuestradeService().get_positions(raw_access_token, api_server, account_id)
            else:
                raise ValueError(f"Unsupported broker: {conn.broker!r}")

            # ------------------------------------------------------------------
            # 3. Upsert into UserPortfolio
            # ------------------------------------------------------------------
            for pos in positions:
                symbol = pos.get("symbol", "").upper()
                quantity = pos.get("quantity", 0)
                avg_cost = pos.get("average_cost", None)

                if not symbol:
                    skipped += 1
                    continue

                try:
                    stock = Stock.objects.get(symbol__iexact=symbol)
                except Stock.DoesNotExist:
                    skipped += 1
                    errors.append(f"Stock not found: {symbol}")
                    continue
                except Exception as exc:
                    skipped += 1
                    errors.append(f"Error looking up {symbol}: {exc}")
                    continue

                try:
                    UserPortfolio.objects.update_or_create(
                        user=conn.user,
                        stock=stock,
                        defaults={
                            "shares_owned": int(quantity),
                            "average_cost": avg_cost,
                            "notes": f"Auto-synced from {conn.broker}",
                        },
                    )
                    synced += 1
                except Exception as exc:
                    skipped += 1
                    errors.append(f"Error saving position for {symbol}: {exc}")

            # ------------------------------------------------------------------
            # 4. Update connection metadata
            # ------------------------------------------------------------------
            conn.last_sync = timezone.now()
            conn.status = "active"
            conn.save()

            return {"synced": synced, "skipped": skipped, "errors": errors}

        except Exception as exc:
            logger.exception("SyncService.sync_broker_holdings error")
            try:
                conn.status = "error"
                conn.sync_error = str(exc)
                conn.save()
            except Exception:
                pass  # best-effort save; don't mask the original error
            raise
