# Repository health; uses the existing locked development environment.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Set up dependencies first: .\Start-ModelTesting.ps1 -Install (then Ctrl+C). See README for direct setup commands.'
}
Push-Location -LiteralPath $repoRoot
try {
    & $python -X utf8 -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed' }
    & $python -X utf8 -m ruff check aaron_model_testing tests scripts
    if ($LASTEXITCODE -ne 0) { throw 'Ruff failed' }
    & $python -X utf8 -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
    Write-Host 'PASS: repository health (dependencies, lint, unit/integration tests and frozen benchmark checks).'
}
finally {
    Pop-Location
}
