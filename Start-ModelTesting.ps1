param([switch]$Install)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required for this launcher. Install it or create .venv manually with Python 3.12+.' }
    $Install = $true
}
if ($Install) {
    & $python -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & $python -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'Project installation failed' }
}
& $python -m aaron_model_testing serve
exit $LASTEXITCODE
