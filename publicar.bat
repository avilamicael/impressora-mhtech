@echo off
cd /d "%~dp0"
title MH Tech - Publicar nova versao

if "%~1"=="" (
    echo.
    echo  Uso: publicar.bat ^<versao^>
    echo  Exemplo: publicar.bat 1.1.0
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publicar.ps1" -Versao "%~1"

echo.
pause
