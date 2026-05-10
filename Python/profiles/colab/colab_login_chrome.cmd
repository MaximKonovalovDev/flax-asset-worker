@echo off
setlocal
set SCRIPT_DIR=%~dp0

echo AssetBoy Colab Chrome login helper
echo.
echo Preparing Colab account HOME folders (uses colab_exec_accounts.example.json).
call "%SCRIPT_DIR%bootstrap_colab_accounts.cmd"
echo.
echo Opening Chrome for Google account + Colab login...
start "" "chrome" "https://accounts.google.com/"
start "" "chrome" "https://colab.research.google.com/"
echo.
echo After login, run any Colab job in Codex to finish token creation.
echo Example:
echo   python -m assetboy.cli emit-hunyuan-batch
echo.
endlocal
