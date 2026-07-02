# -*- coding: utf-8 -*-
"""
Gera PDFs de teste para um dia de fechamento especifico, SEM as travas de data
(nao exige que hoje seja dia 10/20/30 nem valida a data de ultima comunicacao).

Coleta dados frescos da API e gera os PDFs em: teste_fechamento/dia_XX/
Use apenas para conferir o layout / testar. Nao mexe na pasta faturamento.

Uso:  python gerar_teste.py [dia]      (dia = 10, 20 ou 30; padrao 30)
"""
import sys, glob, json, re, os
from pathlib import Path

dia = 30
if len(sys.argv) > 1:
    try:
        dia = int(sys.argv[1])
    except ValueError:
        pass

import contador
from app import app
from flask import render_template
from xhtml2pdf import pisa

print(f"Coletando dados da API para o teste (pode levar ~1 min)...")
try:
    contador.run_collection()
except Exception as e:
    print("Aviso: a coleta falhou, vou usar o ultimo snapshot disponivel. Detalhe:", e)

snaps = sorted(glob.glob("snapshots/*.json"))
if not snaps:
    print("ERRO: nenhum snapshot disponivel. Verifique a conexao com a API.")
    sys.exit(1)
data = json.loads(open(snaps[-1], encoding="utf-8").read())

cfg = json.loads(open("config.json", encoding="utf-8").read()) if Path("config.json").exists() else {"impressoras": []}
cfg_map = {p["printer_id"]: p for p in cfg.get("impressoras", [])}
san = lambda s: re.sub(r'[\\/:*?"<>|]', "_", str(s)).replace(" ", "_")

out = Path("teste_fechamento") / f"dia_{dia:02d}"
out.mkdir(parents=True, exist_ok=True)

n = 0
with app.app_context():
    for p in data.get("printers", []):
        if (p.get("observation") or "").strip() != str(dia):
            continue
        if not cfg_map.get(p["id"], {}).get("ativo", True):
            continue
        html = render_template("pdf_relatorio.html", printer=p,
                               captured_at=data.get("capturedAt", ""), dia=dia)
        fn = f"{san((p.get('customer') or {}).get('name', 'cliente'))}_{san(p.get('assetNumber', 'sp'))}.pdf"
        with open(out / fn, "wb") as f:
            pisa.CreatePDF(html.encode("utf-8"), dest=f)
        n += 1

print(f"\n{n} PDF(s) de teste gerado(s) em: {out.resolve()}")
if n == 0:
    print(f"(Nenhuma impressora com Observation = {dia} e ativa. Tente outro dia: 10, 20 ou 30.)")
try:
    os.startfile(str(out.resolve()))
except Exception:
    pass
