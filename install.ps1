<#
.SYNOPSIS
  Conformiti installer (Windows PowerShell 5.1 or PowerShell 7+).

.DESCRIPTION
  Run it through a policy override that lasts for this one run and changes no
  setting. The default Restricted policy refuses every script ("running
  scripts is disabled on this system"), and RemoteSigned refuses a copy that
  came from a zip download:
    powershell -ExecutionPolicy Bypass -File .\install.ps1 [switches]

    (no switch)   Local dev: venv + npm + migrate + seed, then start the API
                  on :8000 and the web app on :5173 ($env:CONFORMITI_DEV_API_PORT
                  and $env:CONFORMITI_DEV_PORT move them).
    -SetupOnly    Install and seed, but don't start the servers.
    -Docker       Build and start the full Docker stack on
                  http://localhost:8080 and wait until healthy.
    -Test         Run the backend tests, the validator and a production
                  frontend build.
    -Reset        Local only: wipe db.sqlite3 + uploads, reseed.

  Combine with -Demo (load the sample organisation; off by default), -Open
  (launch the browser when ready) and -Port N (Docker host port). With -Docker
  and an existing .env, -Demo / -NoDemo and -Port update SEED_DEMO_DATA and
  CONFORMITI_PORT in it, and the script says so. Every native command is
  exit-code checked: a failed step stops the installer instead of reporting
  success.
#>
[CmdletBinding()]
param(
  [switch]$SetupOnly,
  [switch]$Docker,
  [switch]$Test,
  [switch]$Reset,
  [switch]$Demo,
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
  # Run a native command and stop on a non-zero exit code. A plain function on
  # purpose: an advanced one binds "-d" (docker compose up -d) to -Debug and
  # never passes it on. The command is resolved to its application first
  # (npm.cmd, not the npm.ps1 shim): the shim rebuilds its arguments from the
  # caller's statement text, which here is "& $path @rest", so it gets none.
  $exe = $args[0]
  $rest = @($args | Select-Object -Skip 1)
  $app = Get-Command $exe -CommandType Application -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension } | Select-Object -First 1
  $path = if ($app) { $app.Source } else { $exe }
  & $path @rest
  if ($LASTEXITCODE -ne 0) { Fail "'$exe $($rest -join ' ')' exited with code $LASTEXITCODE" }
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
function Probe {
  # The exit code of a native command run only for its answer, output dropped.
  # "Continue" for the call: under "Stop", Windows PowerShell 5.1 turns each
  # redirected stderr line into a terminating error, so a probe that answers
  # "no" on stderr (docker info with no daemon, the Microsoft Store's python
  # stub) threw before the message that explains it could run.
  $ErrorActionPreference = "Continue"
  $rest = @($args | Select-Object -Skip 1)
  & $args[0] @rest *> $null
  return $LASTEXITCODE
}
function Get-NativeText {
  # A native command's standard output as one string, "" when it fails. Its
  # stderr is dropped, for the reason Probe gives.
  $ErrorActionPreference = "Continue"
  $rest = @($args | Select-Object -Skip 1)
  $out = & $args[0] @rest 2>$null
  if ($LASTEXITCODE -ne 0) { return "" }
  return (@($out) -join "`n")
}
# .env is edited as Latin-1: one character per byte and back, so every line
# this script does not change keeps its bytes, its encoding and its ending.
function Read-EnvText {
  $latin1 = [System.Text.Encoding]::GetEncoding(28591)
  return $latin1.GetString([System.IO.File]::ReadAllBytes((Join-Path $PSScriptRoot ".env")))
}
function Write-EnvText([string]$Text) {
  $latin1 = [System.Text.Encoding]::GetEncoding(28591)
  [System.IO.File]::WriteAllBytes((Join-Path $PSScriptRoot ".env"), $latin1.GetBytes($Text))
}
function Get-EnvValue([string]$Key) {
  # The value Compose reads for KEY: the last KEY= line wins, and Compose takes
  # one pair of surrounding quotes, or else a " # comment" at the end, off the
  # value before a container sees it. $null when no line sets it.
  $found = [regex]::Matches((Read-EnvText), "(?m)^$([regex]::Escape($Key))=([^\r\n]*)")
  if ($found.Count -eq 0) { return $null }
  $v = $found[$found.Count - 1].Groups[1].Value
  $t = $v.TrimStart()
  if ($t -match '^"([^"]*)"' -or $t -match "^'([^']*)'") { return $Matches[1] }
  return ($v -replace '[ \t]+#.*$', '').Trim()
}
function Set-EnvValue([string]$Key, [string]$Value) {
  # Sets every KEY= line in .env to KEY=VALUE, or appends one.
  $text = Read-EnvText
  $pattern = "(?m)^$([regex]::Escape($Key))=[^\r\n]*"
  if ([regex]::IsMatch($text, $pattern)) {
    $text = [regex]::Replace($text, $pattern, "$Key=$Value".Replace('$', '$$'))
  } else {
    $nl = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += $nl }
    $text += "$Key=$Value$nl"
  }
  Write-EnvText $text
}
function Move-EnvOrigins([int]$Old, [int]$New) {
  # Moves the localhost origins this script writes into CSRF_TRUSTED_ORIGINS
  # and CORS_ALLOWED_ORIGINS from port Old to port New; any other origin (a
  # real host name, a proxy) stays exactly as it is. True when one moved.
  $text = Read-EnvText
  $pattern = "(?m)^((?:CSRF_TRUSTED_ORIGINS|CORS_ALLOWED_ORIGINS)=(?:[^\r\n]*,)?http://(?:localhost|127\.0\.0\.1)):$Old(?=,|\r|`$)"
  $moved = $text
  do { $before = $moved; $moved = [regex]::Replace($before, $pattern, "`${1}:$New") } while ($moved -ne $before)
  if ($moved -eq $text) { return $false }
  Write-EnvText $moved
  return $true
}
function Test-PortBusy([int]$P, [string]$Address = "127.0.0.1") {
  # True when something already accepts connections on Address:P. The client
  # is made for the address's family: Windows PowerShell 5.1's default one is
  # IPv4 only and cannot reach ::1.
  $ip = [System.Net.IPAddress]::Parse($Address)
  $client = New-Object System.Net.Sockets.TcpClient($ip.AddressFamily)
  try {
    $pending = $client.BeginConnect($ip, $P, $null, $null)
    return ($pending.AsyncWaitHandle.WaitOne(1000) -and $client.Connected)
  } catch { return $false } finally { $client.Close() }
}
function Test-PortListened([int]$P) {
  # True when a program on this machine listens on TCP port P, on any address
  # and in either IP family. 127.0.0.1 alone is not enough: Vite's default
  # host is "localhost", which a stock Windows resolves to ::1 first, so the
  # dev server listens on [::1] and nowhere else. Windows' own table of
  # listeners covers every address; should it be unreadable, both loopback
  # addresses are tried instead.
  try {
    $all = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    return (@($all | Where-Object { $_.Port -eq $P }).Count -gt 0)
  } catch {
    return ((Test-PortBusy $P "127.0.0.1") -or (Test-PortBusy $P "::1"))
  }
}
function Test-StackHolds([string]$Service, [int]$ContainerPort, [int]$HostPort) {
  # True when this project's own running SERVICE already publishes HostPort,
  # which is what a re-run finds.
  return ((Get-NativeText docker compose port $Service $ContainerPort) -match ":$HostPort(\s|`$)")
}
function Get-DemoPassword {
  # bootstrap_demo's one-time "Sign in as  admin  /  <password>" line, read
  # from the backend's log: up -d is detached, so it never reaches this window.
  $log = (Get-NativeText docker compose logs --no-color --no-log-prefix backend) -split "`n"
  $hit = $log | Select-String -Pattern 'Sign in as\s+admin\s*/\s*(.+?)\s*$' | Select-Object -Last 1
  if ($hit) { return $hit.Matches[0].Groups[1].Value }
  return $null
}
function Get-OwnAdminState {
  # "yes" when the running stack's Default workspace has an administrator that
  # is not a demo account, "no" when it has none, $null when the stack cannot
  # say (it is not up, or its image is older than the test). It is the
  # question remove_demo_data asks before it will run. No double quotes in the
  # code: Windows PowerShell 5.1 passes them to a native command unescaped.
  $code = "from accounts import tenancy; from accounts.management.commands.bootstrap_demo import own_administrator_present as f; print('own_admin=' + ('yes' if f(tenancy.from_option({})) else 'no'))"
  $out = Get-NativeText docker compose exec -T backend python manage.py shell -v 0 -c $code
  $hit = [regex]::Matches($out, '(?m)^own_admin=(yes|no)\r?$')
  if ($hit.Count -gt 0) { return $hit[$hit.Count - 1].Groups[1].Value }
  return $null
}
function Get-RetireDemoAdvice {
  # What to run before real use, one line per element. remove_demo_data
  # refuses until an administrator of the operator's own exists, so
  # createsuperuser comes first unless the stack says there already is one;
  # when it cannot say, the advice covers both cases.
  $state = Get-OwnAdminState
  if ($state -eq "yes") { return @("Before real use: docker compose exec backend python manage.py remove_demo_data") }
  if ($state -eq "no") {
    $lines = @("Before real use, create an administrator of your own (remove_demo_data refuses",
               "until one exists), then retire the demo accounts:")
  } else {
    $lines = @("Before real use, create an administrator of your own if you have none yet",
               "(remove_demo_data refuses until one exists), then retire the demo accounts:")
  }
  return $lines + @("  docker compose exec backend python manage.py createsuperuser",
                    "  docker compose exec backend python manage.py remove_demo_data")
}
function Get-DevPort([string]$Name, [int]$Default) {
  # A local-path port from the environment, where Vite reads it too.
  $v = [Environment]::GetEnvironmentVariable($Name)
  if (-not $v) { return $Default }
  if ($v -notmatch '^\d{1,5}$' -or [int]$v -lt 1 -or [int]$v -gt 65535) { Fail "$Name must be a port number between 1 and 65535 (got '$v')." }
  return [int]$v
}
function Test-FrontendDepsCurrent {
  # True when frontend\node_modules already holds what package-lock.json pins:
  # npm's own record of the installed tree (node_modules\.package-lock.json)
  # lists the same packages at the same version, source and hash, leaving out
  # only optional ones npm skipped (other platforms' binaries), and each of
  # them is on disk. Only those fields are compared, because npm 10 leaves the
  # libc ones out of that record. A run that npm ci stopped part way fails the
  # test. Run from frontend\. No double quotes in the code, for the reason
  # Get-OwnAdminState gives. install.sh carries the same test.
  $js = @'
const fs = require('fs'), read = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const pin = (e) => JSON.stringify([e.version, e.resolved, e.integrity, e.link]);
let ok = false;
try {
  const lock = read('package-lock.json').packages, tree = read('node_modules/.package-lock.json').packages;
  ok = Object.keys(tree).every((k) => k in lock) && Object.keys(lock).every((k) => k === '' ||
    (k in tree ? pin(tree[k]) === pin(lock[k]) && fs.existsSync(k + '/package.json') : lock[k].optional === true));
} catch (e) {}
process.exit(ok ? 0 : 1);
'@
  return ((Probe node -e $js) -eq 0)
}
function Show-OriginWarning([int]$WebPort) {
  Warn "CONFORMITI_DEV_PORT is ${WebPort}: add http://localhost:$WebPort to CSRF_TRUSTED_ORIGINS and"
  Warn "CORS_ALLOWED_ORIGINS in .env, or every sign-in from the web app is refused."
}
if ($Port -lt 1 -or $Port -gt 65535) { Fail "-Port must be between 1 and 65535 (got $Port)." }
# Off unless asked for: an installation carrying the sample organisation says
# so on its own sign-in page, which a real deployment should never publish.
# -NoDemo is kept because older notes say it, and it agrees with the default.
# Not "$demo": PowerShell names are case-insensitive, so that would be the
# [switch]$Demo parameter and assigning a string to it throws.
$seedDemo = if ($Demo -and -not $NoDemo) { "true" } else { "false" }

