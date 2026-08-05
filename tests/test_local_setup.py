from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.local_setup import macos_setup_script, normalize_origin, windows_setup_script
from app.main import app


ORIGIN = "https://repoproof.chingyu.site"
MODEL = "chingyu/repoproof-qwen:v1"


def test_macos_terminal_script_uses_current_origin_and_model():
    script = macos_setup_script(ORIGIN, MODEL)

    assert f"ORIGIN='{ORIGIN}'" in script
    assert f"MODEL='{MODEL}'" in script
    assert "launchctl setenv OLLAMA_ORIGINS" in script
    assert 'ollama pull "$MODEL"' in script
    assert 'open "$ORIGIN/creator"' not in script
    assert "read '?" not in script


def test_windows_terminal_script_uses_current_origin_and_model():
    script = windows_setup_script(ORIGIN, MODEL)

    assert f"$Origin = '{ORIGIN}'" in script
    assert f"$Model = '{MODEL}'" in script
    assert "SetEnvironmentVariable('OLLAMA_ORIGINS'" in script
    assert "& $OllamaPath pull $Model" in script
    assert 'Start-Process "$Origin/creator"' not in script
    assert "Read-Host" not in script


def test_setup_values_reject_shell_injection():
    with pytest.raises(ValueError):
        macos_setup_script("https://example.com;touch /tmp/x", MODEL)
    with pytest.raises(ValueError):
        macos_setup_script(ORIGIN, "model'; touch /tmp/x")
    with pytest.raises(ValueError):
        windows_setup_script(ORIGIN, "model'; touch /tmp/x")


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


def test_public_windows_script_uses_request_origin_without_creator_session():
    with TestClient(app) as client:
        response = client.get(
            "/api/local-setup/windows/script",
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "repoproof.chingyu.site",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-powershell")
    assert f"$Origin = '{ORIGIN}'" in response.text


def test_old_macos_archive_endpoint_is_removed():
    with TestClient(app) as client:
        response = client.get("/api/local-setup/macos")

    assert response.status_code == 404


def test_old_windows_archive_endpoint_is_removed():
    with TestClient(app) as client:
        response = client.get("/api/local-setup/windows")

    assert response.status_code == 404


def test_creator_embeds_local_setup_in_the_question_framework():
    creator = (Path(__file__).parents[1] / "app" / "static" / "creator.html").read_text()

    assert 'id="localInstructions"' in creator
    assert 'id="localMac"' in creator
    assert 'id="localWindows"' in creator
    assert 'id="localCopy"' in creator
    assert 'href="/static/local-setup.html"' not in creator
    assert ".local-setup.ready{display:block;gap:0;margin:0;padding:0;border:0" in creator
    assert "{checking:false, ready:true}" in creator
