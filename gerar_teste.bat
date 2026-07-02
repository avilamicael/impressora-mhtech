@echo off
cd /d "%~dp0"
title MH Tech - Gerar PDFs de teste

:: Gera PDFs de teste para um dia (10/20/30) ignorando a trava de data.
:: Serve para conferir o layout / testar sem esperar o dia do fechamento.

if not exist "venv\Scripts\python.exe" (
    echo  ERRO: venv nao encontrado nesta pasta. Rode dentro da pasta do sistema.
    pause
    exit /b 1
)

set /p DIA="Qual dia de fechamento testar? (10, 20 ou 30) [30]: "
if "%DIA%"=="" set "DIA=30"

echo.
echo  Gerando PDFs de teste para o dia %DIA%...
venv\Scripts\python.exe "gerar_teste.py" %DIA%

echo.
pause
