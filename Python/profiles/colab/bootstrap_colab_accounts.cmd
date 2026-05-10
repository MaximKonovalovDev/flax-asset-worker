@echo off
setlocal
set "PSHOST=pwsh.exe"
where pwsh.exe >nul 2>&1
if errorlevel 1 set "PSHOST=powershell.exe"
set SCRIPT_DIR=%~dp0
%PSHOST% -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bootstrap_colab_accounts.ps1" %*
endlocal
