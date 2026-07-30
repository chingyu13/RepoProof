"""Test-process isolation that must run before any test imports app.config."""
import os
import tempfile


_TEST_WORK_DIR = tempfile.mkdtemp(prefix="repoproof-tests-")
os.environ["REPOPROOF_WORK_DIR"] = _TEST_WORK_DIR
os.environ["REPOPROOF_DB"] = os.path.join(_TEST_WORK_DIR, "repoproof.db")
os.environ.setdefault("REPOPROOF_ACCESS_PASSWORD", "test-access-password")
