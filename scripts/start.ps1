$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Please create .venv and install dependencies; see README.md.'
}
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
