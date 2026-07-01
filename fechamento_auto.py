import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# -- Constantes ----------------------------------------------------------------

BASE_DIR      = Path(__file__).parent
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
CONFIG_FILE   = BASE_DIR / "config.json"
FATURAMENTO   = BASE_DIR / "faturamento"
AUTO_LOG_FILE = BASE_DIR / "fechamento_auto.log"
VALID_DIAS    = frozenset({10, 20, 30})

# -- Logger dedicado -----------------------------------------------------------

_log = logging.getLogger("fechamento_auto")
_log.setLevel(logging.DEBUG)

if not _log.handlers:
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(AUTO_LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    _log.addHandler(fh)

    if sys.stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        _log.addHandler(sh)


# -- Funções -------------------------------------------------------------------

def parse_dia_from_observation(observation: Optional[str]) -> Optional[int]:
    """Retorna 10, 20 ou 30 se observation for exatamente um desses valores."""
    if not observation:
        return None
    stripped = observation.strip()
    try:
        val = int(stripped)
    except ValueError:
        return None
    return val if val in VALID_DIAS else None


def get_relevant_dias_for_today(today: date) -> list[tuple[int, str]]:
    """Retorna lista de (dia_fechamento, role) relevantes para o dia de hoje."""
    d = today.day
    result = []

    mapping = {
        9:  (10, "antes"),
        10: (10, "dia"),
        11: (10, "depois"),
        19: (20, "antes"),
        20: (20, "dia"),
        21: (20, "depois"),
        29: (30, "antes"),
        30: (30, "dia"),
        31: (30, "depois"),
        1:  (30, "depois"),  # dia 1 = depois do fechamento dia 30 do mês anterior
    }

    # Fevereiro: não há dia 30, logo "antes" (dia 29) e "dia" (30) não se aplicam
    if today.month == 2 and d in (29, 30):
        return []

    if d in mapping:
        result.append(mapping[d])

    return result


def resolve_output_folder(dia: int, role: str, today: date) -> Path:
    """Retorna o Path da pasta de saída para um determinado dia/role/data."""
    if dia == 30 and role == "depois" and today.day == 1:
        # Mês anterior
        mes_date = today - timedelta(days=1)
        mes_label = mes_date.strftime("%Y-%m")
    else:
        mes_label = today.strftime("%Y-%m")
    return FATURAMENTO / mes_label / f"fechamento_dia_{dia:02d}"


def should_generate_pdf(role: str, out_dir: Path) -> bool:
    """Decide se deve gerar PDF baseado no role e na existência de PDFs na pasta."""
    if role in ("antes", "dia"):
        return True
    # role == "depois": só gera se não existir nenhum PDF na pasta
    if out_dir.exists():
        return not any(out_dir.glob("*.pdf"))
    return True


def get_active_printer_ids() -> set[str]:
    """Lê config.json e retorna IDs de impressoras ativas (default: True)."""
    if not CONFIG_FILE.exists():
        return set()
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        p["printer_id"]
        for p in cfg.get("impressoras", [])
        if p.get("ativo", True)
    }


def run_collection() -> Optional[Path]:
    """Coleta dados da API e salva snapshot. Retorna Path ou None em caso de falha."""
    try:
        from contador import run_collection as _collect
        return _collect()
    except Exception as e:
        _log.error("Falha ao coletar dados da API: %s", e)
        return None


