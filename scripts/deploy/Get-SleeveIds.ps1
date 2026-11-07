# Parse sleeve ids from config/sleeves.yaml (no Python required).
param(
    [string]$RepoPath = "C:\rsi-cross-swing-bot"
)

$ErrorActionPreference = "Stop"
$path = Join-Path $RepoPath "config\sleeves.yaml"
if (-not (Test-Path -LiteralPath $path)) {
    throw "Missing $path"
}

$ids = [System.Collections.Generic.List[string]]::new()
$inSleeves = $false
foreach ($line in Get-Content -LiteralPath $path) {
    if ($line -match '^\s*#') { continue }
    if ($line -match '^\s*sleeves\s*:') {
        $inSleeves = $true
        continue
    }
    if (-not $inSleeves) { continue }
    # Next top-level key ends the sleeves block
    if ($line -match '^[A-Za-z0-9_]+\s*:') { break }
    if ($line -match '^\s{2}([a-zA-Z0-9_-]+)\s*:') {
        $ids.Add($Matches[1].ToLowerInvariant())
    }
}

if ($ids.Count -eq 0) {
    throw "No sleeves found in $path"
}
$ids
