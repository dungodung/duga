"""Server-side storage for OAuth access/refresh tokens (SPEC.md section 9
write path) -- encrypted at rest via app/token_crypto.py, never in the
session cookie. See app/blueprints/auth/oauth_client.py's module docstring
for why this exists (it reverses M4's original never-persisted design).
"""
from datetime import datetime, timedelta, timezone

from flask import current_app

from .blueprints.auth import oauth_client
from .extensions import db
from .models import ContributorToken
from .token_crypto import decrypt, encrypt

# Treat a token as expired slightly before Wikimedia actually would, so a
# request never starts with a token that dies mid-flight.
EXPIRY_SAFETY_MARGIN = timedelta(seconds=60)


class TokenUnavailable(RuntimeError):
    """No usable access token for this contributor -- caller should send
    them back through /login rather than attempt a write."""


def save_tokens(contributor_id, access_token, refresh_token, expires_in):
    key = current_app.config["DUGA_TOKEN_ENCRYPTION_KEY"]
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None

    row = db.session.get(ContributorToken, contributor_id)
    if row is None:
        row = ContributorToken(contributor_id=contributor_id)
        db.session.add(row)
    row.access_token_encrypted = encrypt(key, access_token)
    row.refresh_token_encrypted = encrypt(key, refresh_token) if refresh_token else None
    row.expires_at = expires_at
    row.updated_at = datetime.now(timezone.utc)


def get_valid_access_token(contributor_id):
    """Returns a currently-usable access token, transparently refreshing it
    first if it's expired (or close to it). Raises TokenUnavailable if
    there's no stored token, no refresh token to fall back on, or the
    refresh itself fails (e.g. the person revoked Duga's access) -- in
    every one of those cases the right move is a fresh /login, not a crash.
    """
    key = current_app.config["DUGA_TOKEN_ENCRYPTION_KEY"]
    row = db.session.get(ContributorToken, contributor_id)
    if row is None:
        raise TokenUnavailable("no stored token for this contributor")

    # Every DateTime column in this codebase is stored as naive-but-UTC
    # (the convention throughout app/models/), and both SQLite and MySQL
    # round-trip DateTime values as naive regardless of what was written --
    # comparing that directly against a tz-aware datetime.now(timezone.utc)
    # raises TypeError. Attach UTC explicitly before comparing.
    expires_at = row.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    still_fresh = expires_at is None or datetime.now(timezone.utc) < expires_at - EXPIRY_SAFETY_MARGIN
    if still_fresh:
        return decrypt(key, row.access_token_encrypted)

    if not row.refresh_token_encrypted:
        raise TokenUnavailable("access token expired and no refresh token was stored")

    refresh_token = decrypt(key, row.refresh_token_encrypted)
    try:
        token = oauth_client.refresh_access_token(
            current_app.config["DUGA_OAUTH_CLIENT_ID"],
            current_app.config["DUGA_OAUTH_CLIENT_SECRET"],
            refresh_token,
        )
    except Exception as exc:  # noqa: BLE001 -- any refresh failure means "log in again", not a 500
        raise TokenUnavailable(f"token refresh failed: {exc}") from exc

    save_tokens(
        contributor_id,
        token["access_token"],
        token.get("refresh_token", refresh_token),
        token.get("expires_in"),
    )
    db.session.commit()
    return token["access_token"]
