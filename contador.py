import requests
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional
from datetime import date, datetime
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# -- Encoding fix (Windows cp1252 -> UTF-8) ------------------------------------
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# -- Fix SSL renegotiation (Windows / schannel) --------------------------------
# A API Printwayy solicita renegociação TLS após o handshake inicial.
# O requests/urllib3 bloqueia isso por padrão - este adapter libera.

class _RenegotiationAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.options |= 0x00040000  # OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

def _build_session() -> requests.Session:
    session = requests.Session()
    adapter = _RenegotiationAdapter()
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session

# -- Logging -------------------------------------------------------------------

LOG_FILE = Path("printwayy.log")

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("printwayy")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Arquivo: DEBUG e acima
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Terminal: INFO e acima (sem poluir com debug de requisições)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

log = setup_logger()

# -- Configuração --------------------------------------------------------------

BASE_URL = "https://api.printwayy.com/devices/v1"
API_KEY  = "35F3094C-C37B-4969-94EE-6BEDC962BFB7"

_SESSION = _build_session()
_SESSION.headers.update({
    "accept": "application/json",
    "printwayy-key": API_KEY,
})

# -- Modelos -------------------------------------------------------------------

@dataclass
class Counter:
    type: str           # blackAndWhite | color | scan
    date_of_capture: str
    total_count: int

    TYPE_LABELS = {
        "blackAndWhite": "P&B",
        "color":         "Colorido",
        "scan":          "Scanner",
    }

    @classmethod
    def from_dict(cls, d: dict) -> "Counter":
        return cls(
            type=d.get("type", ""),
            date_of_capture=d.get("dateOfCapture", ""),
            total_count=d.get("totalCount", 0),
        )

    @property
    def label(self) -> str:
        return self.TYPE_LABELS.get(self.type, self.type)


@dataclass
class Address:
    name: str
    zip_code: str
    state: str
    city: str
    neighborhood: str
    street: str
    number: Optional[int]
    complement: Optional[str]

    @classmethod
    def from_dict(cls, d: dict) -> "Address":
        return cls(
            name=d.get("name", ""),
            zip_code=d.get("zipCode", ""),
            state=d.get("state", ""),
            city=d.get("city", ""),
            neighborhood=d.get("neighborhood", ""),
            street=d.get("street", ""),
            number=d.get("number"),
            complement=d.get("complement"),
        )

    def __str__(self) -> str:
        street = self.street or ""
        parts = [f"{street}, {self.number}" if self.number else street]
        if self.complement:
            parts.append(self.complement)
        city_part = f"{self.neighborhood or ''} - {self.city or ''}/{self.state or ''}".strip(" -/")
        if city_part:
            parts.append(city_part)
        if self.zip_code:
            parts.append(f"CEP: {self.zip_code}")
        return " | ".join(p for p in parts if p)


@dataclass
class Location:
    address: Optional[Address]
    department: Optional[str]

    @classmethod
    def from_dict(cls, d: dict) -> "Location":
        addr_data = d.get("address")
        return cls(
            address=Address.from_dict(addr_data) if addr_data else None,
            department=d.get("department"),
        )


