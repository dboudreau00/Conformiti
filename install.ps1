<#
.SYNOPSIS
  Conformiti installer (Windows PowerShell 5.1 or PowerShell 7+).

.DESCRIPTION
    .\install.ps1               Local dev: venv + npm + migrate + seed, then start
                                the API (:8000) and the web app (:5173).
    .\install.ps1 -SetupOnly    Install and seed, but don't start the servers.
    .\install.ps1 -Docker       Build and start the full Docker stack on
                                http://localhost:8080 and wait until healthy.
    .\install.ps1 -Test         Run the backend tests, the validator and a
                                production frontend build.
    .\install.ps1 -Reset        Local only: wipe db.sqlite3 + uploads, reseed.

  Combine with -NoDemo (skip the demo dataset), -Open (launch the browser when
  ready) and -Port N (Docker host port). Every native command is exit-code
  checked: a failed step stops the installer instead of reporting success.
#>
[CmdletBinding()]
param(
  [switch]$SetupOnly,
  [switch]$Docker,
  [switch]$Test,
  [switch]$Reset,
  [switch]$NoDemo,
  [switch]$Open,
  [int]$Port = 8080
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  * $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "Error: $m" -ForegroundColor Red; exit 1 }
function Run {
  # Run a native command and stop on a non-zero exit code.
  param([Parameter(Mandatory)][string]$Exe, [Parameter(ValueFromRemainingArguments)][string[]]$Args)
  & $Exe @Args
  if ($LASTEXITCODE -ne 0) { Fail "'$Exe $($Args -join ' ')' exited with code $LASTEXITCODE" }
}
function Wait-Healthy([string]$Url, [int]$Seconds = 240) {
  $elapsed = 0
  while ($elapsed -lt $Seconds) {
    try {
      $r = Invoke-RestMethod -Uri $Url -TimeoutSec 5
      if ($r.status -eq "ok") { return $r }
    } catch { }
    Start-Sleep -Seconds 2; $elapsed += 2
    if ($elapsed % 20 -eq 0) { Write-Host "  ... still starting ($elapsed s)" -ForegroundColor DarkGray }
  }
  return $null
}
function New-Secret {
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return ([Convert]::ToBase64String($bytes) -replace '[+/=]', '')
}
$demo = if ($NoDemo) { "false" } else { "true" }

# --- Docker path -------------------------------------------------------------
if ($Docker) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "Docker is not installed (https://docs.docker.com/get-docker/)." }
  & docker compose version *> $null
  if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is required ('docker compose')." }
  & docker info *> $null
  if ($LASTEXITCODE -ne 0) { Fail "The Docker daemon is not running (start Docker Desktop, or use WSL)." }

  if (-not (Test-Path ".env")) {
    $hosts = "localhost,127.0.0.1,backend,$($env:COMPUTERNAME.ToLower())"
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mmZ")
    @(
      "# Written by install.ps1 -Docker on $stamp. Safe production-style",
      "# defaults for a LAN deployment over plain HTTP. See .env.example for every key.",
      "DJANGO_DEBUG=false",
      "DJANGO_SECRET_KEY=$(New-Secret)",
      "DJANGO_ALLOWED_HOSTS=$hosts",
      "CSRF_TRUSTED_ORIGINS=http://localhost:$Port,http://127.0.0.1:$Port",
      "CORS_ALLOWED_ORIGINS=http://localhost:$Port",
      "# Flip to true once a TLS-terminating proxy sits in front of nginx.",
      "BEHIND_TLS=false",
      "EMAIL_PROVIDER=console",
      "SEED_DEMO_DATA=$demo",
      "CONFORMITI_PORT=$Port"
    ) | Set-Content -Path ".env" -Encoding ascii
    Ok ".env written (DEBUG off, unique secret key, demo data $demo)"
  } else {
    Ok ".env already present - leaving it untouched"
    if (Select-String -Path ".env" -Pattern '^DJANGO_DEBUG=(1|true|yes|on)' -Quiet) {
      Warn "your .env sets DJANGO_DEBUG=true - the Docker stack will run in DEBUG mode."
    }
    $p = Select-String -Path ".env" -Pattern '^CONFORMITI_PORT=(\d+)' | Select-Object -Last 1
    if ($p) { $Port = [int]$p.Matches[0].Groups[1].Value }
  }

  Say "Building images and starting the stack (first build takes a few minutes)..."
  Run docker compose up -d --build
  Say "Waiting for the API to report healthy..."
  $health = Wait-Healthy "http://localhost:$Port/api/health/"
  if (-not $health) { & docker compose ps; Fail "The stack did not become healthy in time. Inspect with: docker compose logs backend" }
  Ok "healthy: version $($health.version), database $($health.database)"
  Write-Host ""
  Write-Host "Conformiti is running." -ForegroundColor Green
  Write-Host "  App      http://localhost:$Port"
  Write-Host "  Admin    http://localhost:$Port/admin/"
  Write-Host "  Health   http://localhost:$Port/api/health/"
  if ($demo -eq "true") {
    Write-Host "  Sign in  admin / DemoPass123!   (also mia, owen, aria, val - same password)"
    Write-Host "  Before real use: docker compose exec backend python manage.py remove_demo_data" -ForegroundColor Yellow
  } else {
    Write-Host "  Create your first account: docker compose exec backend python manage.py createsuperuser"
  }
  Write-Host "  Logs: docker compose logs -f    Stop: docker compose down" -ForegroundColor DarkGray
  if ($Open) { Start-Process "http://localhost:$Port" }
  exit 0
}

