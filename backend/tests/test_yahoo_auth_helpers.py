"""Yahoo OAuth helpers: GUID from id_token, app-not-approved detection."""

import base64
import json

import httpx

from app.connectors.yahoo import guid_from_id_token, is_not_authorized


def _jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJFUzI1NiJ9.{body}.sig"


def test_guid_from_id_token_reads_sub():
    assert guid_from_id_token(_jwt({"sub": "ABC123", "aud": "x"})) == "ABC123"


def test_guid_from_id_token_handles_missing_or_garbage():
    assert guid_from_id_token(None) is None
    assert guid_from_id_token("not-a-jwt") is None
    assert guid_from_id_token("a.!!!.c") is None


def _status_error(status: int, text: str) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://fantasysports.yahooapis.com/fantasy/v2/x")
    resp = httpx.Response(status, text=text, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


def test_is_not_authorized_matches_yahoo_app_block():
    exc = _status_error(403, '{"error":{"description":"This application is not authorized to perform this action"}}')
    assert is_not_authorized(exc)


def test_is_not_authorized_ignores_other_failures():
    assert not is_not_authorized(_status_error(401, "token_expired"))
    assert not is_not_authorized(_status_error(500, "boom"))
    assert not is_not_authorized(ValueError("no response"))