@dataclass
class Printer:
    id: str
    type: str
    serial_number: str
    asset_number: str
    owner: str
    color: str
    status: str
    last_communication: str
    contract_name: str
    installation_point: str
    is_backup: bool
    observation: Optional[str]
    ip_address: str
    mac_address: str
    model: str
    manufacturer: str
    firmware_version: str
    customer_id: str
    customer_name: str
    location: Optional[Location]
    counters: list[Counter] = field(default_factory=list)
    supplies: list["Supply"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Printer":
        loc_data = d.get("location") or None
        cust = d.get("customer") or {}
        return cls(
            id=d.get("id", ""),
            type=d.get("type", ""),
            serial_number=d.get("serialNumber", ""),
            asset_number=d.get("assetNumber", ""),
            owner=d.get("owner", ""),
            color=d.get("color", ""),
            status=d.get("status", ""),
            last_communication=d.get("lastCommunication", ""),
            contract_name=d.get("contractName", ""),
            installation_point=d.get("installationPoint", ""),
            is_backup=d.get("isBackup", False),
            observation=d.get("observation"),
            ip_address=d.get("ipAddress", ""),
            mac_address=d.get("macAddress", ""),
            model=d.get("model", ""),
            manufacturer=d.get("manufacturer", ""),
            firmware_version=d.get("firmwareVersion", ""),
            customer_id=cust.get("id", ""),
            customer_name=cust.get("name", ""),
            location=Location.from_dict(loc_data) if loc_data else None,
        )



@dataclass
class Supply:
    id: str
    description: str
    date_of_last_data: str
    type: str
    color: str
    level_percentage: float
    level_description: str
    serial_number: Optional[str]

    COLOR_LABELS = {
        "black":   "Preto",
        "cyan":    "Ciano",
        "magenta": "Magenta",
        "yellow":  "Amarelo",
        "noApply": "-",
    }

    @classmethod
    def from_dict(cls, d: dict) -> "Supply":
        level = d.get("level") or {}
        return cls(
            id=d.get("id", ""),
            description=d.get("description", ""),
            date_of_last_data=d.get("dateOfTheLastReceivedData", ""),
            type=d.get("type", ""),
            color=d.get("color", "noApply"),
            level_percentage=level.get("percentageValue", 0),
            level_description=level.get("description", ""),
            serial_number=d.get("serialNumber"),
        )

    @property
    def color_label(self) -> str:
        return self.COLOR_LABELS.get(self.color, self.color)


# -- API -----------------------------------------------------------------------

def get_printers(
    serial_number: Optional[str] = None,
    model_name: Optional[str] = None,
) -> list[Printer]:
    """Busca todas as impressoras paginando automaticamente (limite da API: 100 por pagina)."""
    all_printers: list[Printer] = []
    skip = 0
    page_size = 100

    while True:
        params: dict = {"top": page_size, "skip": skip}
        if serial_number:
            params["serial-number"] = serial_number
        if model_name:
            params["model-name"] = model_name

        log.debug("GET /printers | skip=%d", skip)
        response = _SESSION.get(f"{BASE_URL}/printers", params=params, timeout=15)
        log.debug("GET /printers | status=%d", response.status_code)
        response.raise_for_status()

        payload = response.json()
        total = payload.get("count", 0)
        page  = [Printer.from_dict(item) for item in payload.get("data", [])]
        all_printers.extend(page)

        log.info("Pagina %d: %d impressoras (total: %d)", skip // page_size + 1, len(page), total)

        skip += page_size
        if skip >= total or len(page) == 0:
            break

    log.info("Total de impressoras recebidas: %d", len(all_printers))
    return all_printers


def get_counters(printer_id: str, ref_date: Optional[date] = None) -> list[Counter]:
    params: dict = {}
    if ref_date:
        params["date"] = ref_date.strftime("%Y-%m-%d")

    log.debug("GET /printers/%s/counters | params=%s", printer_id, params)
    response = _SESSION.get(
        f"{BASE_URL}/printers/{printer_id}/counters",
        params=params,
        timeout=15,
    )
    log.debug("GET /printers/%s/counters | status=%d", printer_id, response.status_code)
    response.raise_for_status()

    counters = [Counter.from_dict(c) for c in response.json()]
    log.debug("Contadores recebidos para %s: %d", printer_id, len(counters))
    return counters



def get_supplies(printer_id: str) -> list[Supply]:
    params = {"printer.id[eq]": printer_id, "top": 100}

    log.debug("GET /supplies | printer_id=%s", printer_id)
    response = _SESSION.get(f"{BASE_URL}/supplies", params=params, timeout=15)
    log.debug("GET /supplies | status=%d", response.status_code)
    response.raise_for_status()

    supplies = [Supply.from_dict(s) for s in response.json().get("data", [])]
    log.debug("Suprimentos recebidos para %s: %d", printer_id, len(supplies))
    return supplies


def fetch_printers_with_counters(
    serial_number: Optional[str] = None,
    model_name: Optional[str] = None,
    ref_date: Optional[date] = None,
) -> list[Printer]:
    """
    Busca todas as impressoras (com paginacao automatica) e popula contadores e suprimentos.

    Args:
        serial_number: Filtro por numero serial.
        model_name:    Filtro por nome do modelo.
        ref_date:      Data de referencia dos contadores. None = contadores atuais.
    """
    log.info("Iniciando busca de impressoras...")
    printers = get_printers(serial_number=serial_number, model_name=model_name)

    for printer in printers:
        try:
            printer.counters = get_counters(printer.id, ref_date)
        except requests.HTTPError as e:
            log.warning(
                "Falha ao buscar contadores | serial=%s id=%s | %s",
                printer.serial_number, printer.id, e,
            )
        try:
            printer.supplies = get_supplies(printer.id)
        except requests.HTTPError as e:
            log.warning(
                "Falha ao buscar suprimentos | serial=%s id=%s | %s",
                printer.serial_number, printer.id, e,
            )

    log.info("Busca concluída. %d impressora(s) processada(s).", len(printers))
    return printers



# -- Snapshots JSON ------------------------------------------------------------

SNAPSHOTS_DIR     = Path("snapshots")
SNAPSHOT_RETENTION_DAYS = 30


def _printer_to_dict(printer: Printer) -> dict:
    """Serializa uma Printer para dict puro (JSON-safe)."""
    loc = printer.location
    return {
        "id":                printer.id,
        "type":              printer.type,
        "serialNumber":      printer.serial_number,
        "assetNumber":       printer.asset_number,
        "owner":             printer.owner,
        "color":             printer.color,
        "status":            printer.status,
        "lastCommunication": printer.last_communication,
        "contractName":      printer.contract_name,
        "installationPoint": printer.installation_point,
        "isBackup":          printer.is_backup,
        "observation":       printer.observation,
        "ipAddress":         printer.ip_address,
        "macAddress":        printer.mac_address,
        "model":             printer.model,
        "manufacturer":      printer.manufacturer,
        "firmwareVersion":   printer.firmware_version,
        "customer": {
            "id":   printer.customer_id,
            "name": printer.customer_name,
        },
        "location": {
            "department": loc.department if loc else None,
            "address": {
                "name":         loc.address.name         if loc and loc.address else None,
                "zipCode":      loc.address.zip_code     if loc and loc.address else None,
                "state":        loc.address.state        if loc and loc.address else None,
                "city":         loc.address.city         if loc and loc.address else None,
                "neighborhood": loc.address.neighborhood if loc and loc.address else None,
                "street":       loc.address.street       if loc and loc.address else None,
                "number":       loc.address.number       if loc and loc.address else None,
                "complement":   loc.address.complement   if loc and loc.address else None,
            } if loc and loc.address else None,
        } if loc else None,
        "counters": [
            {
                "type":          c.type,
                "dateOfCapture": c.date_of_capture,
                "totalCount":    c.total_count,
            }
            for c in printer.counters
        ],
        "supplies": [
            {
                "id":                    s.id,
                "description":           s.description,
                "dateOfTheLastReceivedData": s.date_of_last_data,
                "type":                  s.type,
                "color":                 s.color,
                "serialNumber":          s.serial_number,
                "level": {
                    "percentageValue":   s.level_percentage,
                    "description":       s.level_description,
                },
            }
            for s in printer.supplies
        ],
    }


def save_snapshot(printers: list[Printer]) -> Path:
    """
    Salva um snapshot JSON com todas as impressoras e seus contadores.
    Nome do arquivo: snapshots/YYYY-MM-DD_HH-MM.json
    Retorna o caminho do arquivo criado.
    """
    SNAPSHOTS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    path = SNAPSHOTS_DIR / f"{timestamp}.json"

    payload = {
        "capturedAt": datetime.now().isoformat(),
        "totalPrinters": len(printers),
        "printers": [_printer_to_dict(p) for p in printers],
    }

    with open(path, "w", encoding="utf-8") as f:
        import json
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info("Snapshot salvo: %s (%d impressoras)", path, len(printers))
    return path


def purge_old_snapshots(retention_days: int = SNAPSHOT_RETENTION_DAYS) -> None:
    """Remove snapshots mais antigos que retention_days dias."""
    if not SNAPSHOTS_DIR.exists():
        return

    cutoff = datetime.now().timestamp() - retention_days * 86400
    removed = 0
    for f in SNAPSHOTS_DIR.glob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
            log.debug("Snapshot removido (>%dd): %s", retention_days, f.name)

    if removed:
        log.info("Limpeza de snapshots: %d arquivo(s) removido(s).", removed)


def load_snapshot(path: str | Path) -> list[Printer]:
    """
    Carrega um snapshot JSON e retorna a lista de Printer.
    Útil para gerar documentos/HTML sem precisar chamar a API novamente.

    Exemplo:
        printers = load_snapshot("snapshots/2026-03-09_14-58.json")
    """
    import json
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)

    printers = []
    for p in payload["printers"]:
        printer = Printer.from_dict(p)
        printer.supplies = [Supply.from_dict(s) for s in p.get("supplies", [])]
        printers.append(printer)
    log.info("Snapshot carregado: %s (%d impressoras)", path, len(printers))
    return printers


def list_snapshots() -> list[Path]:
    """Lista todos os snapshots disponíveis, do mais recente ao mais antigo."""
    if not SNAPSHOTS_DIR.exists():
        return []
    return sorted(SNAPSHOTS_DIR.glob("*.json"), reverse=True)

# -- Exibição no terminal ------------------------------------------------------

def _fmt(value, fallback: str = "-") -> str:
    """Retorna o valor como string ou fallback se vazio/None."""
    return str(value) if value else fallback


def display_printer(printer: Printer) -> None:
    """Exibe os dados completos de uma impressora no terminal."""
    sep = "-" * 60

    loc        = printer.location
    address_str = str(loc.address) if loc and loc.address else "-"
    department  = _fmt(loc.department if loc else None)
    loc_name    = _fmt(loc.address.name if loc and loc.address else None)

    # Totais por tipo de contador
    bw_total    = next((c.total_count for c in printer.counters if c.type == "blackAndWhite"), 0)
    color_total = next((c.total_count for c in printer.counters if c.type == "color"), 0)
    scan_total  = next((c.total_count for c in printer.counters if c.type == "scan"), 0)
    total_geral = bw_total + color_total

    lines = [
        sep,
        f"  Fabricante         : {_fmt(printer.manufacturer)}",
        f"  Modelo             : {_fmt(printer.model)}",
        f"  Tipo               : {_fmt(printer.type)}",
        f"  Cor                : {_fmt(printer.color)}",
        f"  Endereço IP        : {_fmt(printer.ip_address)}",
        f"  Endereço MAC       : {_fmt(printer.mac_address)}",
        f"  Número de série    : {_fmt(printer.serial_number)}",
        f"  No de patrimônio   : {_fmt(printer.asset_number)}",
        f"  Status             : {_fmt(printer.status)}",
        f"  Última comunicação : {_fmt(printer.last_communication)}",
        f"  Firmware           : {_fmt(printer.firmware_version)}",
        f"  Ponto de instalação: {_fmt(printer.installation_point)}",
        f"  Contrato           : {_fmt(printer.contract_name)}",
        f"  Cliente            : {_fmt(printer.customer_name)}",
        f"  Localização        : {loc_name}",
        f"  Endereço           : {address_str}",
        f"  Departamento       : {department}",
        f"  Backup             : {'Sim' if printer.is_backup else 'Não'}",
        f"  Observação         : {_fmt(printer.observation)}",
        "",
        "  Contadores:",
        f"    {'Tipo':<22} {'Total':>10}",
        f"    {'-'*22} {'-'*10}",
        f"    {'Geral':<22} {total_geral:>10,}",
        f"    {'Geral P&B':<22} {bw_total:>10,}",
        f"    {'Geral Colorido':<22} {color_total:>10,}",
        f"    {'Scanner':<22} {scan_total:>10,}",
    ]

    if printer.supplies:
        lines += [
            "",
            "  Suprimentos:",
            f"    {'Descrição':<28} {'Tipo':<20} {'Cor':<10} {'Nível'}",
            f"    {'-'*28} {'-'*20} {'-'*10} {'-'*30}",
        ]
        for s in printer.supplies:
            lines.append(
                f"    {s.description:<28} {s.type:<20} {s.color_label:<10} {s.level_description}"
            )
    else:
        lines.append("  Suprimentos: (nenhum)")

    lines.append(sep)
    print("\n".join(lines))


# -- Importável ----------------------------------------------------------------

def run_collection() -> Path:
    """Importável: coleta dados, salva snapshot e limpa antigos. Retorna o Path do snapshot."""
    printers = fetch_printers_with_counters()
    snapshot_path = save_snapshot(printers)
    purge_old_snapshots()
    return snapshot_path


# -- Main ----------------------------------------------------------------------

if __name__ == "__main__":
    try:
        printers = fetch_printers_with_counters()
    except requests.exceptions.Timeout:
        log.error("Timeout ao conectar com a API. Verifique a URL e a rede.")
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        log.error("Erro de conexão com a API: %s", e)
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        log.error("Erro HTTP da API: %s", e)
        sys.exit(1)

    # Salva snapshot e limpa os antigos
    snapshot_path = save_snapshot(printers)
    purge_old_snapshots()

    print(f"\n{'='*60}")
    print(f"  IMPRESSORAS  -  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Total: {len(printers)} impressora(s)")
    print(f"{'='*60}")

    for p in printers:
        display_printer(p)

    print(f"\nSnapshot: {snapshot_path.resolve()}")
    print(f"Log:      {LOG_FILE.resolve()}")

    # -- Para carregar um snapshot sem chamar a API: --------------------------
    # printers = load_snapshot("snapshots/2026-03-09_14-58.json")
    #
    # -- Para listar snapshots disponíveis: ----------------------------------
    # for s in list_snapshots():
    #     print(s)