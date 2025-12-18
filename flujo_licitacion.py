# flujo_licitacion.py
# Flujo de prueba para licitaciones (scraping, sin API) hasta anexos administrativos/técnicos/económicos.

import os
import re
import time
from urllib.parse import urljoin, unquote, urlparse

import requests
import descarga_ca
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BUSCADOR_URL = "https://mercadopublico.cl/Procurement/Modules/RFB/SearchAcquisitions.aspx"


def obtener_url_licitacion(codigo_lici, driver, timeout=20):
    """
    Busca el código en el buscador de licitaciones y devuelve la URL de la ficha si se encuentra.
    Abre el resultado para capturar la URL real (DetailsAcquisition.aspx?qs=...).
    """
    wait = WebDriverWait(driver, timeout)
    try:
        driver.get(BUSCADOR_URL)
        campo_codigo = wait.until(EC.presence_of_element_located((By.ID, "txt_Nombre")))
        campo_codigo.clear()
        campo_codigo.send_keys(codigo_lici)

        btn_buscar = wait.until(EC.element_to_be_clickable((By.ID, "buttonSearchByAll")))
        btn_buscar.click()
    except Exception:
        return ""

    try:
        enlace = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//a[contains(@id,'hlkNumAcquisition') and normalize-space(text())='{codigo_lici}']")
            )
        )
    except Exception:
        try:
            enlace = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@id,'hlkNumAcquisition')]")))
        except Exception:
            return ""

    handle_original = driver.current_window_handle
    handles_prev = driver.window_handles[:]
    try:
        driver.execute_script("arguments[0].click();", enlace)
    except Exception:
        try:
            enlace.click()
        except Exception:
            return ""

    nuevo_handle = _esperar_nueva_ventana(driver, handles_prev, timeout=10)
    if not nuevo_handle:
        return ""

    url_ficha = ""
    try:
        driver.switch_to.window(nuevo_handle)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        url_ficha = driver.current_url or ""
    except Exception:
        url_ficha = ""
    finally:
        try:
            driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(handle_original)
        except Exception:
            pass

    return url_ficha


def test_flujo_licitacion(codigo_lici, driver, carpeta_base="Descargas/Licitaciones", url_directa=None):
    """
    Ejecuta el flujo de licitación:
    - Busca el código
    - Abre la ficha
    - Entra al Cuadro de Ofertas
    - Abre los anexos administrativos/técnicos/económicos del cuadro y los descarga a carpetas separadas.
    """
    wait = WebDriverWait(driver, 20)
    session = _requests_session_from_driver(driver)

    resumen = {"ok": False, "proveedores": [], "errores": []}

    if url_directa:
        try:
            driver.get(url_directa)
        except Exception as e:
            resumen["errores"].append(f"No se pudo abrir URL directa: {e}")
            return resumen
    else:
        try:
            driver.get(BUSCADOR_URL)
            campo_codigo = wait.until(EC.presence_of_element_located((By.ID, "txt_Nombre")))
            campo_codigo.clear()
            campo_codigo.send_keys(codigo_lici)

            btn_buscar = wait.until(EC.element_to_be_clickable((By.ID, "buttonSearchByAll")))
            btn_buscar.click()
        except Exception as e:
            resumen["errores"].append(f"No se pudo buscar la licitación: {e}")
            return resumen

        # Abrir la licitación desde resultados
        try:
            enlace = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, f"//a[contains(@id,'hlkNumAcquisition') and normalize-space(text())='{codigo_lici}']")
                )
            )
        except Exception:
            try:
                enlace = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@id,'hlkNumAcquisition')]")))
            except Exception as e:
                resumen["errores"].append(f"No se encontró la licitación en resultados: {e}")
                return resumen

    handle_original = driver.current_window_handle
    handle_ficha = _click_y_capturar_nueva_ventana(driver, enlace) if not url_directa else driver.current_window_handle
    driver.switch_to.window(handle_ficha)

    # Cuadro de ofertas
    try:
        btn_cuadro = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//input[contains(@id,'imgCuadroOferta')]"))
        )
    except Exception as e:
        resumen["errores"].append(f"No se encontró botón Cuadro de Ofertas: {e}")
        return resumen

    handle_cuadro = _click_y_capturar_nueva_ventana(driver, btn_cuadro) or driver.current_window_handle
    print(f"[LICI] Handles tras abrir Cuadro: {driver.window_handles}, usando={handle_cuadro}")
    driver.switch_to.window(handle_cuadro)
    _debug_dump_context(driver, "post-cuadro")

    # Procesar tabla de ofertas
    carpeta_lici = os.path.join(carpeta_base, codigo_lici)
    os.makedirs(carpeta_lici, exist_ok=True)

    proveedores_info = _procesar_cuadro_ofertas(driver, wait, session, carpeta_lici)
    resumen["proveedores"] = proveedores_info
    resumen["ok"] = any(p.get("total_descargados", 0) > 0 for p in proveedores_info) or len(proveedores_info) > 0

    try:
        driver.switch_to.window(handle_original)
    except Exception:
        pass

    return resumen


