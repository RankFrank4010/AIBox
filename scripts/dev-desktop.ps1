$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python environment missing. Run scripts/setup.ps1 first."
}

Write-Host "[AIBox] Starting the Tauri desktop shell (Windows / macOS only)."
Write-Host "[AIBox] The shell starts the local API automatically."
& pnpm --filter @aibox/desktop dev
