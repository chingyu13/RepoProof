"""Build OS-specific Ollama setup helpers."""
from __future__ import annotations

import io
import re
import zipfile
from urllib.parse import urlsplit


_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def normalize_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid RepoProof web origin.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid RepoProof web origin.") from exc
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"{parsed.scheme}://{host}{f':{port}' if port else ''}"


def _values(origin: str, model: str) -> tuple[str, str]:
    origin = normalize_origin(origin)
    model = model.strip()
    if not _MODEL_RE.fullmatch(model):
        raise ValueError("Invalid Ollama model name.")
    return origin, model


def macos_setup_script(origin: str, model: str) -> str:
    origin, model = _values(origin, model)
    return f'''#!/bin/zsh
set -euo pipefail

ORIGIN='{origin}'
MODEL='{model}'

if ! command -v ollama >/dev/null 2>&1; then
  echo 'Ollama is not installed. Opening the official download page.'
  open 'https://ollama.com/download'
  echo 'Install Ollama, then paste the RepoProof setup command into Terminal again.'
  exit 1
fi

echo "Allowing $ORIGIN to use this computer's Ollama..."
launchctl setenv OLLAMA_ORIGINS "$ORIGIN"

osascript -e 'quit app "Ollama"' >/dev/null 2>&1 || true
pkill -x ollama >/dev/null 2>&1 || true

if open -Ra 'Ollama' >/dev/null 2>&1; then
  open -a 'Ollama'
else
  mkdir -p "$HOME/.ollama"
  OLLAMA_ORIGINS="$ORIGIN" nohup ollama serve >"$HOME/.ollama/repoproof-serve.log" 2>&1 &
fi

READY=0
for _ in {{1..60}}; do
  if curl -fsS 'http://127.0.0.1:11434/api/tags' >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
if [[ "$READY" != '1' ]]; then
  echo 'Ollama did not start within 60 seconds.'
  exit 1
fi

echo "Downloading $MODEL..."
ollama pull "$MODEL"
echo 'RepoProof Local LLM setup is complete.'
open "$ORIGIN/creator"
'''


def _windows_script(origin: str, model: str) -> str:
    return f'''$ErrorActionPreference = 'Stop'
$Origin = '{origin}'
$Model = '{model}'

$Ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $Ollama) {{
    $Candidate = Join-Path $env:LOCALAPPDATA 'Programs\\Ollama\\ollama.exe'
    if (Test-Path $Candidate) {{
        $Ollama = Get-Item $Candidate
    }} else {{
        Write-Host 'Ollama is not installed. Opening the official download page.'
        Start-Process 'https://ollama.com/download'
        Read-Host 'Install Ollama, then run this setup again. Press Enter to close'
        exit 1
    }}
}}
$OllamaPath = $Ollama.Source
if (-not $OllamaPath) {{ $OllamaPath = $Ollama.FullName }}

Write-Host "Allowing $Origin to use this computer's Ollama..."
[Environment]::SetEnvironmentVariable('OLLAMA_ORIGINS', $Origin, 'User')
$env:OLLAMA_ORIGINS = $Origin
Get-Process -Name 'ollama app','ollama' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process -FilePath $OllamaPath -ArgumentList 'serve' -WindowStyle Hidden

$Ready = $false
for ($i = 0; $i -lt 60; $i++) {{
    try {{
        Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
        $Ready = $true
        break
    }} catch {{
        Start-Sleep -Seconds 1
    }}
}}
if (-not $Ready) {{ throw 'Ollama did not start within 60 seconds.' }}

Write-Host "Downloading $Model..."
& $OllamaPath pull $Model
if ($LASTEXITCODE -ne 0) {{ throw 'The Ollama model download failed.' }}
Write-Host 'RepoProof Local LLM setup is complete.'
Start-Process "$Origin/creator"
Read-Host 'Return to RepoProof and click Check again. Press Enter to close'
'''


def _zip(files: list[tuple[str, str, int]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in files:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, content.encode("utf-8"))
    return output.getvalue()


def windows_setup_archive(origin: str, model: str) -> tuple[bytes, str]:
    origin, model = _values(origin, model)
    powershell = _windows_script(origin, model)
    launcher = (
        "@echo off\r\n"
        "powershell.exe -NoProfile -ExecutionPolicy Bypass "
        "-File \"%~dp0RepoProof Local Setup.ps1\"\r\n"
        "if errorlevel 1 pause\r\n"
    )
    return _zip([
        ("RepoProof Local Setup.cmd", launcher, 0o644),
        ("RepoProof Local Setup.ps1", powershell, 0o644),
    ]), "RepoProof-Local-Setup-Windows.zip"
