import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

app = Flask(__name__)

BASE_DIR      = Path(__file__).parent
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
CONFIG_FILE   = BASE_DIR / "config.json"
FATURAMENTO   = BASE_DIR / "faturamento"

# ── Tradução / formatação dos campos crus da API ───────────────────────────────
import re as _re

CONEXAO_LABELS = {
    "network": "Rede", "usb": "USB", "local": "Local", "unknown": "—",
}
COR_IMPRESSORA_LABELS = {
    "monochrome": "Monocromática", "colorful": "Colorida",
}
STATUS_LABELS = {
    "online": "Online", "offline": "Offline", "inDealer": "Em estoque",
}
COR_SUPRIMENTO_LABELS = {
    "black": "Preto", "cyan": "Ciano", "magenta": "Magenta",
    "yellow": "Amarelo", "noApply": "—", "": "—", None: "—",
}

# Frases traduzidas em ordem (mais específicas primeiro). Códigos de modelo
# (HP CE255X etc.) são preservados por não corresponderem a nenhuma frase.
_SUP_PHRASES = [
    ("Black Imaging Unit (OPC Unit)", "Unidade de Imagem Preta (OPC)"),
    ("Black Toner Cartridge", "Cartucho de Toner Preto"),
    ("Black Ink Bottle",   "Garrafa de Tinta Preta"),
    ("Cyan Ink Bottle",    "Garrafa de Tinta Ciano"),
    ("Magenta Ink Bottle", "Garrafa de Tinta Magenta"),
    ("Yellow Ink Bottle",  "Garrafa de Tinta Amarela"),
    ("Black Cartridge",    "Cartucho Preto"),
    ("Cyan Cartridge",     "Cartucho Ciano"),
    ("Magenta Cartridge",  "Cartucho Magenta"),
    ("Yellow Cartridge",   "Cartucho Amarelo"),
    ("Tray 1 Retard Roller Life", "Rolo de Retenção da Bandeja 1"),
    ("Tray 2 Retard Roller Life", "Rolo de Retenção da Bandeja 2"),
    ("Tray 1 Retard Roller", "Rolo de Retenção da Bandeja 1"),
    ("Tray 2 Retard Roller", "Rolo de Retenção da Bandeja 2"),
    ("MP Retard Roller",     "Rolo de Retenção Multiuso"),
    ("Tray 1 Roller", "Rolo da Bandeja 1"),
    ("Tray 2 Roller", "Rolo da Bandeja 2"),
    ("Transfer Roller", "Rolo de Transferência"),
    ("ADF Roller", "Rolo do ADF"),
    ("MP Roller", "Rolo Multiuso"),
    ("T2 Roller", "Rolo T2"),
    ("MP Tray", "Bandeja Multiuso"),
    ("Imaging Unit", "Unidade de Imagem"),
    ("Toner Cartridge", "Cartucho de Toner"),
    ("Ink Bottle", "Garrafa de Tinta"),
    ("Cartridge", "Cartucho"),
    ("Drum Unit", "Cilindro"),
    ("Fuser", "Fusor"),
    ("Tray 1", "Bandeja 1"),
    ("Tray 2", "Bandeja 2"),
    ("Roller", "Rolo"),
    ("Black", "Preto"),
    ("Cyan", "Ciano"),
    ("Magenta", "Magenta"),
    ("Yellow", "Amarelo"),
    (" Life", ""),
]

def _traduzir_suprimento(desc: str) -> str:
    if not desc:
        return "—"
    t = str(desc).strip()
    for en, pt in _SUP_PHRASES:
        t = _re.sub(_re.escape(en), pt, t, flags=_re.IGNORECASE)
    return _re.sub(r"\s+", " ", t).strip()

@app.template_filter("conexao")
def _f_conexao(v):
    return CONEXAO_LABELS.get(v, v or "—")

@app.template_filter("cor_impressora")
def _f_cor_impressora(v):
    return COR_IMPRESSORA_LABELS.get(v, v or "—")

@app.template_filter("status_impressora")
def _f_status(v):
    return STATUS_LABELS.get(v, v or "—")

@app.template_filter("cor_suprimento")
def _f_cor_suprimento(v):
    return COR_SUPRIMENTO_LABELS.get(v, v or "—")

