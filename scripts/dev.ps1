$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
docker compose up -d falkordb
Push-Location frontend
npm ci
Pop-Location
Write-Host 'Database started. Run these in separate terminals:'
Write-Host 'cd backend; ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000'
Write-Host 'cd frontend; npm run dev'
