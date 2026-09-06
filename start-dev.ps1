# ── Dev server launcher ───────────────────────────────────────────────────────
# Always uses .env.dev (the clinic-dev Supabase project).
# Port 8001 so it never conflicts with prod (port 8000).
# ─────────────────────────────────────────────────────────────────────────────

if (-not (Test-Path ".env.dev")) {
    Write-Host ""
    Write-Host "  ERROR: .env.dev not found." -ForegroundColor Red
    Write-Host "  Copy .env.dev from the template and fill in your dev Supabase credentials." -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "  *** DEV MODE — port 8001 — clinic-dev database ***" -ForegroundColor Yellow
Write-Host ""

. venv\Scripts\Activate.ps1
python -m uvicorn main:app --port 8001
Write-Host ""
Write-Host "Server stopped. Press Enter to close." -ForegroundColor Cyan
Read-Host
