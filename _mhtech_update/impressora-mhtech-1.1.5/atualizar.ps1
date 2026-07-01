# ============================================================================
#  MH Tech - Atualizador automatico
#  Verifica a ultima versao no GitHub, baixa, aplica preservando os dados
#  do cliente (config.json, snapshots, faturamento, logs) e reinicia o app.
#
#  NAO execute este .ps1 direto: use "atualizar.bat" (duplo-clique).
# ============================================================================

param([string]$Root = '')

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo    = 'avilamicael/impressora-mhtech'
# Pasta da instalacao: prioridade -> parametro -Root, depois variavel MHT_ROOT,
# depois a pasta do script, por fim o diretorio atual.
if     ($Root)          { $Root = $Root.TrimEnd('\') }
elseif ($env:MHT_ROOT)  { $Root = $env:MHT_ROOT.TrimEnd('\') }
elseif ($PSScriptRoot)  { $Root = $PSScriptRoot }
else                    { $Root = (Get-Location).Path }
$Headers = @{ 'User-Agent' = 'mh-tech-updater' }

# Sanidade: a pasta precisa ter o venv, senao estamos no lugar errado.
if (-not (Test-Path (Join-Path $Root 'venv\Scripts\pythonw.exe'))) {
    Write-Host ''
    Write-Host "  ERRO: pasta do sistema nao encontrada em: $Root" -ForegroundColor Red
    Write-Host '  Rode o atualizar.bat de dentro da pasta do sistema (onde estao app.py e venv).'
    exit 1
}

# Arquivos/pastas do cliente que NUNCA devem ser sobrescritos
$ExcludeFiles = @('config.json')
$ExcludeDirs  = @('venv', 'snapshots', 'faturamento', '__pycache__', '.git', '_mhtech_update')

function Step($m) { Write-Host "  $m" }

Write-Host ''
Write-Host '  MH Tech - Verificacao de atualizacao'
Write-Host '  ===================================='

try {
    # ---- 1) Versao instalada localmente ------------------------------------
    $verFile = Join-Path $Root 'version.txt'
    if (Test-Path $verFile) { $local = (Get-Content $verFile -Raw).Trim() } else { $local = '0.0.0' }
    $localNorm = $local.TrimStart('v', 'V')
    Step "Versao instalada     : $localNorm"

    # ---- 2) Ultima versao no GitHub (Release; senao a maior tag) ------------
    $remoteTag = $null
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers $Headers -TimeoutSec 30
        $remoteTag = $rel.tag_name
    } catch {
        try {
            $tags = Invoke-RestMethod "https://api.github.com/repos/$Repo/tags" -Headers $Headers -TimeoutSec 30
            if ($tags -and @($tags).Count -gt 0) {
                $remoteTag = (@($tags) | Sort-Object {
                    try { [version]($_.name.TrimStart('v','V')) } catch { [version]'0.0.0' }
                } -Descending | Select-Object -First 1).name
            }
        } catch { }
    }

    if (-not $remoteTag) {
        Write-Host ''
        Write-Host '  Nenhuma versao publicada no GitHub ainda. Nada a fazer.' -ForegroundColor Yellow
        exit 0
    }
    $remoteNorm = $remoteTag.TrimStart('v', 'V')
    Step "Ultima versao GitHub : $remoteNorm"

    # ---- 3) Precisa atualizar? --------------------------------------------
    $needUpdate = $false
    try { $needUpdate = [version]$remoteNorm -gt [version]$localNorm }
    catch { $needUpdate = ($remoteNorm -ne $localNorm) }

    if (-not $needUpdate) {
        Write-Host ''
        Write-Host "  O sistema ja esta na versao mais recente (v$localNorm)." -ForegroundColor Green
        exit 0
    }

    Write-Host ''
    Write-Host "  Nova versao disponivel: v$remoteNorm  (instalada: v$localNorm)" -ForegroundColor Cyan
    Write-Host ''

    # ---- 4) Baixa e extrai o pacote ---------------------------------------
    # Usa uma pasta temporaria DENTRO da instalacao (caminho limpo, sem nomes
    # curtos 8.3 tipo C:\Users\MHTECH~1 do %TEMP%, que quebram o Remove-Item).
    $tmp = Join-Path $Root '_mhtech_update'
    if (Test-Path $tmp) { try { Remove-Item $tmp -Recurse -Force } catch {} }
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $zip = Join-Path $tmp 'release.zip'
    $zipUrl = "https://github.com/$Repo/archive/refs/tags/$remoteTag.zip"

    Step "Baixando pacote ($remoteTag)..."
    Invoke-WebRequest $zipUrl -OutFile $zip -Headers $Headers -TimeoutSec 180

    Step 'Extraindo...'
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
    if (-not $src) { throw 'Falha ao extrair o pacote baixado.' }

    # ---- 5) Encerra o app em execucao -------------------------------------
    Step 'Encerrando o app atual...'
    taskkill /f /im pythonw.exe 2>$null | Out-Null
    Start-Sleep -Seconds 2

    # ---- 6) Aplica os arquivos (preservando dados do cliente) -------------
    Step 'Aplicando atualizacao...'
    $rcArgs = @($src.FullName, $Root, '/E', '/XF') + $ExcludeFiles + @('/XD') + $ExcludeDirs + @('/NFL','/NDL','/NJH','/NJS','/NP','/R:2','/W:2')
    & robocopy @rcArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Falha ao copiar arquivos (robocopy codigo $LASTEXITCODE)." }

    # ---- 7) Atualiza dependencias (rapido se nada mudou) ------------------
    Step 'Verificando dependencias...'
    $pip = Join-Path $Root 'venv\Scripts\pip.exe'
    & $pip install -r (Join-Path $Root 'requirements.txt') -q --disable-pip-version-check

    # A atualizacao (codigo + dependencias) ja foi aplicada com sucesso aqui.
    # A partir deste ponto, qualquer falha NAO invalida o update.

    # ---- 8) Limpeza (nunca pode quebrar o update) -------------------------
    try { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue } catch {}

    # ---- 9) Reinicia o app (best-effort) ----------------------------------
    # Usa o mesmo mecanismo do start.bat (comando 'start' do cmd), que ja
    # funciona nesta maquina. Se falhar, apenas avisamos para rodar start.bat.
    Step 'Reiniciando o app...'
    $restarted = $false
    try {
        $pyw   = Join-Path $Root 'venv\Scripts\pythonw.exe'
        $appPy = Join-Path $Root 'app.py'
        $cmdline = 'start "MHTech" /B "' + $pyw + '" "' + $appPy + '"'
        & cmd.exe /c $cmdline
        $restarted = $true
    } catch {
        $restarted = $false
    }

    Write-Host ''
    Write-Host "  Atualizado com sucesso para a versao v$remoteNorm!" -ForegroundColor Green
    if ($restarted) {
        Write-Host '  App reiniciado. Acesse: http://localhost:5000'
    } else {
        Write-Host '  Nao consegui reiniciar o app automaticamente.' -ForegroundColor Yellow
        Write-Host '  Rode o "start.bat" (ou reinicie o Windows) para subir o sistema.'
    }
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Host '  ERRO durante a atualizacao:' -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  [tipo: $($_.Exception.GetType().Name) | linha: $($_.InvocationInfo.ScriptLineNumber)]" -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  Se o codigo ja foi aplicado, rode o "start.bat" para subir o app.'
    exit 1
}