def _procesar_cuadro_ofertas(driver, wait, session, carpeta_lici):
    proveedores = []
    _debug_dump_context(driver, "procesar_cuadro_ofertas")
    tabla = _buscar_tabla_ofertas(driver, wait)
    if not tabla:
        print("[LICI] No se encontró la tabla de ofertas (grdSupplies) en la ventana/iframe actual.")
        return proveedores

    try:
        print(f"[LICI] Tabla encontrada id={tabla.get_attribute('id')} filas={len(tabla.find_elements(By.XPATH, './/tr'))}")
    except Exception as e:
        print(f"[LICI] Tabla encontrada, error leyendo info: {e}")

    filas = tabla.find_elements(By.XPATH, ".//tr[td]")
    for idx, fila in enumerate(filas[1:], 1):  # omitir encabezado
        celdas = fila.find_elements(By.TAG_NAME, "td")
        if len(celdas) < 5:
            continue

        rut = celdas[0].text.strip()
        nombre_prov = celdas[1].text.strip() or f"PROVEEDOR_{idx}"
        nombre_folder = _limpiar_nombre_archivo(nombre_prov or f"PROV_{idx}")
        carpeta_prov = os.path.join(carpeta_lici, nombre_folder)
        os.makedirs(carpeta_prov, exist_ok=True)

        print(f"[LICI] Procesando proveedor: {nombre_prov} ({rut})")

        res_admin = _descargar_anexos_tipo(
            driver, fila, session, carpeta_prov, "Administrativos", ["_GvImgbAdministrativeAttachment"]
        )
        res_tecnico = _descargar_anexos_tipo(
            driver, fila, session, carpeta_prov, "Tecnicos", ["_GvImgbTechnicalAttachment", "_GvImgbTechnical"]
        )
        res_economico = _descargar_anexos_tipo(
            driver, fila, session, carpeta_prov, "Economicos", ["_GvImgbEconomicAttachment", "_GvImgbEconomic"]
        )
        res_certificados = _descargar_certificados_proveedor(rut, carpeta_prov, driver)
        res_comprobante = _descargar_comprobante_oferta(driver, fila, carpeta_prov)

        total_descargados = res_admin["descargados"] + res_tecnico["descargados"] + res_economico["descargados"]
        proveedores.append(
            {
                "rut": rut,
                "nombre": nombre_prov,
                "carpeta": carpeta_prov,
                "admin": res_admin,
                "tecnico": res_tecnico,
                "economico": res_economico,
                "certificados": res_certificados,
                "comprobante": res_comprobante,
                "total_descargados": total_descargados,
            }
        )

    return proveedores


