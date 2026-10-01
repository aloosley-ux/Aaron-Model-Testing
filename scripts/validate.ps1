# Real HTTP workflow in a unique ignored data directory; no inference required.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Set up dependencies first: .\Start-ModelTesting.ps1 -Install (then Ctrl+C). See README for direct setup commands.'
}
Push-Location -LiteralPath $repoRoot
try {
    & $python -X utf8 -m scripts.validate_product
    if ($LASTEXITCODE -ne 0) { throw 'Product validation failed; inspect .local/validation for retained evidence.' }
}
finally {
    Pop-Location
}
