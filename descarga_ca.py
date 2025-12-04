# descarga_ca.py
# Dado un código de compra ágil, descarga carpetas con adjuntos y además crea un zip con los adjuntos llamado (NombreProveedor).zip

import os
import time
import zipfile
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
import re
import json

# Constantes para llamadas API (Compra Ágil)
API_BASE_CA = "https://servicios-compra-agil.mercadopublico.cl/v1/compra-agil"
DEFAULT_COOKIE = "cf8fc9f9992a81aa1f6cd62d77d1d62b=19395daaa97624eb1f7f9f9e68b099e5"

def descargar_compra_agil(codigo_ca, driver=None):
    """
    Descarga todos los adjuntos de una compra ágil
    
    Args:
        codigo_ca (str): Código de la compra ágil
        driver: Instancia del navegador Selenium
    
    Returns:
        bool: True si la descarga fue exitosa, False en caso contrario
    """
    if not driver:
        print("Error: Se requiere una instancia del navegador")
        return False
    
    try:
        # Crear carpeta base para la compra ágil
        carpeta_base = os.path.join("Descargas", "ComprasAgiles", codigo_ca)
        os.makedirs(carpeta_base, exist_ok=True)
        
        # Navegar a la compra ágil
        if not navegar_a_compra_agil(codigo_ca, driver):
            return False
        
        # Obtener lista de proveedores
        proveedores = obtener_proveedores_ca(driver)
        
        if not proveedores:
            print(f"No se encontraron proveedores para la compra ágil {codigo_ca}")
            return False
        
        print(f"Encontrados {len(proveedores)} proveedores")
        # Debug: imprimir información básica de cada proveedor
        for idx, p in enumerate(proveedores, 1):
            print(
                f"Proveedor {idx}: "
                f"nombre='{p.get('nombre')}', "
                f"rut='{p.get('rut')}', "
                f"monto_total='{p.get('monto_total')}', "
                f"descripcion='{p.get('descripcion')[:120]}{'...' if p.get('descripcion') and len(p.get('descripcion'))>120 else ''}'"
            )
        
        # Descargar adjuntos de cada proveedor
        for proveedor in proveedores:
            nombre_proveedor = limpiar_nombre_archivo(proveedor['nombre'])
            carpeta_proveedor = os.path.join(carpeta_base, nombre_proveedor)
            os.makedirs(carpeta_proveedor, exist_ok=True)
            
            print(f"\n=== Descargando adjuntos de proveedor: {nombre_proveedor} ({proveedor.get('rut')}) ===")
            
            # Descargar adjuntos del proveedor
            adjuntos_descargados = descargar_adjuntos_proveedor(proveedor, carpeta_proveedor, driver)
            
            # Crear ZIP si hay adjuntos
            if adjuntos_descargados:
                ruta_zip = crear_zip_proveedor(carpeta_proveedor, nombre_proveedor)
                proveedor['ruta_zip'] = ruta_zip
                proveedor['adjuntos_descargados'] = adjuntos_descargados
            
            time.sleep(2)  # Pausa entre proveedores
        
        print(f"Descarga completada para compra ágil {codigo_ca}")
        return True
        
    except Exception as e:
        print(f"Error durante la descarga: {str(e)}")
        return False


