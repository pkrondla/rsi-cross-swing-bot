# Roll back C:\qqq-rsi-bot to the previous git ref. Does not touch OrbBot.
param(
    [string]$RepoPath = "C:\qqq-rsi-bot"
)

$ErrorActionPreference = "Stop"
$prevFile = Join-Path $RepoPath "deploy\previous_ref.txt"
if (-not (Test-Path $prevFile)) {
    throw "No previous_ref.txt at $prevFile. Cannot roll back."
}
$ref = (Get-Content $prevFile -Raw).Trim()
if (-not $ref) { throw "previous_ref.txt is empty." }
Write-Host "Rolling back qqq-rsi-bot to $ref"
$helper = Join-Path $PSScriptRoot "Nssm-QqqRsiServices.ps1"
& $helper -Action Stop -RepoPath $RepoPath
git -C $RepoPath fetch origin
git -C $RepoPath reset --hard $ref
$venv = Join-Path $RepoPath ".venv\Scripts\python.exe"
& $venv -m pip install --no-deps -r (Join-Path $RepoPath "requirements.lock")
& $venv -m pip install --no-deps -e $RepoPath
& $helper -Action Install -RepoPath $RepoPath
Write-Host "Rollback complete."
