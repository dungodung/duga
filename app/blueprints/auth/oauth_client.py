"""Wikimedia OAuth 2.0 Authorization Code flow (SPEC.md section 9: "Wikimedia
OAuth. A contributor row is created on first login. No Duga-local
passwords, ever.").

As of M6, tokens *are* persisted (encrypted, server-side -- see
app/token_store.py) between login and a later write request, which needs a
still-valid access token possibly minutes or hours after login;
refresh_access_token() is what keeps one usable without asking the person
to log in again every time. M4's original design here was identity-only
with nothing persisted past the single login request; M6's multi-request
preview+confirm write flow (SPEC.md section 9: "show the user an exact
preview... and require confirmation") is why that changed.

Endpoint shape verified against a working production integration
(WikiWhiz's own oauth_client.py, which already hit and fixed the classic
"missing /w/ path segment" mistake) rather than re-derived from scratch.
"""
import secrets
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://meta.wikimedia.org/w/rest.php/oauth2/authorize"
TOKEN_URL = "https://meta.wikimedia.org/w/rest.php/oauth2/access_token"
PROFILE_URL = "https://meta.wikimedia.org/w/rest.php/oauth2/resource/profile"


def new_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(client_id: str, client_secret: str, redirect_uri: str, code: str, timeout: int = 10) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str, timeout: int = 10) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_profile(access_token: str, timeout: int = 10) -> dict:
    resp = requests.get(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()
