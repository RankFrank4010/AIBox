$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pythonCmd = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[AIBox] Creating Python virtual environment..."
    & $pythonCmd -m venv .venv
}

Write-Host "[AIBox] Installing Python API (ASR + dev tools)..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e "services/api[dev,asr]"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[AIBox] Retrying without build isolation..."
    & $venvPython -m pip install --no-build-isolation -e "services/api[dev,asr]"
}

if ($args -contains "--cuda") {
    Write-Host "[AIBox] Installing optional NVIDIA CUDA 12 runtime libraries..."
    & $venvPython -m pip install -e "services/api[cuda12]"
}

$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpm) {
    Write-Host "[AIBox] pnpm was not found. Install Node.js 20+ and pnpm 10+, then rerun this script."
    exit 1
}

Write-Host "[AIBox] Installing WebUI dependencies..."
& pnpm install --store-dir .pnpm-store --package-import-method=copy

Write-Host ""
Write-Host "[AIBox] Setup complete."
Write-Host "  Web dev:      powershell -ExecutionPolicy Bypass -File scripts/dev.ps1"
Write-Host "  Production:   powershell -ExecutionPolicy Bypass -File scripts/start.ps1"
Write-Host "  Desktop dev:  powershell -ExecutionPolicy Bypass -File scripts/dev-desktop.ps1"
Write-Host "  Optional GPU: rerun with --cuda"
