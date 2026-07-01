@echo off
cd /d "%~dp0"
title MH Tech - Atualizar Sistema

:: Este arquivo e autossuficiente: copie-o para dentro da pasta do sistema
:: (onde estao o app.py e o venv) e execute. Ele baixa o atualizador mais
:: recente do GitHub e aplica a nova versao, preservando os dados do cliente.

if not exist "venv\Scripts\pythonw.exe" (
    echo.
    echo  ERRO: pasta do sistema nao reconhecida.
    echo  Copie este arquivo para dentro da pasta onde estao o app.py e o venv,
    echo  e rode novamente.
    echo.
    pause
    exit /b 1
)

:: Pasta de instalacao, SEM a barra final (evita problema de aspas com o caminho).
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: Baixa o atualizador do GitHub (branch main) para um arquivo temporario.
set "PS1=%TEMP%\mhtech_atualizar.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { (New-Object Net.WebClient).DownloadFile('https://raw.githubusercontent.com/avilamicael/impressora-mhtech/main/atualizar.ps1', $env:PS1) } catch { Write-Host '  ERRO ao baixar o atualizador do GitHub. Verifique a internet.' -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

:: Executa o atualizador passando a pasta do sistema explicitamente.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -Root "%ROOT%"

echo.
pause