def _descargar_anexos_tipo(driver, fila, session, carpeta_prov, etiqueta, selectors_substrings):
    resumen = {"descargados": 0, "errores": []}
    try:
        boton = None
        for sub in selectors_substrings:
            botones = fila.find_elements(By.CSS_SELECTOR, f"input[id*='{sub}']")
            if botones:
                boton = botones[0]
                break
        if not boton:
            return resumen

        carpeta_tipo = os.path.join(carpeta_prov, etiqueta.upper())
        os.makedirs(carpeta_tipo, exist_ok=True)

        # Si el botón contiene la URL del popup, descargar adjuntos vía requests sin abrir ventana.
        popup_url = _extraer_url_viewbid(boton, driver.current_url)
        if popup_url:
            descargados, errores = _descargar_adjuntos_viewbid(session, popup_url, carpeta_tipo)
            resumen["descargados"] += descargados
            resumen["errores"].extend(errores)
            if descargados:
                return resumen

        handle_base = driver.current_window_handle
        handles_prev = driver.window_handles[:]
        try:
            driver.execute_script("arguments[0].click();", boton)
        except Exception:
            try:
                boton.click()
            except Exception as e:
                resumen["errores"].append(f"Click {etiqueta} falló: {e}")
                return resumen

        handle_popup = _esperar_nueva_ventana(driver, handles_prev)
        popup_handle = handle_popup or driver.current_window_handle
        driver.switch_to.window(popup_handle)

        try:
            popup_url = driver.current_url
            descargados, errores = _descargar_adjuntos_viewbid(session, popup_url, carpeta_tipo)
            if descargados == 0:
                descargados = _descargar_adjuntos_popup(driver, session, carpeta_tipo)
            resumen["descargados"] = descargados
            resumen["errores"].extend(errores)
        except Exception as e:
            resumen["errores"].append(f"Error descargando {etiqueta}: {e}")
        finally:
            # Cerrar popup si corresponde
            if handle_popup:
                try:
                    driver.close()
                except Exception:
                    pass
                try:
                    driver.switch_to.window(handle_base)
                    driver.switch_to.default_content()
                except Exception:
                    pass
            else:
                try:
                    driver.switch_to.window(handle_base)
                    driver.switch_to.default_content()
                except Exception:
                    pass

    except Exception as e:
        resumen["errores"].append(str(e))
    return resumen


def _descargar_certificados_proveedor(rut, carpeta_prov, driver):
    """
    Descarga certificados del proveedor (declaración jurada y certificado de habilidad) reutilizando la lógica de compra ágil.
    """
    resumen = {"declaracion": False, "habilidad": False, "errores": []}
    try:
        ok_dj = descarga_ca.descargar_declaracion_jurada(rut, carpeta_prov, driver=driver)
        resumen["declaracion"] = bool(ok_dj)
        if not ok_dj:
            resumen["errores"].append("Declaración jurada no descargada")
    except Exception as exc:
        resumen["errores"].append(f"Error DJ: {exc}")

    try:
        ok_hab = descarga_ca.descargar_certificado_habilidad(rut, carpeta_prov, driver=driver)
        resumen["habilidad"] = bool(ok_hab)
        if not ok_hab:
            resumen["errores"].append("Certificado de habilidad no descargado")
    except Exception as exc:
        resumen["errores"].append(f"Error habilidad: {exc}")

    return resumen


def _descargar_comprobante_oferta(driver, fila, carpeta_prov):
    """
    Intenta abrir y guardar el comprobante de oferta (HTML) desde la fila del proveedor.
    """
    resumen = {"guardado": False, "archivo": "", "errores": []}
    try:
        botones = fila.find_elements(
            By.XPATH,
            ".//input[contains(@title,'Comprobante') or contains(@id,'Comprobante') or contains(@onclick,'Comprobante') or contains(@src,'comprobante')]",
        )
        boton = botones[0] if botones else None
        if not boton:
            candidatos = fila.find_elements(By.XPATH, ".//input[@type='image' or @type='button' or @type='submit']")
            if candidatos:
                boton = candidatos[-1]
        if not boton:
            return resumen

        handle_base = driver.current_window_handle
        handles_prev = driver.window_handles[:]
        try:
            driver.execute_script("arguments[0].click();", boton)
        except Exception:
            try:
                boton.click()
            except Exception as exc:
                resumen["errores"].append(f"Click comprobante falló: {exc}")
                return resumen

        handle_popup = _esperar_nueva_ventana(driver, handles_prev, timeout=10)
        if handle_popup:
            driver.switch_to.window(handle_popup)
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception:
            pass

        try:
            html = driver.page_source or ""
        except Exception as exc:
            resumen["errores"].append(f"No se pudo leer HTML del comprobante: {exc}")
            html = ""

        if html:
            carpeta_comp = os.path.join(carpeta_prov, "COMPROBANTE")
            os.makedirs(carpeta_comp, exist_ok=True)
            destino = os.path.join(carpeta_comp, "ComprobanteOferta.html")
            with open(destino, "w", encoding="utf-8") as f:
                f.write(html)
            resumen["guardado"] = True
            resumen["archivo"] = destino
            print(f"[LICI] Comprobante de oferta guardado en {destino}")

        if handle_popup:
            try:
                driver.close()
            except Exception:
                pass
            try:
                driver.switch_to.window(handle_base)
            except Exception:
                pass

    except Exception as exc:
        resumen["errores"].append(f"Error comprobante: {exc}")
        try:
            driver.switch_to.window(driver.window_handles[0])
        except Exception:
            pass

    return resumen


