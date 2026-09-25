import calendar
import json
import logging
import sys
import threading
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
MARCA_CONCLUIDO  = ".concluido"   # gravado na pasta quando o grupo termina sem erro
DIAS_RECUPERACAO = 20             # quantos dias para trás procurar fechamentos perdidos

# Impede duas execuções simultâneas (scheduler, recuperação e botão manual)
_job_lock = threading.Lock()

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


def closing_date(dia: int, year: int, month: int) -> date:
    """Data do fechamento 'dia' no mês informado (dia 30 em fevereiro = último dia do mês)."""
    return date(year, month, min(dia, calendar.monthrange(year, month)[1]))


def closing_date_for_role(dia: int, role: str, today: date) -> date:
    """Data do fechamento a que o role de hoje se refere."""
    if dia == 30 and role == "depois" and today.day == 1:
        # Mês anterior
        ontem = today - timedelta(days=1)
        return closing_date(dia, ontem.year, ontem.month)
    return closing_date(dia, today.year, today.month)


def folder_for_closing(dia: int, closing: date) -> Path:
    """Retorna o Path da pasta de saída do fechamento 'dia' na data 'closing'."""
    return FATURAMENTO / closing.strftime("%Y-%m") / f"fechamento_dia_{dia:02d}"


def is_concluido(out_dir: Path) -> bool:
    return (out_dir / MARCA_CONCLUIDO).exists()


def marcar_concluido(out_dir: Path) -> None:
    (out_dir / MARCA_CONCLUIDO).write_text(datetime.now().isoformat(), encoding="utf-8")


def should_generate_pdf(role: str, out_dir: Path) -> bool:
    """Decide se deve gerar PDF baseado no role e na marca de conclusão da pasta."""
    if role in ("antes", "dia"):
        return True
    # role == "depois": só gera se o fechamento ainda não foi concluído
    # (pasta vazia ou geração anterior interrompida no meio)
    return not is_concluido(out_dir)


def _sanitize(value: str) -> str:
    return value.replace(" ", "_").replace("/", "-").replace("\\", "-")


def pdf_name_for(printer: dict) -> str:
    """Nome do PDF: CLIENTE_PATRIMONIO.pdf (campos nulos na API viram placeholder)."""
    cliente    = (printer.get("customer") or {}).get("name") or "cliente"
    patrimonio = printer.get("assetNumber") or "sem_patrimonio"
    return f"{_sanitize(cliente)}_{_sanitize(patrimonio)}.pdf"


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


def collect_for_date(ref_date: date) -> Optional[dict]:
    """Coleta contadores da API na data de referência, sem salvar snapshot
    (o snapshot mais recente precisa continuar sendo o de contadores atuais)."""
    try:
        from contador import fetch_printers_with_counters, _printer_to_dict
        printers = fetch_printers_with_counters(ref_date=ref_date)
    except Exception as e:
        _log.error("Falha ao coletar dados da API (ref=%s): %s", ref_date, e)
        return None
    return {
        "capturedAt": datetime.now().isoformat(),
        "printers": [_printer_to_dict(p) for p in printers],
    }


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


