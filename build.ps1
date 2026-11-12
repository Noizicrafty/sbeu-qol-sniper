$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить сборщик' }
& .\.venv\Scripts\python.exe build_exe.py
if ($LASTEXITCODE -ne 0) { throw 'Сборка exe не завершена' }
