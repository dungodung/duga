"""Wikimedia OAuth 2.0 Authorization Code flow (SPEC.md section 9: "Wikimedia
OAuth. A contributor row is created on first login. No Duga-local
passwords, ever."). Identity-only: Duga never persists access/refresh
tokens past the single request that uses one to fetch the profile.

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


def fetch_profile(access_token: str, timeout: int = 10) -> dict:
    resp = requests.get(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()
