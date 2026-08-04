import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.local_setup import macos_setup_script, normalize_origin, windows_setup_archive
from app.main import app


ORIGIN = "https://repoproof.chingyu.site"
MODEL = "chingyu/repoproof-qwen:v1"


def _files(archive: bytes) -> dict[str, tuple[str, int]]:
    result = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        for info in package.infolist():
            result[info.filename] = (
                package.read(info).decode("utf-8"),
                info.external_attr >> 16,
            )
    return result


def test_macos_terminal_script_uses_current_origin_and_model():
    script = macos_setup_script(ORIGIN, MODEL)

    assert f"ORIGIN='{ORIGIN}'" in script
    assert f"MODEL='{MODEL}'" in script
    assert "launchctl setenv OLLAMA_ORIGINS" in script
    assert 'ollama pull "$MODEL"' in script
    assert "read '?" not in script


def test_windows_setup_persists_origin_and_uses_current_model():
    archive, filename = windows_setup_archive(ORIGIN, MODEL)
    files = _files(archive)
    powershell, _ = files["RepoProof Local Setup.ps1"]
    launcher, _ = files["RepoProof Local Setup.cmd"]

    assert filename.endswith("Windows.zip")
    assert set(files) == {
        "RepoProof Local Setup.cmd",
        "RepoProof Local Setup.ps1",
    }
    assert f"$Origin = '{ORIGIN}'" in powershell
    assert f"$Model = '{MODEL}'" in powershell
    assert "SetEnvironmentVariable('OLLAMA_ORIGINS'" in powershell
    assert "ExecutionPolicy Bypass" in launcher


def test_setup_values_reject_shell_injection():
    with pytest.raises(ValueError):
        macos_setup_script("https://example.com;touch /tmp/x", MODEL)
    with pytest.raises(ValueError):
        macos_setup_script(ORIGIN, "model'; touch /tmp/x")


def test_origin_is_reduced_to_scheme_host_and_port():
    assert normalize_origin("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"


def test_public_macos_script_uses_request_origin_without_creator_session():
    with TestClient(app) as client:
        response = client.get(
            "/api/local-setup/macos/script",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "repoproof.chingyu.site",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-shellscript")
    assert f"ORIGIN='{ORIGIN}'" in response.text


def test_public_windows_download_remains_available():
    with TestClient(app) as client:
        response = client.get(
            "/api/local-setup/windows",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "repoproof.chingyu.site",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    powershell, _ = _files(response.content)["RepoProof Local Setup.ps1"]
    assert f"$Origin = '{ORIGIN}'" in powershell


def test_old_macos_archive_endpoint_is_removed():
    with TestClient(app) as client:
        response = client.get("/api/local-setup/macos")

    assert response.status_code == 404
