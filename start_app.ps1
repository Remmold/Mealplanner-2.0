# start_app.ps1 - Start both backend (FastAPI) and frontend (Vite) dev servers

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "Starting Mealplanner..." -ForegroundColor Cyan

# Start backend
$backend = Start-Process -PassThru -NoNewWindow -FilePath "cmd" -ArgumentList "/c cd /d `"$root\backend`" && uv run uvicorn api.main:app --reload --port 8000"
Write-Host "Backend starting on http://localhost:8000" -ForegroundColor Green

# Start frontend
$frontend = Start-Process -PassThru -NoNewWindow -FilePath "cmd" -ArgumentList "/c cd /d `"$root\frontend`" && npm run dev"
Write-Host "Frontend starting on http://localhost:5173" -ForegroundColor Green

Write-Host ""
Write-Host "Press Ctrl+C to stop both servers" -ForegroundColor Yellow

try {
    # Wait for either process to exit
    while (!$backend.HasExited -and !$frontend.HasExited) {
        Start-Sleep -Milliseconds 500
    }
} finally {
    # Clean up both processes
    if (!$backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    if (!$frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "Servers stopped." -ForegroundColor Red
}
