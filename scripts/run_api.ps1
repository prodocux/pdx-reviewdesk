$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Create .venv and pip install -e `".[dev]`" first."
}
& $python -m uvicorn reviewdesk_api.main:app --reload --host 127.0.0.1 --port 8000
