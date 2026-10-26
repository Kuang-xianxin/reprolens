$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$record = Get-Content -LiteralPath (Join-Path $projectDir 'runtime/service.json') -Raw | ConvertFrom-Json
$owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.pid)" -ErrorAction SilentlyContinue
if (-not $owner) { Write-Output 'Recorded process is no longer running.'; exit 0 }
$recordedCreated = [DateTimeOffset]$record.creation_date
if ($owner.ExecutablePath -ne $record.executable -or $owner.CreationDate.ToUniversalTime().Ticks -ne $recordedCreated.UtcTicks -or $owner.CommandLine -ne $record.command_line) { throw 'PID identity changed; refusing to stop an unrelated process.' }
if ($owner.CommandLine -notmatch 'reprolens.app:app' -or $owner.CommandLine -notmatch '8211') { throw 'Process does not match this project.' }
Stop-Process -Id $record.pid
Write-Output "Stopped ReproLens PID $($record.pid). No files deleted."

