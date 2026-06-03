"""Application settings loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Repo root: web/backend/config.py -> web/backend/ -> web/ -> OntologyMapper/
_repo_root = Path(__file__).resolve().parents[2]


class Settings:
    runs_dir: Path = Path(os.getenv("RUNS_DIR", str(_repo_root / "runner" / ".mapper-runs")))
    runner_dir: Path = Path(os.getenv("RUNNER_DIR", str(_repo_root / "runner")))
    backend_port: int = int(os.getenv("BACKEND_PORT", "8000"))


settings = Settings()
