$cap = "C:\Users\ryolo\AppData\Roaming\Reqable\capture"
$markerFile = "C:\Users\ryolo\capture_start.txt"
$markerTime = if (Test-Path $markerFile) { (Get-Item $markerFile).LastWriteTime } else { [DateTime]::MinValue }
$outDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$sess = Get-ChildItem $cap -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $markerTime }

$map = @{}
foreach($f in $sess){
    $parts = $f.Name -split '-'
    if($parts.Count -lt 4){ continue }
    $prefix = "$($parts[0])-$($parts[1])-$($parts[2])"
    $type = ($parts[3..($parts.Count-1)] -join '-') -replace '\.reqable$',''
    if(-not $map.ContainsKey($prefix)){ $map[$prefix] = @{} }
    $content = ""
    try { $content = [System.IO.File]::ReadAllText($f.FullName) } catch { $content = "<unreadable>" }
    if($type -eq 'req_raw-body'){ $map[$prefix]['req'] = $content }
    elseif($type -eq 'req-extract-body'){ if(-not $map[$prefix].ContainsKey('req')){ $map[$prefix]['req'] = $content } }
    elseif($type -eq 'res_raw-body'){ $map[$prefix]['res'] = $content }
    elseif($type -eq 'res-extract-body'){ $map[$prefix]['resx'] = $content }
    else { $map[$prefix]['other_'+$type] = $content }
}

$epochBase = [DateTime]::new(1970,1,1,0,0,0,0,[DateTimeKind]::Utc)
$sorted = $map.Keys | Sort-Object { [long]($_ -split '-')[0] }, { [int]($_ -split '-')[1] }, { [int]($_ -split '-')[2] }
$sb = New-Object System.Text.StringBuilder
$cnt = 0
foreach($p in $sorted){
    $parts = $p -split '-'
    $epoch = [long]$parts[0]
    try {
        if ($epoch -gt 100000000000000) {
            # Microseconds (16 digits) -> 1 microsecond = 10 ticks
            $dt = $epochBase.AddTicks($epoch * 10).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss.fff')
        } elseif ($epoch -gt 100000000000) {
            # Milliseconds (13 digits)
            $dt = $epochBase.AddMilliseconds($epoch).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss.fff')
        } else {
            # Seconds (10 digits)
            $dt = $epochBase.AddSeconds($epoch).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss.fff')
        }
    } catch { $dt = "unknown" }
    $null = $sb.AppendLine("==================================================")
    $null = $sb.AppendLine("TIME: $dt   STREAM: $p")
    $null = $sb.AppendLine("--------------------------------------------------")
    if($map[$p].ContainsKey('req')){ $null = $sb.AppendLine("[REQUEST BODY]"); $null = $sb.AppendLine($map[$p]['req']) }
    if($map[$p].ContainsKey('resx')){ $null = $sb.AppendLine("[RESPONSE BODY (decoded)]"); $null = $sb.AppendLine($map[$p]['resx']) }
    elseif($map[$p].ContainsKey('res')){ $null = $sb.AppendLine("[RESPONSE BODY]"); $null = $sb.AppendLine($map[$p]['res']) }
    $null = $sb.AppendLine("")
    $cnt++
}
$report = Join-Path $outDir "firstcry_session.txt"
[System.IO.File]::WriteAllText($report, $sb.ToString(), [System.Text.Encoding]::UTF8)
Write-Output ("Report entries: $cnt")
Write-Output ("Report: $report  size: "+((Get-Item $report).Length))

# Sync to webapp folder if present
$webappReport = Join-Path $outDir "webapp\firstcry_session.txt"
if (Test-Path (Join-Path $outDir "webapp")) {
    Copy-Item $report $webappReport -Force
    Write-Output ("Synced to: $webappReport")
}

if ($sess -and $sess.Count -gt 0) {
    $zip = Join-Path $outDir "firstcry_session.zip"
    Compress-Archive -Path ($sess.FullName) -DestinationPath $zip -Force
    Write-Output ("Zip: $zip  size: "+((Get-Item $zip).Length))
}
