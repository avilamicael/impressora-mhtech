@echo off
title MH Tech - Sistema de Faturamento
cd /d "%~dp0"

echo.
echo   __  __   _    _     _______   ______    _____   _    _
echo  ^|  \/  ^| ^| ^|  ^| ^|   ^|__   __^| ^|  ____^|  / ____^| ^| ^|  ^| ^|
echo  ^| \  / ^| ^| ^|__^| ^|      ^| ^|    ^| ^|__    ^| ^|      ^| ^|__^| ^|
echo  ^| ^|\/^| ^| ^|  __  ^|      ^| ^|    ^|  __^|   ^| ^|      ^|  __  ^|
echo  ^| ^|  ^| ^| ^| ^|  ^| ^|      ^| ^|    ^| ^|____  ^| ^|____  ^| ^|  ^| ^|
echo  ^|_^|  ^|_^| ^|_^|  ^|_^|      ^|_^|    ^|______^|  \_____^| ^|_^|  ^|_^|
echo.
echo  Sistema de Gerenciamento
echo.

:: Verifica se o Python esta disponivel (necessario apenas na primeira vez)
python --version >nul 2>&1
if errorlevel 1 (
  echo  [ERRO] Python nao encontrado. Instale o Python 3.10+.
  pause
  exit /b
)

:: Cria o ambiente virtual se ainda nao existir
if not exist "venv\Scripts\python.exe" (
  echo  Criando ambiente virtual...
  python -m venv venv
  if errorlevel 1 (
    echo  [ERRO] Falha ao criar ambiente virtual.
    pause
    exit /b
  )
)

:: Instala/atualiza dependencias via requirements.txt
echo  Verificando dependencias...
venv\Scripts\pip install -r requirements.txt -q --disable-pip-version-check

echo  Iniciando servidor...
echo  Acesse: http://localhost:5000
echo.

:: Abre o navegador apos 2 segundos
timeout /t 2 /nobreak >nul
start "" http://localhost:5000

:: Inicia o servidor usando o Python do venv
venv\Scripts\python.exe app.py

pause
