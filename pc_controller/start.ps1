$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonCommand = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { 'python' }
& $pythonCommand (Join-Path $PSScriptRoot 'controller.py')
if ($LASTEXITCODE -ne 0) { throw "Control Trial exited with code $LASTEXITCODE" }