def descargar_compra_agil_api(codigo_ca, token_path="token"):
    """
    Descarga los adjuntos de una compra ágil usando la API oficial con el token Bearer.

    Args:
        codigo_ca (str): Código de la compra ágil
        token_path (str): Ruta al archivo que contiene el token (por defecto 'token')

    Returns:
        bool: True si todo fue bien, False en caso contrario
    """
    try:
        token = _leer_token(token_path)
    except Exception as e:
        print(f"[API] Error leyendo token: {e}")
        return False

    carpeta_base = os.path.join("Descargas", "ComprasAgiles", codigo_ca)
    os.makedirs(carpeta_base, exist_ok=True)

    exitosos = 0
    errores = 0

    # 1) Descargas generales (comprador/listar) - pueden ser bases administrativas o anexos generales
    try:
        archivos_generales, _ = _listar_adjuntos_api(codigo_ca, token)
    except Exception as e:
        print(f"[API] Error al listar adjuntos generales: {e}")
        archivos_generales = []

    if archivos_generales:
        print(f"[API] Adjuntos generales encontrados: {len(archivos_generales)}")
        carpeta_adjuntos = os.path.join(carpeta_base, "Adjuntos")
        os.makedirs(carpeta_adjuntos, exist_ok=True)
        for adjunto in archivos_generales:
            file_id = adjunto.get("fileId") or adjunto.get("id") or adjunto.get("uuid")
            if not file_id:
                continue
            nombre_archivo = adjunto.get("filename") or adjunto.get("nombre") or f"{file_id}.bin"
            try:
                contenido, nombre_final = _descargar_archivo_api(file_id, token, nombre_archivo)
                ruta_archivo = os.path.join(carpeta_adjuntos, nombre_final)
                with open(ruta_archivo, "wb") as f:
                    f.write(contenido)
                exitosos += 1
                print(f"[API] Descargado (general) {nombre_final} -> {ruta_archivo}")
            except Exception as e:
                errores += 1
                print(f"[API] Error al descargar (general) {file_id}: {e}")

    # 2) Adjuntos por postulante (cotización) usando IDs de candidatos
    try:
        info_data = _obtener_info_compra(codigo_ca, token)
        candidatos = extract_candidate_ids(info_data)
    except Exception as e:
        print(f"[API] Error al obtener información de compra o candidatos: {e}")
        candidatos = []

    if not candidatos:
        print(f"[API] No se encontraron candidatos/postulantes para la compra ágil {codigo_ca}")
    else:
        print(f"[API] Candidatos encontrados: {len(candidatos)}")

    for candidato in candidatos:
        candidato_id = candidato.get("id")
        etiqueta = candidato.get("label") or f"Postulante_{candidato_id}"
        carpeta_candidato = os.path.join(carpeta_base, limpiar_nombre_archivo(etiqueta))
        os.makedirs(carpeta_candidato, exist_ok=True)

        try:
            documentos = _obtener_documentos_por_cotizacion(candidato_id, token)
        except Exception as e:
            print(f"[API] Error al obtener adjuntos para {etiqueta}: {e}")
            errores += 1
            continue

        if not documentos:
            print(f"[API] Sin documentos para {etiqueta}")
            continue

        print(f"[API] Descargando {len(documentos)} documentos de {etiqueta}")

        for doc in documentos:
            file_id = doc.get("id") or doc.get("documentoId") or doc.get("fileId")
            if not file_id:
                continue
            nombre_archivo = doc.get("filename") or doc.get("nombre") or doc.get("fileName") or f"{file_id}.bin"
            try:
                contenido, nombre_final = _descargar_archivo_api(file_id, token, nombre_archivo)
                ruta_archivo = os.path.join(carpeta_candidato, nombre_final)
                with open(ruta_archivo, "wb") as f:
                    f.write(contenido)
                exitosos += 1
                print(f"[API] Descargado ({etiqueta}) {nombre_final} -> {ruta_archivo}")
            except Exception as e:
                errores += 1
                print(f"[API] Error al descargar ({etiqueta}) {file_id}: {e}")

    print(f"[API] Descarga finalizada. Éxitos: {exitosos} | Errores: {errores}")
    return exitosos > 0

