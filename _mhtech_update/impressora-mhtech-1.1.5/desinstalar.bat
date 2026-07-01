@echo off
cd /d "%~dp0"

echo.
echo  MH Tech - Desinstalador
echo  ========================
echo.

:: Remove a tarefa do Task Scheduler
echo [1/2] Removendo tarefa do Task Scheduler...
schtasks /delete /tn "MH_Tech_Print" /f >nul 2>&1
if errorlevel 1 (
    echo  AVISO: Tarefa nao encontrada ou ja removida.
) else (
    echo  Tarefa removida com sucesso.
)

:: Pergunta se deseja remover o ambiente virtual
echo.
set /p REMOVER_VENV="[2/2] Deseja remover o ambiente virtual (venv)? Isso apaga as dependencias instaladas. [s/N] "
if /i "%REMOVER_VENV%"=="s" (
    if exist "venv\" (
        rmdir /s /q venv
        echo  Ambiente virtual removido.
    ) else (
        echo  Pasta venv nao encontrada.
    )
) else (
    echo  Ambiente virtual mantido.
)

echo.
echo  Desinstalacao concluida. O app nao iniciara mais automaticamente.
echo  Os arquivos do sistema (PDFs, snapshots, logs) foram mantidos.
echo.
pause
