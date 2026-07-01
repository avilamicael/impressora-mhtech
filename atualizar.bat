@echo off
cd /d "%~dp0"
title MH Tech - Atualizar Sistema

:: Este arquivo e autossuficiente: basta copia-lo para dentro da pasta do
:: sistema (onde esta o app.py / venv) na maquina do cliente e executar.
:: Ele baixa o atualizador mais recente do GitHub e aplica a nova versao.

if not exist "venv\Scripts\pythonw.exe" (
    echo.
    echo  ERRO: pasta do sistema nao reconhecida.
    echo  Copie este arquivo para dentro da pasta onde esta o app.py e o venv,
    echo  e rode novamente.
    echo.
    pause
    exit /b 1
)

:: A pasta atual (onde o .bat esta) e a pasta de instalacao.
set "MHT_ROOT=%~dp0"

:: Baixa o atualizador do GitHub (branch main) e executa.
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $u='https://raw.githubusercontent.com/avilamicael/impressora-mhtech/main/atualizar.ps1'; try { $s=(New-Object Net.WebClient).DownloadString($u) } catch { Write-Host ''; Write-Host '  ERRO: nao foi possivel baixar o atualizador do GitHub. Verifique a internet.' -ForegroundColor Red; exit 1 }; Invoke-Expression $s"

echo.
pause
