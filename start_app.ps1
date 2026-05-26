# start_app.ps1 - Launch backend (FastAPI + uvicorn --reload) and frontend
# (Vite) in SEPARATE terminal windows so each set of logs is easy to read.
# Ctrl+C in the launcher window kills both child trees; closing either
# child window leaves the other running.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "Starting Mealplanner..." -ForegroundColor Cyan

# Backend in its own window. `cmd /k` keeps the window open after uvicorn
# exits (so you can read the traceback if it crashes). `title` labels the
# tab so the two windows are distinguishable on the taskbar.
$backend = Start-Process -PassThru -FilePath "cmd" -ArgumentList @(
    "/k",
    "title Hearth Backend && cd /d `"$root\backend`" && uv run uvicorn api.main:app --reload --port 8000"
)
Write-Host "Backend window opened — http://localhost:8000" -ForegroundColor Green

# Frontend in its own window.
$frontend = Start-Process -PassThru -FilePath "cmd" -ArgumentList @(
    "/k",
    "title Hearth Frontend && cd /d `"$root\frontend`" && npm run dev"
)
Write-Host "Frontend window opened — http://localhost:5173" -ForegroundColor Green

Write-Host ""
Write-Host "Two terminal windows opened. Close them individually, or" -ForegroundColor Yellow
Write-Host "Ctrl+C in THIS window to kill both process trees at once." -ForegroundColor Yellow

try {
    while (!$backend.HasExited -and !$frontend.HasExited) {
        Start-Sleep -Milliseconds 500
    }
} finally {
    # taskkill /T cascades to all descendants (uvicorn worker, node, etc.)
    if (!$backend.HasExited)  { taskkill /T /F /PID $backend.Id  2>$null | Out-Null }
    if (!$frontend.HasExited) { taskkill /T /F /PID $frontend.Id 2>$null | Out-Null }
    Write-Host "Servers stopped." -ForegroundColor Red
}
