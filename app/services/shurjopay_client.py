from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ShurjoPayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ShurjoPayClient:
    _token_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def __init__(
        self,
        *,
        api_root: str | None = None,
        api_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        order_prefix: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        configured_root = api_root or settings.SHURJOPAY_API_ROOT or api_url or settings.SHURJOPAY_API_URL
        self.api_root = self._normalize_api_root(configured_root)
        self.username = username or settings.SHURJOPAY_USERNAME
        self.password = password or settings.SHURJOPAY_PASSWORD
        self.order_prefix = str(order_prefix or settings.SHURJOPAY_ORDER_PREFIX).strip() or "HES"
        self.timeout = timeout

    @staticmethod
    def _mask_token(token: str | None) -> str:
        value = str(token or "").strip()
        return value[:10] if value else ""

    def _log_api_event(
        self,
        *,
        endpoint: str,
        method: str,
        response_status: int | None,
        payload: Any,
        request_token: str | None,
        store_id: str | int | None = None,
        prefix: str | None = None,
        order_id: str | None = None,
        token_in_body: str | None = None,
    ) -> None:
        sp_code = str(payload.get("sp_code")) if isinstance(payload, dict) and payload.get("sp_code") is not None else None
        message = self._extract_message(payload)
        log_data = {
            "endpoint": endpoint,
            "method": method,
            "status_code": response_status,
            "sp_code": sp_code,
            "message": message,
            "store_id": str(store_id) if store_id is not None else None,
            "prefix": prefix,
            "order_id": order_id,
            "has_authorization_header": bool(request_token),
            "token_prefix": self._mask_token(request_token),
        }
        if token_in_body is not None:
            log_data["body_token_matches_auth"] = str(token_in_body).strip() == str(request_token or "").strip()
            log_data["body_token_prefix"] = self._mask_token(token_in_body)

        if sp_code == "1064":
            log_data["debug_checks"] = {
                "environment": "live",
                "authorization_format_expected": "Bearer <token>",
                "token_missing": not bool(str(request_token or "").strip()),
                "possible_bearer_duplication": str(request_token or "").startswith("Bearer "),
                "store_id_present": store_id not in {None, ""},
                "prefix_present": bool(str(prefix or "").strip()),
                "body_mode_expected": "form-data" if endpoint == "/secret-pay" else "json",
                "base_url": self.api_root,
            }
            logger.warning("ShurjoPay unauthorized diagnostic: %s", log_data)
            return
        logger.info("ShurjoPay API event: %s", log_data)

    @classmethod
    def _normalize_api_root(cls, value: str | None) -> str:
        normalized = str(value or "https://engine.shurjopayment.com/api").strip().rstrip("/")
        return normalized if normalized.endswith("/api") else f"{normalized}/api"

    def _ensure_credentials(self) -> None:
        if self.username and self.password:
            return
        raise ShurjoPayError("ShurjoPay credentials are not configured", status_code=500)

    def _build_url(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.api_root}{normalized}"

    def _cache_key(self) -> tuple[str, str]:
        return self.api_root, str(self.username or "")

    def _cached_token(self) -> dict[str, Any] | None:
        cached = self._token_cache.get(self._cache_key())
        if not cached:
            return None
        if float(cached.get("expires_at", 0)) <= time.time():
            self._token_cache.pop(self._cache_key(), None)
            return None
        return cached.get("payload")

    def _cache_token(self, payload: dict[str, Any]) -> None:
        expires_in = self._normalize_expires_in(payload.get("expires_in"))
        self._token_cache[self._cache_key()] = {
            "payload": payload,
            "expires_at": time.time() + max(30, expires_in - 30),
        }

    def _normalize_expires_in(self, raw_value: Any) -> float:
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError):
            return 15 * 60
        if numeric <= 0:
            return 15 * 60
        if numeric > 10_000:
            return numeric / 1000.0
        return numeric

    def _parse_response(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    def _extract_message(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("message", "error", "detail", "sp_message"):
                value = payload.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    return text
        if isinstance(payload, str):
            text = payload.strip()
            return text or None
        return None

    def _raise_error(self, message: str, response: httpx.Response | None = None, payload: Any = None) -> None:
        normalized_payload = payload if payload is not None else (self._parse_response(response) if response is not None else None)
        status_code = response.status_code if response is not None else 502
        detail = self._extract_message(normalized_payload)
        raise ShurjoPayError(detail or message, status_code=status_code, payload=normalized_payload)

    def _validate_gateway_payload(self, payload: Any, *, action: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ShurjoPayError(f"ShurjoPay {action} response was invalid", payload=payload)

        sp_code = str(payload.get("sp_code") or "").strip()

        # Live /secret-pay success returns no sp_code at all — that is fine.
        if not sp_code:
            return payload

        # Known success codes
        if sp_code in {"1000", "200"}:
            return payload

        # ShurjoPay uses sp_code 400 for merchant-side validation errors
        # (e.g. "amount below minimum"). Treat these as HTTP 400, not 502.
        http_status = 400 if sp_code == "400" else 502
        message = self._extract_message(payload) or f"ShurjoPay {action} request failed"

        # Only raise if there is no usable checkout result alongside the error code.
        if not payload.get("token") and not payload.get("checkout_url"):
            raise ShurjoPayError(message, status_code=http_status, payload=payload)

        logger.warning("ShurjoPay %s non-success sp_code=%s: %s", action, sp_code, message)
        return payload

    def authenticate(self, *, force_refresh: bool = False) -> dict[str, Any]:
        self._ensure_credentials()
        if not force_refresh:
            cached = self._cached_token()
            if cached is not None:
                return cached

        logger.info("Requesting shurjoPay token from %s", self.api_root)
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                self._build_url("/get_token"),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json={"username": self.username, "password": self.password},
            )
        if not response.is_success:
            self._raise_error("Unable to authenticate with ShurjoPay", response)

        payload = self._validate_gateway_payload(self._parse_response(response), action="auth")
        self._log_api_event(
            endpoint="/get_token",
            method="POST",
            response_status=response.status_code,
            payload=payload,
            request_token=None,
            store_id=payload.get("store_id") if isinstance(payload, dict) else None,
            prefix=self.order_prefix,
        )
        if not payload.get("token"):
            raise ShurjoPayError("ShurjoPay token response was invalid", payload=payload)
        token_type = str(payload.get("token_type") or "").strip().lower()
        if token_type and token_type != "bearer":
            raise ShurjoPayError("ShurjoPay token_type is invalid", payload=payload)
        sp_code = str(payload.get("sp_code") or "").strip()
        if sp_code and sp_code not in {"1000", "200"}:
            raise ShurjoPayError("ShurjoPay token response rejected", payload=payload)
        if payload.get("store_id") in {None, ""}:
            raise ShurjoPayError("ShurjoPay token response missing store_id", payload=payload)
        logger.info(
            "ShurjoPay token obtained: store_id=%s expires_in=%s token_type=%s",
            payload.get("store_id"),
            payload.get("expires_in"),
            payload.get("token_type"),
        )
        self._cache_token(payload)
        return payload

    def get_shurjopay_token(self, *, force_refresh: bool = False) -> dict[str, Any]:
        payload = self.authenticate(force_refresh=force_refresh)
        return {
            "token": str(payload.get("token") or "").strip(),
            "storeId": payload.get("store_id"),
            "tokenType": str(payload.get("token_type") or "Bearer").strip() or "Bearer",
        }

    def _authorized_post(
        self,
        endpoint: str,
        *,
        json_body: dict[str, Any],
        include_body_token: bool = False,
        body_mode: str = "json",
    ) -> Any:
        last_error: ShurjoPayError | None = None
        for attempt in (0, 1):
            auth_payload = self.authenticate(force_refresh=attempt > 0)
            token = str(auth_payload.get("token") or "").strip()
            token_type = str(auth_payload.get("token_type") or "Bearer").strip() or "Bearer"
            if not token:
                raise ShurjoPayError("ShurjoPay token response was invalid", payload=auth_payload)
            request_body = dict(json_body)
            if include_body_token:
                request_body["token"] = token
                if auth_payload.get("store_id") not in {None, ""}:
                    # Explicitly convert to string — form-data requires string values
                    # and store_id comes back as an integer from the token response (e.g. 1667)
                    request_body["store_id"] = str(auth_payload.get("store_id"))

            request_kwargs: dict[str, Any] = {}
            headers = {
                "Accept": "application/json",
                "Authorization": f"{token_type} {token}",
            }
            if body_mode == "form":
                # ShurjoPay's /secret-pay requires multipart/form-data.
                # Do NOT set Content-Type manually — httpx sets the correct
                # multipart boundary automatically when files= is used.
                request_kwargs["files"] = {
                    key: (None, str(val) if val is not None else "")
                    for key, val in request_body.items()
                }
            else:
                headers["content-type"] = "application/json"
                request_kwargs["json"] = request_body

            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self._build_url(endpoint),
                    headers=headers,
                    **request_kwargs,
                )
            payload = self._parse_response(response)
            self._log_api_event(
                endpoint=endpoint,
                method="POST",
                response_status=response.status_code,
                payload=payload,
                request_token=token,
                store_id=auth_payload.get("store_id"),
                prefix=request_body.get("prefix"),
                order_id=request_body.get("order_id"),
                token_in_body=request_body.get("token") if include_body_token else None,
            )
            if response.is_success:
                return payload
            if response.status_code in {401, 403} and attempt == 0:
                logger.warning("Refreshing shurjoPay token after auth failure on %s", endpoint)
                self._token_cache.pop(self._cache_key(), None)
                last_error = ShurjoPayError(
                    self._extract_message(payload) or "ShurjoPay authorization failed",
                    status_code=response.status_code,
                    payload=payload,
                )
                continue
            self._raise_error(f"Unable to call ShurjoPay endpoint {endpoint}", response, payload=payload)

        if last_error is not None:
            raise last_error
        raise ShurjoPayError(f"Unable to call ShurjoPay endpoint {endpoint}")

    def initiate_payment(
        self,
        checkout_payload: dict[str, Any],
        *,
        return_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        # Build the customer/order payload without auth fields.
        # _authorized_post with include_body_token=True follows the ShurjoPay pattern:
        #   Step 1 — POST /get_token  → receive token + store_id (e.g. 1667)
        #   Step 2 — POST /secret-pay → inject token + store_id into form-data body
        #   Step 3 — redirect user to checkout_url → securepay.shurjopayment.com/spaycheckout?token=...
        payload = {
            **checkout_payload,
            "prefix": self.order_prefix,
            "return_url": return_url,
            "cancel_url": cancel_url,
        }
        logger.info("Initiating shurjoPay checkout for merchant order %s via %s", payload.get("order_id"), self.api_root)
        # ShurjoPay's /secret-pay requires multipart/form-data (not JSON).
        # Sending JSON causes customer details to not be stored in the checkout session,
        # resulting in an empty pre-fill form shown to the user.
        body = self._authorized_post(
            "/secret-pay",
            json_body=payload,
            include_body_token=True,   # injects token + store_id from Step 1 auth response
            body_mode="form",
        )
        validated = self._validate_gateway_payload(body, action="initiate")
        checkout_url = None
        for key in ("checkout_url", "checkout_url_mobile", "checkout_url_iframe", "gateway_url"):
            value = str(validated.get(key) or "").strip()
            if value:
                checkout_url = value
                break
        checkout_url = self._normalize_checkout_url(checkout_url, validated)
        if not checkout_url:
            raise ShurjoPayError("ShurjoPay initiate response was invalid — no checkout URL returned", payload=validated)
        logger.info("ShurjoPay checkout_url: %s", checkout_url)
        return validated

    @staticmethod
    def _normalize_checkout_url(checkout_url: str | None, payload: dict[str, Any]) -> str | None:
        raw = str(checkout_url or "").strip()
        if not raw:
            return None

        parsed = urlparse(raw)
        if "spaycheckout" not in parsed.path:
            return raw

        query = parse_qs(parsed.query, keep_blank_values=True)
        token_values = [str(v or "").strip() for v in query.get("token", [])]
        has_token = any(token_values)
        if has_token:
            return raw

        payload_token = str(payload.get("token") or "").strip()
        payload_order = str(payload.get("sp_order_id") or payload.get("order_id") or "").strip()
        if not payload_token:
            return raw

        query["token"] = [payload_token]
        if payload_order and not any(str(v or "").strip() for v in query.get("order_id", [])):
            query["order_id"] = [payload_order]

        rebuilt = parsed._replace(query=urlencode(query, doseq=True))
        return urlunparse(rebuilt)

    def verify_payment(self, reference: str) -> Any:
        logger.info("Verifying shurjoPay payment reference %s", reference)
        return self._authorized_post("/verification", json_body={"order_id": reference}, body_mode="json")

    def verify_shurjopay_payment(self, sp_order_id: str, *, force_refresh_token: bool = False) -> Any:
        if force_refresh_token:
            self.authenticate(force_refresh=True)
        return self.verify_payment(sp_order_id)

    def debug_shurjopay_auth_flow(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        token_data = self.get_shurjopay_token(force_refresh=True)
        masked = {
            "token_prefix": self._mask_token(token_data.get("token")),
            "store_id": token_data.get("storeId"),
            "token_type": token_data.get("tokenType"),
            "base_url": self.api_root,
        }
        try:
            checkout = self.initiate_payment(
                order_payload,
                return_url=str(order_payload.get("return_url") or settings.SHURJOPAY_RETURN_URL or ""),
                cancel_url=str(order_payload.get("cancel_url") or settings.SHURJOPAY_CANCEL_URL or ""),
            )
            return {"ok": True, "token": masked, "checkout_response": checkout}
        except ShurjoPayError as exc:
            reason = "unauthorized" if isinstance(exc.payload, dict) and str(exc.payload.get("sp_code") or "") == "1064" else "gateway_error"
            return {
                "ok": False,
                "reason": reason,
                "token": masked,
                "error": str(exc),
                "payload": exc.payload if isinstance(exc.payload, dict) else {"raw": str(exc.payload)},
            }
