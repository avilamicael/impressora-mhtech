@echo off
:: Inicia o app em segundo plano (sem janela visivel).
:: Usa o Python do venv local — funciona em qualquer maquina.

cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo ERRO: venv nao encontrado. Execute install.bat primeiro.
    pause
    exit /b 1
)

:: pythonw.exe = Python sem janela de console
start "" /B "venv\Scripts\pythonw.exe" "%~dp0app.py"
