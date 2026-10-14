import csv
import gzip
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import base64
from http.cookiejar import CookieJar


BASE_URL = "https://www.mercadopublico.cl"
DETAILS_URL = (
    "https://www.mercadopublico.cl/Procurement/Modules/RFB/"
    "DetailsAcquisition.aspx?idlicitacion={licitacion}"
)
DOWNLOAD_DIR = os.path.join(os.getcwd(), "descargas")
DEBUG_DIR = os.path.join(os.getcwd(), "debug_html")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Safari/537.36"
CRAWL_KEYWORDS = (
    "DetailsAcquisition.aspx",
    "OpeningFrame.aspx",
    "OpeningHeader.aspx",
    "SupplySummary.aspx",
    "/POPUPS/",
)
ATTACHMENT_PATH = "/bid/modules/popups/viewbidattachment.aspx?enc="

ATTACHMENT_TYPES = {
    "administrativos": "AdministrativeAttachment",
    "tecnicos": "TechnicalAttachment",
    "economicos": "EconomicAttachment",
}

try:
    from . import get_dj_ip
except Exception:
    try:
        import get_dj_ip  # type: ignore
    except Exception:
        get_dj_ip = None

LOG_LEVEL = os.environ.get("MP_LICI_LOG_LEVEL", "info").lower()
_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}
_CHROMEDRIVER_BIN = None


def _log(level, message):
    if _LEVELS.get(level, 20) >= _LEVELS.get(LOG_LEVEL, 20):
        print(f"[{level.upper()}] {message}")


def _log_debug(message):
    _log("debug", message)


def _log_info(message):
    _log("info", message)


def _log_warn(message):
    _log("warn", message)


def _log_error(message):
    _log("error", message)


def _tools_dir():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
    os.makedirs(base, exist_ok=True)
    return base


