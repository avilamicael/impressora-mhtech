@echo off
:: Executa uma vez em cada máquina para configurar o ambiente.
:: Não precisa saber onde o Python está instalado no sistema do cliente
:: — usa o "python" do PATH para criar o venv, depois tudo vem do venv.

cd /d "%~dp0"

echo [1/3] Criando ambiente virtual...
python -m venv venv
if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH. Instale o Python e tente novamente.
    pause
    exit /b 1
)

echo [2/3] Instalando dependencias...
venv\Scripts\pip install --upgrade pip --quiet
venv\Scripts\pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERRO: Falha ao instalar dependencias.
    pause
    exit /b 1
)

echo [3/3] Registrando inicializacao automatica no Task Scheduler...
schtasks /create /tn "MH_Tech_Print" /tr "\"%~dp0start.bat\"" /sc onlogon /rl HIGHEST /f
if errorlevel 1 (
    echo AVISO: Nao foi possivel registrar no Task Scheduler automaticamente.
    echo Registre manualmente conforme as instrucoes do README.
)

echo.
echo Instalacao concluida! O app vai iniciar automaticamente com o Windows.
echo Para iniciar agora: execute start.bat
echo.
pause