def _descargar_adjuntos_popup(driver, session, carpeta_destino):
    """
    En la ventana de adjuntos, recorre las filas y descarga los links de 'Ver' o los href.
    """
    try:
        current_url = driver.current_url
    except Exception:
        current_url = ""
    if "ViewBidAttachment.aspx" in (current_url or ""):
        descargados, _ = _descargar_adjuntos_viewbid(session, current_url, carpeta_destino)
        return descargados

    descargados = 0
    wait = WebDriverWait(driver, 15)
    try:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass

    links = driver.find_elements(
        By.XPATH,
        "//a[contains(@href,'http') or contains(@href,'Download') or contains(@href,'View') or "
        "contains(@href,'.pdf') or contains(@href,'.doc') or contains(@href,'.xls') or contains(@href,'.jpg') "
        "or contains(@href,'.jpeg') or contains(@href,'.png')]"
    )
    # Si no hay enlaces claros, intentar botones de lupa
    if not links:
        links = driver.find_elements(
            By.XPATH,
            "//input[contains(@onclick,'Download') or contains(@onclick,'open') or contains(@onclick,'View')]"
        )
    # Si sigue vacío, intentar dentro de iframes
    if not links:
        _switch_to_frame_containing(driver, (By.XPATH, "//table"))
        links = driver.find_elements(
            By.XPATH,
            "//a[contains(@href,'http') or contains(@href,'Download') or contains(@href,'View') or "
            "contains(@href,'.pdf') or contains(@href,'.doc') or contains(@href,'.xls') or contains(@href,'.jpg') "
            "or contains(@href,'.jpeg') or contains(@href,'.png')]"
        )
        if not links:
            links = driver.find_elements(
                By.XPATH,
                "//input[contains(@onclick,'Download') or contains(@onclick,'open') or contains(@onclick,'View')]"
            )

    for link in links:
        try:
            href = link.get_attribute("href")
            onclick = link.get_attribute("onclick") or ""
            url = None
            if href and "javascript" not in href.lower():
                url = href
            else:
                m = re.search(r"(['\"])(https?://[^'\"]+)", onclick)
                if m:
                    url = m.group(2)
                else:
                    m = re.search(r"['\"](/[^'\"]+)", onclick)
                    if m:
                        url = urljoin(driver.current_url, m.group(1))
            if not url:
                continue

            nombre = _inferir_nombre(url, link.text)
            ruta_archivo = _descargar_archivo(session, url, carpeta_destino, nombre)
            if ruta_archivo:
                descargados += 1
        except Exception:
            continue

    return descargados


