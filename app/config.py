"""Central configuration, read from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = Path(os.environ.get("REPOPROOF_WORK_DIR", BASE_DIR / "data"))
PROJECTS_DIR = WORK_DIR / "projects"
DB_PATH = Path(os.environ.get("REPOPROOF_DB", WORK_DIR / "repoproof.db"))

MAX_PROJECT_MB = int(os.environ.get("REPOPROOF_MAX_MB", "1024"))
PRO_CONTACT = "jobs@chingyu.site"

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def openai_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def mock_mode() -> bool:
    """Mock mode is forced on when no API key is configured."""
    if os.environ.get("MOCK_LLM", "").lower() in ("1", "true", "yes"):
        return True
    return not openai_api_key()


# Consent copy (RepoProof UI / Step 1). Bump CONSENT_VERSION whenever the wording
# changes so stored per-project consent records stay auditable.
CONSENT_VERSION = "2026-07-12-v2"

# Required acknowledgment — the taker must accept this to analyse a project.
CONSENT_TEXT = (
    "*I acknowledge that RepoProof analyses this project's contents to generate assessment "
    "questions. The content will be deleted unless I opt in to data sharing above."
)

# Optional opt-in — sharing a de-identified copy to help improve the model.
DATA_SHARING_TEXT = (
    "I agree to share a de-identified copy of the project for improving RepoProof's models."
)
