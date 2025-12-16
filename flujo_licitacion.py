# flujo_licitacion.py
# Flujo de prueba para licitaciones (scraping, sin API) hasta anexos administrativos/técnicos/económicos.

import os
import re
import time
from urllib.parse import urljoin, unquote, urlparse

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BUSCADOR_URL = "https://mercadopublico.cl/Procurement/Modules/RFB/SearchAcquisitions.aspx"


def test_flujo_licitacion(codigo_lici, driver, carpeta_base="Descargas/Licitaciones"):
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
    handle_ficha = _click_y_capturar_nueva_ventana(driver, enlace) or driver.current_window_handle
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
    driver.switch_to.window(handle_cuadro)

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
    tabla = _buscar_tabla_ofertas(driver, wait)
    if not tabla:
        print("[LICI] No se encontró la tabla de ofertas (grdSupplies) en la ventana/iframe actual.")
        return proveedores

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

        total_descargados = res_admin["descargados"] + res_tecnico["descargados"] + res_economico["descargados"]
        proveedores.append(
            {
                "rut": rut,
                "nombre": nombre_prov,
                "carpeta": carpeta_prov,
                "admin": res_admin,
                "tecnico": res_tecnico,
                "economico": res_economico,
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
            descargados = _descargar_adjuntos_popup(driver, session, carpeta_tipo)
            resumen["descargados"] = descargados
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


def _descargar_adjuntos_popup(driver, session, carpeta_destino):
    """
    En la ventana de adjuntos, recorre las filas y descarga los links de 'Ver' o los href.
    """
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


def _requests_session_from_driver(driver):
    session = requests.Session()
    try:
        for cookie in driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
    except Exception:
        pass
    return session


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


def _click_y_capturar_nueva_ventana(driver, elemento):
    handles_prev = driver.window_handles[:]
    try:
        driver.execute_script("arguments[0].click();", elemento)
    except Exception:
        try:
            elemento.click()
        except Exception:
            return None
    return _esperar_nueva_ventana(driver, handles_prev)


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
        return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table[id*='grdSupplies']")))
    except Exception:
        pass

    # Probar dentro de iframes
    if not _switch_to_frame_containing(driver, (By.CSS_SELECTOR, "table[id*='grdSupplies']")):
        return None
    try:
        return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table[id*='grdSupplies']")))
    except Exception:
        return None


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
