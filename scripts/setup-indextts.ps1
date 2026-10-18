$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$home = if ($env:AIBOX_INDEXTTS_HOME) { $env:AIBOX_INDEXTTS_HOME } else { Join-Path $root "runtimes\index-tts" }
$repoUrl = "https://github.com/index-tts/index-tts.git"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it with: pip install -U uv"
}

if (-not (Test-Path (Join-Path $home "indextts"))) {
    Write-Host "[AIBox] Cloning IndexTTS runtime to $home ..."
    New-Item -ItemType Directory -Force (Split-Path -Parent $home) | Out-Null
    git clone --depth 1 $repoUrl $home
} else {
    Write-Host "[AIBox] IndexTTS checkout already exists: $home"
}

Write-Host "[AIBox] Installing IndexTTS dependencies with uv (this can take a long time)..."
Push-Location $home
try {
    uv sync
} finally {
    Pop-Location
}

$python = if ($IsWindows -or $env:OS -eq "Windows_NT") {
    Join-Path $home ".venv\Scripts\python.exe"
} else {
    Join-Path $home ".venv/bin/python"
}

Write-Host ""
Write-Host "[AIBox] IndexTTS runtime is ready."
Write-Host "Set these before starting AIBox:"
Write-Host "  AIBOX_INDEXTTS_HOME=$home"
Write-Host "  AIBOX_INDEXTTS_PYTHON=$python"
Write-Host ""
Write-Host "Then open the AIBox model library → IndexTTS and download IndexTTS 2.5 or 2."
Write-Host "For a quick UI-only test use AIBOX_DEMO_TTS=1 instead."
