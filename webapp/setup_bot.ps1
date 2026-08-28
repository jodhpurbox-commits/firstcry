# Configures @firstcry4bot to launch the Telegram Mini App (Web App)
# via the chat menu button. Run AFTER the webapp folder is hosted on public HTTPS.
param(
    [string]$Url,
    [string]$BotToken
)

$tok = if ($BotToken) { $BotToken } elseif ($env:TELEGRAM_BOT_TOKEN) { $env:TELEGRAM_BOT_TOKEN } else { "8709329900:AAFyAgNOqZRCzEUhTI1jEP3EyWcNMECPDjc" }

if (-not $Url) { $Url = Read-Host "Enter the PUBLIC https:// URL of index.html (the Mini App)" }
if ($Url -notmatch '^https://') { Write-Error "URL must start with https://"; exit 1 }

$body = @{ menu_button = @{ type="web_app"; text="Open Mini App"; web_app=@{ url=$Url } } } | ConvertTo-Json -Depth 4 -Compress

Write-Output "Setting menu button -> $Url"
$resp = & curl.exe -s -X POST ("https://api.telegram.org/bot"+$tok+"/setChatMenuButton") `
    -H "Content-Type: application/json" -d $body

Write-Output "Response: $resp"

$domain = $Url -replace '^https?://([^/]+).*','$1'
Write-Output ""
Write-Output "Also add the domain to the bot in @BotFather: send /setdomain and choose @firstcry4bot, then enter:"
Write-Output ("  " + $domain)
