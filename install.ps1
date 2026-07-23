<#
  Conformiti - simple installer (Windows PowerShell)

    .\install.ps1              Set up everything and start both dev servers.
    .\install.ps1 -SetupOnly   Install and seed, but don't start the servers.
    .\install.ps1 -Docker      Use Docker Compose instead of the local path.

  The local path needs no external services: SQLite + console email. Requires
  Python 3.10+ and Node.js/npm on PATH.
#>
param(
  [switch]$SetupOnly,
  [switch]$Docker
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "  * $m" -ForegroundColor Green }

if ($Docker) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker is not installed." }
  if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Ok "created .env" }
  Say "Starting with Docker Compose (app on http://localhost:8080)..."
  docker compose up --build
  return
}

# Prerequisites
$py = $null
foreach ($c in @("python", "python3", "py")) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if (-not $py) { throw "Python 3 is required but was not found on PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js / npm is required but was not found on PATH." }
Ok "using $(& $py --version) and npm $(npm --version)"

# .env with a generated secret key
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  $secret = & $py -c "import secrets; print(secrets.token_urlsafe(50))"
  (Get-Content ".env") -replace '^DJANGO_SECRET_KEY=.*$', "DJANGO_SECRET_KEY=$secret" | Set-Content ".env"
  Ok ".env created (SQLite + console email; secret key generated)"
} else {
  Ok ".env already present - leaving it untouched"
}

# Virtualenv + backend deps
if (-not (Test-Path ".venv")) { Say "Creating Python virtual environment (.venv)..."; & $py -m venv .venv }
$pyexe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Say "Installing backend dependencies..."
& $pyexe -m pip install --quiet --upgrade pip
& $pyexe -m pip install --quiet -r backend/requirements.txt
Ok "backend dependencies installed"

# Database + seed
Say "Applying migrations and seeding control libraries + demo data..."
Push-Location backend
& $pyexe manage.py makemigrations accounts compliance documents calendar_app notifications audit governance integrations
& $pyexe manage.py migrate --noinput
& $pyexe manage.py seed_frameworks --with-folders
try { & $pyexe manage.py bootstrap_demo } catch {}
try { & $pyexe manage.py generate_folder_tree } catch {}
Pop-Location
Ok "database ready (SOC 2 / ISO 27001 / PCI DSS seeded)"

# Frontend deps
Say "Installing frontend dependencies (this can take a minute)..."
Push-Location frontend
npm install --silent
Pop-Location
Ok "frontend dependencies installed"

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "  Sign in:  admin / DemoPass123!"
Write-Host "  Mailer dry run:  cd backend; ..\.venv\Scripts\python.exe manage.py send_review_reminders --dry-run"
Write-Host ""

if ($SetupOnly) {
  Write-Host "To start later:"
  Write-Host "  (backend)   cd backend; ..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000"
  Write-Host "  (frontend)  cd frontend; npm run dev"
  Write-Host "Then open http://localhost:5173"
  return
}

Say "Starting servers - backend on :8000, frontend on :5173."
Say "Open http://localhost:5173 in your browser. Close the two windows to stop."
$backendDir = Join-Path $PSScriptRoot "backend"
$frontendDir = Join-Path $PSScriptRoot "frontend"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "`"$pyexe`" manage.py runserver 127.0.0.1:8000" -WorkingDirectory $backendDir
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "npm run dev" -WorkingDirectory $frontendDir
Ok "Servers launched in two console windows."
