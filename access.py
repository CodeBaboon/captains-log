"""Cloudflare Access as the identity provider.

When the app sits behind a Cloudflare Tunnel with an Access policy in front,
Cloudflare has already authenticated the visitor and sends a signed token with
every request. Trusting that token means no registration flow, no invite codes,
no password resets: people are invited in the Cloudflare dashboard and a user
row is created here the first time they arrive.

The token must be verified rather than merely read. The email header on its own
is trivially forgeable by anything that can reach the origin, so this module
checks the JWT signature against Cloudflare's published keys and confirms the
audience matches this application.

Access is off unless both CC_ACCESS_TEAM and CC_ACCESS_AUD are set, so there is
no configuration in which the app trusts an unverified header.
"""

import time

import requests

import config

try:
    import jwt
    from jwt import PyJWKClient

    HAVE_JWT = True
except ImportError:  # pragma: no cover - only when the extra is not installed
    HAVE_JWT = False


COOKIE = "CF_Authorization"
HEADER = "Cf-Access-Jwt-Assertion"
EMAIL_HEADER = "Cf-Access-Authenticated-User-Email"


class AccessError(Exception):
    """The request did not carry a token this app can trust."""


_jwk_client = None
_jwk_fetched_at = 0.0
# Cloudflare rotates signing keys, and PyJWKClient caches internally, but a
# long-lived process should still refresh periodically.
_JWK_TTL = 3600


def enabled():
    return bool(config.ACCESS_TEAM and config.ACCESS_AUD and HAVE_JWT)


def _certs_url():
    team = config.ACCESS_TEAM.strip().rstrip("/")
    if not team.startswith("https://"):
        team = f"https://{team}"
    if not team.endswith(".cloudflareaccess.com"):
        team = f"{team}.cloudflareaccess.com"
    return f"{team}/cdn-cgi/access/certs"


def _client():
    global _jwk_client, _jwk_fetched_at
    now = time.time()
    if _jwk_client is None or now - _jwk_fetched_at > _JWK_TTL:
        _jwk_client = PyJWKClient(_certs_url(), cache_keys=True)
        _jwk_fetched_at = now
    return _jwk_client


def token_from(request):
    """Access sends the token as a header, and as a cookie on direct hits."""
    return request.headers.get(HEADER) or request.cookies.get(COOKIE)


def identify(request):
    """Return the verified email address, or raise AccessError.

    Never falls back to the plain email header: that header is only as
    trustworthy as whoever can reach the origin.
    """
    if not enabled():
        raise AccessError("Access is not configured.")

    token = token_from(request)
    if not token:
        raise AccessError("No Access token on this request.")

    try:
        signing_key = _client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.ACCESS_AUD,
            options={"require": ["exp", "iat", "aud"]},
        )
    except requests.RequestException as exc:
        raise AccessError(f"Could not reach Cloudflare to verify: {exc}") from exc
    except Exception as exc:
        raise AccessError(f"Token rejected: {exc}") from exc

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise AccessError("Token carried no email address.")
    return email


def username_for(email):
    """A readable username from an email address, kept unique by the caller."""
    local = email.split("@", 1)[0]
    cleaned = "".join(ch for ch in local if ch.isalnum() or ch in "._-").strip("._-")
    return cleaned[:40] or "user"
