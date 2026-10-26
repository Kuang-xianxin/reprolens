param([string]$ModelConfig = '')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectDir 'runtime'
$pythonExe = Join-Path $projectDir '.venv/Scripts/python.exe'
if (Test-Path -LiteralPath (Join-Path $projectDir '.venv-hardening/Scripts/python.exe')) { $pythonExe = Join-Path $projectDir '.venv-hardening/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Create .venv and install requirements.lock.txt first.' }
New-Item -ItemType Directory -Force $runtimeDir | Out-Null
$listeners = @(Get-NetTCPConnection -LocalPort 8211 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count) { throw 'Port 8211 is already in use. Inspect runtime/service.json; do not start another process.' }
$info = [Diagnostics.ProcessStartInfo]::new()
$info.FileName = $pythonExe
$info.WorkingDirectory = $projectDir
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.Environment.Clear()
$safeNames = @('SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA','NUMBER_OF_PROCESSORS')
foreach ($item in [Environment]::GetEnvironmentVariables().GetEnumerator()) { if ($safeNames -contains $item.Key.ToUpperInvariant()) { $info.Environment[$item.Key] = $item.Value } }
$info.Environment['PYTHONUTF8'] = '1'
$info.Environment['PYTHONDONTWRITEBYTECODE'] = '1'
foreach ($arg in @((Join-Path $PSScriptRoot 'serve.py'),'--log-dir',$runtimeDir)) { $info.ArgumentList.Add($arg) }
if ($ModelConfig) { $info.ArgumentList.Add('--model-config'); $info.ArgumentList.Add((Resolve-Path -LiteralPath $ModelConfig).Path) }
$proc = [Diagnostics.Process]::Start($info)
$health = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 250
    try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8211/api/health' -TimeoutSec 1; break } catch { }
    if ($proc.HasExited) { throw "Server exited. Inspect $runtimeDir" }
}
if (-not $health) { throw "Health not verified. Launcher PID $($proc.Id); inspect $runtimeDir" }
$ownerPid = (Get-NetTCPConnection -LocalPort 8211 -State Listen | Select-Object -First 1).OwningProcess
$owner = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid"
$record = [ordered]@{ project='ReproLens'; url='http://127.0.0.1:8211'; port=8211; pid=$ownerPid; launcher_pid=$proc.Id; executable=$owner.ExecutablePath; command_line=$owner.CommandLine; creation_date=$owner.CreationDate.ToString('o'); started_at=(Get-Date).ToString('o'); log_directory=$runtimeDir; health=$health }
[IO.File]::WriteAllText((Join-Path $runtimeDir 'service.json'),($record | ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
$record | ConvertTo-Json -Depth 5

