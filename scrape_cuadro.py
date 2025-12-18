"""
Script para abrir la licitación, pulsar "Cuadro de ofertas" y contar
cuántos proveedores aparecen (filas de la tabla grdSupplies).

Requisitos previos:
- Tener Chrome y el binario de chromedriver instalados y visibles en PATH
  (o exportar CHROMEDRIVER_PATH con la ruta al binario).
- Instalar dependencias: pip install selenium

Ejecución:
  python scrape_cuadro.py
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from typing import Iterable, List, Tuple
from urllib.parse import urljoin

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import descarga_ca

URL = "https://mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?qs=5vvQo+7VGfY18eev2hYLBQ=="
BASE = "https://mercadopublico.cl"
DOWNLOAD_DIR = "adjuntos"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)


def build_driver() -> webdriver.Chrome:
    """Crea el driver apuntando al chromedriver disponible."""
    chrome_service = None
    custom_driver = os.environ.get("CHROMEDRIVER_PATH")
    if custom_driver:
        chrome_service = Service(executable_path=custom_driver)
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--lang=es-CL")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(service=chrome_service, options=options)
    _configure_stealth(driver)
    return driver


def open_frame_directly(driver: webdriver.Chrome, wait: WebDriverWait, base_url: str | None = None) -> bool:
    """
    Detecta el iframe del popup (OpeningFrame.aspx) y navega directamente a su URL.
    """
    base_url = base_url or URL
    driver.switch_to.default_content()
    # Pequeño respiro para que aparezca el overlay como usuario real
    time.sleep(1.0)
    try:
        popup_iframe = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#RadWindowWrapper_PopupFicha iframe"))
        )
    except TimeoutException:
        print("No se encontró el iframe del popup dentro del overlay.")
        return False

    src = popup_iframe.get_attribute("src") or ""
    if not src:
        print("Iframe del popup sin src.")
        return False

    full_url = src if src.startswith("http") else urljoin(base_url, src)
    print(f"Abrir directamente OpeningFrame: {full_url}")
    driver.get(full_url)
    return True


def switch_to_supply_summary(driver: webdriver.Chrome) -> bool:
    """
    En la página actual, busca iframe con SupplySummary.aspx y cambia a él si existe.
    """
    driver.switch_to.default_content()
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for idx, frame in enumerate(frames):
        src = frame.get_attribute("src") or ""
        if "SupplySummary.aspx" in src:
            driver.switch_to.frame(frame)
            print(f"Cambiado a iframe SupplySummary (#{idx}) con src {src}")
            return True
    frame_list = [frame.get_attribute("src") or "(sin src)" for frame in frames]
    print(f"No se encontró iframe con SupplySummary.aspx; iframes vistos: {frame_list}")
    print("Se intentará localizar la tabla en el contexto actual.")
    return True


def switch_to_cuerpo_frame(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """Busca el frame 'Cuerpo' dentro del frameset y cambia a él."""
    try:
        frame_el = wait.until(EC.presence_of_element_located((By.NAME, "Cuerpo")))
    except TimeoutException:
        print("No se encontró frame 'Cuerpo'.")
        return False
    src = frame_el.get_attribute("src") or ""
    print(f"Frame 'Cuerpo' encontrado, src='{src}'")
    try:
        driver.switch_to.frame(frame_el)
        time.sleep(1.0)
        return True
    except Exception as exc:
        print(f"No se pudo cambiar al frame Cuerpo: {exc}")
        return False


def count_elements(driver: webdriver.Chrome) -> int:
    """Cuenta, lista y descarga adjuntos; retorna total descargados."""
    descargados, _ = _count_elements_with_providers(driver)
    return descargados


def _normalize_provider_dir(provider_name: str, idx: int | None = None) -> str:
    """
    Normaliza un nombre de proveedor para usar como carpeta (compatible Windows).
    """
    nombre = (provider_name or "").strip()
    if not nombre:
        return f"Proveedor_{idx}" if idx else "Proveedor"
    # Remover caracteres inválidos en Windows
    nombre = re.sub(r'[<>:"/\\\\|?*]', "_", nombre)
    # Colapsar espacios
    nombre = " ".join(nombre.split())
    # Limitar longitud
    nombre = nombre[:100].rstrip()
    return nombre or (f"Proveedor_{idx}" if idx else "Proveedor")


def _count_elements_with_providers(driver: webdriver.Chrome) -> Tuple[int, List[dict]]:
    """
    Cuenta, lista y descarga adjuntos; retorna (total_descargados, proveedores_meta).

    proveedores_meta: lista de dicts {rut, nombre, carpeta_rel}
    donde carpeta_rel es el nombre de carpeta del proveedor bajo DOWNLOAD_DIR.
    """
    print(f"URL actual: {driver.current_url}")
    rows = driver.find_elements(
        By.CSS_SELECTOR,
        "#grdSupplies tr.cssFwkItemStyle, #grdSupplies tr.cssFwkAlternatingItemStyle",
    )
    if not rows:
        print("No se encontraron filas de proveedores en grdSupplies.")
        return 0, []

    # Imprime solo RUT en bloque para fácil lectura
    rut_links = driver.find_elements(By.CSS_SELECTOR, "#grdSupplies a[id$='_GvLblRutProvider']")
    ruts = [el.text.strip() for el in rut_links if el.text.strip()]
    print(f"RUT proveedores ({len(ruts)}): {', '.join(ruts)}")
    print(f"Total filas: {len(rows)}")

    admin_attach = driver.find_elements(By.CSS_SELECTOR, "input[id$='_GvImgbAdministrativeAttachment']")
    print(f"Botones 'Anexos Administrativos' detectados: {len(admin_attach)}")
    # Log de primeros botones admin
    for idx, btn in enumerate(admin_attach[:5]):
        print(f" Admin btn {idx} id={btn.get_attribute('id')} title={btn.get_attribute('title')} onclick={btn.get_attribute('onclick')}")

    # Detalle por fila
    print("Detalle por fila:")
    all_attachment_urls: List[Tuple[str, str, str, str]] = []  # (url, rut, prov, title_hint)
    proveedores_meta: List[dict] = []
    for row in rows:
        rut = _safe_text(row.find_elements(By.CSS_SELECTOR, "a[id$='_GvLblRutProvider']"))
        prov = _safe_text(row.find_elements(By.CSS_SELECTOR, "a[id$='_GvLblProvider']"))
        nombre = _safe_text(row.find_elements(By.CSS_SELECTOR, "span[id$='_GvLblSuppliesName']"))
        total = _safe_text(row.find_elements(By.CSS_SELECTOR, "span[id$='TotalOferta']"))
        estado = _safe_text(row.find_elements(By.CSS_SELECTOR, "span[id$='EstadoOferta']"))
        print(f"- {rut} | {prov} | {nombre} | {total} | {estado}")
        carpeta_rel = _normalize_provider_dir(prov, len(proveedores_meta) + 1)
        voucher_url = ""
        try:
            voucher_btns = row.find_elements(
                By.CSS_SELECTOR,
                "input[type='image'][id$='_imgView'], input[type='image'][title*='Comprobante'], input[type='image'][onclick*='voucherview.aspx']",
            )
            for btn in voucher_btns:
                onclick = btn.get_attribute("onclick") or ""
                rel = _extract_url_from_openpopup(onclick)
                if rel and "voucherview.aspx" in rel.lower():
                    voucher_url = rel
                    break
        except Exception:
            voucher_url = ""

        if voucher_url and not voucher_url.startswith("http"):
            try:
                voucher_url = urljoin(driver.current_url or BASE, voucher_url)
            except Exception:
                voucher_url = urljoin(BASE, voucher_url)

        proveedores_meta.append(
            {
                "rut": (rut or "").strip(),
                "nombre": (prov or "").strip(),
                "carpeta_rel": carpeta_rel,
                "voucher_url": voucher_url,
            }
        )
        attachments = _extract_attachments(row)
        print(f"  Adjuntos en fila: {len(attachments)} -> {[t for t, _ in attachments]}")
        for title, url in attachments:
            if url:
                all_attachment_urls.append((url, rut, prov, title))

    # Fallback: busca cualquier botón admin por título/src aunque no haya sido capturado por fila
    fallback_admin_btns = driver.find_elements(
        By.CSS_SELECTOR,
        "input[id*='ImgbAdministrativeAttachment'], input[title*='Anexos Administrativos'], input[src*='adj-administrativos']",
    )
    print(f"Fallback botones admin encontrados: {len(fallback_admin_btns)}")
    for btn in fallback_admin_btns:
        onclick = btn.get_attribute("onclick") or ""
        url = _extract_url_from_onclick(onclick)
        if url:
            all_attachment_urls.append((url, "", "", btn.get_attribute("title") or ""))

    # Descarga de todos los adjuntos (incluidos administrativos)
    sess = _requests_session_from_driver(driver)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    log_path = os.path.join(DOWNLOAD_DIR, "adjuntos.log")
    downloaded_total = 0
    seen: dict[str, Tuple[str, str, str]] = {}
    for url, rut, prov, title_hint in all_attachment_urls:
        prev = seen.get(url)
        if prev:
            prev_rut, prev_prov, prev_title = prev
            rut = rut or prev_rut
            prov = prov or prev_prov
            title_hint = title_hint or prev_title
        seen[url] = (rut, prov, title_hint)

    with open(log_path, "a", encoding="utf-8") as log:
        for idx, (url, (rut, prov, title_hint)) in enumerate(seen.items(), start=1):
            fname_hint = f"adjunto_{idx}"
            saved_list = _download_attachment_popup(
                sess, url, fname_hint, current_rut=rut, current_prov=prov, icon_title=title_hint
            )
            if not saved_list:
                log.write(f"{url}|\n")
                print(f"No se pudo descargar {url}")
                continue
            for saved in saved_list:
                log.write(f"{url}|{saved}\n")
                downloaded_total += 1
                print(f"Descargado: {saved}")
    print(f"Total adjuntos descargados: {downloaded_total}. Log: {log_path}")
    return downloaded_total, proveedores_meta


def _safe_iter(elements: Iterable) -> Iterable:
    """Itera elementos permitiendo None si no existen."""
    return elements or []


def _safe_text(elements: Iterable) -> str:
    """Devuelve el texto del primer elemento o cadena vacía."""
    for el in elements or []:
        return el.text.strip()
    return ""


def _extract_attachments(row) -> List[Tuple[str, str]]:
    """Obtiene títulos y URLs absolutas de adjuntos en la fila."""
    atts = []
    inputs = row.find_elements(By.CSS_SELECTOR, "input[type='image'][onclick*='ViewBidAttachment.aspx']")
    for inp in inputs:
        onclick = inp.get_attribute("onclick") or ""
        url = _extract_url_from_onclick(onclick)
        if not url:
            continue
        title = inp.get_attribute("title") or "Adjunto"
        atts.append((title, url))
    return atts


def _extract_url_from_onclick(onclick: str) -> str:
    """Extrae la URL relativa a ViewBidAttachment desde el onclick."""
    m = re.search(r"openPopUp\(['\"]([^'\"]*ViewBidAttachment\.aspx[^'\"]*)", onclick)
    if not m:
        return ""
    rel = m.group(1)
    return rel if rel.startswith("http") else urljoin(BASE, rel)

def _extract_url_from_openpopup(onclick: str) -> str:
    """
    Extrae la URL (primer parámetro) desde openPopUp('...').
    Devuelve URL relativa o absoluta, o '' si no calza.
    """
    if not onclick:
        return ""
    m = re.search(r"openPopUp\(\s*['\"]([^'\"]+)['\"]", onclick)
    if not m:
        return ""
    return (m.group(1) or "").strip()


def _requests_session_from_driver(driver: webdriver.Chrome) -> requests.Session:
    """Crea sesión requests con cookies del driver."""
    sess = requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT, "Referer": driver.current_url})
    for c in driver.get_cookies():
        sess.cookies.set(c["name"], c["value"])
    return sess


def _download_file(session: requests.Session, url: str, name_hint: str) -> str:
    """Descarga un adjunto a DOWNLOAD_DIR; devuelve ruta o ''."""
    if not url:
        return ""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    try:
        resp = session.get(url, stream=True, timeout=60)
        resp.raise_for_status()
    except Exception as exc:
        print(f"Error descargando {url}: {exc}")
        return ""

    dispo = resp.headers.get("content-disposition", "")
    fname = _filename_from_disposition(dispo)
    if not fname:
        ext = _guess_ext(resp.headers.get("content-type", ""))
        fname = f"{name_hint}{ext}"

    safe_name = fname.replace("/", "-")
    path = os.path.join(DOWNLOAD_DIR, safe_name)
    try:
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except Exception as exc:
        print(f"Error guardando {path}: {exc}")
        return ""
    return path


def _filename_from_disposition(dispo: str) -> str:
    m = re.search(r'filename="?([^";]+)"?', dispo)
    return m.group(1) if m else ""


def _guess_ext(content_type: str) -> str:
    """Devuelve extensión simple según content-type."""
    ct = content_type.lower()
    if "pdf" in ct:
        return ".pdf"
    if "zip" in ct:
        return ".zip"
    if "msword" in ct or "officedocument" in ct or "doc" in ct:
        return ".doc"
    if "excel" in ct or "spreadsheet" in ct or "xls" in ct:
        return ".xls"
    if "xml" in ct:
        return ".xml"
    return ".bin"


def _normalize_type_dir(file_type: str) -> str:
    ft_raw = file_type or ""
    ft = unicodedata.normalize("NFKD", ft_raw).encode("ascii", "ignore").decode().lower()
    if "administrativ" in ft or "documento para contratar" in ft:
        return "Anexos_Administrativos"
    if "tecnic" in ft:
        return "Anexos_Tecnicos"
    if "econ" in ft:
        return "Anexos_Economicos"
    if "garant" in ft:
        return "Garantias"
    return "Otros"


def _parse_popup_metadata(html: str) -> dict:
    """
    Retorna dict ctlXX -> (filename, type) del grid DWNL.
    """
    meta = {}
    rows = re.findall(
        r'id="DWNL_grdId_(ctl\d+)_File">([^<]+)</span>.*?id="DWNL_grdId_\1_Type">([^<]+)</span>',
        html,
        flags=re.DOTALL,
    )
    for ctl, fname, ftype in rows:
        meta[ctl] = (fname.strip(), ftype.strip())
    return meta


def _download_attachment_popup(
    session: requests.Session,
    url: str,
    name_hint: str,
    current_rut: str = "",
    current_prov: str = "",
    icon_title: str = "",
) -> List[str]:
    """
    Descarga un adjunto de la página ViewBidAttachment.aspx realizando el POST
    que dispara cada botón de búsqueda.
    """
    downloaded_paths: List[str] = []
    pending_pages = ["1"]
    processed_pages = set()

    while pending_pages:
        page = pending_pages.pop(0)
        if page in processed_pages:
            continue
        processed_pages.add(page)

        # Obtiene HTML de la página/página específica
        try:
            if page == "1":
                resp = session.get(url, timeout=30)
            else:
                # Post para cambiar de página
                state = _parse_state(html) if "html" in locals() else {}
                data = state.copy()
                data["__EVENTTARGET"] = "DWNL$grdId"
                data["__EVENTARGUMENT"] = f"Page${page}"
                resp = session.post(url, data=data, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            print(f"Error al obtener popup/página {page} {url}: {exc}")
            continue

        html = resp.text
        state = _parse_state(html)
        search_names = re.findall(r'name="(DWNL\$grdId\$ctl\d+\$search)"', html)
        page_links = re.findall(r"__doPostBack\('DWNL\$grdId','Page\$(\d+)'", html)
        for p in page_links:
            if p not in processed_pages and p not in pending_pages:
                pending_pages.append(p)

        if not search_names:
            print(f"No se encontraron botones de descarga en popup {url} página {page}")
            continue

        meta = _parse_popup_metadata(html)

        for idx, name in enumerate(search_names, start=1):
            data = state.copy()
            data["__EVENTTARGET"] = name
            data["__EVENTARGUMENT"] = ""
            data[name + ".x"] = "10"
            data[name + ".y"] = "10"
            data.setdefault("DWNL$ctl10", "")
            try:
                r = session.post(url, data=data, stream=True, timeout=60)
                r.raise_for_status()
            except Exception as exc:
                print(f"Error al postear {name} en {url}: {exc}")
                continue
            ctl = name.split("$")[-2]  # ctlXX
            file_name, file_type = meta.get(ctl, ("", icon_title))
            saved = _save_stream_to_file(
                r,
                f"{name_hint}_{page}_{idx}",
                current_rut=current_rut,
                current_prov=current_prov,
                file_name=file_name,
                file_type=file_type,
            )
            if saved:
                downloaded_paths.append(saved)
                print(f"Descargado desde popup {url}: {saved}")
    return downloaded_paths


def _save_stream_to_file(
    resp: requests.Response,
    name_hint: str,
    current_rut: str = "",
    current_prov: str = "",
    file_name: str = "",
    file_type: str = "",
) -> str:
    dispo = resp.headers.get("content-disposition", "")
    fname = file_name or _filename_from_disposition(dispo)
    if not fname:
        ext = _guess_ext(resp.headers.get("content-type", ""))
        fname = f"{name_hint}{ext}"
    safe_name = fname.replace("/", "-")

    prov_dir = _normalize_provider_dir(current_prov)
    tipo_dir = _normalize_type_dir(file_type or fname)
    base_path = os.path.join(DOWNLOAD_DIR, prov_dir, tipo_dir)
    os.makedirs(base_path, exist_ok=True)
    path = os.path.join(base_path, safe_name)
    try:
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return path
    except Exception as exc:
        print(f"Error guardando {path}: {exc}")
        return ""


def _extract_hidden(html: str, field: str) -> str:
    m = re.search(rf'name="{re.escape(field)}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _parse_state(html: str) -> dict:
    state = {}
    for field in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        val = _extract_hidden(html, field)
        if val:
            state[field] = val
    return state


def _configure_stealth(driver: webdriver.Chrome) -> None:
    """Ajustes básicos para parecer usuario real."""
    try:
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {"userAgent": USER_AGENT, "acceptLanguage": "es-CL,es;q=0.9,en;q=0.8"},
        )
    except Exception:
        pass
    script = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
    Object.defineProperty(navigator, 'language', {get: () => 'es-CL'});
    Object.defineProperty(navigator, 'languages', {get: () => ['es-CL', 'es', 'en']});
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
    except Exception:
        pass


def main() -> None:
    driver = build_driver()
    wait = WebDriverWait(driver, 60)

    try:
        print("Abriendo la licitación...")
        driver.get(URL)
        cuadro_btn = wait.until(EC.element_to_be_clickable((By.ID, "imgCuadroOferta")))
        print("Botón 'Cuadro de ofertas' listo, haciendo click...")
        cuadro_btn.click()

        if not open_frame_directly(driver, wait, base_url=URL):
            print("No se pudo abrir directamente el OpeningFrame.")
            return
        # Esperar carga completa del documento
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(2.0)
        os.makedirs("capturas", exist_ok=True)
        debug_html_path = os.path.join("capturas", "opening_debug.html")
        with open(debug_html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"HTML guardado en {debug_html_path} (largo {len(driver.page_source)})")
        print(f"Handle actual: {driver.current_window_handle}")
        print(f"Handles disponibles: {driver.window_handles}")
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"Cantidad de iframes en la página: {len(frames)} -> {[f.get_attribute('src') for f in frames[:5]]}")
        # Log rápido de elementos clave
        print(f"Filas encontradas sin espera: {len(driver.find_elements(By.CSS_SELECTOR, '#grdSupplies tr'))}")
        print(
            f"Botones admin sin espera: "
            f"{len(driver.find_elements(By.CSS_SELECTOR, 'input[id$=\"_GvImgbAdministrativeAttachment\"]'))}"
        )

        # Si es frameset, entra al frame Cuerpo
        switched_cuerpo = switch_to_cuerpo_frame(driver, wait)
        if switched_cuerpo:
            os.makedirs("capturas", exist_ok=True)
            cuerpo_path = os.path.join("capturas", "cuerpo_debug.html")
            with open(cuerpo_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"HTML del frame Cuerpo guardado en {cuerpo_path} (largo {len(driver.page_source)})")

        # Primero intenta encontrar la tabla directamente.
        try:
            wait.until(
                EC.presence_of_all_elements_located(
                    (
                        By.CSS_SELECTOR,
                        "#grdSupplies tr.cssFwkItemStyle, #grdSupplies tr.cssFwkAlternatingItemStyle",
                    )
                )
            )
            count_elements(driver)
            return
        except TimeoutException:
            print("No se encontró la tabla grdSupplies en la página directa; se intentará buscar en iframes internos.")
        except Exception as exc:
            print(f"Error inesperado buscando tabla directa: {exc}")

        # Algunos contenidos anidan otro iframe SupplySummary; probar allí.
        switch_to_supply_summary(driver)
        try:
            wait.until(
                EC.presence_of_all_elements_located(
                    (
                        By.CSS_SELECTOR,
                        "#grdSupplies tr.cssFwkItemStyle, #grdSupplies tr.cssFwkAlternatingItemStyle",
                    )
                )
            )
        except TimeoutException:
            print("No se encontró la tabla grdSupplies tras buscar en iframes.")
            return
        except Exception as exc:
            print(f"Error inesperado buscando tabla en iframe: {exc}")
            return
        count_elements(driver)
    finally:
        # Cierra el navegador al terminar para evitar procesos colgados.
        driver.quit()


if __name__ == "__main__":
    main()


def descargar_adjuntos_desde_url(url: str, driver: webdriver.Chrome, codigo: str | None = None, download_dir: str | None = None) -> dict:
    """
    Abre la licitación indicada, ingresa al Cuadro de Ofertas y descarga adjuntos
    usando la misma lógica de scrape_cuadro, devolviendo un resumen.
    """
    wait = WebDriverWait(driver, 60)
    global DOWNLOAD_DIR
    previo_dir = DOWNLOAD_DIR
    destino = download_dir
    if not destino:
        destino = os.path.join("Descargas", "Licitaciones", codigo or "sin_codigo")
    DOWNLOAD_DIR = destino

    resultado = {"ok": False, "descargados": 0, "download_dir": destino, "errores": [], "proveedores": []}

    try:
        print(f"[SCRAPE_CUADRO] Abriendo URL directa: {url}")
        driver.get(url)
    except Exception as exc:
        resultado["errores"].append(f"No se pudo abrir la URL: {exc}")
        return resultado

    try:
        cuadro_btn = wait.until(EC.element_to_be_clickable((By.ID, "imgCuadroOferta")))
        cuadro_btn.click()
    except Exception as exc:
        resultado["errores"].append(f"No se pudo hacer click en 'Cuadro de ofertas': {exc}")
        return resultado

    try:
        if not open_frame_directly(driver, wait, base_url=url):
            resultado["errores"].append("No se pudo abrir OpeningFrame del cuadro.")
            return resultado
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(1.5)
    except Exception as exc:
        resultado["errores"].append(f"Error abriendo OpeningFrame: {exc}")
        return resultado

    try:
        switch_to_cuerpo_frame(driver, wait)
    except Exception:
        pass

    try:
        wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "#grdSupplies tr.cssFwkItemStyle, #grdSupplies tr.cssFwkAlternatingItemStyle")
            )
        )
    except TimeoutException:
        # Intentar dentro de iframe interno de resumen
        try:
            switch_to_supply_summary(driver)
            wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "#grdSupplies tr.cssFwkItemStyle, #grdSupplies tr.cssFwkAlternatingItemStyle")
                )
            )
        except Exception as exc:
            resultado["errores"].append(f"No se encontró la tabla de ofertas: {exc}")
            return resultado
    except Exception as exc:
        resultado["errores"].append(f"Error esperando la tabla de ofertas: {exc}")
        return resultado

    try:
        descargados, proveedores_meta = _count_elements_with_providers(driver)
        proveedores_meta = proveedores_meta or []

        # Asegurar carpetas de proveedores aunque no tengan adjuntos
        for prov in proveedores_meta:
            carpeta_rel = (prov.get("carpeta_rel") or "").strip()
            if not carpeta_rel:
                continue
            try:
                os.makedirs(os.path.join(destino, carpeta_rel), exist_ok=True)
            except Exception:
                pass

        # Descargar certificados por proveedor (si hay código y RUT)
        if codigo and proveedores_meta:
            for prov in proveedores_meta:
                rut = (prov.get("rut") or "").strip()
                carpeta_rel = (prov.get("carpeta_rel") or "").strip()
                if not rut or not carpeta_rel:
                    continue

                carpeta_prov = os.path.join(destino, carpeta_rel)
                carpeta_certificados = os.path.join(carpeta_prov, "Certificados")
                try:
                    os.makedirs(carpeta_certificados, exist_ok=True)
                except Exception:
                    pass

                try:
                    descarga_ca.descargar_declaracion_jurada_licitacion_a_carpeta(
                        codigo,
                        rut,
                        carpeta_certificados,
                        driver=driver,
                        nombre_archivo="DeclaracionJurada.pdf",
                    )
                except Exception:
                    pass

                try:
                    descarga_ca.descargar_certificado_habilidad_a_carpeta(
                        rut,
                        carpeta_certificados,
                        driver=driver,
                        nombre_archivo="CertificadoHabilidad.pdf",
                    )
                except Exception:
                    pass

                # Comprobante de oferta (voucherview.aspx) -> PDF
                voucher_url = (prov.get("voucher_url") or "").strip()
                if voucher_url:
                    try:
                        descarga_ca.descargar_pdf_a_archivo(
                            voucher_url,
                            os.path.join(carpeta_certificados, "ComprobanteOferta.pdf"),
                            driver=driver,
                            tag="[VOUCHER]",
                        )
                    except Exception:
                        pass

        resultado["descargados"] = descargados
        resultado["ok"] = descargados > 0
        resultado["proveedores"] = _build_proveedores_resumen(destino, proveedores_meta=proveedores_meta)
        return resultado
    except Exception as exc:
        resultado["errores"].append(f"Error descargando adjuntos: {exc}")
        return resultado
    finally:
        DOWNLOAD_DIR = previo_dir


def _build_proveedores_resumen(destino: str, proveedores_meta: List[dict] | None = None) -> List[dict]:
    """
    Construye una lista de proveedores basada en la estructura de carpetas creada por _save_stream_to_file:
      destino/{Proveedor}/{Tipo}/archivo

    Esto permite reutilizar el flujo de zips + Excel en producción aunque el scraping no entregue
    una lista explícita de proveedores.
    """
    proveedores: List[dict] = []
    if not destino or not os.path.isdir(destino):
        return proveedores

    def _count_files(path: str) -> int:
        if not os.path.isdir(path):
            return 0
        total = 0
        for _, _, files in os.walk(path):
            total += len(files)
        return total

    meta_by_dir = {}
    for prov in proveedores_meta or []:
        carpeta_rel = (prov.get("carpeta_rel") or "").strip()
        if not carpeta_rel:
            continue
        meta_by_dir[carpeta_rel] = prov

    def _match_tipo(tipo_dir: str) -> str:
        t = (tipo_dir or "").lower()
        if t == "certificados":
            return "ignorar"
        if "administrativ" in t:
            return "admin"
        if "tecnic" in t:
            return "tecnico"
        if "econ" in t:
            return "economico"
        return "otros"

    for carpeta_rel in sorted(os.listdir(destino)):
        prov_path = os.path.join(destino, carpeta_rel)
        if not os.path.isdir(prov_path):
            continue

        counts = {"admin": 0, "tecnico": 0, "economico": 0, "otros": 0}
        for tipo_dir in os.listdir(prov_path):
            tipo_path = os.path.join(prov_path, tipo_dir)
            if not os.path.isdir(tipo_path):
                continue
            bucket = _match_tipo(tipo_dir)
            if bucket == "ignorar":
                continue
            counts[bucket] += _count_files(tipo_path)

        total = counts["admin"] + counts["tecnico"] + counts["economico"] + counts["otros"]
        meta = meta_by_dir.get(carpeta_rel) or {}
        rut = (meta.get("rut") or "").strip()
        nombre = (meta.get("nombre") or "").strip() or carpeta_rel
        proveedores.append(
            {
                "rut": rut,
                "nombre": nombre,
                "carpeta": prov_path,
                "admin": {"descargados": counts["admin"], "errores": []},
                "tecnico": {"descargados": counts["tecnico"], "errores": []},
                "economico": {"descargados": counts["economico"], "errores": []},
                "otros": {"descargados": counts["otros"], "errores": []},
                "total_descargados": total,
            }
        )
    return proveedores
