param([ValidateSet("cuda","cpu")][string]$Mode = "cuda")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
# WSL2 Ubuntu is preferred for the native C++ pilot. This script only sets up Python.
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Previous command failed: $LASTEXITCODE" } }
py -3.12 -m venv .venv; Check-Exit
$P = ".venv\Scripts\python.exe"
& $P -m pip install --upgrade pip; Check-Exit
& $P -m pip install -r requirements/base.txt -r requirements/dev.txt; Check-Exit
$Index = "https://download.pytorch.org/whl/cu128"
if ($Mode -eq "cpu") { $Index = "https://download.pytorch.org/whl/cpu" }
& $P -m pip install torch==2.9.1 --index-url $Index; Check-Exit
& $P -m pip install -e . --no-deps; Check-Exit
& $P -m pip check; Check-Exit
& $P -m pip freeze | Out-File -Encoding utf8 requirements/target-resolved.txt
if ($Mode -eq "cuda") { & $P -m stsai doctor --require-cuda } else { & $P -m stsai doctor }
Check-Exit
Write-Host "Run: .venv\Scripts\python.exe -m pytest -q"