def _descargar_adjuntos_viewbid(session, url, carpeta_destino):
    """
    Descarga adjuntos desde ViewBidAttachment.aspx replicando la lógica robusta de scrape_cuadro.py.
    """
    descargados = 0
    errores = []
    if not url:
        return descargados, errores

    try:
        session.headers.setdefault("Referer", url)
    except Exception:
        pass

    pending_pages = ["1"]
    processed_pages = set()
    state = {}
    os.makedirs(carpeta_destino, exist_ok=True)

    while pending_pages:
        page = pending_pages.pop(0)
        if page in processed_pages:
            continue
        processed_pages.add(page)

        try:
            if page == "1":
                resp = session.get(url, timeout=30)
            else:
                data = state.copy()
                data["__EVENTTARGET"] = "DWNL$grdId"
                data["__EVENTARGUMENT"] = f"Page${page}"
                resp = session.post(url, data=data, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            errores.append(f"Error al obtener popup página {page}: {exc}")
            continue

        html = resp.text
        state = _parse_state(html)
        search_names = re.findall(r'name="(DWNL\$grdId\$ctl\d+\$search)"', html)
        page_links = re.findall(r"__doPostBack\\('DWNL\$grdId','Page\$(\d+)'", html)
        for p in page_links:
            if p not in processed_pages and p not in pending_pages:
                pending_pages.append(p)

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
                errores.append(f"Error al postear {name} (página {page}): {exc}")
                continue

            ctl = name.split("$")[-2] if "$" in name else ""
            file_name, _file_type = meta.get(ctl, ("", ""))
            saved = _guardar_stream_descarga(
                r,
                carpeta_destino,
                name_hint=f"{page}_{idx}",
                file_name=file_name,
                fallback_ext=_guess_ext(r.headers.get("content-type", "")),
            )
            if saved:
                descargados += 1

    return descargados, errores


def _requests_session_from_driver(driver):
    session = requests.Session()
    try:
        for cookie in driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
    except Exception:
        pass
    try:
        ua = driver.execute_script("return navigator.userAgent") or ""
        if ua:
            session.headers.setdefault("User-Agent", ua)
    except Exception:
        pass
    try:
        ref = driver.current_url
        if ref:
            session.headers.setdefault("Referer", ref)
    except Exception:
        pass
    return session


def _extraer_url_viewbid(elemento, base_url):
    """Extrae la URL absoluta de ViewBidAttachment desde onclick/href."""
    try:
        onclick = elemento.get_attribute("onclick") or ""
    except Exception:
        onclick = ""
    m = re.search(r"openPopUp\(['\"]([^'\"]*ViewBidAttachment\.aspx[^'\"]*)", onclick, flags=re.IGNORECASE)
    if m:
        rel = m.group(1)
        return rel if rel.startswith("http") else urljoin(base_url, rel)
    try:
        href = elemento.get_attribute("href") or ""
    except Exception:
        href = ""
    if "ViewBidAttachment.aspx" in href:
        return href if href.startswith("http") else urljoin(base_url, href)
    return ""


def _inferir_nombre(url, texto):
    texto = (texto or "").strip()
    parsed = urlparse(url)
    base = os.path.basename(parsed.path)
    if base:
        base = unquote(base)
    if texto and len(texto) > 3:
        texto = _limpiar_nombre_archivo(texto)
        if "." in texto:
            return texto
    if base:
        return _limpiar_nombre_archivo(base)
    return "archivo"


def _descargar_archivo(session, url, carpeta, nombre):
    os.makedirs(carpeta, exist_ok=True)
    resp = session.get(url, stream=True, timeout=60)
    resp.raise_for_status()

    # Si content-disposition trae un nombre, usarlo
    dispo = resp.headers.get("content-disposition") or resp.headers.get("Content-Disposition")
    if dispo:
        m = re.search(r"filename\\*=(?:UTF-8''|utf-8'')?([^;]+)", dispo)
        if m:
            candidato = unquote(m.group(1).strip().strip('"').strip("'"))
            if candidato:
                nombre = candidato
        else:
            m = re.search(r"filename=([^;]+)", dispo)
            if m:
                candidato = m.group(1).strip().strip('"').strip("'")
                if candidato:
                    nombre = candidato

    nombre = _asegurar_nombre_unico(carpeta, _limpiar_nombre_archivo(nombre))
    ruta = os.path.join(carpeta, nombre)
    with open(ruta, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"[LICI] Descargado: {ruta}")
    return ruta


def _extract_hidden(html, field):
    m = re.search(rf'name="{re.escape(field)}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _parse_state(html):
    state = {}
    for field in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        val = _extract_hidden(html, field)
        if val:
            state[field] = val
    return state


def _parse_popup_metadata(html):
    """
    Devuelve un dict ctlXX -> (filename, type) del grid DWNL.
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


def _filename_from_disposition(dispo):
    m = re.search(r'filename="?([^";]+)"?', dispo or "")
    return m.group(1) if m else ""


def _guess_ext(content_type):
    """Devuelve una extensión simple a partir del content-type."""
    ct = (content_type or "").lower()
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
    if "jpeg" in ct:
        return ".jpg"
    if "png" in ct:
        return ".png"
    return ".bin"


def _guardar_stream_descarga(resp, carpeta_destino, name_hint, file_name="", fallback_ext=".bin"):
    dispo = resp.headers.get("content-disposition") or resp.headers.get("Content-Disposition") or ""
    fname = file_name or _filename_from_disposition(dispo)
    if not fname:
        ext = fallback_ext if fallback_ext.startswith(".") else f".{fallback_ext or 'bin'}"
        fname = f"{name_hint}{ext}"
    safe_name = _asegurar_nombre_unico(carpeta_destino, _limpiar_nombre_archivo(fname))
    path = os.path.join(carpeta_destino, safe_name)
    try:
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"[LICI] Descargado desde popup: {path}")
        return path
    except Exception as exc:
        print(f"[LICI] Error guardando {path}: {exc}")
        return ""


def _click_y_capturar_nueva_ventana(driver, elemento):
    handles_prev = driver.window_handles[:]
    print(f"[LICI] Handles antes de click: {handles_prev}")
    try:
        driver.execute_script("arguments[0].click();", elemento)
    except Exception:
        try:
            elemento.click()
        except Exception:
            return None
    nuevo = _esperar_nueva_ventana(driver, handles_prev)
    print(f"[LICI] Handles después de click: {driver.window_handles}, nuevo={nuevo}")
    return nuevo


def _esperar_nueva_ventana(driver, handles_prev, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(lambda d: len(d.window_handles) > len(handles_prev))
        for h in driver.window_handles:
            if h not in handles_prev:
                return h
    except Exception:
        return None
    return None


def _switch_to_frame_containing(driver, locator, timeout=2):
    """
    Recorre iframes/frames y cambia al primero que contenga el elemento indicado por locator.
    """
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
    for frame in frames:
        try:
            driver.switch_to.frame(frame)
            elems = driver.find_elements(*locator)
            if elems:
                return True
        except Exception:
            continue
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
    return False


def _buscar_tabla_ofertas(driver, wait):
    """
    Busca la tabla de ofertas (grdSupplies) en la ventana actual o dentro de iframes.
    """
    try:
        tablas = driver.find_elements(By.CSS_SELECTOR, "table")
        print(f"[LICI] Tablas visibles (contexto actual): {len(tablas)}")
        if tablas[:3]:
            print("       Primeras tablas ids:", [t.get_attribute("id") for t in tablas[:3]])
    except Exception as e:
        print(f"[LICI] No se pudieron listar tablas en contexto actual: {e}")
    try:
        encontrado = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table[id*='grdSupplies']")))
        return encontrado
    except Exception:
        pass

    # Probar recursivamente en iframes/frames
    locator = (By.CSS_SELECTOR, "table[id*='grdSupplies']")
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    tabla = _find_element_in_frames(driver, locator, max_depth=4)
    if tabla:
        print("[LICI] Tabla encontrada dentro de algún frame.")
        return tabla
    print("[LICI] No se encontró frame con la tabla de ofertas.")
    return None


def _find_element_in_frames(driver, locator, max_depth=3):
    """
    Busca un elemento tratando de descender en iframes/frames hasta max_depth.
    Devuelve el elemento si lo encuentra y deja el foco en el frame donde está.
    """
    try:
        elem = driver.find_element(*locator)
        return elem
    except Exception:
        pass
    if max_depth <= 0:
        return None
    frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
    print(f"[LICI] Buscando en {len(frames)} frames (depth={max_depth})")
    for i, frame in enumerate(frames, 1):
        try:
            src = frame.get_attribute("src")
            print(f"   [LICI] Entrando frame {i} src={src}")
            driver.switch_to.frame(frame)
            found = _find_element_in_frames(driver, locator, max_depth=max_depth - 1)
            if found:
                return found  # Mantenernos en el frame donde se encontró
        except Exception as e:
            print(f"   [LICI] No se pudo entrar a frame {i}: {e}")
        # Si no se encontró en este frame, volver al contexto anterior
        try:
            driver.switch_to.parent_frame()
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
    return None


def _debug_dump_context(driver, label):
    try:
        print(f"[LICI][{label}] URL: {driver.current_url}")
        print(f"[LICI][{label}] Title: {driver.title}")
        print(f"[LICI][{label}] Handles: {driver.window_handles}")
    except Exception:
        pass
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
        print(f"[LICI][{label}] Frames encontrados: {len(frames)}")
        for i, fr in enumerate(frames[:5], 1):
            try:
                src = fr.get_attribute("src")
                print(f"   Frame {i}: src={src}")
            except Exception:
                continue
    except Exception:
        pass


def _asegurar_nombre_unico(carpeta, nombre):
    base, ext = os.path.splitext(nombre)
    if not base:
        base = "archivo"
    candidato = f"{base}{ext}"
    i = 2
    while os.path.exists(os.path.join(carpeta, candidato)):
        candidato = f"{base} ({i}){ext}"
        i += 1
    return candidato


def _limpiar_nombre_archivo(nombre, max_len=160):
    nombre = (nombre or "").strip()
    nombre = re.sub(r'[<>:"/\\\\|?*]', "_", nombre)
    nombre = re.sub(r"\\s+", " ", nombre)
    if len(nombre) > max_len:
        nombre = nombre[:max_len].rstrip()
    return nombre or "archivo"


if __name__ == "__main__":
    print("Este módulo está pensado para ser usado desde app.py (botón Testear flujo licitación).")
