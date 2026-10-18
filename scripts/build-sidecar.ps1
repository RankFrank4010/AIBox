$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python environment missing. Run scripts/setup.ps1 --cuda first."
}

Write-Host "[AIBox] Installing PyInstaller..."
& $venvPython -m pip install -e "services/api[desktop]"

$hostLine = (& rustc -vV | Select-String "^host:").ToString()
$triple = ($hostLine -split ":")[1].Trim()
Write-Host "[AIBox] Building API sidecar for $triple ..."

$buildDir = Join-Path $root "build\sidecar"
$distDir = Join-Path $root "build\sidecar-dist"
$binaries = Join-Path $root "apps\desktop\src-tauri\binaries"
New-Item -ItemType Directory -Force $binaries | Out-Null

& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name "aibox-server" `
    --distpath $distDir `
    --workpath $buildDir `
    --specpath $buildDir `
    --collect-all ctranslate2 `
    --collect-all faster_whisper `
    --collect-all tokenizers `
    --collect-all onnxruntime `
    --collect-all av `
    --collect-submodules uvicorn `
    --collect-submodules grpc `
    --collect-submodules grpc_reflection `
    --collect-submodules aibox_api `
    --collect-data aibox_api `
    "services\api\aibox_sidecar.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$extension = if ($IsWindows -or $env:OS -eq "Windows_NT") { ".exe" } else { "" }
$target = Join-Path $binaries "aibox-server-$triple$extension"
Copy-Item (Join-Path $distDir "aibox-server$extension") $target -Force
Write-Host "[AIBox] Sidecar ready: $target"
Write-Host "Next: pnpm --filter @aibox/desktop build"