# --- Prerequisites (local paths) ---------------------------------------------
$py = $null
foreach ($c in @("python", "python3", "py")) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if (-not $cmd) { continue }
  & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
  if ($LASTEXITCODE -eq 0) { $py = $c; break }
}
if (-not $py) { Fail "Python 3.11+ is required but was not found on PATH (https://www.python.org/downloads/)." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js 20.19+ (with npm) is required but was not found on PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "npm is required but was not found on PATH." }
$nodeOk = & node -e "const [a,b]=process.versions.node.split('.').map(Number); process.stdout.write((a>20||(a===20&&b>=19))?'y':'n')"
if ($nodeOk -ne "y") { Fail "Node.js 20.19+ is required (found $(node --version))." }
Ok "using $(& $py --version), node $(node --version), npm $(npm --version)"

# --- .env with a generated secret key ---------------------------------------
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  $secret = & $py -c "import secrets; print(secrets.token_urlsafe(50))"
  (Get-Content ".env") -replace '^DJANGO_SECRET_KEY=.*$', "DJANGO_SECRET_KEY=$secret" | Set-Content ".env"
  Ok ".env created (SQLite + console email; secret key generated)"
} else {
  Ok ".env already present - leaving it untouched"
}

# --- Virtualenv + backend deps ------------------------------------------------
$pyexe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pyexe)) {
  Say "Creating Python virtual environment (.venv)..."
  if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
  Run $py -m venv .venv
}
Say "Installing backend dependencies..."
Run $pyexe -m pip install --quiet --upgrade pip
Run $pyexe -m pip install --quiet -r backend/requirements.txt
Ok "backend dependencies installed"

if ($Reset) {
  Say "Resetting the local database and uploads..."
  Remove-Item -Force "backend\db.sqlite3" -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force "backend\media" -ErrorAction SilentlyContinue
  Ok "clean slate"
  $SetupOnly = $true
}

# --- Frontend deps -------------------------------------------------------------
Say "Installing frontend dependencies (this can take a minute)..."
Push-Location frontend
try { Run npm install --no-fund --no-audit --silent } finally { Pop-Location }
Ok "frontend dependencies installed"

# --- Test mode -----------------------------------------------------------------
if ($Test) {
  Say "Static validator"
  Run $pyexe tools/validate.py
  Say "Backend test suite"
  Push-Location backend
  try {
    Run $pyexe manage.py check
    Run $pyexe manage.py makemigrations --check --dry-run
    Run $pyexe manage.py test --noinput
  } finally { Pop-Location }
  Say "Frontend production build"
  Push-Location frontend
  try { Run npm run build } finally { Pop-Location }
  Ok "all checks passed"
  exit 0
}

# --- Database + seed -------------------------------------------------------------
Say "Applying migrations and seeding control libraries..."
Push-Location backend
try {
  Run $pyexe manage.py migrate --noinput
  Run $pyexe manage.py seed_frameworks --with-folders
  & $pyexe manage.py generate_folder_tree *> $null
  if ($demo -eq "true") { Run $pyexe manage.py bootstrap_demo }
} finally { Pop-Location }
if ($demo -eq "true") {
  Ok "database ready (SOC 2 / ISO 27001 / PCI DSS seeded, demo data loaded)"
} else {
  Ok "database ready (SOC 2 / ISO 27001 / PCI DSS seeded, no demo data)"
  Warn "create your first account with: cd backend; ..\.venv\Scripts\python.exe manage.py createsuperuser"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
if ($demo -eq "true") { Write-Host "  Sign in:  admin / DemoPass123!   (also mia, owen, aria, val - same password)" }
Write-Host "  Tests:    .\install.ps1 -Test"
Write-Host "  Mailer:   cd backend; ..\.venv\Scripts\python.exe manage.py send_review_reminders --dry-run"
Write-Host ""

if ($SetupOnly) {
  Write-Host "To start later:"
  Write-Host "  (backend)   cd backend; ..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000"
  Write-Host "  (frontend)  cd frontend; npm run dev"
  Write-Host "Then open http://localhost:5173"
  exit 0
}

Say "Starting servers - backend on :8000, frontend on :5173."
Say "Open http://localhost:5173 in your browser. Close the two windows to stop."
$backendDir = Join-Path $PSScriptRoot "backend"
$frontendDir = Join-Path $PSScriptRoot "frontend"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "`"$pyexe`" manage.py runserver 127.0.0.1:8000" -WorkingDirectory $backendDir
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "npm run dev" -WorkingDirectory $frontendDir
Ok "Servers launched in two console windows."
if ($Open) { Start-Sleep -Seconds 6; Start-Process "http://localhost:5173" }
