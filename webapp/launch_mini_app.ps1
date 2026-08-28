# launch_mini_app.ps1  —  run this (double-click launch.bat)
# Starts the local web server + Cloudflare quick tunnel, grabs the public URL,
# and points @firstcry4bot's menu button at the Mini App.
$ErrorActionPreference = "SilentlyContinue"
$webapp = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools  = "C:\Users\ryolo\AppData\Local\Temp\opencode"
if (-not (Test-Path $tools)) { New-Item -ItemType Directory -Path $tools -Force | Out-Null }

# Locate python binary
$py = $null
$candidatePyPaths = @(
    $env:PYTHON_PATH,
    (Get-Command python.exe -ErrorAction SilentlyContinue).Source,
    (Get-Command py.exe -ErrorAction SilentlyContinue).Source,
    "C:\Users\ryolo\AppData\Local\Python\pythoncore-3.14-64\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)
foreach ($cand in $candidatePyPaths) {
    if ($cand -and (Test-Path $cand)) { $py = $cand; break }
}
if (-not $py) { $py = "python" }

# Locate cloudflared binary
$cf = "$tools\cloudflared.exe"
if (-not (Test-Path $cf)) {
    $cfCmd = (Get-Command cloudflared.exe -ErrorAction SilentlyContinue).Source
    if ($cfCmd) { $cf = $cfCmd }
}

$tok    = if ($env:TELEGRAM_BOT_TOKEN) { $env:TELEGRAM_BOT_TOKEN } else { "8709329900:AAFyAgNOqZRCzEUhTI1jEP3EyWcNMECPDjc" }
$port   = 8777
$cflog  = "$tools\cf_run.log"
$cferr  = "$tools\cf_err.log"

# Clean up any previous run on this port
(Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | 
    Select-Object -Unique | 
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

# 1) local static server (bind loopback)
$pyArgs = if ($py -like "*py.exe") { @("-3","-m","http.server",$port,"--bind","127.0.0.1","--directory",$webapp) } else { @("-m","http.server",$port,"--bind","127.0.0.1","--directory",$webapp) }
$pyProc = Start-Process -FilePath $py -ArgumentList $pyArgs `
    -RedirectStandardOutput "$tools\httpd_run.log" -WindowStyle Hidden -PassThru

# wait until it actually answers (retry up to 15s)
$localOk = $false
for ($i=0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    $code = curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:$port/index.html"
    if ($code -eq "200") { $localOk = $true; break }
}
if (-not $localOk) {
    Write-Host "Local server failed to start (see $tools\httpd_run.log)" -ForegroundColor Red
    pause; exit
}
Write-Host "Local server OK on :$port" -ForegroundColor Cyan

# 2) cloudflared quick tunnel with http2 protocol for reliable TCP connections
Remove-Item $cflog,$cferr -ErrorAction SilentlyContinue
$cfArgs = @("tunnel","--url","http://127.0.0.1:$port","--protocol","http2","--loglevel","info","--logfile",$cflog)
$cfProc = Start-Process -FilePath $cf -ArgumentList $cfArgs `
    -RedirectStandardError $cferr -WindowStyle Hidden -PassThru

# 3) wait for the public URL in the log file
$url = ""
for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    $txt = Get-Content $cflog -Raw -ErrorAction SilentlyContinue
    $m = [regex]::Match($txt,'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Success) { $url = $m.Value.TrimEnd('/'); break }
}
if (-not $url) {
    Write-Host "Could not get tunnel URL. cf log:" -ForegroundColor Red
    Get-Content $cflog -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    if ($pyProc) { Stop-Process -Id $pyProc.Id -Force -ErrorAction SilentlyContinue }
    pause; exit
}
Write-Host "`nPublic Mini App URL:" -ForegroundColor Green
Write-Host $url -ForegroundColor Yellow

# Save URL to shared file for telegram_bot.py
$urlFile = Join-Path (Split-Path $webapp -Parent) "miniapp_url.txt"
Set-Content -Path $urlFile -Value $url -Force

# give cloudflare a moment, then verify it is reachable
Start-Sleep -Seconds 4
$rk = curl.exe -s -o NUL -w "%{http_code}" "$url/index.html"
Write-Host ("Tunnel reachable: HTTP $rk") -ForegroundColor Cyan

# 4) set the bot menu button to launch the Mini App
$body = @{ menu_button = @{ type="web_app"; text="Open Mini App"; web_app=@{ url=$url } } } | ConvertTo-Json -Depth 4 -Compress
$r = curl.exe -s -X POST ("https://api.telegram.org/bot"+$tok+"/setChatMenuButton") `
    -H "Content-Type: application/json" -d $body
Write-Host "`nsetChatMenuButton result: $r" -ForegroundColor Cyan

$domainName = $url -replace '^https?://([^/]+).*','$1'
Write-Host "`nNEXT STEP (once, in Telegram):" -ForegroundColor Magenta
Write-Host "  @BotFather -> /setdomain -> @firstcry4bot -> send:" -ForegroundColor White
Write-Host "    $domainName" -ForegroundColor Yellow
Write-Host "  Then open @firstcry4bot and tap the menu (☰ -> 'Open Data')." -ForegroundColor White

Write-Host "`nMini App is LIVE while this window stays open. Press Enter to stop the server+tunnel." -ForegroundColor Green
pause

# Clean shutdown
if ($pyProc) { Stop-Process -Id $pyProc.Id -Force -ErrorAction SilentlyContinue }
if ($cfProc) { Stop-Process -Id $cfProc.Id -Force -ErrorAction SilentlyContinue }
(Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | 
    Select-Object -Unique | 
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Write-Host "Stopped." -ForegroundColor Gray