def _download_file(url, dest_path):
    _log_info(f"Descargando: {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path


def _extract_zip(zip_path, dest_dir):
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _find_chrome_version_windows():
    try:
        import winreg
    except Exception:
        return ""
    reg_paths = [
        (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Google\Chrome\BLBeacon"),
    ]
    for root, path in reg_paths:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, "version")
                if value:
                    return value
        except Exception:
            continue
    return ""


def _get_chromedriver_download_url(chrome_version):
    major = ""
    if chrome_version:
        major = chrome_version.split(".", 1)[0]
    latest_url = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
    with urllib.request.urlopen(latest_url, timeout=60) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    data = json.loads(payload)
    if major:
        versions_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        with urllib.request.urlopen(versions_url, timeout=60) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
        versions = json.loads(payload).get("versions") or []
        for entry in reversed(versions):
            version = entry.get("version", "")
            if version.startswith(f"{major}."):
                downloads = entry.get("downloads", {}).get("chromedriver", [])
                for item in downloads:
                    if item.get("platform") == "win64":
                        return item.get("url", "")
    downloads = data.get("channels", {}).get("Stable", {}).get("downloads", {}).get("chromedriver", [])
    for item in downloads:
        if item.get("platform") == "win64":
            return item.get("url", "")
    return ""


def _chromedriver_major(path):
    """Major de un chromedriver ya instalado, o '' si no se puede leer."""
    if not path or not os.path.isfile(path):
        return ""
    kwargs = {}
    if os.name == "nt":
        # Sin esto se abre una consola en cada chequeo.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        salida = subprocess.run(
            [path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            **kwargs,
        ).stdout
    except Exception as exc:
        _log_debug(f"no se pudo leer la version de {path}: {exc}")
        return ""
    match = re.search(r"ChromeDriver\s+(\d+)\.", salida or "")
    return match.group(1) if match else ""


def _ensure_tools_windows():
    global _CHROMEDRIVER_BIN
    if os.name != "nt":
        return
    tools_dir = _tools_dir()

    chrome_ver = _find_chrome_version_windows()
    chrome_major = chrome_ver.split(".", 1)[0] if chrome_ver else ""

    # Un chromedriver ya presente solo sirve si su major calza con el Chrome
    # instalado: Chrome se autoactualiza solo y el driver viejo deja de abrir
    # sesion ("only supports Chrome version N"), asi que hay que renovarlo.
    existente = _CHROMEDRIVER_BIN or shutil.which("chromedriver")
    if existente and chrome_major:
        major_drv = _chromedriver_major(existente)
        if major_drv and major_drv != chrome_major:
            _log_warn(
                f"chromedriver {major_drv} no calza con Chrome {chrome_major}; se renueva."
            )
            _CHROMEDRIVER_BIN = None
            existente = ""
    if existente:
        return

    cd_dir = os.path.join(tools_dir, "chromedriver")
    cd_bin = os.path.join(cd_dir, "chromedriver-win64", "chromedriver.exe")

    necesita_descarga = not os.path.isfile(cd_bin)
    if not necesita_descarga and chrome_major:
        major_propio = _chromedriver_major(cd_bin)
        if major_propio and major_propio != chrome_major:
            _log_info(
                f"chromedriver propio {major_propio} quedo viejo frente a Chrome "
                f"{chrome_major}; se descarga de nuevo."
            )
            necesita_descarga = True

    if necesita_descarga:
        os.makedirs(cd_dir, exist_ok=True)
        try:
            url = _get_chromedriver_download_url(chrome_ver)
        except Exception as exc:
            _log_warn(f"No se pudo resolver URL chromedriver: {exc}")
            url = ""
        if url:
            zip_path = os.path.join(cd_dir, "chromedriver.zip")
            try:
                _download_file(url, zip_path)
                _extract_zip(zip_path, cd_dir)
            except Exception as exc:
                _log_warn(f"No se pudo descargar chromedriver: {exc}")
        else:
            _log_warn(
                f"No se encontro chromedriver para Chrome {chrome_major or '?'}: "
                f"DJ/IP y garantias.pdf no se generaran."
            )

    if os.path.isfile(cd_bin):
        _CHROMEDRIVER_BIN = cd_bin
        os.environ["PATH"] = f"{os.path.dirname(cd_bin)};{os.environ.get('PATH', '')}"
        major_final = _chromedriver_major(cd_bin)
        if chrome_major and major_final and major_final != chrome_major:
            _log_warn(
                f"chromedriver quedo en {major_final} y Chrome es {chrome_major}: "
                f"DJ/IP puede seguir fallando."
            )
        else:
            _log_info(f"chromedriver listo en {cd_bin} (v{major_final or '?'})")


def build_opener():
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def read_response(resp):
    data = resp.read()
    encoding = resp.headers.get("Content-Encoding", "").lower()
    if encoding == "gzip":
        data = gzip.decompress(data)
    return data


def request_url(opener, url, method="GET", data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    return opener.open(req, timeout=30)


def fetch_html(opener, url, debug_path=None):
    _log_debug(f"fetch {url}")
    with request_url(opener, url) as resp:
        _log_debug(
            f"fetch status={getattr(resp, 'status', 'n/a')} "
            f"content_type={resp.headers.get('Content-Type', '')}"
        )
        raw = read_response(resp)
        charset = resp.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        if debug_path:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(text)
        return text


def extract_urls(html, base_url):
    urls = set()

    def add_url(candidate):
        if not candidate:
            return
        candidate = html_lib.unescape(candidate.strip())
        if candidate.lower().startswith("javascript:"):
            return
        if any(ch in candidate for ch in (" ", "(", ")", ";")):
            return
        urls.add(candidate)

    def add_openpopup_targets(text):
        text = html_lib.unescape(text)
        if "openPopUp" not in text:
            return
        for match in re.findall(r"openPopUp\(\s*'([^']+)'", text, re.I):
            add_url(match)
        for match in re.findall(r'openPopUp\(\s*"([^"]+)"', text, re.I):
            add_url(match)

    for match in re.findall(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', html, re.I):
        add_url(match)
    for match in re.findall(r'onclick\s*=\s*["\']([^"\']+)["\']', html, re.I):
        add_url(match)
        add_openpopup_targets(match)
        for inner in re.findall(r'["\']([^"\']+\.aspx[^"\']*)["\']', match, re.I):
            add_url(inner)
    for match in re.findall(r'openPopup\(\s*["\']([^"\']+)["\']', html, re.I):
        add_url(match)
    for match in re.findall(r'window\.open\(\s*["\']([^"\']+)["\']', html, re.I):
        add_url(match)
    for match in re.findall(r'location\s*=\s*["\']([^"\']+)["\']', html, re.I):
        add_url(match)
    for match in re.findall(r'["\']([^"\']+\.aspx[^"\']*)["\']', html, re.I):
        add_url(match)
    for match in re.findall(r'ViewBidAttachment\.aspx\?enc=[^"\'>\s]+', html, re.I):
        add_url(match)

    abs_urls = set()
    for url in urls:
        abs_url = urllib.parse.urljoin(base_url, url)
        abs_url = abs_url.split("#", 1)[0]
        abs_urls.add(abs_url)
    return abs_urls


def should_crawl(url):
    parsed = urllib.parse.urlparse(url)
    if "mercadopublico.cl" not in parsed.netloc:
        return False
    if parsed.path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".css", ".js", ".ico", ".svg")):
        return False
    return any(keyword in url for keyword in CRAWL_KEYWORDS)


def find_supply_summary(opener, start_url, max_pages=20):
    queue = [start_url]
    visited = set()
    supply_url = None
    supply_html = None

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        _log_debug(f"crawl {len(visited)}/{max_pages} {url}")
        debug_name = re.sub(r"[^a-zA-Z0-9]+", "_", url)[:120]
        debug_path = os.path.join(DEBUG_DIR, f"{len(visited):02d}_{debug_name}.html")

        try:
            html = fetch_html(opener, url, debug_path=debug_path)
        except Exception as exc:
            _log_warn(f"crawl error al cargar {url}: {exc}")
            continue

        found_urls = extract_urls(html, url)
        _log_debug(f"crawl urls encontradas: {len(found_urls)}")
        if "ViewBidAttachment.aspx" in html:
            _log_debug("crawl encontrado texto ViewBidAttachment.aspx en HTML")
        if "SupplySummary.aspx" in url:
            supply_url = url
            supply_html = html
            _log_info(f"SupplySummary encontrado: {url}")
            break

        for found in found_urls:
            if should_crawl(found) and found not in visited:
                queue.append(found)

        time.sleep(0.3)

    return supply_url, supply_html


def sanitize_name(value):
    value = value.strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    return value[:120] or "sin_nombre"


def extract_first(pattern, text):
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return ""
    return html_lib.unescape(match.group(1)).strip()


def parse_licitacion_nombre(html):
    return extract_first(r'id="Lbl_Descripcion_Value"[^>]*>([^<]+)<', html)

def parse_url_dj(html):
    return extract_first(r'id="UrlDj"[^>]*value="([^"]+)"', html)


def parse_providers(html):
    html = html_lib.unescape(html)
    indices = sorted(set(re.findall(r'grdSupplies_ctl(\d{2})__GvLblProvider', html)))
    providers = []
    for idx in indices:
        rut = extract_first(rf'id="grdSupplies_ctl{idx}__GvLblRutProvider"[^>]*>([^<]+)<', html)
        nombre = extract_first(rf'id="grdSupplies_ctl{idx}__GvLblProvider"[^>]*>([^<]+)<', html)
        oferta = extract_first(rf'id="grdSupplies_ctl{idx}_TotalOferta"[^>]*>([^<]+)<', html)
        estado = extract_first(rf'id="grdSupplies_ctl{idx}_EstadoOferta"[^>]*>([^<]+)<', html)
        suministro = extract_first(rf'id="grdSupplies_ctl{idx}__GvLblSuppliesName"[^>]*>([^<]+)<', html)

        attachments = {}
        for label, key in ATTACHMENT_TYPES.items():
            pattern = (
                rf'grdSupplies_ctl{idx}__GvImgb{key}[^>]*'
                rf'openPopUp\(\s*[\'"]([^\'"]+ViewBidAttachment\.aspx\?enc=[^\'"]+)'
            )
            url = extract_first(pattern, html)
            if url:
                attachments[label] = urllib.parse.urljoin(BASE_URL, url)

        firma = extract_first(
            rf'grdSupplies_ctl{idx}__GvImgFirma[^>]*onclick="ver_declaracion\(&#39;([^&#]+)',
            html,
        )
        ficha = extract_first(
            rf'grdSupplies_ctl{idx}__GvImgbAttachmentOther[^>]*onclick="verFicha\(&#39;([^&#]+)',
            html,
        )
        garantia = extract_first(
            rf'grdSupplies_ctl{idx}__GvImgbGuarante[^>]*onclick="EnvioVariables\(([^)]+)\)',
            html,
        )
        garantia_vals = []
        if garantia:
            garantia_vals = [v.strip() for v in garantia.split(",")]

        providers.append(
            {
                "rut": rut,
                "nombre": nombre,
                "oferta": oferta,
                "estado": estado,
                "suministro": suministro,
                "attachments": attachments,
                "rut_firma": firma,
                "rut_ficha": ficha,
                "garantia_vals": garantia_vals,
            }
        )
    return providers


def _extract_hidden_fields(html):
    # Se parsean los atributos sin depender del orden: los hidden del paginador
    # del cuadro vienen como name=... type="hidden" ... value=..., al revés que
    # __VIEWSTATE, y con un patrón posicional quedaban fuera del postback.
    fields = {}
    for tag in re.findall(r"<input\b[^>]*>", html, re.I):
        attrs = {
            k.lower(): v
            for k, v in re.findall(r'([A-Za-z_:][-\w:.]*)\s*=\s*"([^"]*)"', tag)
        }
        if (attrs.get("type") or "").lower() != "hidden":
            continue
        name = attrs.get("name")
        if name:
            fields[name] = attrs.get("value", "")
    return fields


def _extract_pager_grid(html):
    """
    Paginador del cuadro de ofertas (user control WucPagerGrid).

    Retorna (nombre_control, [indices de hoja enlazados]). Los índices se leen de
    los propios enlaces (fnMovePage(indice, '<control>')) para no asumir el rango
    ni la base: el paginador muestra solo una ventana de números cuando hay
    muchas hojas.
    """
    control = ""
    indices = []
    for idx, ctrl in re.findall(
        r"fnMovePage\(\s*(\d+)\s*,\s*['\"]([^'\"]+)['\"]", html, re.I
    ):
        control = control or ctrl
        if ctrl != control:
            continue
        valor = int(idx)
        if valor not in indices:
            indices.append(valor)
    return control, indices


def _total_filas_cuadro(html):
    """Total de proveedores que declara el paginador (hidCountRows), o 0."""
    for name, value in _extract_hidden_fields(html).items():
        if name.endswith("$hidCountRows"):
            try:
                return int((value or "").strip())
            except ValueError:
                return 0
    return 0


def _firma_provider(provider):
    """Identidad de una fila del cuadro: un proveedor puede tener varias ofertas."""
    return (
        provider.get("rut") or "",
        provider.get("nombre") or "",
        provider.get("suministro") or "",
        provider.get("oferta") or "",
        tuple(sorted((provider.get("attachments") or {}).items())),
    )


def parse_providers_todas_las_hojas(opener, supply_url, supply_html):
    """
    Proveedores de TODAS las hojas del cuadro de ofertas.

    parse_providers lee un solo HTML, y ese HTML trae únicamente la hoja visible
    (10 filas, hidMaxRowCount), así que las hojas siguientes se piden por postback
    ASP.NET, igual que la grilla de adjuntos en download_attachment.
    """
    providers = list(parse_providers(supply_html))
    vistos = {_firma_provider(p) for p in providers}

    control, pendientes = _extract_pager_grid(supply_html)
    if not control:
        _log_debug("cuadro de ofertas sin paginador: una sola hoja")
        return providers

    action_url = supply_url
    accion = re.search(r'<form[^>]+action="([^"]+)"', supply_html, re.I)
    if accion:
        action_url = urllib.parse.urljoin(supply_url, accion.group(1))

    current_html = supply_html
    visitadas = set()
    hoja = 1
    while pendientes:
        indice = pendientes.pop(0)
        if indice in visitadas:
            continue
        visitadas.add(indice)

        form_data = _extract_hidden_fields(current_html)
        form_data["__EVENTTARGET"] = f"{control}$btn_GoToPage"
        form_data["__EVENTARGUMENT"] = str(indice)
        data = urllib.parse.urlencode(form_data).encode("utf-8")
        try:
            _log_debug(f"cuadro POST hoja indice {indice} {action_url}")
            with request_url(
                opener,
                action_url,
                method="POST",
                data=data,
                headers={
                    "Referer": supply_url,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            ) as resp:
                nuevo_html = read_response(resp).decode(
                    resp.headers.get_content_charset() or "utf-8", errors="replace"
                )
        except Exception as exc:
            _log_warn(f"No se pudo abrir la hoja de indice {indice} del cuadro: {exc}")
            continue

        de_la_hoja = parse_providers(nuevo_html)
        if not de_la_hoja:
            # Respuesta sin filas: se conserva el HTML anterior, porque el
            # __VIEWSTATE del siguiente postback tiene que salir de uno válido.
            _log_warn(f"La hoja de indice {indice} del cuadro no trajo proveedores.")
            continue

        current_html = nuevo_html
        hoja += 1
        nuevos = 0
        for provider in de_la_hoja:
            firma = _firma_provider(provider)
            if firma in vistos:
                continue
            vistos.add(firma)
            providers.append(provider)
            nuevos += 1
        _log_info(f"Cuadro de ofertas hoja {hoja}: {nuevos} proveedor(es) nuevos")
        if not nuevos:
            # El postback devolvió la misma hoja: no se sigue ampliando por ahí.
            continue

        _, mas_hojas = _extract_pager_grid(current_html)
        for nuevo in mas_hojas:
            if nuevo not in visitadas and nuevo not in pendientes:
                pendientes.append(nuevo)

    return providers


def _extract_download_inputs(html, label=None, debug_dir=None):
    image_inputs = []
    for name, title in re.findall(
        r'<input[^>]+type="image"[^>]+name="([^"]+)"[^>]*title="([^"]*)"',
        html,
        re.I,
    ):
        if "ver" in title.lower():
            image_inputs.append(name)
    if not image_inputs:
        for name in re.findall(
            r'<input[^>]+type="image"[^>]+name="([^"]+)"[^>]*>',
            html,
            re.I,
        ):
            if name.lower().endswith("$search"):
                image_inputs.append(name)
    if not image_inputs:
        debug_name = f"popup_sin_botones_{label or 'descarga'}"
        debug_path = _guardar_debug_html(debug_dir, debug_name, html)
        if debug_path:
            _log_warn(f"popup sin botones de descarga, HTML guardado en {debug_path}")
        else:
            _log_warn("popup sin botones de descarga")
    return image_inputs


def _extract_pagination_pages(html):
    pages = set(
        re.findall(
            r"__doPostBack\(['\"]DWNL\$grdId['\"],\s*['\"]Page\$(\d+)['\"]",
            html,
            re.I,
        )
    )
    pages.add("1")
    try:
        return sorted(pages, key=lambda x: int(x))
    except ValueError:
        return sorted(pages)


def filename_from_headers(headers, fallback):
    content_disp = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disp, re.I)
    if match:
        return _fix_filename_encoding(urllib.parse.unquote(match.group(1)))
    match = re.search(r'filename="([^"]+)"', content_disp, re.I)
    if match:
        return _fix_filename_encoding(match.group(1))
    match = re.search(r"filename=([^;]+)", content_disp, re.I)
    if match:
        return _fix_filename_encoding(match.group(1).strip())
    return _fix_filename_encoding(fallback)


def _fix_filename_encoding(value):
    if not value:
        return value
    # Try to repair latin1-decoded UTF-8 (e.g., "NÂº" -> "Nº").
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except Exception:
        return value
    return repaired


def ensure_unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for idx in range(1, 1000):
        candidate = f"{base}_{idx}{ext}"
        if not os.path.exists(candidate):
            return candidate
    return path


def _guardar_debug_html(debug_dir, prefix, content):
    if not debug_dir:
        return ""
    os.makedirs(debug_dir, exist_ok=True)
    safe_prefix = sanitize_name(prefix)
    path = os.path.join(debug_dir, f"{safe_prefix}.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except Exception:
        return ""


def download_attachment(opener, url, download_dir, index, debug_dir=None, label=None):
    try:
        _log_debug(f"download GET popup {url}")
        with request_url(opener, url, headers={"Referer": url}) as resp:
            popup_html = read_response(resp).decode(
                resp.headers.get_content_charset() or "utf-8", errors="replace"
            )
    except Exception as exc:
        _log_warn(f"download error GET popup {url}: {exc}")
        return None

    popup_html = html_lib.unescape(popup_html)
    saved = []
    action_url = url
    current_html = popup_html

    # La grilla de adjuntos usa paginación ASP.NET por __doPostBack(Page$N).
    # Algunas licitaciones muestran solo un subconjunto de páginas (con "..." / ventana deslizante).
    # Para no perder adjuntos, avanzamos secuencialmente y vamos ampliando el máximo de páginas vistas.
    max_page = 1
    page = 1
    while page <= max_page:
        action_match = re.search(r'<form[^>]+action="([^"]+)"', current_html, re.I)
        if action_match:
            action_url = urllib.parse.urljoin(url, action_match.group(1))

        pages_here = _extract_pagination_pages(current_html)
        try:
            max_here = max(int(p) for p in pages_here) if pages_here else 1
        except Exception:
            max_here = 1
        if max_here > max_page:
            _log_debug(f"download popup: max_page {max_page} -> {max_here}")
            max_page = max_here

        image_inputs = _extract_download_inputs(
            current_html,
            label=f"{label or index}_p{page}",
            debug_dir=debug_dir,
        )
        if not image_inputs:
            if page == max_page:
                break
            page += 1
            hidden_fields = _extract_hidden_fields(current_html)
            form_data = dict(hidden_fields)
            form_data["__EVENTTARGET"] = "DWNL$grdId"
            form_data["__EVENTARGUMENT"] = f"Page${page}"
            data = urllib.parse.urlencode(form_data).encode("utf-8")
            try:
                _log_debug(f"download POST paginacion {page} {action_url}")
                with request_url(
                    opener,
                    action_url,
                    method="POST",
                    data=data,
                    headers={"Referer": url, "Content-Type": "application/x-www-form-urlencoded"},
                ) as resp:
                    current_html = read_response(resp).decode(
                        resp.headers.get_content_charset() or "utf-8", errors="replace"
                    )
            except Exception as exc:
                _log_warn(f"download error paginacion {page} {action_url}: {exc}")
            continue

        hidden_fields = _extract_hidden_fields(current_html)
        for input_name in image_inputs:
            form_data = dict(hidden_fields)
            form_data[f"{input_name}.x"] = "1"
            form_data[f"{input_name}.y"] = "1"
            data = urllib.parse.urlencode(form_data).encode("utf-8")
            try:
                _log_debug(f"download POST action {action_url} ({input_name})")
                with request_url(
                    opener,
                    action_url,
                    method="POST",
                    data=data,
                    headers={"Referer": url, "Content-Type": "application/x-www-form-urlencoded"},
                ) as resp:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    payload = read_response(resp)
                    _log_debug(
                        f"download status={getattr(resp, 'status', 'n/a')} "
                        f"content_type={content_type} bytes={len(payload)}"
                    )
            except Exception as exc:
                _log_warn(f"download error POST {action_url}: {exc}")
                continue

            if "text/html" in content_type:
                debug_name = f"popup_respuesta_html_{label or index}_{input_name}"
                html_text = payload.decode("utf-8", errors="replace")
                debug_path = _guardar_debug_html(debug_dir, debug_name, html_text)
                if debug_path:
                    _log_warn(f"respuesta HTML inesperada, guardada en {debug_path}")
                else:
                    _log_warn("respuesta HTML inesperada en descarga")
                continue

            fallback = f"adjunto_{index}.bin"
            filename = filename_from_headers(resp.headers, fallback)
            filename = os.path.basename(filename).strip() or fallback
            path = ensure_unique_path(os.path.join(download_dir, filename))
            with open(path, "wb") as f:
                f.write(payload)
            saved.append(path)

        if page == max_page:
            break

        page += 1
        hidden_fields = _extract_hidden_fields(current_html)
        form_data = dict(hidden_fields)
        form_data["__EVENTTARGET"] = "DWNL$grdId"
        form_data["__EVENTARGUMENT"] = f"Page${page}"
        data = urllib.parse.urlencode(form_data).encode("utf-8")
        try:
            _log_debug(f"download POST paginacion {page} {action_url}")
            with request_url(
                opener,
                action_url,
                method="POST",
                data=data,
                headers={"Referer": url, "Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                current_html = read_response(resp).decode(
                    resp.headers.get_content_charset() or "utf-8", errors="replace"
                )
        except Exception as exc:
            _log_warn(f"download error paginacion {page} {action_url}: {exc}")

    return saved


def write_providers_csv(csv_path, providers):
    fieldnames = [
        "rut",
        "nombre",
        "oferta",
        "estado",
        "suministro",
        "admin_url",
        "tecnico_url",
        "economico_url",
        "declaracion_url",
        "proveedor_url",
        "garantia_info",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in providers:
            row = {
                "rut": item["rut"],
                "nombre": item["nombre"],
                "oferta": item["oferta"],
                "estado": item["estado"],
                "suministro": item["suministro"],
                "admin_url": item["attachments"].get("administrativos", ""),
                "tecnico_url": item["attachments"].get("tecnicos", ""),
                "economico_url": item["attachments"].get("economicos", ""),
                "declaracion_url": item.get("declaracion_url", ""),
                "proveedor_url": item.get("proveedor_url", ""),
                "garantia_info": ",".join(item.get("garantia_vals", [])),
            }
            writer.writerow(row)


def get_access_token(opener):
    url = f"{BASE_URL}/Autenticacion/Registro"
    with request_url(opener, url) as resp:
        payload = read_response(resp).decode("utf-8", errors="replace")
    data = json.loads(payload)
    return data.get("access_token", "")

def _render_html_to_pdf_chrome(html_text, output_path, chromedriver_path=None):
    """
    Renderiza un HTML a PDF usando Chrome headless + DevTools (Page.printToPDF).
    Requiere tener Chrome instalado y chromedriver disponible en PATH (o en chromedriver_path).
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception as exc:
        return False, f"selenium no disponible: {exc}"

    chromedriver_path = chromedriver_path or shutil.which("chromedriver")
    if not chromedriver_path:
        return False, "chromedriver no encontrado en PATH"

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1280,2000")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    driver = None
    try:
        driver = webdriver.Chrome(service=Service(chromedriver_path), options=chrome_options)
        url = "data:text/html;charset=utf-8," + urllib.parse.quote(html_text)
        driver.get(url)
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(1)
        pdf_data = driver.execute_cdp_cmd(
            "Page.printToPDF",
            {
                "printBackground": True,
                "landscape": False,
                "paperWidth": 8.27,  # A4 inches
                "paperHeight": 11.69,  # A4 inches
                "marginTop": 0.4,
                "marginBottom": 0.4,
                "marginLeft": 0.4,
                "marginRight": 0.4,
                "displayHeaderFooter": False,
                "preferCSSPageSize": True,
                "generateDocumentOutline": False,
                "generateTaggedPDF": False,
            },
        )
        data_b64 = (pdf_data or {}).get("data") or ""
        if not data_b64:
            return False, "Page.printToPDF no devolvio datos"
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(data_b64))
        return True, ""
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


def render_url_to_pdf(url, output_path, extra_args=None):
    args = [
        "wkhtmltopdf",
        "--enable-javascript",
        "--javascript-delay",
        "6000",
        "--no-stop-slow-scripts",
        "--print-media-type",
    ]
    if extra_args:
        args.extend(extra_args)
    args.extend([url, output_path])
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode == 0, result.stderr.strip()


def render_html_to_pdf(html_text, output_path):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(html_text)
        tmp_path = tmp.name
    try:
        return render_url_to_pdf(tmp_path, output_path, extra_args=["--enable-local-file-access"])
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def wait_for_text(url, needle, timeout_s=40, poll_s=2):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                text = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            text = ""
        if needle.lower() in text.lower():
            return True
        time.sleep(poll_s)
    return False


def download_pdf_from_url(url, output_path, wait_text=None):
    if wait_text:
        _log_debug(f"pdf esperando texto '{wait_text}' en {url}")
        if not wait_for_text(url, wait_text):
            _log_warn(f"pdf no se encontro '{wait_text}' antes del timeout: {url}")
            return False
    success, err = render_url_to_pdf(url, output_path)
    if not success:
        _log_warn(f"pdf error {url}: {err}")
    return success


def build_garantias_pdf(opener, rfb_code, bid_id, org_code, output_path):
    base = f"{BASE_URL}/SuministroGarantia/api/garantias"
    header_url = f"{base}/outputRFBHeader?rbhCode={rfb_code}"
    doc_url = f"{base}/cargaDocumento?rbhCode={rfb_code}"
    prov_url = f"{base}/SuministroGarantia?rbhCode={rfb_code}&bidID={bid_id}"
    try:
        header = json.loads(fetch_html(opener, header_url))
        documentos = json.loads(fetch_html(opener, doc_url))
        proveedores = json.loads(fetch_html(opener, prov_url))
    except Exception as exc:
        _log_warn(f"garantias error al obtener datos: {exc}")
        return False

    def rows(items, keys):
        lines = []
        for item in items:
            cols = "".join(f"<td>{html_lib.escape(str(item.get(k, '')))}</td>" for k in keys)
            lines.append(f"<tr>{cols}</tr>")
        return "\n".join(lines)

    html_page = f"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Garantias</title>
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 12px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; }}
    th, td {{ border: 1px solid #ccc; padding: 4px; text-align: left; }}
    h3 {{ margin: 12px 0 6px; }}
  </style>
</head>
<body>
  <h3>Datos de la Licitacion</h3>
  <table>
    <tr><th>Codigo</th><th>Nombre</th><th>Creacion</th><th>Cierre</th></tr>
    {rows(header, ["rbhExternalCode", "rbhName", "rbhCreationDate", "CloseDate"])}
  </table>
  <h3>Datos del Proveedor</h3>
  <table>
    <tr><th>RUT</th><th>Razon Social</th><th>Banco</th></tr>
    {rows(proveedores, ["Rut", "RazonSocial", "insName"])}
  </table>
  <h3>Documentacion</h3>
  <table>
    <tr><th>Tipo</th><th>Moneda</th><th>Monto</th></tr>
    {rows(documentos, ["rgtName", "rgaCurrency", "rgaAmount"])}
  </table>
</body>
</html>
"""
    chromedriver_path = shutil.which("chromedriver")
    success, err = _render_html_to_pdf_chrome(html_page, output_path, chromedriver_path=chromedriver_path)
    if not success:
        _log_warn(f"garantias error al generar PDF (Chrome): {err}")
    return success


def descargar_licitacion_automatica(licitacion, base_dir=None, debug_dir=None):
    resumen = {"ok": False, "proveedores": [], "errores": []}
    codigo = (str(licitacion) or "").strip()
    if not codigo:
        resumen["errores"].append("Codigo de licitacion vacio.")
        return resumen

    if base_dir:
        download_root = os.path.abspath(base_dir)
        debug_root = os.path.abspath(debug_dir or os.path.join(download_root, "debug_html"))
    else:
        download_root = DOWNLOAD_DIR
        debug_root = debug_dir or DEBUG_DIR

    prev_download = DOWNLOAD_DIR
    prev_debug = DEBUG_DIR

    try:
        globals()["DOWNLOAD_DIR"] = download_root
        globals()["DEBUG_DIR"] = debug_root
        os.makedirs(download_root, exist_ok=True)
        os.makedirs(debug_root, exist_ok=True)

        _ensure_tools_windows()

        chromedriver_path = shutil.which("chromedriver")
        resumen["dependencias"] = {
            "chromedriver": chromedriver_path or "",
        }
        if not chromedriver_path:
            _log_warn("chromedriver no encontrado en PATH (DJ/IP y garantias.pdf no se generaran)")

        opener = build_opener()
        start_url = DETAILS_URL.format(licitacion=codigo)
        resumen["url"] = start_url
        _log_info(f"Iniciando descarga licitacion {codigo}")

        try:
            details_html = fetch_html(opener, start_url)
        except Exception as exc:
            resumen["errores"].append(f"No se pudo abrir la ficha: {exc}")
            _log_error(f"No se pudo abrir la ficha: {exc}")
            return resumen

        nombre_licitacion = parse_licitacion_nombre(details_html) or "licitacion"
        resumen["nombre_licitacion"] = nombre_licitacion

        _log_info("Buscando SupplySummary...")
        supply_url, supply_html = find_supply_summary(opener, start_url)
        if not supply_url or not supply_html:
            resumen["errores"].append("No se pudo encontrar SupplySummary para extraer proveedores.")
            _log_error("No se pudo encontrar SupplySummary para extraer proveedores.")
            return resumen
        resumen["supply_url"] = supply_url

        providers = parse_providers_todas_las_hojas(opener, supply_url, supply_html)
        if not providers:
            resumen["errores"].append("No se encontraron proveedores en la tabla.")
            _log_warn("No se encontraron proveedores en la tabla.")
            return resumen

        total_declarado = _total_filas_cuadro(supply_html)
        _log_info(
            f"Proveedores detectados: {len(providers)}"
            + (f" de {total_declarado} que declara el cuadro" if total_declarado else "")
        )
        if total_declarado and len(providers) < total_declarado:
            aviso = (
                f"Solo se leyeron {len(providers)} de {total_declarado} proveedores "
                f"del cuadro de ofertas: la descarga queda incompleta."
            )
            resumen["errores"].append(aviso)
            _log_warn(aviso)

        try:
            token = get_access_token(opener)
            if not token:
                resumen["errores"].append("No se pudo obtener access_token.")
                _log_warn("No se pudo obtener access_token.")
        except Exception as exc:
            resumen["errores"].append(f"No se pudo obtener access_token: {exc}")
            _log_warn(f"No se pudo obtener access_token: {exc}")

        carpeta_base = os.path.join(download_root, f"{codigo} {sanitize_name(nombre_licitacion)}")
        os.makedirs(carpeta_base, exist_ok=True)
        resumen["carpeta_base"] = carpeta_base

        type_map = {
            "administrativos": "admin",
            "tecnicos": "tecnico",
            "economicos": "economico",
        }

        total_global = 0
        carpetas_usadas = {}
        for provider in providers:
            rut = provider["rut"] or provider["rut_firma"] or ""
            nombre = provider["nombre"] or "proveedor"
            provider_name = sanitize_name(f"{rut} {nombre}".strip())
            # Un proveedor puede presentar más de una oferta: sin esto las dos
            # filas caen en la misma carpeta y se mezclan sus documentos.
            carpetas_usadas[provider_name] = carpetas_usadas.get(provider_name, 0) + 1
            if carpetas_usadas[provider_name] > 1:
                provider_name = f"{provider_name} (oferta {carpetas_usadas[provider_name]})"
            provider_dir = os.path.join(carpeta_base, provider_name)
            os.makedirs(provider_dir, exist_ok=True)
            _log_info(f"Procesando proveedor: {provider_name}")

            prov_resumen = {
                "rut": rut,
                "nombre": nombre,
                "carpeta": provider_dir,
                "admin": {"descargados": 0, "errores": []},
                "tecnico": {"descargados": 0, "errores": []},
                "economico": {"descargados": 0, "errores": []},
                "otros": {"descargados": 0, "errores": []},
            }

            total_descargados = 0
            for label, key in type_map.items():
                url = provider["attachments"].get(label)
                if not url:
                    continue
                target_dir = os.path.join(provider_dir, label)
                os.makedirs(target_dir, exist_ok=True)
                saved = download_attachment(
                    opener,
                    url,
                    target_dir,
                    1,
                    debug_dir=debug_root,
                    label=f"{provider_name}_{label}",
                )
                if saved:
                    count = len(saved)
                else:
                    prov_resumen[key]["errores"].append(f"No se pudo descargar {label}")
                    count = 0
                prov_resumen[key]["descargados"] = count
                total_descargados += count

            prov_resumen["total_descargados"] = total_descargados
            total_global += total_descargados
            resumen["proveedores"].append(prov_resumen)
            _log_info(f"Adjuntos descargados para {provider_name}: {total_descargados}")

            if rut:
                declaracion_url = f"https://proveedor.mercadopublico.cl/dj-requisitos/{codigo}/{rut}"
                proveedor_url = f"https://proveedor.mercadopublico.cl/ficha/{rut}"
                provider["declaracion_url"] = declaracion_url
                provider["proveedor_url"] = proveedor_url

                if get_dj_ip and chromedriver_path:
                    urls = {
                        "declaracion_jurada.pdf": declaracion_url,
                        "informacion_proveedor.pdf": proveedor_url,
                    }
                    wait_texts = {
                        "declaracion_jurada.pdf": "Identificación del declarante",
                        "informacion_proveedor.pdf": "Estado de habilidad",
                    }
                    try:
                        errores_dj = get_dj_ip.render_pdfs(urls, provider_dir, wait_texts)
                        for err in errores_dj or []:
                            prov_resumen["otros"]["errores"].append(f"DJ/IP: {err}")
                    except Exception as exc:
                        prov_resumen["otros"]["errores"].append(f"Error DJ/IP: {exc}")
                        _log_warn(f"Error DJ/IP para {provider_name}: {exc}")
                else:
                    if not get_dj_ip:
                        prov_resumen["otros"]["errores"].append("get_dj_ip no disponible")
                    if not chromedriver_path:
                        prov_resumen["otros"]["errores"].append("chromedriver no encontrado en PATH")

            garantia_vals = provider.get("garantia_vals", [])
            if len(garantia_vals) >= 2:
                g_path = os.path.join(provider_dir, "garantias.pdf")
                if not chromedriver_path:
                    prov_resumen["otros"]["errores"].append("chromedriver no encontrado en PATH")
                else:
                    try:
                        ok_garantia = build_garantias_pdf(
                            opener,
                            garantia_vals[0],
                            garantia_vals[1],
                            garantia_vals[2] if len(garantia_vals) > 2 else "",
                            g_path,
                        )
                        if not ok_garantia:
                            prov_resumen["otros"]["errores"].append("No se pudo generar garantias.pdf")
                    except Exception as exc:
                        prov_resumen["otros"]["errores"].append(f"Error garantias: {exc}")
                        _log_warn(f"Error garantias para {provider_name}: {exc}")

        try:
            csv_path = os.path.join(carpeta_base, "proveedores.csv")
            write_providers_csv(csv_path, providers)
            resumen["csv_path"] = csv_path
        except Exception as exc:
            resumen["errores"].append(f"No se pudo escribir proveedores.csv: {exc}")

        resumen["total_descargados"] = total_global
        if total_global == 0:
            resumen["errores"].append("No se descargaron adjuntos.")
        resumen["ok"] = total_global > 0
        _log_info(f"Descarga finalizada. Total adjuntos: {total_global}")
        return resumen
    finally:
        globals()["DOWNLOAD_DIR"] = prev_download
        globals()["DEBUG_DIR"] = prev_debug


def main():
    licitacion = sys.argv[1] if len(sys.argv) > 1 else "728-1-LE26"
    resumen = descargar_licitacion_automatica(licitacion)
    if not resumen.get("ok"):
        errores = "; ".join(resumen.get("errores") or [])
        print(f"No se pudo completar la descarga: {errores}")


if __name__ == "__main__":
    main()
