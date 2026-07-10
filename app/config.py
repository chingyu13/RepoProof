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


CONSENT_TEXT = (
    "By submitting this project you confirm that you own it or have the right to share it, "
    "and you agree that RepoProof analyzes its contents to generate assessment questions. "
    "Only public repositories and files you upload yourself are accepted. "
    "Your code is used solely for this assessment and is deleted after the assessment "
    "lifecycle ends. It is never used to train models."
)
