[CmdletBinding()]
param(
    [switch]$Watch,
    [string]$PythonExecutable
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if ($PythonExecutable) { $venvPython = (Get-Command $PythonExecutable -ErrorAction Stop).Source }
elseif (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $venvPython = (Get-Command python -ErrorAction Stop).Source
}
$repoRoot = Split-Path $PSScriptRoot -Parent
$sdkPaths = @("packages/candlescope-plugin-sdk/src", "packages/candlescope-backtest-sdk/src") |
    ForEach-Object { Join-Path $repoRoot $_ }
$env:PYTHONPATH = (@($sdkPaths) + @($env:PYTHONPATH) | Where-Object { $_ }) -join [IO.Path]::PathSeparator
# Keep legacy databases untouched when resuming the existing development profile.
$devReplayDb = Join-Path $repoRoot "output/dev-servers/replay-current.db"
if (-not $env:REPLAY_DB_PATH -and (Test-Path -LiteralPath $devReplayDb -PathType Leaf)) {
    $env:REPLAY_DB_PATH = $devReplayDb
}
Write-Host "[dev] Python: $venvPython"

# Uvicorn 0.34 switches Windows reload workers to SelectorEventLoop. CandleScope
# starts plugin sidecars with asyncio subprocesses, which require ProactorEventLoop.
# In watch mode, watchfiles keeps Uvicorn itself single-process and sends it SIGINT
# before each restart, so FastAPI can run the normal sidecar shutdown path.
Push-Location $PSScriptRoot
try {
    if ($Watch) {
        # Use a relative executable here: watchfiles' Windows command parser does
        # not strip quotes from an absolute executable path containing spaces.
        $watchPython = $venvPython
        if ($venvPython -eq (Join-Path $PSScriptRoot ".venv\Scripts\python.exe")) {
            $watchPython = ".\.venv\Scripts\python.exe"
        }
        if ($watchPython.Contains(' ')) { throw "Watch mode requires a Python executable path without spaces; use non-watch mode or a local venv." }
        $watchCommand = "$watchPython -m uvicorn app.main:app --host 127.0.0.1 --port 18080"
        Write-Host "[dev] Watching $PSScriptRoot\app for Python changes; restart with Ctrl+C."
        & $venvPython -m watchfiles `
            --filter python `
            --sigint-timeout 20 `
            --target-type command `
            $watchCommand `
            (Join-Path $PSScriptRoot "app")
    }
    else {
        & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 18080
    }
}
finally {
    Pop-Location
}
