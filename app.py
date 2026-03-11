import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

BASE_DIR      = Path(__file__).parent
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
CONFIG_FILE   = BASE_DIR / "config.json"
FATURAMENTO   = BASE_DIR / "faturamento"

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
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            return jsonify({"ok": False, "erro": result.stderr}), 500
        return jsonify({"ok": True, "snapshots": list_snapshots()})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "erro": "Timeout ao coletar dados."}), 500

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
        if cfg.get("dia_fechamento") == dia and cfg.get("ativo", True):
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
        if cfg.get("dia_fechamento") != dia or not cfg.get("ativo", True):
            continue

        html = render_template(
            "pdf_relatorio.html",
            printer=p,
            captured_at=data.get("capturedAt", ""),
            dia=dia,
        )

        cliente  = (p.get("customer") or {}).get("name", "cliente").replace(" ", "_")
        serial   = p.get("serialNumber", "sem_serial")
        pdf_name = f"{cliente}_{serial}.pdf"
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


if __name__ == "__main__":
    app.run(debug=False, port=5000)