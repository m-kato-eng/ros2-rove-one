$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonCommand = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { 'python' }
$trialConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'connection.json') | ConvertFrom-Json
$trialLogDirectory = if ($trialConfig.log_directory) { $trialConfig.log_directory } else { 'logs' }
$trialLogPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $trialLogDirectory))
$validationLog = Join-Path $trialLogPath 'validation.txt'
New-Item -ItemType Directory -Force $trialLogPath | Out-Null
"Validation started: $(Get-Date -Format o)" | Set-Content -Encoding UTF8 -LiteralPath $validationLog
foreach ($trial in @('controller.py', 'smoke_test.py', 'gui_test.py')) {
    $trialPath = Join-Path $PSScriptRoot $trial
    if ($trial -eq 'controller.py') {
        & $pythonCommand $trialPath --gui-check 2>&1 | Tee-Object -FilePath $validationLog -Append
    } else {
        & $pythonCommand $trialPath 2>&1 | Tee-Object -FilePath $validationLog -Append
    }
    if ($LASTEXITCODE -ne 0) { throw "$trial failed with code $LASTEXITCODE. See $validationLog" }
}
'ALL PC VALIDATIONS PASSED' | Tee-Object -FilePath $validationLog -Append
