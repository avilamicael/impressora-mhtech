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


:: Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
  echo  [ERRO] Python nao encontrado. Instale o Python 3.10+.
  pause
  exit /b
)

:: Instala dependencias se necessario
echo  Verificando dependencias...
pip install flask xhtml2pdf requests urllib3 -q --disable-pip-version-check

echo  Iniciando servidor...
echo  Acesse: http://localhost:5000
echo.

:: Abre o navegador apos 2 segundos
timeout /t 2 /nobreak >nul
start "" http://localhost:5000

:: Inicia o servidor
python app.py

pause