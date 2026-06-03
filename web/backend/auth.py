"""Local user stub for FastAPI routes.

This web layer runs with a single fixed local user and no external
authentication provider. `require_auth` always returns the same local
user; `get_org_slug` extracts that user's organization slug. The route
modules depend on these as FastAPI dependencies for org-scoping, so the
signatures are preserved.

There is NO access control — intended for internal / reviewer /
single-tenant deployments only. Do not expose this deployment publicly.
"""

from fastapi import Depends

# The single local user. Org claims mirror the historical compressed 'o'
# shape so get_org_slug and downstream consumers are unchanged.
LOCAL_USER = {"sub": "demo-user", "o": {"slg": "demo", "rol": "admin"}}


async def require_auth() -> dict:
    """Return the fixed local user. No authentication is performed."""
    return LOCAL_USER


def get_org_slug(user: dict = Depends(require_auth)) -> str:
    """Extract the active organization slug from the local user."""
    o = user.get("o") or {}
    slug = o.get("slg") or user.get("org_slug") or user.get("org_id")
    if not slug:
        slug = "personal"
    return slug
