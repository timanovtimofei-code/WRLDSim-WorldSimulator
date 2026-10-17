# Пересобирает WRLDSim1.exe, если исходники новее него. Лог - build\rebuild.log.
$name = "WRLDSim1"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$exe = Get-Item "$name.exe" -ErrorAction SilentlyContinue
$sources = @(Get-ChildItem -Path "wrldsim", "tools" -Recurse -File -Include *.py) +
    @(Get-Item "main.py", "assets\icon.ico", "build_exe.bat" -ErrorAction SilentlyContinue)
$newest = $sources | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($exe -and $newest.LastWriteTime -le $exe.LastWriteTime) { exit 0 }

New-Item -ItemType Directory -Force "build" | Out-Null
$log = Join-Path $root "build\rebuild.log"
Get-Process $name -ErrorAction SilentlyContinue | Stop-Process -Force  # запущенный exe держит файл и не даёт его заменить
Start-Sleep -Milliseconds 300
"[$(Get-Date -Format s)] rebuild: newest source $($newest.FullName)" | Out-File $log -Encoding utf8
& cmd /c "`"$root\build_exe.bat`" >> `"$log`" 2>&1"
$exe = Get-Item "$name.exe" -ErrorAction SilentlyContinue
if ($exe -and $exe.LastWriteTime -ge $newest.LastWriteTime) {
    "[$(Get-Date -Format s)] OK $($exe.FullName)" | Out-File $log -Append -Encoding utf8
} else {
    "[$(Get-Date -Format s)] FAILED, $name.exe not updated (see log above)" | Out-File $log -Append -Encoding utf8
    Write-Error "Build of $name.exe failed, see build\rebuild.log"
    exit 1
}
