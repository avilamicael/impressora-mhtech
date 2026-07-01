# ============================================================================
#  MH Tech - Publicar nova versao (uso do desenvolvedor)
#  Atualiza o version.txt, faz commit, cria a tag e envia para o GitHub.
#  O cliente entao recebe a atualizacao rodando "atualizar.bat".
#
#  Uso:  publicar.bat 1.1.0
# ============================================================================

param([Parameter(Mandatory = $true)][string]$Versao)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

$v = $Versao.TrimStart('v', 'V')
if ($v -notmatch '^\d+\.\d+\.\d+$') {
    Write-Host "Versao invalida: '$Versao'. Use o formato X.Y.Z (ex: 1.1.0)." -ForegroundColor Red
    exit 1
}
$tag = "v$v"

# tag ja existe?
git rev-parse -q --verify "refs/tags/$tag" > $null 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "A tag $tag ja existe. Escolha um numero de versao maior." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  Publicando versao $tag ..." -ForegroundColor Cyan

# 1) grava version.txt
Set-Content -Path (Join-Path $Root 'version.txt') -Value $v -NoNewline -Encoding ASCII

# 2) commit de tudo que estiver pendente
git add -A
git commit -m "release $tag" 2>$null | Out-Null

# 3) tag + push
git tag $tag
git push
if ($LASTEXITCODE -ne 0) { Write-Host "Falha no 'git push'." -ForegroundColor Red; exit 1 }
git push origin $tag
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao enviar a tag." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  Versao $tag publicada com sucesso!" -ForegroundColor Green
Write-Host "  Na maquina do cliente, rode 'atualizar.bat' para aplicar."
Write-Host ""
Write-Host "  (Opcional) Adicionar notas da versao no GitHub:"
Write-Host "  https://github.com/avilamicael/impressora-mhtech/releases/new?tag=$tag"
Write-Host ""