def navegar_a_compra_agil(codigo_ca, driver):
    """
    Navega a la página de la compra ágil específica
    
    Args:
        codigo_ca (str): Código de la compra ágil
        driver: Instancia del navegador Selenium
    
    Returns:
        bool: True si la navegación fue exitosa
    """
    try:
        # URL de resumen de compras ágiles (nueva interfaz)
        url_resumen = f"https://compra-agil.mercadopublico.cl/resumen-cotizacion/{codigo_ca}"
        
        print(f"Navegando a compra ágil (resumen): {codigo_ca}")
        driver.get(url_resumen)
        
        wait = WebDriverWait(driver, 20)
        
        # Esperar a que cargue el cuerpo de la página
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        # Intentar esperar un título característico
        try:
            wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//h2[contains(normalize-space(),'Detalle de la cotización') or contains(normalize-space(),'Detalle de la cotizacion')]")
                )
            )
        except TimeoutException:
            print("Advertencia: no se encontró el título 'Detalle de la cotización'.")
        
        # Instalar hook para capturar respuestas de la API de cotizaciones
        try:
            driver.execute_script(
                """
                if (!window.__MP_CA_API_HOOK_INSTALLED__) {
                    window.__MP_CA_API_HOOK_INSTALLED__ = true;
                    window.__MP_CA_COTIZACIONES__ = [];
                    const originalFetch = window.fetch;
                    window.fetch = function() {
                        const args = arguments;
                        return originalFetch.apply(this, args).then(function(resp) {
                            try {
                                var url = resp.url || (args[0] && args[0].url) || args[0];
                                if (typeof url === 'string' && url.indexOf('/v1/compra-agil/solicitud/cotizacion/') !== -1) {
                                    resp.clone().json().then(function(data) {
                                        try {
                                            window.__MP_CA_COTIZACIONES__.push({ url: url, data: data });
                                        } catch (e) {}
                                    }).catch(function() {});
                                }
                            } catch (e) {}
                            return resp;
                        });
                    };
                }
                """
            )
        except Exception as e:
            print(f"Advertencia: no se pudo instalar hook de API: {e}")
        
        # Verificar si la página cargó correctamente
        if "error" in driver.current_url.lower() or "not found" in driver.page_source.lower():
            print(f"No se encontró la compra ágil {codigo_ca}")
            return False
        
        return True
        
    except TimeoutException:
        print("Timeout al cargar la página de compra ágil")
        return False
    except Exception as e:
        print(f"Error al navegar a compra ágil: {str(e)}")
        return False

def obtener_proveedores_ca(driver):
    """
    Obtiene la lista de proveedores participantes en la compra ágil
    
    Args:
        driver: Instancia del navegador Selenium
    
    Returns:
        list: Lista de diccionarios con información de proveedores
    """
    proveedores = []
    
    try:
        wait = WebDriverWait(driver, 20)
        
        # Intentar localizar el encabezado "Listado de proveedores que cotizaron"
        try:
            encabezado = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//h3[contains(normalize-space(),'Listado de proveedores que cotizaron')]")
                )
            )
            # Hacer scroll hasta el encabezado para asegurar que la sección se renderice
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", encabezado)
            time.sleep(1)
        except TimeoutException:
            print("Advertencia: no se encontró el encabezado del listado de proveedores.")
        
        # Buscar tarjetas de proveedores en toda la página:
        #  - div con clase MuiPaper-root (la tarjeta)
        #  - que contenga un enlace "Ver detalle"
        #  - y un enlace a la ficha del proveedor
        tarjetas = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'MuiPaper-root') and "
            ".//a[contains(normalize-space(),'Ver detalle')] and "
            ".//a[contains(@href,'proveedor.mercadopublico.cl/ficha')]]"
        )
        
        if not tarjetas:
            print("No se encontraron tarjetas de proveedores en la página.")
            return []
        
        vistos_por_rut = set()
        
        for i, tarjeta in enumerate(tarjetas, 1):
            try:
                # Nombre del proveedor (enlace a ficha de proveedor)
                try:
                    elemento_nombre = tarjeta.find_element(
                        By.XPATH,
                        ".//a[contains(@href,'proveedor.mercadopublico.cl/ficha')]"
                    )
                    nombre = elemento_nombre.text.strip()
                except NoSuchElementException:
                    nombre = f"PROVEEDOR_{i}"
                
                # RUT del proveedor: buscar patrón de RUT chileno dentro del texto de la tarjeta
                rut = f"PROVEEDOR_{i}"
                for linea in tarjeta.text.splitlines():
                    rut_match = re.search(r'(\d{1,2}\.\d{3}\.\d{3}-[\dkK])', linea)
                    if rut_match:
                        rut = rut_match.group(1)
                        break
                
                # Evitar duplicados por RUT
                if rut in vistos_por_rut:
                    continue
                vistos_por_rut.add(rut)
                
                # Descripción (texto más largo del proveedor)
                descripcion = ""
                try:
                    elemento_desc = tarjeta.find_element(
                        By.XPATH,
                        ".//p[contains(@class,'MuiTypography-body2')][string-length(normalize-space())>40]"
                    )
                    descripcion = elemento_desc.text.strip()
                except NoSuchElementException:
                    pass
                
                # Monto total (h3 asociado al texto "Monto total")
                monto_total = ""
                try:
                    elemento_monto = tarjeta.find_element(
                        By.XPATH,
                        ".//p[contains(normalize-space(),'Monto total')]/ancestor::div[1]/preceding-sibling::div//h3"
                    )
                    monto_total = elemento_monto.text.strip()
                except NoSuchElementException:
                    pass
                
                # Enlace "Ver detalle" para abrir el modal de cotización
                elemento_ver_detalle = tarjeta.find_element(
                    By.XPATH,
                    ".//a[contains(normalize-space(),'Ver detalle')]"
                )
                
                proveedor = {
                    'nombre': nombre,
                    'rut': rut,
                    'descripcion': descripcion,
                    'monto_total': monto_total,
                    'elemento_ver_detalle': elemento_ver_detalle,
                    'carpeta_path': '',
                    'ruta_zip': '',
                    'adjuntos_descargados': []
                }
                
                proveedores.append(proveedor)
                
            except Exception as e:
                print(f"Error al procesar proveedor {i}: {str(e)}")
                continue
        
        return proveedores
        
    except Exception as e:
        print(f"Error al obtener proveedores: {str(e)}")
        return []

