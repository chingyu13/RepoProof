"""Central configuration, read from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = Path(os.environ.get("REPOPROOF_WORK_DIR", BASE_DIR / "data"))
PROJECTS_DIR = WORK_DIR / "projects"
DB_PATH = Path(os.environ.get("REPOPROOF_DB", WORK_DIR / "repoproof.db"))

MAX_PROJECT_MB = int(os.environ.get("REPOPROOF_MAX_MB", "1024"))
PRO_CONTACT = "jobs@chingyu.site"

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-terra")
OPENAI_RAW_MAX_CHARS = int(os.environ.get("REPOPROOF_OPENAI_RAW_MAX_CHARS", "350000"))
ACCESS_PASSWORD = os.environ.get("REPOPROOF_ACCESS_PASSWORD", "").strip()
SESSION_SECRET = os.environ.get("REPOPROOF_SESSION_SECRET", "").strip()

_OPENAI_MODEL_OPTIONS = (
    {
        "id": "gpt-5.6-terra",
        "name": "GPT-5.6 Terra",
        "note": "recommended balance",
    },
    {
        "id": "gpt-5.6-luna",
        "name": "GPT-5.6 Luna",
        "note": "lower cost",
    },
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o mini",
        "note": "fast baseline",
    },
)
if OPENAI_MODEL not in {option["id"] for option in _OPENAI_MODEL_OPTIONS}:
    OPENAI_MODEL = "gpt-5.6-terra"

# Local LLM (privacy mode): any OpenAI-compatible server works.
#   Ollama    -> http://127.0.0.1:11434/v1   (default)
#   LM Studio -> http://127.0.0.1:1234/v1
LOCAL_LLM_URL = os.environ.get("REPOPROOF_LOCAL_LLM_URL", "http://127.0.0.1:11434/v1").rstrip("/")
LOCAL_LLM_MODEL = os.environ.get("REPOPROOF_LOCAL_LLM_MODEL", "qwen2.5-coder:7b")
LOCAL_LLM_MAX_TOKENS = int(os.environ.get("REPOPROOF_LOCAL_LLM_MAX_TOKENS", "700"))
# optional forced default: 'openai' | 'local' | 'mock'
_FORCED_PROVIDER = os.environ.get("REPOPROOF_LLM_PROVIDER", "").strip().lower()


def openai_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def openai_model_options() -> list[dict]:
    return [dict(option) for option in _OPENAI_MODEL_OPTIONS]


def resolve_model(provider: str, requested: str = "") -> str:
    if provider == "local":
        return LOCAL_LLM_MODEL
    if provider == "openai":
        allowed = {option["id"] for option in openai_model_options()}
        return requested if requested in allowed else OPENAI_MODEL
    return "mock"


def local_llm_available(timeout: float = 1.2) -> bool:
    """Ping the local server's /models endpoint. Cheap enough to call per request."""
    import urllib.request
    try:
        req = urllib.request.Request(LOCAL_LLM_URL + "/models")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def default_provider(*, local_available: bool | None = None) -> str:
    """Resolution order: explicit env override > MOCK_LLM flag > OpenAI key > local server > mock.

    Pass ``local_available`` when the caller already probed the local server so
    availability and the selected default stay consistent in one response.
    """
    if _FORCED_PROVIDER in ("openai", "local", "mock"):
        return _FORCED_PROVIDER
    if os.environ.get("MOCK_LLM", "").lower() in ("1", "true", "yes"):
        return "mock"
    if openai_api_key():
        return "openai"
    available = local_llm_available() if local_available is None else local_available
    if available:
        return "local"
    return "mock"

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
