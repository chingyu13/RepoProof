"""RepoProof dev server entry point."""
import os

from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("REPOPROOF_PORT", "8000"))
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)