def _parse_date(raw: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(raw[:19].replace("Z", "")).date()
    except ValueError:
        return None


def get_printer_last_communication_date(printer: dict) -> Optional[date]:
    """Retorna a data completa da última comunicação da impressora, ou None."""
    raw = printer.get("lastCommunication") or ""
    return _parse_date(raw) if raw else None


def get_printer_counter_date(printer: dict) -> Optional[date]:
    """Retorna a data da captura de contador mais recente da impressora, ou None."""
    datas = [_parse_date(c.get("dateOfCapture") or "") for c in printer.get("counters") or []]
    datas = [d for d in datas if d]
    return max(datas) if datas else None


def build_valid_dates(closing: date) -> set[date]:
    """Retorna o conjunto de datas válidas (±1 dia) para o fechamento na data 'closing'."""
    return {closing + timedelta(days=delta) for delta in (-1, 0, 1)}


def generate_pdfs_for_group(
    snapshot_data: dict,
    dia: int,
    out_dir: Path,
    active_ids: set[str],
    flask_app,
    closing: date,
    recuperacao: bool = False,
) -> list[str]:
    """Gera PDFs para as impressoras do grupo 'dia' dentro do snapshot.

    Em modo recuperação os PDFs que já existem na pasta são mantidos. Num snapshot
    histórico (coleta com data de referência) a data validada é a da captura do
    contador, porque lastCommunication é sempre a de hoje.
    """
    from xhtml2pdf import pisa

    gerados = []
    captured_at = snapshot_data.get("capturedAt", "")
    usar_data_contador = snapshot_data.get("historico", False)
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    cfg_map = {p["printer_id"]: p for p in cfg.get("impressoras", [])}
    valid_dates = build_valid_dates(closing)

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
            if usar_data_contador:
                last_comm_date = get_printer_counter_date(printer)
            else:
                last_comm_date = get_printer_last_communication_date(printer)
            if last_comm_date is None or last_comm_date not in valid_dates:
                cliente = (printer.get("customer") or {}).get("name", "?")
                patrimonio = printer.get("assetNumber", "?")
                _log.warning(
                    "Impressora ignorada (comunicacao atrasada): %s pat=%s | ultima comunicacao=%s | esperado=%s",
                    cliente, patrimonio, last_comm_date,
                    ", ".join(d.isoformat() for d in sorted(valid_dates)),
                )
                continue

            pdf_name = pdf_name_for(printer)
            pdf_path = out_dir / pdf_name

            if recuperacao and pdf_path.exists():
                continue

            html = ""
            try:
                html = template.render(printer=printer, captured_at=captured_at, dia=dia)
                with open(pdf_path, "wb") as pdf_file:
                    result = pisa.CreatePDF(html.encode("utf-8"), dest=pdf_file, encoding="utf-8")
                if result.err:
                    raise RuntimeError(f"xhtml2pdf error: {result.err}")
                gerados.append(pdf_name)
                _log.debug("PDF gerado: %s", pdf_name)
            except Exception:
                # Uma impressora com problema não pode interromper as demais
                _log.exception("Erro ao gerar PDF %s (id=%s)", pdf_name, pid)
                if html:
                    html_path = out_dir / pdf_name.replace(".pdf", ".html")
                    html_path.write_text(html, encoding="utf-8")
                    gerados.append(html_path.name)

    return gerados


def auto_fechamento_job(flask_app) -> None:
    """Ponto de entrada do scheduler: detecta dias relevantes e gera PDFs,
    depois recupera fechamentos que ficaram para trás."""
    if not _job_lock.acquire(blocking=False):
        _log.warning("auto_fechamento_job ignorado: já existe um fechamento em execução.")
        return
    try:
        _auto_fechamento(flask_app)
        _recuperar_fechamentos(flask_app)
    except Exception:
        _log.exception("Erro inesperado no auto_fechamento_job")
    finally:
        _job_lock.release()


def recuperar_fechamentos_perdidos(flask_app) -> None:
    """Ponto de entrada da recuperação na subida do app."""
    if not _job_lock.acquire(blocking=False):
        _log.warning("Recuperação ignorada: já existe um fechamento em execução.")
        return
    try:
        _recuperar_fechamentos(flask_app)
    except Exception:
        _log.exception("Erro inesperado na recuperação de fechamentos")
    finally:
        _job_lock.release()


def _auto_fechamento(flask_app) -> None:
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
        closing = closing_date_for_role(dia, role, today)
        out_dir = folder_for_closing(dia, closing)

        if not should_generate_pdf(role, out_dir):
            _log.info("Skip dia=%d role=%s (fechamento já concluído em %s)", dia, role, out_dir)
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            gerados = generate_pdfs_for_group(
                snapshot_data, dia, out_dir, active_ids, flask_app, closing,
                # "depois" só completa o que faltou; não sobrescreve o PDF do dia
                recuperacao=(role == "depois"),
            )
        except Exception:
            _log.exception("Erro ao gerar dia=%d role=%s — fechamento NÃO concluído", dia, role)
            continue
        marcar_concluido(out_dir)
        total_gerados += len(gerados)
        _log.info(
            "dia=%d role=%s | pasta=%s | gerados=%d",
            dia, role, out_dir, len(gerados),
        )

    _log.info("=== auto_fechamento_job concluído | total gerados: %d ===", total_gerados)


# -- Recuperação de fechamentos perdidos ---------------------------------------

def find_missed_fechamentos(today: date) -> list[tuple[int, date]]:
    """Fechamentos dos últimos DIAS_RECUPERACAO dias cuja janela (antes/dia/depois)
    já passou e que não foram concluídos (app fechado, PC desligado ou erro)."""
    missed = []
    mes_atual = today.replace(day=1)
    mes_anterior = (mes_atual - timedelta(days=1)).replace(day=1)
    for mes in (mes_anterior, mes_atual):
        for dia in sorted(VALID_DIAS):
            closing = closing_date(dia, mes.year, mes.month)
            if closing + timedelta(days=1) >= today:
                continue  # janela ainda aberta: o job diário cuida
            if (today - closing).days > DIAS_RECUPERACAO:
                continue
            if not is_concluido(folder_for_closing(dia, closing)):
                missed.append((dia, closing))
    return missed


def _recuperar_fechamentos(flask_app) -> None:
    """Gera os fechamentos perdidos com os contadores do dia seguinte ao
    fechamento (mesma referência do role 'depois'), completando só os PDFs
    que faltam na pasta."""
    missed = find_missed_fechamentos(date.today())
    if not missed:
        return

    _log.info("=== Recuperação de fechamentos perdidos: %s ===",
              ", ".join(f"dia {dia} ({c:%d/%m})" for dia, c in missed))
    active_ids = get_active_printer_ids()

    for dia, closing in missed:
        ref_date = closing + timedelta(days=1)
        out_dir = folder_for_closing(dia, closing)

        snapshot_data = collect_for_date(ref_date)
        if snapshot_data is None:
            _log.error("Recuperação dia=%d (%s) abortada: coleta falhou.", dia, closing)
            continue
        snapshot_data["historico"] = True

        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            gerados = generate_pdfs_for_group(
                snapshot_data, dia, out_dir, active_ids, flask_app, closing,
                recuperacao=True,
            )
        except Exception:
            _log.exception("Erro na recuperação dia=%d (%s) — fechamento NÃO concluído", dia, closing)
            continue
        marcar_concluido(out_dir)
        _log.info(
            "Recuperado dia=%d fechamento=%s contadores_de=%s | pasta=%s | gerados=%d",
            dia, closing, ref_date, out_dir, len(gerados),
        )
