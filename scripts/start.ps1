$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python environment missing. Run scripts/setup.ps1 first."
}

Write-Host "[AIBox] Building the Fluent WebUI..."
& pnpm build:web
if ($LASTEXITCODE -ne 0) { throw "WebUI build failed." }

Write-Host "[AIBox] Starting AIBox at http://127.0.0.1:8765 ..."
& $venvPython -m aibox_api --host 127.0.0.1 --port 8765 --open