# --- Docker path -------------------------------------------------------------
if ($Docker) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "Docker is not installed (https://docs.docker.com/get-docker/)." }
  if ((Probe docker compose version) -ne 0) { Fail "Docker Compose v2 is required ('docker compose')." }
  # docker-compose.yml's optional .env entry (required: false) and the ghcr
  # file's !reset need Compose 2.24.0; an older one rejects the file. The
  # short form is "2.40.3", "v2.20.2" or a distribution's "2.40.3+ds1-...".
  if ((Get-NativeText docker compose version --short) -match '(\d+)\.(\d+)\.(\d+)') {
    $composeVer = [version]"$($Matches[1]).$($Matches[2]).$($Matches[3])"
    if ($composeVer -lt [version]"2.24.0") { Fail "Docker Compose 2.24.0 or newer is required (found $composeVer): older releases reject the compose file's optional .env entry. Update Docker Desktop or the Compose plugin." }
  } else {
    Warn "could not read the Docker Compose version; the compose file needs 2.24.0 or newer."
  }
  if ((Probe docker info) -ne 0) { Fail "The Docker daemon is not running (start Docker Desktop, or use WSL)." }

  if (-not (Test-Path ".env")) {
    $hosts = "localhost,127.0.0.1,backend,$($env:COMPUTERNAME.ToLower())"
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mmZ")
    @(
      "# Written by install.ps1 -Docker on $stamp. Safe production-style",
      "# defaults for a LAN deployment over plain HTTP. See .env.example for every key.",
      "#",
      "# The Docker stack reads CONFORMITI_DEBUG / CONFORMITI_SECRET_KEY, not",
      "# DJANGO_DEBUG / DJANGO_SECRET_KEY: those two belong to the local dev path",
      "# and must never leak into a container. CONFORMITI_SECRET_KEY is left unset",
      "# on purpose: the container generates its own key and keeps it in the",
      "# 'secrets' volume, which scripts/backup.sh saves with the database.",
      "CONFORMITI_DEBUG=false",
      "DJANGO_ALLOWED_HOSTS=$hosts",
      "CSRF_TRUSTED_ORIGINS=http://localhost:$Port,http://127.0.0.1:$Port",
      "CORS_ALLOWED_ORIGINS=http://localhost:$Port",
      "# Flip to true once a TLS-terminating proxy sits in front of nginx.",
      "BEHIND_TLS=false",
      "EMAIL_PROVIDER=console",
      "SEED_DEMO_DATA=$seedDemo",
      "CONFORMITI_PORT=$Port"
    ) | Set-Content -Path ".env" -Encoding ascii
    Ok ".env written (DEBUG off, demo data $seedDemo)"
    Ok "no secret key in .env: the container generates one and keeps it in the 'secrets' volume"
    # No chmod here on purpose: NTFS inherits its ACL from the directory, and
    # pretending otherwise would be a promise this script cannot keep. The
    # file holds no secret as written; mail and database passwords usually
    # end up in it later.
    Warn ".env holds no secret yet, but mail or database passwords you add to it will. Keep the folder out of a shared location."
  } else {
    Ok ".env already present: using it"
    if (Select-String -Path ".env" -Pattern '^CONFORMITI_DEBUG=(1|true|yes|on)' -Quiet) {
      Warn "your .env sets CONFORMITI_DEBUG=true, so the Docker stack will run in DEBUG mode."
    } elseif (Select-String -Path ".env" -Pattern '^DJANGO_DEBUG=(1|true|yes|on)' -Quiet) {
      Warn "your .env has DJANGO_DEBUG=true (from the local dev path). It does NOT affect"
      Warn "the Docker stack, which stays in production mode. Use CONFORMITI_DEBUG to change that."
    }
    # -Demo / -NoDemo: the stack seeds from SEED_DEMO_DATA in .env, so a switch
    # that disagrees with it is written there instead of being ignored. The
    # values below are the ones backend/entrypoint.sh treats as "seed".
    if ($Demo -or $NoDemo) {
      $envDemo = Get-EnvValue "SEED_DEMO_DATA"
      $envDemoOn = if (@("1", "true", "TRUE", "yes", "on") -ccontains $envDemo) { "true" } else { "false" }
      if ($seedDemo -ne $envDemoOn) {
        Set-EnvValue "SEED_DEMO_DATA" $seedDemo
        $was = if ($null -eq $envDemo) { "unset" } else { $envDemo }
        if ($seedDemo -eq "true") {
          Ok "-Demo: set SEED_DEMO_DATA=true in .env (it was $was)"
        } else {
          Ok "-NoDemo: set SEED_DEMO_DATA=false in .env (it was $was)"
          Warn "demo accounts that already exist stay until remove_demo_data retires them."
          Get-RetireDemoAdvice | ForEach-Object { Warn $_ }
        }
      }
    }
    # -Port wins over CONFORMITI_PORT in .env and is saved there, so a later
    # plain "docker compose up" keeps using it. Without -Port, .env decides.
    $envPort = Get-EnvValue "CONFORMITI_PORT"
    $envPortNum = if ($envPort -match '^\d{1,5}$') { [int]$envPort } else { $null }
    if ($PSBoundParameters.ContainsKey("Port")) {
      $oldPort = if ($envPortNum) { $envPortNum } else { 8080 }
      if ($Port -ne $oldPort) {
        Set-EnvValue "CONFORMITI_PORT" "$Port"
        $was = if ($null -eq $envPort) { "unset, so 8080" } else { $envPort }
        Ok "-Port: set CONFORMITI_PORT=$Port in .env (it was $was)"
        if (Move-EnvOrigins $oldPort $Port) {
          Ok "-Port: moved the localhost origins in CSRF_TRUSTED_ORIGINS / CORS_ALLOWED_ORIGINS from $oldPort to $Port"
        }
      }
    } elseif ($envPortNum) {
      $Port = $envPortNum
    }
  }

  # A host port something else holds would stop Compose part way, with the
  # database up and the API left without a network. Ports this project's own
  # containers publish are fine: that is a re-run, and Compose recreates them.
  # The API port is read the way Compose reads it: the environment, then .env.
  $apiText = if ($env:CONFORMITI_API_PORT) { $env:CONFORMITI_API_PORT } else { Get-EnvValue "CONFORMITI_API_PORT" }
  $apiPort = if ($apiText -match '^\d{1,5}$') { [int]$apiText } else { 8000 }
  if ((Test-PortBusy $Port) -and -not (Test-StackHolds frontend 80 $Port)) {
    Fail "port $Port is already in use on this machine. Choose another with -Port N (it is saved as CONFORMITI_PORT in .env)."
  }
  if ((Test-PortBusy $apiPort) -and -not (Test-StackHolds backend 8000 $apiPort)) {
    Fail "port $apiPort on 127.0.0.1, where the stack publishes its API, is already in use (a local 'manage.py runserver' is the usual holder). Set CONFORMITI_API_PORT to a free port in .env and run this again."
  }

  Say "Building images and starting the stack (first build takes a few minutes)..."
  # Set for this one call, so a CONFORMITI_PORT already in the environment
  # (which beats .env) cannot publish the app on a port other than the one
  # waited on below. Put back after it, since this can be the user's session.
  # No provenance attestation either: under the containerd image store (the
  # default for Docker Desktop and new Docker Engine installs) it gives every
  # build a new image id, even when each step came from the cache, and a new
  # id makes Compose recreate the container. A re-run of an unchanged checkout
  # then restarted the stack and took the demo password out of the log.
  $shellPort = $env:CONFORMITI_PORT
  $shellAttest = $env:BUILDX_NO_DEFAULT_ATTESTATIONS
  $env:CONFORMITI_PORT = "$Port"
  $env:BUILDX_NO_DEFAULT_ATTESTATIONS = "1"
  try { Run docker compose up -d --build } finally {
    $env:CONFORMITI_PORT = $shellPort
    $env:BUILDX_NO_DEFAULT_ATTESTATIONS = $shellAttest
  }
  Say "Waiting for the API to report healthy..."
  $health = Wait-Healthy "http://localhost:$Port/api/health/"
  if (-not $health) { & docker compose ps; Fail "The stack did not become healthy in time. Inspect with: docker compose logs backend" }
  Ok "healthy: version $($health.version), database $($health.database)"
  Write-Host ""
  Write-Host "Conformiti is running." -ForegroundColor Green
  Write-Host "  App      http://localhost:$Port"
  Write-Host "  Admin    http://localhost:$Port/admin/"
  Write-Host "  Health   http://localhost:$Port/api/health/"
  # What the running stack holds decides the banner, not the switches: a .env
  # or an earlier run can seed demo accounts this run never asked for.
  if ($health.demo_accounts -eq $true) {
    Write-Host "  Sign in  admin   (also mia, owen, aria, val; same password)"
    # The stack runs detached, so bootstrap_demo's one-time "Sign in as" line
    # is only in the backend log, and only when this container created the
    # accounts; a container that found them already there never prints it.
    $demoPw = Get-DemoPassword
    if ($demoPw) {
      Write-Host "  Password $demoPw   (note it now)"
      Write-Host "  The backend log keeps it only until that container is recreated, which -Port," -ForegroundColor DarkGray
      Write-Host "  an upgrade or any .env change does." -ForegroundColor DarkGray
    } else {
      Write-Host "  Password: not in the current backend log. It is printed once, by the container that" -ForegroundColor DarkGray
      Write-Host "  created the demo accounts. Set a new one for admin with:" -ForegroundColor DarkGray
      Write-Host "    docker compose exec backend python manage.py changepassword admin" -ForegroundColor DarkGray
    }
    Get-RetireDemoAdvice | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
  } else {
    if ($seedDemo -eq "true") { Warn "-Demo was given but the stack reports no demo accounts. Check: docker compose logs backend" }
    # first_admin_needed is true only while no active account exists, so a
    # re-run or an update on a used installation is not told to make one.
    # An image older than the field says neither, hence the third wording.
    if ($health.first_admin_needed -eq $true) {
      Write-Host "  Create your first account: docker compose exec backend python manage.py createsuperuser"
    } elseif ($health.first_admin_needed -eq $false) {
      Write-Host "  Sign in  with an existing account (this installation already has one)"
    } else {
      Write-Host "  No account yet? docker compose exec backend python manage.py createsuperuser"
    }
  }
  # A re-run rebuilds the checkout on disk, nothing more. An upgrade is a
  # backup and a checkout of the new release first (README, "Upgrading").
  Write-Host "  Logs: docker compose logs -f    Stop: docker compose down" -ForegroundColor DarkGray
  Write-Host "  Rebuild: powershell -ExecutionPolicy Bypass -File .\install.ps1 -Docker" -ForegroundColor DarkGray
  Write-Host "  Upgrade: back up with scripts/backup.sh, check out the new release tag, then rebuild" -ForegroundColor DarkGray
  Write-Host "           (README, `"Upgrading`", has the commands)" -ForegroundColor DarkGray
  if ($Open) { Start-Process "http://localhost:$Port" }
  exit 0
}

# --- Prerequisites (local paths) ---------------------------------------------
$py = $null
foreach ($c in @("python", "python3", "py")) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if (-not $cmd) { continue }
  if ((Probe $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)") -eq 0) { $py = $c; break }
}
if (-not $py) { Fail "Python 3.11 or newer is required but was not found on PATH (tested: 3.11 to 3.14; https://www.python.org/downloads/)." }
# Newer than the tested range is allowed, not refused: it usually works, but
# a dependency without wheels for it yet is the usual way it does not.
if ((Probe $py -c "import sys; sys.exit(0 if sys.version_info < (3, 15) else 1)") -ne 0) {
  Warn "$(& $py --version) is newer than the tested range (3.11 to 3.14): carrying on, but it is untested."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js 20.19+ or 22.12+ (with npm) is required but was not found on PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "npm is required but was not found on PATH." }
# Same range as frontend/package.json "engines" (^20.19.0 || >=22.12.0): Vite
# rejects 21.x and 22.0 to 22.11.
$nodeOk = & node -e "const [a,b]=process.versions.node.split('.').map(Number); process.stdout.write(((a===20&&b>=19)||(a===22&&b>=12)||a>22)?'y':'n')"
if ($nodeOk -ne "y") { Fail "Node.js 20.19+ or 22.12+ is required (found $(node --version))." }
Ok "using $(& $py --version), node $(node --version), npm $(npm --version)"

# The local path's own ports, never the Docker ones: a CONFORMITI_API_PORT set
# for the stack must not put runserver on the stack's API port. Vite reads the
# same two names from the environment (frontend/vite.config.js).
$devApiPort = 8000; $devPort = 5173
if (-not $Test) {
  $devApiPort = Get-DevPort "CONFORMITI_DEV_API_PORT" 8000
  $devPort = Get-DevPort "CONFORMITI_DEV_PORT" 5173
}

# --- .env with a generated secret key ---------------------------------------
$envCreated = $false
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  $secret = & $py -c "import secrets; print(secrets.token_urlsafe(50))"
  (Get-Content ".env") -replace '^DJANGO_SECRET_KEY=.*$', "DJANGO_SECRET_KEY=$secret" | Set-Content ".env"
  $envCreated = $true
  Ok ".env created (SQLite + console email; secret key generated)"
} else {
  Ok ".env already present: leaving it untouched"
}
# Sign-in is refused from any origin CSRF_TRUSTED_ORIGINS does not list, and
# .env.example lists http://localhost:5173 only. A .env this run created is
# this script's own file, so a moved web app's origin goes into it here, the
# way -Docker -Port moves its origins. An existing .env is the user's: it is
# only warned about, here and again in the closing lines.
$originMissing = $false
if (-not $Test -and $devPort -ne 5173) {
  $origin = "http://localhost:$devPort"
  if ($envCreated) {
    foreach ($key in @("CSRF_TRUSTED_ORIGINS", "CORS_ALLOWED_ORIGINS")) {
      $current = Get-EnvValue $key
      if (-not $current) { $current = "http://localhost:5173" }
      $list = @($current -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
      if ($list -notcontains $origin) { Set-EnvValue $key (($list + $origin) -join ",") }
    }
    Ok "added $origin (CONFORMITI_DEV_PORT) to CSRF_TRUSTED_ORIGINS and CORS_ALLOWED_ORIGINS in the new .env"
  }
  $origins = if ($env:CSRF_TRUSTED_ORIGINS) { $env:CSRF_TRUSTED_ORIGINS } else { Get-EnvValue "CSRF_TRUSTED_ORIGINS" }
  if (-not $origins) { $origins = "http://localhost:5173" }
  if (@($origins -split "," | ForEach-Object { $_.Trim() }) -notcontains $origin) {
    $originMissing = $true
    Show-OriginWarning $devPort
  }
}

# --- Virtualenv + backend deps ------------------------------------------------
# An existing .venv is reused only when its pip runs: a creation that stopped
# part way leaves a python.exe with no pip, and every later run would die at
# the pip step below.
$pyexe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if ((Test-Path $pyexe) -and (Probe $pyexe -m pip --version) -ne 0) {
  Warn "the existing .venv has no working pip (an earlier creation probably stopped part way): recreating it"
  Remove-Item -Recurse -Force ".venv"
}
if (-not (Test-Path $pyexe)) {
  Say "Creating Python virtual environment (.venv)..."
  if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
  Run $py -m venv .venv
  if ((Probe $pyexe -m pip --version) -ne 0) {
    Remove-Item -Recurse -Force ".venv" -ErrorAction SilentlyContinue
    Fail "the new .venv has no working pip, so nothing can be installed into it. Install Python from https://www.python.org/downloads/ (keep its pip option ticked), then run this again."
  }
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
# "npm ci" installs exactly what the lock file pins and never rewrites it;
# "npm install" from npm 10 drops the lock's libc fields and leaves the
# checkout dirty. npm install stays for a tree without a lock file.
#
# npm ci empties node_modules first, and Windows refuses to delete a file a
# running program has loaded. With the web app's dev server still up (Vite
# holds its native bundler binding), -Test stopped at "exited with code
# -4048" and left node_modules half deleted, so the dev server's next start
# failed too. A node_modules that already matches the lock file is therefore
# kept, which covers every re-run and -Test of an unchanged checkout, and a
# reinstall over an existing node_modules is refused while anything listens
# on the dev port, on any address (Vite is often on [::1] only). With no
# node_modules there is nothing to hold, so a fresh clone is never refused
# over another program on that port. --loglevel=error rather than --silent,
# so npm's own explanation of a failure reaches the screen.
# -Test ignores CONFORMITI_DEV_PORT for everything else, so it is read
# leniently here: the probe is the only use it has in that mode.
$webPort = $devPort
if ($Test -and $env:CONFORMITI_DEV_PORT -match '^\d{1,5}$' -and [int]$env:CONFORMITI_DEV_PORT -ge 1 -and [int]$env:CONFORMITI_DEV_PORT -le 65535) {
  $webPort = [int]$env:CONFORMITI_DEV_PORT
}
Push-Location frontend
try {
  if ((Test-Path "package-lock.json") -and (Test-FrontendDepsCurrent)) {
    Ok "frontend dependencies already match package-lock.json: kept as they are"
  } else {
    if ((Test-Path "node_modules") -and (Test-PortListened $webPort)) {
      Fail ("the frontend dependencies need reinstalling, but something is serving the web app's dev port, " +
            "$webPort (usually the dev server window an earlier run opened). Windows does not let npm replace " +
            "files a running dev server has loaded, and npm would stop part way with node_modules half deleted. " +
            "Close the two server windows, or stop whatever holds port $webPort, then run this again.")
    }
    Say "Installing frontend dependencies (this can take a minute)..."
    if (Test-Path "package-lock.json") {
      Run npm ci --no-fund --no-audit --loglevel=error
    } else {
      Run npm install --no-fund --no-audit --loglevel=error
    }
    Ok "frontend dependencies installed"
  }
} finally { Pop-Location }

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
$demoOut = @()
Push-Location backend
try {
  Run $pyexe manage.py migrate --noinput
  Run $pyexe manage.py seed_frameworks --with-folders
  $null = Probe $pyexe manage.py generate_folder_tree
  if ($seedDemo -eq "true") {
    # Captured so the banner below can repeat the one-time password. It is only
    # printed when this run created the accounts; a re-run keeps the old one.
    $demoOut = @(& $pyexe manage.py bootstrap_demo)
    $demoCode = $LASTEXITCODE
    $demoOut | ForEach-Object { Write-Host $_ }
    if ($demoCode -ne 0) { Fail "loading the demo data failed (see above)." }
  }
} finally { Pop-Location }
$demoState = ""; $demoPw = $null
if ($seedDemo -eq "true") {
  $hit = $demoOut | Select-String -Pattern 'Sign in as\s+admin\s*/\s*(.+?)\s*$' | Select-Object -Last 1
  if ($hit) { $demoPw = $hit.Matches[0].Groups[1].Value }
  # bootstrap_demo exits 0 in all three cases, so its words tell them apart.
  # "retired": remove_demo_data retired the demo here, and the accounts are
  # switched off or gone, so there is nothing to sign in with.
  $demoText = $demoOut -join "`n"
  $demoState = "loaded"
  if ($demoText.Contains("Demo data not seeded")) {
    $demoState = "retired"
  } elseif ($demoText.Contains("existing accounts kept their password")) {
    $demoState = "kept"
  }
  if ($demoState -eq "retired") {
    Ok "database ready (SOC 2 / ISO 27001 / PCI DSS seeded; demo data retired, not loaded)"
    Warn "remove_demo_data retired the demo in this database, so -Demo loaded nothing and"
    Warn "there are no demo accounts to sign in with. To seed them again anyway:"
    Warn "  cd backend; ..\.venv\Scripts\python.exe manage.py bootstrap_demo --force"
  } else {
    Ok "database ready (SOC 2 / ISO 27001 / PCI DSS seeded, demo data loaded)"
  }
} else {
  Ok "database ready (SOC 2 / ISO 27001 / PCI DSS seeded, no demo data)"
  Warn "create your first account with: cd backend; ..\.venv\Scripts\python.exe manage.py createsuperuser"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
if ($seedDemo -eq "true" -and $demoState -ne "retired") {
  Write-Host "  Sign in:  admin   (also mia, owen, aria, val; same password)"
  if ($demoPw) {
    Write-Host "  Password: $demoPw   (not shown again: note it now)"
  } elseif ($demoState -eq "kept") {
    Write-Host "  Password: unchanged. The demo accounts already existed and kept the one set when" -ForegroundColor DarkGray
    Write-Host "            they were created. Set a new one for admin with:" -ForegroundColor DarkGray
    Write-Host "            cd backend; ..\.venv\Scripts\python.exe manage.py changepassword admin" -ForegroundColor DarkGray
  } else {
    Write-Host "  Password: not in the seeding output above. Set one for admin with:" -ForegroundColor DarkGray
    Write-Host "            cd backend; ..\.venv\Scripts\python.exe manage.py changepassword admin" -ForegroundColor DarkGray
  }
}
Write-Host "  Tests:    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Test"
Write-Host "  Mailer:   cd backend; ..\.venv\Scripts\python.exe manage.py send_review_reminders --dry-run"
Write-Host ""

if ($SetupOnly) {
  # A moved port has to reach Vite too, so the command carries it. npm.cmd,
  # not npm: in a PowerShell window "npm" is the npm.ps1 shim, which the
  # default Restricted execution policy refuses to run.
  $devEnv = ""
  if ($devApiPort -ne 8000) { $devEnv += "`$env:CONFORMITI_DEV_API_PORT=$devApiPort; " }
  if ($devPort -ne 5173) { $devEnv += "`$env:CONFORMITI_DEV_PORT=$devPort; " }
  Write-Host "To start later:"
  Write-Host "  (backend)   cd backend; ..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:$devApiPort"
  Write-Host "  (frontend)  cd frontend; ${devEnv}npm.cmd run dev"
  Write-Host "Then open http://localhost:$devPort"
  if ($originMissing) { Show-OriginWarning $devPort }
  Write-Host "Ports: CONFORMITI_DEV_API_PORT=$devApiPort (API), CONFORMITI_DEV_PORT=$devPort (web app); set them in the shell to move either." -ForegroundColor DarkGray
  exit 0
}

Say "Starting servers: API on :$devApiPort (CONFORMITI_DEV_API_PORT), web app on :$devPort (CONFORMITI_DEV_PORT)."
Say "Open http://localhost:$devPort in your browser. Close the two windows to stop."
if ($originMissing) { Show-OriginWarning $devPort }
$backendDir = Join-Path $PSScriptRoot "backend"
$frontendDir = Join-Path $PSScriptRoot "frontend"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "`"$pyexe`" manage.py runserver 127.0.0.1:$devApiPort" -WorkingDirectory $backendDir
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "npm run dev" -WorkingDirectory $frontendDir
Ok "Servers launched in two console windows."
if ($Open) { Start-Sleep -Seconds 6; Start-Process "http://localhost:$devPort" }
