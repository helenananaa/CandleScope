[CmdletBinding()]
param(
    [switch]$Offline,
    [switch]$SkipPineRuntime,
    [switch]$ForceDependencies
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$setupArguments = @()
if ($Offline) {
    $setupArguments += "-Offline"
}
if ($SkipPineRuntime) {
    $setupArguments += "-SkipPineRuntime"
}
if ($ForceDependencies) {
    $setupArguments += "-ForceDependencies"
}

& (Join-Path $PSScriptRoot "setup.ps1") @setupArguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Push-Location $PSScriptRoot
try {
    & $python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 18080
    $serverExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $serverExitCode