def extraer_nombre_proveedor(texto, rut):
    """
    Extrae el nombre del proveedor del texto
    
    Args:
        texto (str): Texto que contiene la información del proveedor
        rut (str): RUT del proveedor
    
    Returns:
        str: Nombre del proveedor
    """
    # Limpiar el texto
    texto_limpio = texto.replace('\n', ' ').replace('\t', ' ')
    
    # Si hay RUT, tomar el texto antes del RUT como nombre
    if rut in texto_limpio:
        partes = texto_limpio.split(rut)
        if partes[0].strip():
            return partes[0].strip()
    
    # Si no hay RUT válido, tomar las primeras palabras
    palabras = texto_limpio.split()
    if len(palabras) > 0:
        # Tomar hasta 5 palabras como nombre
        return ' '.join(palabras[:5])
    
    return "PROVEEDOR_SIN_NOMBRE"

def descargar_adjuntos_proveedor(proveedor, carpeta_destino, driver):
    """
    Descarga los adjuntos de un proveedor específico
    
    Args:
        proveedor (dict): Información del proveedor
        carpeta_destino (str): Carpeta donde guardar los adjuntos
        driver: Instancia del navegador Selenium
    
    Returns:
        list: Lista de archivos descargados
    """
    adjuntos_descargados = []
    
    try:
        wait = WebDriverWait(driver, 20)
        
        print(
            f"Abrir detalle de proveedor: nombre='{proveedor.get('nombre')}', "
            f"rut='{proveedor.get('rut')}', "
            f"monto_total='{proveedor.get('monto_total')}'"
        )
        
        # Hacer clic en "Ver detalle" para ver los adjuntos de la cotización
        elemento_ver_detalle = proveedor.get('elemento_ver_detalle') or proveedor.get('elemento')
        if not elemento_ver_detalle:
            print("No se encontró el enlace 'Ver detalle' para el proveedor")
            return []
        
        # Hacer scroll al enlace y hacer clic
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento_ver_detalle)
        except Exception:
            pass
        
        try:
            wait.until(EC.element_to_be_clickable(elemento_ver_detalle))
            elemento_ver_detalle.click()
        except Exception:
            # Fallback a click por JavaScript
            driver.execute_script("arguments[0].click();", elemento_ver_detalle)
        
        # Esperar a que aparezca la sección con "Adjuntos de la cotización"
        try:
            etiqueta_adjuntos = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//p[contains(normalize-space(),'Adjuntos de la cotización')]")
                )
            )
        except TimeoutException:
            print("Timeout esperando la sección 'Adjuntos de la cotización' para este proveedor.")
            try:
                outer_html = elemento_ver_detalle.get_attribute("outerHTML")
                print(f"HTML del enlace 'Ver detalle' para debug:\n{outer_html}")
            except Exception:
                pass
            return []
        
        # Contenedor principal de adjuntos a partir de la etiqueta
        try:
            contenedor_adjuntos = etiqueta_adjuntos.find_element(
                By.XPATH,
                "./ancestor::div[contains(@class,'MuiGrid-root')][1]/following-sibling::div[1]"
            )
        except NoSuchElementException:
            # Fallback: usar el ancestro inmediato
            contenedor_adjuntos = etiqueta_adjuntos.find_element(By.XPATH, "./ancestor::div[1]")
        
        # Intentar obtener la cotización desde la API interceptada
        try:
            cotizaciones_api = driver.execute_script("return window.__MP_CA_COTIZACIONES__ || []")
        except Exception:
            cotizaciones_api = []
        
        print(f"Cotizaciones capturadas por API hasta ahora: {len(cotizaciones_api)}")
        
        adjuntos_api = []
        nombre_prov_api = (proveedor.get('nombre') or '').strip().upper()
        if cotizaciones_api:
            for item in reversed(cotizaciones_api):
                try:
                    data = item.get('data', {})
                    payload = data.get('payload', {})
                    razon = (payload.get('razonSocial') or '').strip().upper()
                    if razon == nombre_prov_api:
                        adjuntos_api = payload.get('documentosAdjuntos') or []
                        break
                except Exception:
                    continue
        
        if adjuntos_api:
            print(f"Adjuntos vía API para {proveedor.get('nombre')}:")
            for j, doc in enumerate(adjuntos_api, 1):
                print(f"  (API) [{j}] filename='{doc.get('filename')}', id='{doc.get('id')}'")
        
        # Primero intentamos con el selector específico de los enlaces de adjuntos
        enlaces_descarga = contenedor_adjuntos.find_elements(By.CSS_SELECTOR, "a.sc-cInsRk")
        # Fallback genérico si no se encontró nada
        if not enlaces_descarga:
            enlaces_descarga = contenedor_adjuntos.find_elements(By.TAG_NAME, "a")
        
        print(f"Adjuntos encontrados en el modal: {len(enlaces_descarga)}")
        
        for i, enlace in enumerate(enlaces_descarga, 1):
            try:
                href = enlace.get_attribute('href')
                texto_enlace = enlace.text.strip()
                
                # Obtener nombre del archivo
                nombre_archivo = texto_enlace if texto_enlace else f"adjunto_{len(adjuntos_descargados)+1}"
                nombre_archivo = limpiar_nombre_archivo(nombre_archivo)
                print(f"  [{i}] adjunto nombre='{nombre_archivo}', href='{href}'")
                
                if not href:
                    # Aún no sabemos la URL de descarga, pero dejamos trazas para debug
                    continue
                
                # Descargar archivo si tenemos URL
                ruta_archivo = descargar_archivo(href, carpeta_destino, nombre_archivo, driver)
                
                if ruta_archivo:
                    adjuntos_descargados.append(ruta_archivo)
                    print(f"  - Descargado: {nombre_archivo}")
            
            except Exception as e:
                print(f"Error al descargar adjunto: {str(e)}")
                continue
        
        # Actualizar información del proveedor
        proveedor['carpeta_path'] = carpeta_destino
        
        # Cerrar el modal (botón "Cerrar" o tecla ESC)
        try:
            boton_cerrar = modal.find_element(By.XPATH, ".//button[.//text()[contains(.,'Cerrar')]]")
            driver.execute_script("arguments[0].click();", boton_cerrar)
        except Exception:
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
            except Exception:
                pass
        
        time.sleep(1)
        
        return adjuntos_descargados
        
    except Exception as e:
        print(f"Error al descargar adjuntos del proveedor: {str(e)}")
        return []