@app.template_filter("suprimento")
def _f_suprimento(v):
    return _traduzir_suprimento(v)

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"impressoras": []}

def save_config(data: dict):
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def list_snapshots() -> list[dict]:
    if not SNAPSHOTS_DIR.exists():
        return []
    snapshots = []
    for f in sorted(SNAPSHOTS_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            raw = meta.get("capturedAt", "")
            snapshots.append({
                "filename": f.name,
                "captured_at": raw,  # ISO kept for slicing in templates
                "total": meta.get("totalPrinters", 0),
            })
        except Exception:
            pass
    return snapshots

def load_snapshot(filename: str) -> dict:
    path = SNAPSHOTS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))

def get_config_map() -> dict:
    """Retorna dict printer_id -> config"""
    cfg = load_config()
    return {p["printer_id"]: p for p in cfg.get("impressoras", [])}

# ── Scheduler ─────────────────────────────────────────────────────────────────

def _start_scheduler():
    from fechamento_auto import auto_fechamento_job
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        func=lambda: auto_fechamento_job(app),
        trigger=CronTrigger(hour=12, minute=0),
        id="fechamento_auto",
        name="Fechamento Automatico",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler

# Evita duplo start com debug reloader do Werkzeug
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _scheduler = _start_scheduler()

# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("snapshots.html", snapshots=list_snapshots())

@app.route("/configuracoes")
def configuracoes():
    snapshots = list_snapshots()
    printers = []
    if snapshots:
        data = load_snapshot(snapshots[0]["filename"])
        cfg_map = get_config_map()
        for p in data.get("printers", []):
            pid = p["id"]
            cfg = cfg_map.get(pid, {})
            printers.append({
                "printer_id":     pid,
                "serial":         p.get("serialNumber", "—"),
                "cliente":        (p.get("customer") or {}).get("name", "—"),
                "modelo":         f"{p.get('manufacturer','')} {p.get('model','')}".strip(),
                "patrimonio":     p.get("assetNumber", "—"),
                "observation":    p.get("observation", ""),
                "dia_fechamento": cfg.get("dia_fechamento", ""),
                "ativo":          cfg.get("ativo", True),
            })
    return render_template("configuracoes.html", printers=printers)

@app.route("/fechamento")
def fechamento():
    snapshots = list_snapshots()
    return render_template("fechamento.html", snapshots=snapshots)

# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/coletar", methods=["POST"])
def api_coletar():
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "contador.py")],
            capture_output=True, text=True, encoding="utf-8", timeout=300
        )
        if result.returncode != 0:
            return jsonify({"ok": False, "erro": result.stderr}), 500
        return jsonify({"ok": True, "snapshots": list_snapshots()})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "erro": "Timeout ao coletar dados."}), 500

