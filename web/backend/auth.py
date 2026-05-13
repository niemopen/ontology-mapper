"""Clerk JWT verification for FastAPI routes.

When `settings.demo_mode` is true, JWT verification is bypassed and
`require_auth` returns a fixed demo payload. Intended for OASIS / reviewer
deployments where Clerk provisioning is impractical. Never enable in
production — every request becomes the same demo user with admin rights.
"""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWKClient

from config import settings

# auto_error=False lets demo mode skip the Authorization header entirely.
_security = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None


DEMO_USER = {"sub": "demo-user", "o": {"slg": "demo", "rol": "admin"}}


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = settings.clerk_jwks_url
        if not url:
            raise HTTPException(
                status_code=500,
                detail="Clerk JWKS URL not configured. Set CLERK_PUBLISHABLE_KEY in .env",
            )
        _jwks_client = PyJWKClient(url)
    return _jwks_client


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> dict:
    """Dependency that verifies Clerk JWT and returns the decoded payload.

    Returns a dict with at least 'sub' (Clerk user ID).
    """
    if settings.demo_mode:
        return DEMO_USER

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = credentials.credentials
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def get_org_slug(user: dict = Depends(require_auth)) -> str:
    """Extract the active organization slug from the Clerk JWT.

    Clerk v2 JWTs use compressed claims: org data is in the 'o' claim
    as {'id': ..., 'rol': ..., 'slg': ...}. Older/custom templates may
    use 'org_slug' and 'org_id' at the top level.
    """
    # Check compressed 'o' claim first (Clerk v2 default)
    o = user.get("o") or {}
    slug = o.get("slg") or user.get("org_slug") or user.get("org_id")
    if not slug:
        slug = "personal"
    return slug
