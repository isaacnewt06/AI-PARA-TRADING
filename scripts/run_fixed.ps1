$ErrorActionPreference = "Stop"

cd "C:\Users\Administrador\Desktop\BOTEXTRATOR"

Write-Host "=== CLEANUP PROCESSES ===" -ForegroundColor Cyan

Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

Write-Host "=== REMOVE LOCK FILES ===" -ForegroundColor Cyan

Remove-Item ".\data\*.db-wal" -ErrorAction SilentlyContinue
Remove-Item ".\data\*.db-shm" -ErrorAction SilentlyContinue

Write-Host "=== STATUS ===" -ForegroundColor Cyan
python -m src.cli.main status

Write-Host "=== START DOWNLOAD (REAL) ===" -ForegroundColor Cyan

python -m src.cli.main download-archives --limit 1 --max-group-size-mb 2500 --download-only-complete-groups

Write-Host "=== VERIFY FILE ===" -ForegroundColor Cyan

Get-ChildItem ".\data\raw\telegram" -Recurse |
Sort-Object Length -Descending |
Select-Object -First 5 Name,Length

Write-Host "=== INSPECT ===" -ForegroundColor Cyan
python -m src.cli.main inspect-archives --limit 5

Write-Host "=== RANK ===" -ForegroundColor Cyan
python -m src.cli.main rank-archives

Write-Host "=== PROCESS ===" -ForegroundColor Cyan
python -m src.cli.main process-selected-archives --limit 1 --max-size-mb 2500

Write-Host "=== BUILD KB ===" -ForegroundColor Cyan
python -m src.cli.main rebuild-kb --filtered

Write-Host "=== EXTRACT ===" -ForegroundColor Cyan
python -m src.cli.main extract-rules

Write-Host "=== DETECT ===" -ForegroundColor Cyan
python -m src.cli.main detect-strategies

Write-Host "=== FINAL STATUS ===" -ForegroundColor Green
python -m src.cli.main status