$ErrorActionPreference = 'Stop'
$application = Join-Path $PSScriptRoot 'dist\SBEU qol sniper\SBEU qol sniper.exe'
if (-not (Test-Path -LiteralPath $application)) { throw 'Сначала соберите приложение: .\build.ps1' }
Start-Process -FilePath $application -WindowStyle Hidden