@app.route("/api/fechamento/executar/<int:dia>", methods=["POST"])
def api_fechamento_executar(dia):
    """Coleta API + gera PDFs para o dia informado (10, 20 ou 30) baseado no campo observation."""
    if dia not in (10, 20, 30):
        return jsonify({"ok": False, "erro": "Dia inválido. Use 10, 20 ou 30."}), 400

    app.logger.info("[fechamento] Iniciando fechamento dia=%d", dia)

    # 1. Coleta
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "contador.py")],
            capture_output=True, text=True, encoding="utf-8", timeout=300
        )
        if result.returncode != 0:
            return jsonify({"ok": False, "erro": f"Falha na coleta: {result.stderr}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "erro": "Timeout ao coletar dados."}), 500

    # 2. Carrega snapshot recém-gerado
    snapshots = list_snapshots()
    if not snapshots:
        return jsonify({"ok": False, "erro": "Nenhum snapshot disponível após coleta."}), 500

    data      = load_snapshot(snapshots[0]["filename"])
    captured  = data.get("capturedAt", "")[:10]
    dt        = datetime.fromisoformat(captured).date() if captured else datetime.now().date()
    mes_label = dt.strftime("%Y-%m")
    cfg_map   = get_config_map()

    # Datas válidas para o fechamento: ano+mês completo ± 1 dia do fechamento
    from datetime import date as _date
    valid_dates = set()
    for delta in (-1, 0, 1):
        try:
            valid_dates.add(_date(dt.year, dt.month, dia + delta))
        except ValueError:
            pass
    app.logger.info("[fechamento] datas aceitas=%s", valid_dates)

    out_dir = FATURAMENTO / mes_label / f"fechamento_dia_{dia:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    app.logger.info("[fechamento] Snapshot: %s | total impressoras: %d", snapshots[0]["filename"], len(data.get("printers", [])))

    # 3. Gera PDFs filtrando por observation e lastCommunication
    gerados = []
    ignorados = []
    for p in data.get("printers", []):
        cfg      = cfg_map.get(p["id"], {})
        obs      = (p.get("observation") or "").strip()
        cliente  = (p.get("customer") or {}).get("name", "?")
        pat      = p.get("assetNumber", "?")

        if obs != str(dia):
            continue

        if not cfg.get("ativo", True):
            app.logger.debug("[fechamento] SKIP (inativa): %s pat=%s", cliente, pat)
            continue

        # Verifica lastCommunication dentro de ±1 dia do fechamento (data completa)
        last_comm_raw = p.get("lastCommunication", "")
        try:
            last_comm_date = datetime.fromisoformat(last_comm_raw[:19].replace("Z", "")).date() if last_comm_raw else None
        except ValueError:
            last_comm_date = None

        app.logger.info("[fechamento] %s pat=%s | lastCommunication=%s | aceito=%s",
            cliente, pat, last_comm_raw[:10] if last_comm_raw else "N/A",
            last_comm_date in valid_dates if last_comm_date else False)

        if last_comm_date is None or last_comm_date not in valid_dates:
            app.logger.warning("[fechamento] IGNORADO (comunicacao fora do intervalo): %s pat=%s | lastComm=%s | esperado=%s",
                cliente, pat, last_comm_date, valid_dates)
            ignorados.append(f"{cliente}_pat{pat}")
            continue

        html = render_template(
            "pdf_relatorio.html",
            printer=p,
            captured_at=data.get("capturedAt", ""),
            dia=dia,
        )
        cliente_fn = cliente.replace(" ", "_")
        pat_fn     = pat.replace(" ", "_")
        pdf_name   = f"{cliente_fn}_{pat_fn}.pdf"
        pdf_path   = out_dir / pdf_name

        try:
            from xhtml2pdf import pisa
            with open(pdf_path, "wb") as pdf_file:
                r = pisa.CreatePDF(html.encode("utf-8"), dest=pdf_file, encoding="utf-8")
            if r.err:
                raise RuntimeError(f"xhtml2pdf error: {r.err}")
            gerados.append(pdf_name)
            app.logger.info("[fechamento] PDF gerado: %s", pdf_name)
        except Exception as e:
            app.logger.error("[fechamento] Erro ao gerar PDF %s: %s", pdf_name, e)
            html_path = out_dir / pdf_name.replace(".pdf", ".html")
            html_path.write_text(html, encoding="utf-8")
            gerados.append(html_path.name)

    app.logger.info("[fechamento] Concluido dia=%d | gerados=%d | ignorados=%d | pasta=%s",
        dia, len(gerados), len(ignorados), out_dir)

    return jsonify({"ok": True, "gerados": gerados, "ignorados": ignorados, "pasta": str(out_dir), "total": len(gerados)})

@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.get_json()
    save_config(data)
    return jsonify({"ok": True})

@app.route("/api/snapshots")
def api_snapshots():
    return jsonify(list_snapshots())

@app.route("/api/fechamento/preview", methods=["POST"])
def api_fechamento_preview():
    body = request.get_json()
    filename = body.get("snapshot")
    dia = int(body.get("dia", 0))

    data = load_snapshot(filename)
    cfg_map = get_config_map()

    impressoras = []
    for p in data.get("printers", []):
        cfg = cfg_map.get(p["id"], {})
        obs = (p.get("observation") or "").strip()
        if obs != str(dia) or not cfg.get("ativo", True):
            continue
        bw    = next((c["totalCount"] for c in p.get("counters", []) if c["type"] == "blackAndWhite"), 0)
        color = next((c["totalCount"] for c in p.get("counters", []) if c["type"] == "color"), 0)
        impressoras.append({
            "serial":     p.get("serialNumber", "—"),
            "cliente":    (p.get("customer") or {}).get("name", "—"),
            "modelo":     f"{p.get('manufacturer','')} {p.get('model','')}".strip(),
            "patrimonio": p.get("assetNumber", "—"),
            "total_pb":   bw,
            "total_cor":  color,
            "total":      bw + color,
        })

    return jsonify({"ok": True, "impressoras": impressoras, "total": len(impressoras)})

@app.route("/api/fechamento/gerar", methods=["POST"])
def api_fechamento_gerar():
    body     = request.get_json()
    filename = body.get("snapshot")
    dia      = int(body.get("dia", 0))

    data       = load_snapshot(filename)
    captured   = data.get("capturedAt", "")[:10]
    dt         = datetime.fromisoformat(captured) if captured else datetime.now()
    mes_label  = dt.strftime("%Y-%m")
    cfg_map    = get_config_map()

    out_dir = FATURAMENTO / mes_label / f"fechamento_dia_{dia:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    gerados = []
    for p in data.get("printers", []):
        cfg = cfg_map.get(p["id"], {})
        obs = (p.get("observation") or "").strip()
        if obs != str(dia) or not cfg.get("ativo", True):
            continue

        html = render_template(
            "pdf_relatorio.html",
            printer=p,
            captured_at=data.get("capturedAt", ""),
            dia=dia,
        )

        cliente    = (p.get("customer") or {}).get("name", "cliente").replace(" ", "_")
        patrimonio = p.get("assetNumber", "sem_patrimonio").replace(" ", "_")
        pdf_name   = f"{cliente}_{patrimonio}.pdf"
        pdf_path = out_dir / pdf_name

        # Gera PDF via xhtml2pdf (puro Python, sem dependencias externas)
        try:
            from xhtml2pdf import pisa
            with open(pdf_path, "wb") as pdf_file:
                result = pisa.CreatePDF(html.encode("utf-8"), dest=pdf_file, encoding="utf-8")
            if result.err:
                raise RuntimeError(f"xhtml2pdf error: {result.err}")
            gerados.append(pdf_name)
        except Exception as e:
            app.logger.error("Erro ao gerar PDF %s: %s", pdf_name, e)
            # Fallback: salva HTML
            html_path = out_dir / pdf_name.replace(".pdf", ".html")
            html_path.write_text(html, encoding="utf-8")
            gerados.append(html_path.name)

    return jsonify({"ok": True, "gerados": gerados, "pasta": str(out_dir)})


@app.route("/api/fechamento/auto/executar", methods=["POST"])
def api_auto_fechamento_executar():
    """Disparo manual do auto-fechamento (roda em background thread)."""
    from fechamento_auto import auto_fechamento_job
    import threading
    threading.Thread(target=auto_fechamento_job, args=(app,), daemon=True).start()
    return jsonify({"ok": True, "mensagem": "Auto-fechamento iniciado."})


@app.route("/api/fechamento/auto/log")
def api_auto_fechamento_log():
    """Retorna as últimas 100 linhas do log de auto-fechamento."""
    log_path = BASE_DIR / "fechamento_auto.log"
    if not log_path.exists():
        return jsonify({"ok": True, "linhas": []})
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return jsonify({"ok": True, "linhas": lines[-100:]})


@app.route("/api/config/sincronizar", methods=["POST"])
def api_config_sincronizar():
    """Sincroniza config.json com as impressoras do snapshot mais recente, preservando configurações existentes."""
    snapshots = list_snapshots()
    if not snapshots:
        return jsonify({"ok": False, "erro": "Nenhum snapshot disponível. Faça uma coleta primeiro."})

    data = load_snapshot(snapshots[0]["filename"])
    cfg_map = get_config_map()

    impressoras = []
    for p in data.get("printers", []):
        pid = p["id"]
        existing = cfg_map.get(pid, {})
        impressoras.append({
            "printer_id":     pid,
            "serial":         p.get("serialNumber", ""),
            "cliente":        (p.get("customer") or {}).get("name", ""),
            "modelo":         f"{p.get('manufacturer','')} {p.get('model','')}".strip(),
            "patrimonio":     p.get("assetNumber", ""),
            "dia_fechamento": existing.get("dia_fechamento", None),
            "ativo":          existing.get("ativo", True),
        })

    save_config({"impressoras": impressoras})
    return jsonify({"ok": True, "total": len(impressoras)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)