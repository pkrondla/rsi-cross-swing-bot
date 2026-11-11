# Write NSSM launcher scripts for every sleeve in config/sleeves.yaml plus watch/ctrl.
param(
    [string]$RepoPath = "C:\rsi-cross-swing-bot"
)

$ErrorActionPreference = "Stop"
$venv = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venv)) {
    throw "Missing venv python at $venv"
}

$getIds = Join-Path $PSScriptRoot "Get-SleeveIds.ps1"
$sleeveIds = @( & $getIds -RepoPath $RepoPath )
Write-Host "Sleeves: $($sleeveIds -join ', ')"

function Write-Launcher {
    param(
        [string]$File,
        [string]$ModuleArgs,
        [string]$SleeveId = ""
    )
    $path = Join-Path $RepoPath $File
    $lines = @(
        '$ErrorActionPreference = "Stop"'
        "`$repo = `"$RepoPath`""
        'Get-Content (Join-Path $repo ".env") -ErrorAction SilentlyContinue | ForEach-Object {'
        '  if ($_ -match "^\s*#" -or [string]::IsNullOrWhiteSpace($_)) { return }'
        '  $parts = $_.Split("=", 2)'
        '  if ($parts.Count -eq 2) { [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process") }'
        '}'
    )
    if ($SleeveId) {
        $lines += "[System.Environment]::SetEnvironmentVariable(`"SLEEVE`", `"$SleeveId`", `"Process`")"
        $lines += "`$allocKey = `"SLEEVE_$($SleeveId.ToUpperInvariant())_ALLOCATED_USD`""
        $lines += "`$alloc = [System.Environment]::GetEnvironmentVariable(`$allocKey, `"Process`")"
        $lines += 'if ($alloc) { [System.Environment]::SetEnvironmentVariable("ALLOCATED_USD", $alloc, "Process") }'
    }
    $lines += "Set-Location `$repo"
    $lines += "& `"$venv`" -m rsi_cross_swing_bot $ModuleArgs"
    $lines | Set-Content -Path $path -Encoding utf8
    Write-Host "wrote $File"
}

foreach ($sid in $sleeveIds) {
    Write-Launcher -File "start-rsi-cross-$sid.ps1" -ModuleArgs "serve --sleeve $sid" -SleeveId $sid
}
Write-Launcher -File "start-rsi-cross-watch.ps1" -ModuleArgs "watchdog"
Write-Launcher -File "start-rsi-cross-ctrl.ps1" -ModuleArgs "telegram"
Write-Launcher -File "start-rsi-cross-list.ps1" -ModuleArgs "watch"
Write-Host "launchers written for $($sleeveIds.Count) sleeve(s)"
