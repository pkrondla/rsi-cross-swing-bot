# Roll back C:\rsi-cross-swing-bot to the previous git SHA recorded by CD.
$ErrorActionPreference = "Stop"
$repo = "C:\rsi-cross-swing-bot"
$prevFile = Join-Path $repo "deploy\previous_ref.txt"
if (-not (Test-Path $prevFile)) {
    throw "No previous_ref.txt; cannot roll back"
}
$sha = (Get-Content -LiteralPath $prevFile -Raw).Trim()
if (-not $sha) { throw "previous_ref.txt empty" }
$helper = Join-Path $PSScriptRoot "Nssm-RsiCrossServices.ps1"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& $helper -Action Stop
git -c core.pager=cat -C $repo reset --hard $sha
$venv = Join-Path $repo ".venv\Scripts\python.exe"
& $venv -m pip install --no-deps -r (Join-Path $repo "requirements.lock")
& $venv -m pip install --no-deps -e $repo
& $helper -Action Install
Write-Host "Rolled back to $sha"
