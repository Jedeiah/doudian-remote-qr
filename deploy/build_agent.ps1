# Build Rust Windows agent (self-contained exe, no Python on target)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
Push-Location agent-rs
cargo build --release
Pop-Location
New-Item -ItemType Directory -Force -Path dist | Out-Null
Copy-Item agent-rs\target\release\DoudianRemoteQR.exe dist\DoudianRemoteQR.exe -Force
Write-Host "输出：dist\DoudianRemoteQR.exe"
