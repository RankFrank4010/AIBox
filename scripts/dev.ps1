$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python environment missing. Run scripts/setup.ps1 first."
}

$backend = Start-Process -FilePath $venvPython `
    -ArgumentList "-m", "aibox_api", "--host", "127.0.0.1", "--port", "8765" `
    -WorkingDirectory $root -PassThru

try {
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:5173"
    & pnpm dev:web
}
finally {
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
