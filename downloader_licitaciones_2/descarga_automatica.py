import csv
import gzip
import html as html_lib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
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
    print(f"[fetch] {url}")
    with request_url(opener, url) as resp:
        print(
            f"[fetch] status={getattr(resp, 'status', 'n/a')} "
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
        print(f"[crawl] {len(visited)}/{max_pages} {url}")
        debug_name = re.sub(r"[^a-zA-Z0-9]+", "_", url)[:120]
        debug_path = os.path.join(DEBUG_DIR, f"{len(visited):02d}_{debug_name}.html")

        try:
            html = fetch_html(opener, url, debug_path=debug_path)
        except Exception as exc:
            print(f"[crawl] error al cargar {url}: {exc}")
            continue

        found_urls = extract_urls(html, url)
        print(f"[crawl] urls encontradas: {len(found_urls)}")
        if "ViewBidAttachment.aspx" in html:
            print("[crawl] encontrado texto ViewBidAttachment.aspx en HTML")
        if "SupplySummary.aspx" in url:
            supply_url = url
            supply_html = html
            print(f"[crawl] encontrado SupplySummary: {url}")
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


def filename_from_headers(headers, fallback):
    content_disp = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disp, re.I)
    if match:
        return urllib.parse.unquote(match.group(1))
    match = re.search(r'filename="([^"]+)"', content_disp, re.I)
    if match:
        return match.group(1)
    match = re.search(r"filename=([^;]+)", content_disp, re.I)
    if match:
        return match.group(1).strip()
    return fallback


def ensure_unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for idx in range(1, 1000):
        candidate = f"{base}_{idx}{ext}"
        if not os.path.exists(candidate):
            return candidate
    return path