def load_latest_snapshot_raw() -> Optional[dict]:
    """Carrega o JSON do snapshot mais recente. Retorna None se não houver nenhum."""
    if not SNAPSHOTS_DIR.exists():
        return None
    files = sorted(SNAPSHOTS_DIR.glob("*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception as e:
        _log.error("Falha ao ler snapshot %s: %s", files[0], e)
        return None


def get_printer_last_communication_date(printer: dict) -> Optional[date]:
    """Retorna a data completa da última comunicação da impressora, ou None."""
    raw = printer.get("lastCommunication", "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19].replace("Z", "")).date()
    except ValueError:
        return None


def build_valid_dates(dia: int, ref_date: date) -> set[date]:
    """Retorna o conjunto de datas válidas (ano+mês completo) para o fechamento de 'dia'."""
    valid = set()
    for delta in (-1, 0, 1):
        try:
            valid.add(date(ref_date.year, ref_date.month, dia + delta))
        except ValueError:
            pass  # dia+delta inválido para o mês (ex: 31+1 em mês com 30 dias)
    return valid


def generate_pdfs_for_group(
    snapshot_data: dict,
    dia: int,
    out_dir: Path,
    active_ids: set[str],
    flask_app,
    today: date,
) -> list[str]:
    """Gera PDFs para as impressoras do grupo 'dia' dentro do snapshot."""
    from xhtml2pdf import pisa

    gerados = []
    captured_at = snapshot_data.get("capturedAt", "")
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    cfg_map = {p["printer_id"]: p for p in cfg.get("impressoras", [])}
    valid_dates = build_valid_dates(dia, today)

    with flask_app.app_context():
        template = flask_app.jinja_env.get_template("pdf_relatorio.html")

        for printer in snapshot_data.get("printers", []):
            pid = printer.get("id", "")

            # Verifica se a impressora está ativa
            if pid in cfg_map:
                if not cfg_map[pid].get("ativo", True):
                    continue
            # Se não está no config, inclui por default

            # Verifica dia de fechamento pelo campo observation
            obs_dia = parse_dia_from_observation(printer.get("observation"))
            if obs_dia != dia:
                continue

            # Verifica se a última comunicação da impressora está dentro de ±1 dia do fechamento
            last_comm_date = get_printer_last_communication_date(printer)
            if last_comm_date is None or last_comm_date not in valid_dates:
                cliente = (printer.get("customer") or {}).get("name", "?")
                patrimonio = printer.get("assetNumber", "?")
                _log.warning(
                    "Impressora ignorada (comunicacao atrasada): %s pat=%s | ultima comunicacao=%s | esperado=%s",
                    cliente, patrimonio, last_comm_date, valid_dates,
                )
                continue

            cliente    = (printer.get("customer") or {}).get("name", "cliente").replace(" ", "_").replace("/", "-").replace("\\", "-")
            patrimonio = printer.get("assetNumber", "sem_patrimonio").replace(" ", "_").replace("/", "-").replace("\\", "-")
            pdf_name   = f"{cliente}_{patrimonio}.pdf"
            pdf_path = out_dir / pdf_name

            html = template.render(printer=printer, captured_at=captured_at, dia=dia)

            try:
                with open(pdf_path, "wb") as pdf_file:
                    result = pisa.CreatePDF(html.encode("utf-8"), dest=pdf_file, encoding="utf-8")
                if result.err:
                    raise RuntimeError(f"xhtml2pdf error: {result.err}")
                gerados.append(pdf_name)
                _log.debug("PDF gerado: %s", pdf_name)
            except Exception as e:
                _log.error("Erro ao gerar PDF %s: %s", pdf_name, e)
                html_path = out_dir / pdf_name.replace(".pdf", ".html")
                html_path.write_text(html, encoding="utf-8")
                gerados.append(html_path.name)

    return gerados


def auto_fechamento_job(flask_app) -> None:
    """Ponto de entrada do scheduler: detecta dias relevantes e gera PDFs."""
    _log.info("=== auto_fechamento_job iniciado ===")
    today = date.today()
    relevant = get_relevant_dias_for_today(today)

    if not relevant:
        _log.info("Hoje (%s) não é dia de fechamento. Nada a fazer.", today)
        return

    _log.info("Dias relevantes para %s: %s", today, relevant)

    snapshot_path = run_collection()
    if snapshot_path is None:
        _log.error("Coleta falhou — abortando auto-fechamento.")
        return

    snapshot_data = load_latest_snapshot_raw()
    if snapshot_data is None:
        _log.error("Nenhum snapshot disponível — abortando auto-fechamento.")
        return

    active_ids = get_active_printer_ids()
    total_gerados = 0

    for dia, role in relevant:
        out_dir = resolve_output_folder(dia, role, today)

        if not should_generate_pdf(role, out_dir):
            _log.info("Skip dia=%d role=%s (PDFs já existem em %s)", dia, role, out_dir)
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        gerados = generate_pdfs_for_group(snapshot_data, dia, out_dir, active_ids, flask_app, today)
        total_gerados += len(gerados)
        _log.info(
            "dia=%d role=%s | pasta=%s | gerados=%d",
            dia, role, out_dir, len(gerados),
        )

    _log.info("=== auto_fechamento_job concluído | total gerados: %d ===", total_gerados)
