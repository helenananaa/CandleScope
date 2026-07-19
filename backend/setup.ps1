[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [switch]$Offline,
    [switch]$SkipPineRuntime,
    [switch]$ForceDependencies
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$backendDir = $PSScriptRoot
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirementsPath = Join-Path $backendDir "requirements.txt"
$requirementsMarker = Join-Path $venvDir ".candlescope-requirements.sha256"
$ensureRuntime = Join-Path $backendDir "scripts\ensure_pine_runtime.py"

function Test-CompatiblePython {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    & $Executable @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Resolve-BootstrapPython {
    $requested = $PythonExecutable
    if (-not $requested) {
        $requested = $env:CANDLESCOPE_PYTHON
    }
    if ($requested) {
        $command = Get-Command $requested -ErrorAction SilentlyContinue
        if (-not $command -or -not (Test-CompatiblePython -Executable $command.Source)) {
            throw "CANDLESCOPE_PYTHON/PythonExecutable must resolve to Python 3.10 or newer: $requested"
        }
        return [pscustomobject]@{ Executable = $command.Source; PrefixArguments = @() }
    }

    $launcher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @("3.13", "3.12", "3.11", "3.10")) {
            $prefix = @("-$version")
            if (Test-CompatiblePython -Executable $launcher.Source -PrefixArguments $prefix) {
                return [pscustomobject]@{
                    Executable = $launcher.Source
                    PrefixArguments = $prefix
                }
            }
        }
    }

    foreach ($name in @("python", "python3")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and (Test-CompatiblePython -Executable $command.Source)) {
            return [pscustomobject]@{ Executable = $command.Source; PrefixArguments = @() }
        }
    }
    throw "Python 3.10 or newer was not found. Install CPython and retry."
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$CommandArguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    & $Executable @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
}

if ((Test-Path -LiteralPath $venvDir) -and -not (Test-Path -LiteralPath $venvPython)) {
    throw "Existing backend/.venv is not a Windows virtual environment. Move it or choose a different worktree."
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $bootstrap = Resolve-BootstrapPython
    $bootstrapArguments = @($bootstrap.PrefixArguments) + @("-m", "venv", $venvDir)
    Write-Host "[setup] Creating backend virtual environment at $venvDir"
    Invoke-CheckedCommand `
        -Executable $bootstrap.Executable `
        -CommandArguments $bootstrapArguments `
        -FailureMessage "Unable to create the backend virtual environment"
}

if (-not (Test-CompatiblePython -Executable $venvPython)) {
    throw "The backend virtual environment is missing Python 3.10+: $venvPython"
}

$requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirementsPath).Hash.ToLowerInvariant()
$installedRequirementsHash = ""
if (Test-Path -LiteralPath $requirementsMarker) {
    $installedRequirementsHash = (Get-Content -Raw -LiteralPath $requirementsMarker).Trim()
}
if ($ForceDependencies -or $installedRequirementsHash -ne $requirementsHash) {
    if ($Offline) {
        throw "Offline mode requires backend dependencies to have been installed by an earlier successful setup."
    }
    Write-Host "[setup] Installing backend dependencies"
    Invoke-CheckedCommand `
        -Executable $venvPython `
        -CommandArguments @("-m", "pip", "install", "--upgrade", "pip") `
        -FailureMessage "Unable to update pip"
    Invoke-CheckedCommand `
        -Executable $venvPython `
        -CommandArguments @("-m", "pip", "install", "-r", $requirementsPath) `
        -FailureMessage "Unable to install backend dependencies"
    [System.IO.File]::WriteAllText(
        $requirementsMarker,
        "$requirementsHash`n",
        [System.Text.UTF8Encoding]::new($false)
    )
} else {
    Write-Host "[setup] Backend dependencies are current"
}

if (-not $SkipPineRuntime) {
    $runtimeArguments = @($ensureRuntime)
    if ($Offline) {
        $runtimeArguments += "--offline"
    }
    Write-Host "[setup] Verifying Pine-compatible runtime"
    Invoke-CheckedCommand `
        -Executable $venvPython `
        -CommandArguments $runtimeArguments `
        -FailureMessage "Unable to prepare the Pine-compatible runtime"
} else {
    Write-Host "[setup] Pine-compatible runtime was explicitly skipped"
}

Write-Host "[setup] Backend environment is ready: $venvPython"