def download_attachment(opener, url, download_dir, index):
    try:
        print(f"[download] GET popup {url}")
        with request_url(opener, url, headers={"Referer": url}) as resp:
            popup_html = read_response(resp).decode(
                resp.headers.get_content_charset() or "utf-8", errors="replace"
            )
    except Exception as exc:
        print(f"[download] error GET popup {url}: {exc}")
        return None

    popup_html = html_lib.unescape(popup_html)
    action_match = re.search(r'<form[^>]+action="([^"]+)"', popup_html, re.I)
    action_url = url
    if action_match:
        action_url = urllib.parse.urljoin(url, action_match.group(1))

    hidden_fields = {}
    for name, value in re.findall(
        r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"',
        popup_html,
        re.I,
    ):
        hidden_fields[name] = value

    image_inputs = []
    for name, title in re.findall(
        r'<input[^>]+type="image"[^>]+name="([^"]+)"[^>]*title="([^"]*)"',
        popup_html,
        re.I,
    ):
        if "ver" in title.lower():
            image_inputs.append(name)
    if not image_inputs:
        for name in re.findall(
            r'<input[^>]+type="image"[^>]+name="([^"]+)"[^>]*>',
            popup_html,
            re.I,
        ):
            if name.lower().endswith("$search"):
                image_inputs.append(name)

    saved = []
    for input_name in image_inputs:
        form_data = dict(hidden_fields)
        form_data[f"{input_name}.x"] = "1"
        form_data[f"{input_name}.y"] = "1"
        data = urllib.parse.urlencode(form_data).encode("utf-8")
        try:
            print(f"[download] POST action {action_url} ({input_name})")
            with request_url(
                opener,
                action_url,
                method="POST",
                data=data,
                headers={"Referer": url, "Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                content_type = resp.headers.get("Content-Type", "").lower()
                payload = read_response(resp)
                print(
                    f"[download] status={getattr(resp, 'status', 'n/a')} "
                    f"content_type={content_type} bytes={len(payload)}"
                )
        except Exception as exc:
            print(f"[download] error POST {action_url}: {exc}")
            continue

        if "text/html" in content_type:
            print("[download] respuesta HTML, no es adjunto")
            continue

        fallback = f"adjunto_{index}.bin"
        filename = filename_from_headers(resp.headers, fallback)
        filename = os.path.basename(filename).strip() or fallback
        path = ensure_unique_path(os.path.join(download_dir, filename))
        with open(path, "wb") as f:
            f.write(payload)
        saved.append(path)

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
        print(f"[pdf] esperando texto '{wait_text}' en {url}")
        if not wait_for_text(url, wait_text):
            print(f"[pdf] no se encontro '{wait_text}' antes del timeout: {url}")
            return False
    success, err = render_url_to_pdf(url, output_path)
    if not success:
        print(f"[pdf] error {url}: {err}")
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
        print(f"[garantias] error al obtener datos: {exc}")
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
    success, err = render_html_to_pdf(html_page, output_path)
    if not success:
        print(f"[garantias] error al generar PDF: {err}")
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

        opener = build_opener()
        start_url = DETAILS_URL.format(licitacion=codigo)
        resumen["url"] = start_url

        try:
            details_html = fetch_html(opener, start_url)
        except Exception as exc:
            resumen["errores"].append(f"No se pudo abrir la ficha: {exc}")
            return resumen

        nombre_licitacion = parse_licitacion_nombre(details_html) or "licitacion"
        resumen["nombre_licitacion"] = nombre_licitacion

        supply_url, supply_html = find_supply_summary(opener, start_url)
        if not supply_url or not supply_html:
            resumen["errores"].append("No se pudo encontrar SupplySummary para extraer proveedores.")
            return resumen
        resumen["supply_url"] = supply_url

        providers = parse_providers(supply_html)
        if not providers:
            resumen["errores"].append("No se encontraron proveedores en la tabla.")
            return resumen

        try:
            token = get_access_token(opener)
            if not token:
                resumen["errores"].append("No se pudo obtener access_token.")
        except Exception as exc:
            resumen["errores"].append(f"No se pudo obtener access_token: {exc}")

        carpeta_base = os.path.join(download_root, f"{codigo} {sanitize_name(nombre_licitacion)}")
        os.makedirs(carpeta_base, exist_ok=True)
        resumen["carpeta_base"] = carpeta_base

        type_map = {
            "administrativos": "admin",
            "tecnicos": "tecnico",
            "economicos": "economico",
        }

        total_global = 0
        for provider in providers:
            rut = provider["rut"] or provider["rut_firma"] or ""
            nombre = provider["nombre"] or "proveedor"
            provider_name = sanitize_name(f"{rut} {nombre}".strip())
            provider_dir = os.path.join(carpeta_base, provider_name)
            os.makedirs(provider_dir, exist_ok=True)

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
                saved = download_attachment(opener, url, target_dir, 1)
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

            if rut:
                declaracion_url = f"https://proveedor.mercadopublico.cl/dj-requisitos/{codigo}/{rut}"
                proveedor_url = f"https://proveedor.mercadopublico.cl/ficha/{rut}"
                provider["declaracion_url"] = declaracion_url
                provider["proveedor_url"] = proveedor_url

                if get_dj_ip:
                    urls = {
                        "declaracion_jurada.pdf": declaracion_url,
                        "informacion_proveedor.pdf": proveedor_url,
                    }
                    wait_texts = {
                        "declaracion_jurada.pdf": "Identificación del declarante",
                        "informacion_proveedor.pdf": "Estado de habilidad",
                    }
                    try:
                        get_dj_ip.render_pdfs(urls, provider_dir, wait_texts)
                    except Exception as exc:
                        prov_resumen["otros"]["errores"].append(f"Error DJ/IP: {exc}")
                else:
                    prov_resumen["otros"]["errores"].append("get_dj_ip no disponible")

            garantia_vals = provider.get("garantia_vals", [])
            if len(garantia_vals) >= 2:
                g_path = os.path.join(provider_dir, "garantias.pdf")
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