def descargar_archivo(url, carpeta_destino, nombre_archivo, driver):
    """
    Descarga un archivo desde una URL
    
    Args:
        url (str): URL del archivo
        carpeta_destino (str): Carpeta donde guardar el archivo
        nombre_archivo (str): Nombre del archivo
        driver: Instancia del navegador Selenium
    
    Returns:
        str: Ruta del archivo descargado o None si falló
    """
    try:
        # Obtener cookies del navegador para la sesión
        cookies = driver.get_cookies()
        session = requests.Session()
        
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        
        # Descargar archivo
        response = session.get(url, stream=True)
        response.raise_for_status()
        
        # Determinar extensión del archivo
        content_type = response.headers.get('content-type', '')
        extension = obtener_extension_por_content_type(content_type)
        
        if not nombre_archivo.endswith(extension) and extension:
            nombre_archivo += extension
        
        ruta_archivo = os.path.join(carpeta_destino, nombre_archivo)
        
        # Guardar archivo
        with open(ruta_archivo, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return ruta_archivo
        
    except Exception as e:
        print(f"Error al descargar archivo {nombre_archivo}: {str(e)}")
        return None

def obtener_extension_por_content_type(content_type):
    """
    Obtiene la extensión de archivo basada en el content-type
    
    Args:
        content_type (str): Content-Type del archivo
    
    Returns:
        str: Extensión del archivo
    """
    extensiones = {
        'application/pdf': '.pdf',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.ms-excel': '.xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'text/plain': '.txt',
        'application/zip': '.zip'
    }
    
    return extensiones.get(content_type.lower(), '')


# ==========================
# Funciones auxiliares API
# ==========================

def _leer_token(token_path):
    with open(token_path, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise ValueError("El archivo de token está vacío")
    return token


def _headers_api(token):
    return {
        "Authorization": token,
        "Cookie": DEFAULT_COOKIE,
        "Origin": "https://compra-agil.mercadopublico.cl",
        "Referer": "https://compra-agil.mercadopublico.cl/",
        "Accept": "application/json, text/plain, */*",
    }


def _listar_adjuntos_api(codigo_ca, token):
    url = f"{API_BASE_CA}/comprador/listar/{codigo_ca}"
    resp = requests.get(url, headers=_headers_api(token), timeout=40)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    payload = data.get("payload") or {}
    archivos = payload.get("files") or []
    return archivos, payload


def _descargar_archivo_api(file_id, token, nombre_archivo):
    url = f"{API_BASE_CA}/comprador/descargar?id={file_id}"
    resp = requests.get(url, headers=_headers_api(token), timeout=60, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

    # Si Content-Disposition trae nombre de archivo, respetarlo
    disposition = resp.headers.get("content-disposition") or resp.headers.get("Content-Disposition")
    if disposition:
        try:
            # Ej: attachment;filename=nombre.pdf
            parts = disposition.split("filename=")
            if len(parts) > 1:
                candidato = parts[1].strip().strip('"').strip("'")
                if candidato:
                    nombre_archivo = candidato
        except Exception:
            pass

    return resp.content, nombre_archivo


def _obtener_info_compra(codigo_compra, token):
    url = f"{API_BASE_CA}/solicitud/{codigo_compra}?size=20&page=0"
    resp = requests.get(url, headers=_headers_api(token), timeout=40)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    return resp.json()


def _obtener_documentos_por_cotizacion(id_objetivo, token):
    url = f"{API_BASE_CA}/solicitud/cotizacion/{id_objetivo}"
    resp = requests.get(url, headers=_headers_api(token), timeout=40)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    payload = data.get("payload") or {}
    documentos = payload.get("documentosAdjuntos") or []
    resultados = []
    for doc in documentos:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id") or doc.get("documentoId") or doc.get("fileId")
        nombre = doc.get("filename") or doc.get("nombre") or doc.get("fileName")
        if not doc_id:
            continue
        resultados.append({"id": doc_id, "filename": nombre})
    return resultados


def extract_candidate_ids(info_data):
    payload = info_data.get("payload") or {}
    records = []
    for key in ("ofertasSeleccionadas", "ofertas", "detalleOfertasProveedor", "ofertasInadmisibles"):
        section = payload.get(key)
        if isinstance(section, list):
            records.extend(section)
        elif isinstance(section, dict):
            if all(isinstance(item, dict) for item in section.values()):
                records.extend(section.values())
            else:
                records.append(section)
    candidates = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        identifier = (
            record.get("idEntidad")
            or record.get("idRespuesta")
            or record.get("id")
            or record.get("codigoEmpresa")
            or record.get("codigoSucursalEmpresa")
        )
        if identifier is None:
            continue
        identifier_str = str(identifier).strip()
        if not identifier_str or identifier_str in seen:
            continue
        label = (
            record.get("razonSocial")
            or record.get("nombre")
            or record.get("nombreApellido")
            or f"Postulante {identifier_str}"
        )
        candidates.append({"id": identifier_str, "label": label})
        seen.add(identifier_str)
    return candidates


def build_user_label(file_info):
    """Genera una etiqueta legible para el postulante/usuario dueño del archivo."""
    posibles_nombres = [
        "postulanteNombre",
        "postulante",
        "usuarioNombre",
        "usuario",
        "userName",
        "providerName",
        "provider",
        "nombre",
        "empresaNombre",
    ]
    posibles_rut = ["postulanteRut", "usuarioRut", "rut"]

    nombre = next((file_info.get(key) for key in posibles_nombres if file_info.get(key)), None)
    rut = next((file_info.get(key) for key in posibles_rut if file_info.get(key)), None)

    if nombre and rut:
        return f"{nombre} ({rut})"
    if nombre:
        return str(nombre)
    if rut:
        return f"RUT {rut}"
    return "Adjuntos"

def crear_zip_proveedor(ruta_proveedor, nombre_proveedor):
    """
    Crea un archivo ZIP con todos los adjuntos de un proveedor
    
    Args:
        ruta_proveedor (str): Ruta a la carpeta del proveedor
        nombre_proveedor (str): Nombre del proveedor
    
    Returns:
        str: Ruta del archivo ZIP creado
    """
    try:
        nombre_zip = f"{nombre_proveedor}.zip"
        ruta_zip = os.path.join(os.path.dirname(ruta_proveedor), nombre_zip)
        
        with zipfile.ZipFile(ruta_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Agregar todos los archivos de la carpeta del proveedor
            for root, dirs, files in os.walk(ruta_proveedor):
                for file in files:
                    ruta_archivo = os.path.join(root, file)
                    # Nombre relativo en el ZIP
                    nombre_en_zip = os.path.relpath(ruta_archivo, ruta_proveedor)
                    zipf.write(ruta_archivo, nombre_en_zip)
        
        print(f"ZIP creado: {nombre_zip}")
        return ruta_zip
        
    except Exception as e:
        print(f"Error al crear ZIP para {nombre_proveedor}: {str(e)}")
        return None

def limpiar_nombre_archivo(nombre):
    """
    Limpia un nombre para usarlo como nombre de archivo/carpeta
    
    Args:
        nombre (str): Nombre a limpiar
    
    Returns:
        str: Nombre limpio
    """
    # Remover caracteres no válidos para nombres de archivo
    caracteres_invalidos = r'[<>:"/\\|?*]'
    nombre_limpio = re.sub(caracteres_invalidos, '_', nombre)
    
    # Remover espacios extra y limitar longitud
    nombre_limpio = ' '.join(nombre_limpio.split())
    nombre_limpio = nombre_limpio[:100]  # Limitar a 100 caracteres
    
    return nombre_limpio.strip()


def crear_zips_proveedores(codigo_ca):
    """
    Recorre las carpetas de proveedores de una compra ágil y genera un ZIP por cada una.
    Ignora la carpeta 'Adjuntos' (adjuntos generales).
    """
    carpeta_base = os.path.join("Descargas", "ComprasAgiles", codigo_ca)
    if not os.path.isdir(carpeta_base):
        print(f"[ZIP] Carpeta base no existe: {carpeta_base}")
        return []

    generados = []
    for nombre in os.listdir(carpeta_base):
        ruta = os.path.join(carpeta_base, nombre)
        if not os.path.isdir(ruta):
            continue
        if nombre.lower() == "adjuntos":
            continue
        zip_path = crear_zip_proveedor(ruta, nombre)
        if zip_path:
            generados.append(zip_path)
    print(f"[ZIP] Zips generados: {len(generados)}")
    return generados

if __name__ == "__main__":
    # Función principal para pruebas
    print("Módulo descarga_ca.py - Descarga de adjuntos de compras ágiles")
    print("Este módulo debe ser importado y usado desde app.py")
