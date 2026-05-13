"""Application settings loaded from environment variables."""

import base64
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Repo root: web/backend/config.py -> web/backend/ -> web/ -> OntologyMapper/
_repo_root = Path(__file__).resolve().parents[2]


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    clerk_publishable_key: str = os.getenv("CLERK_PUBLISHABLE_KEY", "")
    clerk_secret_key: str = os.getenv("CLERK_SECRET_KEY", "")
    runs_dir: Path = Path(os.getenv("RUNS_DIR", str(_repo_root / "runner" / ".compiler-runs")))
    runner_dir: Path = Path(os.getenv("RUNNER_DIR", str(_repo_root / "runner")))
    backend_port: int = int(os.getenv("BACKEND_PORT", "8000"))
    admin_user_id: str = os.getenv("ADMIN_USER_ID", "")
    # Demo mode: bypass Clerk authentication. Backend returns a fixed demo
    # user from require_auth; admin checks treat the demo user as admin.
    #
    # DEFAULT: ON. This makes a fresh checkout runnable with zero config,
    # which is the shape OASIS reviewers and other external consumers will
    # follow. To run with real Clerk auth (production, maintainer dev with
    # Clerk), set DEMO_MODE=0 in .env and configure CLERK_PUBLISHABLE_KEY +
    # CLERK_SECRET_KEY.
    demo_mode: bool = _truthy(os.getenv("DEMO_MODE", "1"))

    @property
    def clerk_jwks_url(self) -> str:
        """Derive JWKS URL from the publishable key's frontend API domain."""
        # Clerk publishable keys are: pk_test_<base64-encoded-domain>
        # The third segment is the frontend API domain, base64-encoded.
        if not self.clerk_publishable_key:
            return ""
        parts = self.clerk_publishable_key.split("_", 2)
        if len(parts) >= 3:
            encoded = parts[2]
            # Add padding if needed and decode
            padded = encoded + "=" * (-len(encoded) % 4)
            domain = base64.b64decode(padded).decode("utf-8").rstrip("$")
            return f"https://{domain}/.well-known/jwks.json"
        return ""


settings = Settings()
