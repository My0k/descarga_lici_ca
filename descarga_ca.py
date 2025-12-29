# descarga_ca.py
# Dado un código de compra ágil, descarga carpetas con adjuntos y además crea un zip con los adjuntos llamado (NombreProveedor).zip

import os
import time
import zipfile
import requests
import base64
from datetime import datetime
from urllib.parse import unquote
import unicodedata
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.keys import Keys
import re
import json

# Constantes para llamadas API (Compra Ágil)
API_BASE_CA = "https://servicios-compra-agil.mercadopublico.cl/v1/compra-agil"
DEFAULT_COOKIE = "cf8fc9f9992a81aa1f6cd62d77d1d62b=19395daaa97624eb1f7f9f9e68b099e5"
CERT_BASE_URL = "https://proveedor.mercadopublico.cl/ficha/certificado"
DECLARACION_JURADA_BASE_URL = "https://proveedor.mercadopublico.cl/BeneficiariosFinales/lectura"
DECLARACION_JURADA_LICITACION_BASE_URL = "https://proveedor.mercadopublico.cl/dj-requisitos"
MANIFEST_ADJUNTOS_FILENAME = "manifest_adjuntos.json"


def _normalizar_content_type(content_type):
    if not content_type:
        return ""
    return str(content_type).split(";", 1)[0].strip().lower()


def _asegurar_nombre_unico(carpeta_destino, nombre_archivo):
    base, ext = os.path.splitext(nombre_archivo)
    candidato = nombre_archivo
    contador = 2
    while os.path.exists(os.path.join(carpeta_destino, candidato)):
        candidato = f"{base} ({contador}){ext}"
        contador += 1
    return candidato


def _limpiar_nombre_archivo_con_extension(nombre, max_len=160):
    """
    Limpia nombres de archivo intentando preservar la extensión y el sufijo del nombre,
    evitando truncar justo donde va el diferenciador (ej: "... 1.jpg", "... 2.jpg").
    """
    nombre = (nombre or "").strip()
    if not nombre:
        return "archivo"
    base, ext = os.path.splitext(nombre)
    ext = ext[:20]
    base_limpia = limpiar_nombre_archivo(base)
    if ext:
        # Dejar espacio para extensión
        limite_base = max(1, max_len - len(ext))
        if len(base_limpia) > limite_base:
            base_limpia = base_limpia[:limite_base].rstrip()
        return f"{base_limpia}{ext}"
    return limpiar_nombre_archivo(nombre)[:max_len].rstrip()


def _listar_archivos_descargados(carpeta_proveedor):
    try:
        return sorted(
            f
            for f in os.listdir(carpeta_proveedor)
            if os.path.isfile(os.path.join(carpeta_proveedor, f))
        )
    except Exception:
        return []


def _normalizar_nombre_para_comparar(nombre):
    return _limpiar_nombre_archivo_con_extension(nombre).lower()


def _wait_ready(driver, timeout=20):
    """Espera a que document.readyState sea 'complete'."""
    if not driver:
        return
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        return


def _safe_click(driver, element):
    """Click robusto (normal + fallback JS)."""
    if not driver or not element:
        return False
    try:
        element.click()
        return True
    except ElementClickInterceptedException:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def _archivo_listo(ruta, min_bytes=1024):
    try:
        return os.path.isfile(ruta) and os.path.getsize(ruta) >= int(min_bytes)
    except Exception:
        return False


def _normalizar_texto_busqueda(texto):
    texto = (texto or "").strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _js_click_ver_detalle(driver, idx=None, rut=None, nombre=None):
    """
    Clickea "Ver detalle" desde JS (sin pasar WebElements), útil para evitar stale elements.
    - Si idx es válido, clickea el idx-ésimo link.
    - Si hay rut/nombre, intenta matchear por texto de la tarjeta.
    """
    if not driver:
        return False
    try:
        script = """
            (function() {
              var idx = arguments[0];
              var rut = (arguments[1] || '').toString().trim();
              var nombre = (arguments[2] || '').toString().trim().toUpperCase();

              function normRut(s) {
                return (s || '').toString().replace(/[.\\s]/g, '').toUpperCase();
              }

              function isVerDetalle(a) {
                var t = (a && a.textContent ? a.textContent : '').trim().toLowerCase();
                return t === 'ver detalle' || t.indexOf('ver detalle') !== -1;
              }

              var links = Array.from(document.querySelectorAll('a')).filter(isVerDetalle);
              if (!links.length) return false;

              function clickLink(a) {
                try { a.scrollIntoView({block: 'center'}); } catch(e) {}
                try { a.click(); return true; } catch(e) {}
                return false;
              }

              if (idx !== null && idx !== undefined) {
                var n = parseInt(idx, 10);
                if (!isNaN(n) && n >= 0 && n < links.length) {
                  return clickLink(links[n]);
                }
              }

              if (!rut && !nombre) return false;
              var rutNorm = normRut(rut);

              for (var i = 0; i < links.length; i++) {
                var a = links[i];
                var card = null;
                try {
                  card = a.closest('div, section, article') || a.parentElement;
                } catch (e) {
                  card = a.parentElement;
                }
                var text = '';
                try {
                  text = (card && card.innerText ? card.innerText : '').toString();
                } catch (e) {
                  text = '';
                }
                var textUpper = text.toUpperCase();
                if (rutNorm && normRut(textUpper).indexOf(rutNorm) !== -1) {
                  return clickLink(a);
                }
                if (nombre && textUpper.indexOf(nombre) !== -1) {
                  return clickLink(a);
                }
              }

              return false;
            })();
        """
        return bool(driver.execute_script(script, idx, rut or "", (nombre or "")))
    except Exception:
        return False


def descargar_compra_agil(codigo_ca, driver=None, base_dir="Descargas", nombre_proyecto=None):
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
        # Navegar a la compra ágil
        if not navegar_a_compra_agil(codigo_ca, driver):
            return False

        if not nombre_proyecto and driver:
            nombre_proyecto = _extraer_nombre_compra_agil_desde_ui(driver, codigo_ca)

        # Crear carpeta base para la compra ágil
        carpeta_base = resolver_carpeta_base(base_dir, "ComprasAgiles", codigo_ca, nombre_proyecto)
        os.makedirs(carpeta_base, exist_ok=True)
        
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

            try:
                descargar_certificado_habilidad(proveedor.get("rut"), carpeta_proveedor, driver)
            except Exception as cert_error:
                print(f"[CERT] Error al obtener certificado para {nombre_proveedor}: {cert_error}")

            try:
                descargar_declaracion_jurada(proveedor.get("rut"), carpeta_proveedor, driver)
            except Exception as dj_error:
                print(f"[DJ] Error al obtener declaración jurada para {nombre_proveedor}: {dj_error}")

            try:
                descargar_comprobante_oferta_compra_agil_por_proveedor(proveedor, carpeta_proveedor, driver)
            except Exception as voucher_error:
                print(f"[VOUCHER_CA] Error al obtener comprobante para {nombre_proveedor}: {voucher_error}")
            
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


def descargar_compra_agil_api(codigo_ca, token_path="token", driver=None, base_dir="Descargas", nombre_proyecto=None):
    """
    Descarga los adjuntos de una compra ágil usando la API oficial con el token Bearer.

    Args:
        codigo_ca (str): Código de la compra ágil
        token_path (str): Ruta al archivo que contiene el token (por defecto 'token')
        driver: Instancia Selenium opcional, usada como respaldo para imprimir certificados

    Returns:
        bool: True si todo fue bien, False en caso contrario
    """
    try:
        token = _leer_token(token_path)
    except Exception as e:
        print(f"[API] Error leyendo token: {e}")
        return False

    info_data = None
    if not nombre_proyecto:
        try:
            info_data = _obtener_info_compra(codigo_ca, token)
            nombre_proyecto = _extraer_nombre_proyecto_compra_info(info_data)
        except Exception as e:
            print(f"[API] Error obteniendo nombre de compra agil: {e}")
            info_data = None

    if not nombre_proyecto and driver:
        try:
            if navegar_a_compra_agil(codigo_ca, driver):
                nombre_proyecto = _extraer_nombre_compra_agil_desde_ui(driver, codigo_ca)
        except Exception:
            pass

    carpeta_base = resolver_carpeta_base(base_dir, "ComprasAgiles", codigo_ca, nombre_proyecto)
    os.makedirs(carpeta_base, exist_ok=True)

    exitosos = 0
    errores = 0
    manifest = {
        "codigo": codigo_ca,
        "nombre_proyecto": nombre_proyecto or "",
        "carpeta_base": carpeta_base,
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "proveedores": [],
    }

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
                contenido, nombre_final, content_type = _descargar_archivo_api(file_id, token, nombre_archivo)
                nombre_final = _limpiar_nombre_archivo_con_extension(nombre_final)
                if not os.path.splitext(nombre_final)[1]:
                    extension = obtener_extension_por_content_type(content_type)
                    if extension:
                        nombre_final += extension
                nombre_final = _asegurar_nombre_unico(carpeta_adjuntos, nombre_final)
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
        if info_data is None:
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
            documentos, rut_cotizacion = _obtener_documentos_por_cotizacion(candidato_id, token)
        except Exception as e:
            print(f"[API] Error al obtener adjuntos para {etiqueta}: {e}")
            errores += 1
            continue

        rut_candidato = candidato.get("rut") or rut_cotizacion or _extraer_rut_desde_texto(etiqueta)
        rut_normalizado = _normalizar_rut(rut_candidato) or rut_candidato

        entry_manifest = {
            "id_cotizacion": candidato_id,
            "label": etiqueta,
            "rut": rut_normalizado,
            "carpeta": carpeta_candidato,
            "esperados_api": len(documentos) if documentos else 0,
            "nombres_esperados_api": [
                (d.get("filename") or d.get("nombre") or d.get("fileName") or str(d.get("id") or "")).strip()
                for d in (documentos or [])
                if isinstance(d, dict)
            ],
            "descargados": [],
            "errores_descarga": [],
        }
        manifest["proveedores"].append(entry_manifest)

        if not documentos:
            print(f"[API] Sin documentos para {etiqueta}")
            try:
                certificado_ok = descargar_certificado_habilidad(rut_candidato, carpeta_candidato, driver)
                if certificado_ok:
                    exitosos += 1
            except Exception as cert_error:
                errores += 1
                print(f"[CERT] Error al descargar certificado de {etiqueta}: {cert_error}")

            try:
                dj_ok = descargar_declaracion_jurada(rut_candidato, carpeta_candidato, driver)
                if dj_ok:
                    exitosos += 1
            except Exception as dj_error:
                errores += 1
                print(f"[DJ] Error al descargar declaración jurada de {etiqueta}: {dj_error}")
            continue

        print(f"[API] Descargando {len(documentos)} documentos de {etiqueta}")

        for doc in documentos:
            file_id = doc.get("id") or doc.get("documentoId") or doc.get("fileId")
            if not file_id:
                continue
            nombre_archivo = doc.get("filename") or doc.get("nombre") or doc.get("fileName") or f"{file_id}.bin"
            try:
                contenido, nombre_final, content_type = _descargar_archivo_api(file_id, token, nombre_archivo)
                nombre_final = _limpiar_nombre_archivo_con_extension(nombre_final)
                if not os.path.splitext(nombre_final)[1]:
                    extension = obtener_extension_por_content_type(content_type)
                    if extension:
                        nombre_final += extension
                nombre_final = _asegurar_nombre_unico(carpeta_candidato, nombre_final)
                ruta_archivo = os.path.join(carpeta_candidato, nombre_final)
                with open(ruta_archivo, "wb") as f:
                    f.write(contenido)
                exitosos += 1
                entry_manifest["descargados"].append(nombre_final)
                print(f"[API] Descargado ({etiqueta}) {nombre_final} -> {ruta_archivo}")
            except Exception as e:
                errores += 1
                entry_manifest["errores_descarga"].append({"id": file_id, "nombre": nombre_archivo, "error": str(e)})
                print(f"[API] Error al descargar ({etiqueta}) {file_id}: {e}")

        try:
            certificado_ok = descargar_certificado_habilidad(rut_candidato, carpeta_candidato, driver)
            if certificado_ok:
                exitosos += 1
        except Exception as cert_error:
            errores += 1
            print(f"[CERT] Error al descargar certificado de {etiqueta}: {cert_error}")

        try:
            dj_ok = descargar_declaracion_jurada(rut_candidato, carpeta_candidato, driver)
            if dj_ok:
                exitosos += 1
        except Exception as dj_error:
            errores += 1
            print(f"[DJ] Error al descargar declaración jurada de {etiqueta}: {dj_error}")

    # Verificación final (si hay Selenium) comparando contra la UI
    try:
        if driver:
            _verificar_adjuntos_con_ui(codigo_ca, driver, manifest)
    except Exception as e:
        print(f"[VERIFY] Error inesperado verificando adjuntos con UI: {e}")

    # Guardar manifest para análisis/Excel
    try:
        ruta_manifest = os.path.join(carpeta_base, MANIFEST_ADJUNTOS_FILENAME)
        with open(ruta_manifest, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"[API] Manifest guardado -> {ruta_manifest}")
    except Exception as e:
        print(f"[API] No se pudo guardar manifest: {e}")

    # Comprobante de oferta por proveedor (UI "Ver detalle") -> PDF
    try:
        if driver:
            descargar_comprobantes_oferta_compra_agil(codigo_ca, driver, base_dir=base_dir)
    except Exception as e:
        print(f"[VOUCHER_CA] Error inesperado descargando comprobantes de oferta: {e}")

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

        # Basar la detección en los links "Ver detalle" (como test_comprobanteorden.py),
        # evitando depender de clases (MuiPaper-root) que cambian con frecuencia.
        ver_detalle_global = driver.find_elements(By.XPATH, "//a[normalize-space()='Ver detalle']")
        if not ver_detalle_global:
            ver_detalle_global = driver.find_elements(By.XPATH, "//a[contains(normalize-space(),'Ver detalle')]")

        if not ver_detalle_global:
            print("No se encontraron enlaces 'Ver detalle' en la página.")
            return []

        vistos_por_rut = set()

        for idx, elemento_ver_detalle in enumerate(ver_detalle_global, 1):
            tarjeta = None
            try:
                tarjeta = elemento_ver_detalle.find_element(
                    By.XPATH,
                    "./ancestor::*[.//a[contains(@href,'proveedor.mercadopublico.cl/ficha')] and .//a[normalize-space()='Ver detalle']][1]",
                )
            except Exception:
                try:
                    tarjeta = elemento_ver_detalle.find_element(
                        By.XPATH,
                        "./ancestor::div[.//a[contains(normalize-space(),'Ver detalle')]][1]",
                    )
                except Exception:
                    tarjeta = None

            try:
                # Nombre del proveedor (enlace a ficha de proveedor)
                try:
                    if tarjeta:
                        elemento_nombre = tarjeta.find_element(
                            By.XPATH,
                            ".//a[contains(@href,'proveedor.mercadopublico.cl/ficha')]",
                        )
                        nombre = elemento_nombre.text.strip()
                    else:
                        nombre = ""
                except NoSuchElementException:
                    nombre = ""
                
                # RUT del proveedor: buscar patrón de RUT chileno dentro del texto de la tarjeta
                rut = f"PROVEEDOR_{idx}"
                texto_tarjeta = ""
                try:
                    texto_tarjeta = (tarjeta.text or "").strip() if tarjeta else ""
                except Exception:
                    texto_tarjeta = ""
                if texto_tarjeta:
                    for linea in texto_tarjeta.splitlines():
                        rut_match = re.search(r"(\d{1,2}\.\d{3}\.\d{3}-[\dkK])", linea)
                        if rut_match:
                            rut = rut_match.group(1)
                            break
                
                if not nombre:
                    nombre = extraer_nombre_proveedor(texto_tarjeta, rut)

                # Evitar duplicados por RUT
                if rut in vistos_por_rut:
                    continue
                vistos_por_rut.add(rut)
                
                # Descripción (texto más largo del proveedor)
                descripcion = ""
                try:
                    if tarjeta:
                        elemento_desc = tarjeta.find_element(
                            By.XPATH,
                            ".//p[contains(@class,'MuiTypography-body2')][string-length(normalize-space())>40]",
                        )
                        descripcion = elemento_desc.text.strip()
                except NoSuchElementException:
                    pass
                
                # Monto total (h3 asociado al texto "Monto total")
                monto_total = ""
                try:
                    if tarjeta:
                        elemento_monto = tarjeta.find_element(
                            By.XPATH,
                            ".//p[contains(normalize-space(),'Monto total')]/ancestor::div[1]/preceding-sibling::div//h3",
                        )
                        monto_total = elemento_monto.text.strip()
                except NoSuchElementException:
                    pass

                idx_ver_detalle = idx - 1

                proveedor = {
                    'nombre': nombre,
                    'rut': rut,
                    'descripcion': descripcion,
                    'monto_total': monto_total,
                    'elemento_ver_detalle': elemento_ver_detalle,
                    'idx_ver_detalle': idx_ver_detalle,
                    'carpeta_path': '',
                    'ruta_zip': '',
                    'adjuntos_descargados': []
                }
                
                proveedores.append(proveedor)
                
            except Exception as e:
                print(f"Error al procesar proveedor {idx}: {str(e)}")
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
        
        # Intentar fallback API cuando los enlaces no traen href (caso típico: imágenes con click JS)
        token_fallback = None
        mapa_adjuntos_api = {}
        if adjuntos_api:
            try:
                token_fallback = _leer_token("token")
            except Exception:
                token_fallback = None
            for doc in adjuntos_api:
                if not isinstance(doc, dict):
                    continue
                doc_id = doc.get("id") or doc.get("documentoId") or doc.get("fileId")
                nombre_doc = doc.get("filename") or doc.get("nombre") or doc.get("fileName")
                if not doc_id or not nombre_doc:
                    continue
                mapa_adjuntos_api[_normalizar_nombre_para_comparar(nombre_doc)] = {
                    "id": doc_id,
                    "filename": nombre_doc,
                }

        for i, enlace in enumerate(enlaces_descarga, 1):
            try:
                href = enlace.get_attribute('href')
                texto_enlace = enlace.text.strip()
                
                # Obtener nombre del archivo
                nombre_archivo = texto_enlace if texto_enlace else f"adjunto_{len(adjuntos_descargados)+1}"
                nombre_archivo = _limpiar_nombre_archivo_con_extension(nombre_archivo)
                print(f"  [{i}] adjunto nombre='{nombre_archivo}', href='{href}'")
                
                if not href:
                    if token_fallback and texto_enlace:
                        clave = _normalizar_nombre_para_comparar(texto_enlace)
                        info_api = mapa_adjuntos_api.get(clave)
                        if info_api:
                            try:
                                contenido, nombre_final, content_type = _descargar_archivo_api(
                                    info_api["id"], token_fallback, info_api["filename"]
                                )
                                nombre_final = _limpiar_nombre_archivo_con_extension(nombre_final)
                                if not os.path.splitext(nombre_final)[1]:
                                    extension = obtener_extension_por_content_type(content_type)
                                    if extension:
                                        nombre_final += extension
                                nombre_final = _asegurar_nombre_unico(carpeta_destino, nombre_final)
                                ruta_archivo = os.path.join(carpeta_destino, nombre_final)
                                with open(ruta_archivo, "wb") as f:
                                    f.write(contenido)
                                adjuntos_descargados.append(ruta_archivo)
                                print(f"  - Descargado (API fallback): {nombre_final}")
                                continue
                            except Exception as e:
                                print(f"  - Error API fallback para '{texto_enlace}': {e}")
                    # Aún no sabemos la URL de descarga; se omite
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
        response = session.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        # Determinar extensión del archivo
        content_type = _normalizar_content_type(response.headers.get('content-type', ''))
        extension = obtener_extension_por_content_type(content_type)
        
        # Si el nombre ya incluye extensión, no forzar; si no, inferir desde content-type
        if not os.path.splitext(nombre_archivo)[1] and extension:
            nombre_archivo += extension

        nombre_archivo = _limpiar_nombre_archivo_con_extension(nombre_archivo)
        nombre_archivo = _asegurar_nombre_unico(carpeta_destino, nombre_archivo)
        
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
    content_type = _normalizar_content_type(content_type)

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
            # Soporta filename= y filename*=UTF-8''...
            m_star = re.search(r"filename\\*=(?:UTF-8''|utf-8'')?([^;]+)", disposition)
            if m_star:
                candidato = unquote(m_star.group(1).strip().strip('"').strip("'"))
                if candidato:
                    nombre_archivo = candidato
            else:
                m = re.search(r"filename=([^;]+)", disposition)
                if m:
                    candidato = m.group(1).strip().strip('"').strip("'")
                    if candidato:
                        nombre_archivo = candidato
        except Exception:
            pass

    content_type = _normalizar_content_type(resp.headers.get("content-type", ""))
    return resp.content, nombre_archivo, content_type


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
    rut = _extraer_rut_de_record(payload)
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
    return resultados, rut


def _normalizar_nombre_laxo(nombre):
    limpio = _normalizar_nombre_para_comparar(nombre)
    base, ext = os.path.splitext(limpio)
    base = re.sub(r" \\(\\d+\\)$", "", base).strip()
    return f"{base[:90]}{ext}"


def _verificar_adjuntos_con_ui(codigo_ca, driver, manifest):
    """
    Verifica al final del proceso que los adjuntos descargados coinciden con los adjuntos
    visibles en la UI (modal 'Adjuntos de la cotización') para cada proveedor.
    Anota resultados dentro del manifest y reporta por consola.
    """
    if not navegar_a_compra_agil(codigo_ca, driver):
        print("[VERIFY] No se pudo navegar a la compra ágil para verificación UI")
        return

    proveedores_ui = obtener_proveedores_ca(driver)
    if not proveedores_ui:
        print("[VERIFY] No se encontraron proveedores en UI para verificación")
        return

    entradas = manifest.get("proveedores") or []
    by_rut = {}
    by_label = {}
    for e in entradas:
        rut = e.get("rut")
        rut_norm = _normalizar_rut(rut) or (str(rut).strip() if rut else None)
        if rut_norm:
            by_rut[rut_norm] = e
        label = (e.get("label") or "").strip().upper()
        if label:
            by_label[label] = e

    faltantes_total = 0
    proveedores_con_faltantes = 0

    for proveedor in proveedores_ui:
        rut_ui = _normalizar_rut(proveedor.get("rut")) or (proveedor.get("rut") or "").strip()
        label_ui = (proveedor.get("nombre") or "").strip().upper()

        entry = by_rut.get(rut_ui) if rut_ui else None
        if not entry and label_ui:
            entry = by_label.get(label_ui)

        if not entry:
            # Crea una entrada mínima para que quede registro
            entry = {
                "id_cotizacion": None,
                "label": proveedor.get("nombre") or "",
                "rut": rut_ui or proveedor.get("rut") or "",
                "carpeta": "",
                "esperados_api": None,
                "nombres_esperados_api": [],
                "descargados": [],
                "errores_descarga": [],
            }
            entradas.append(entry)
            if rut_ui:
                by_rut[rut_ui] = entry
            if label_ui:
                by_label[label_ui] = entry

        nombres_ui = _listar_nombres_adjuntos_ui(proveedor, driver)
        entry["esperados_ui"] = len(nombres_ui)
        entry["nombres_esperados_ui"] = nombres_ui

        carpeta = entry.get("carpeta") or ""
        descargados_fs = _listar_archivos_descargados(carpeta) if carpeta else []
        entry["descargados_fs"] = descargados_fs

        descargados_norm = {_normalizar_nombre_para_comparar(n) for n in descargados_fs}
        descargados_laxo = {_normalizar_nombre_laxo(n) for n in descargados_fs}

        faltantes = []
        for n in nombres_ui:
            n_norm = _normalizar_nombre_para_comparar(n)
            if n_norm in descargados_norm:
                continue
            if _normalizar_nombre_laxo(n) in descargados_laxo:
                continue
            faltantes.append(n)

        entry["faltantes_ui"] = faltantes
        entry["ok_ui"] = len(faltantes) == 0

        if faltantes:
            proveedores_con_faltantes += 1
            faltantes_total += len(faltantes)
            print(
                f"[VERIFY] Faltan {len(faltantes)}/{len(nombres_ui)} adjuntos para "
                f"'{entry.get('label')}' ({entry.get('rut')}). Carpeta='{carpeta}'."
            )
            for n in faltantes[:10]:
                print(f"         - {n}")
            if len(faltantes) > 10:
                print(f"         - ... y {len(faltantes) - 10} más")

    manifest["proveedores"] = entradas
    manifest["verificacion_ui"] = {
        "total_proveedores_ui": len(proveedores_ui),
        "proveedores_con_faltantes": proveedores_con_faltantes,
        "faltantes_total": faltantes_total,
        "verificado_en": datetime.now().isoformat(timespec="seconds"),
    }


def _listar_nombres_adjuntos_ui(proveedor, driver):
    """
    Abre el detalle del proveedor y devuelve los nombres visibles en la sección 'Adjuntos de la cotización'.
    """
    elemento_ver_detalle = proveedor.get("elemento_ver_detalle") or proveedor.get("elemento")
    if not elemento_ver_detalle:
        return []

    wait = WebDriverWait(driver, 20)

    try:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento_ver_detalle)
        except Exception:
            pass

        try:
            wait.until(EC.element_to_be_clickable(elemento_ver_detalle))
            elemento_ver_detalle.click()
        except Exception:
            driver.execute_script("arguments[0].click();", elemento_ver_detalle)

        etiqueta_adjuntos = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//p[contains(normalize-space(),'Adjuntos de la cotización') or "
                    "contains(normalize-space(),'Adjuntos de la cotizacion')]",
                )
            )
        )

        try:
            contenedor_adjuntos = etiqueta_adjuntos.find_element(
                By.XPATH,
                "./ancestor::div[contains(@class,'MuiGrid-root')][1]/following-sibling::div[1]",
            )
        except Exception:
            contenedor_adjuntos = etiqueta_adjuntos.find_element(By.XPATH, "./ancestor::div[1]")

        enlaces = contenedor_adjuntos.find_elements(By.CSS_SELECTOR, "a.sc-cInsRk")
        if not enlaces:
            enlaces = contenedor_adjuntos.find_elements(By.TAG_NAME, "a")

        nombres = []
        for enlace in enlaces:
            try:
                t = (enlace.text or "").strip()
                if t:
                    nombres.append(t)
            except Exception:
                continue

        # Cerrar modal
        try:
            boton_cerrar = driver.find_element(By.XPATH, "//button[contains(normalize-space(),'Cerrar')]")
            driver.execute_script("arguments[0].click();", boton_cerrar)
        except Exception:
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
            except Exception:
                pass

        time.sleep(0.5)
        return nombres
    except Exception:
        # Intentar cerrar en caso de error
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
        except Exception:
            pass
        return []


def _extraer_rut_de_record(record):
    if not isinstance(record, dict):
        return None

    for key, value in record.items():
        if value is None:
            continue
        key_lower = str(key).lower()
        texto = str(value)

        # Solo confia en claves que indican rut/tributario
        if "rut" in key_lower or "tribut" in key_lower:
            rut_detectado = _normalizar_rut(texto)
            if rut_detectado:
                return rut_detectado

        # Como fallback, busca un patrón de RUT en el texto (debe tener guion)
        rut_en_texto = _extraer_rut_en_string(texto)
        if rut_en_texto:
            return rut_en_texto

    return None


def _extraer_rut_desde_texto(texto):
    if not texto:
        return None
    return _extraer_rut_en_string(str(texto))


def _normalizar_rut(rut_raw):
    """
    Normaliza un RUT para dejarlo en formato con puntos y guion (ej: 76.709.823-5).
    Acepta formatos con guion y también el caso compacto sin guion (ej: 767098235).
    """
    if not rut_raw:
        return None

    texto = str(rut_raw).strip().upper()
    texto = re.sub(r"\s+", "", texto)

    match = re.search(
        r'(\d{1,2}\.?\d{3}\.?\d{3}-[\dK])|(\d{7,8}-[\dK])|(\d{7,8}[\dK])',
        texto,
    )
    if not match:
        return None

    texto = match.group(0)
    if "-" not in texto:
        texto = f"{texto[:-1]}-{texto[-1]}"
    solo_permitidos = re.sub(r'[^0-9K]', '', texto)
    cuerpo = solo_permitidos[:-1]
    dv = solo_permitidos[-1]
    if not cuerpo:
        return None
    cuerpo_formateado = _formatear_cuerpo_con_puntos(cuerpo)
    return f"{cuerpo_formateado}-{dv}"


def _extraer_rut_en_string(texto):
    if not texto:
        return None
    match = re.search(r'(\d{1,2}\.?\d{3}\.?\d{3}-[\dK])', str(texto).upper())
    if match:
        return _normalizar_rut(match.group(0))
    match_simple = re.search(r'\d{7,8}-[\dK]', str(texto).upper())
    if match_simple:
        return _normalizar_rut(match_simple.group(0))
    return None


def _formatear_cuerpo_con_puntos(cuerpo):
    cuerpo = str(cuerpo)
    partes = []
    while len(cuerpo) > 3:
        partes.insert(0, cuerpo[-3:])
        cuerpo = cuerpo[:-3]
    partes.insert(0, cuerpo)
    return ".".join(partes)


def descargar_certificado_habilidad(rut, carpeta_proveedor, driver=None):
    """
    Descarga el certificado de habilidad del proveedor y lo guarda como PDF.
    Intenta primero con requests (esperando un PDF directo). Si la respuesta no es un PDF,
    usa el navegador (si está disponible) para imprimir la página a PDF vía Chrome DevTools.
    """
    rut_normalizado = _normalizar_rut(rut)
    if not rut_normalizado:
        print(f"[CERT] RUT no válido o ausente para certificado: {rut}")
        return False

    carpeta_certificados = os.path.join(carpeta_proveedor, "CERTIFICADOS")
    os.makedirs(carpeta_certificados, exist_ok=True)
    destino_pdf = os.path.join(carpeta_certificados, "CertificadoHabilidad.pdf")
    url = f"{CERT_BASE_URL}/{rut_normalizado}"

    return descargar_pdf_a_archivo(url, destino_pdf, driver=driver, tag="[CERT]")


def descargar_declaracion_jurada(rut, carpeta_proveedor, driver=None):
    """
    Descarga la página de Beneficiarios Finales (Declaración Jurada) del proveedor y la guarda como PDF.
    Intenta primero con requests (si devuelve PDF directo). Si no es PDF o falla, usa el navegador
    (si está disponible) para imprimir la página a PDF vía Chrome DevTools.
    """
    rut_normalizado = _normalizar_rut(rut)
    if not rut_normalizado:
        print(f"[DJ] RUT no válido o ausente para declaración jurada: {rut}")
        return False

    carpeta_certificados = os.path.join(carpeta_proveedor, "CERTIFICADOS")
    os.makedirs(carpeta_certificados, exist_ok=True)
    destino_pdf = os.path.join(carpeta_certificados, "DeclaracionJurada.pdf")
    url = f"{DECLARACION_JURADA_BASE_URL}/{rut_normalizado}"

    return descargar_pdf_a_archivo(url, destino_pdf, driver=driver, tag="[DJ]")


def descargar_pdf_a_archivo(url, destino_pdf, driver=None, tag="[PDF]"):
    """
    Descarga/guarda un PDF desde una URL.
    - Intenta requests (PDF directo).
    - Si no es PDF o falla, usa el navegador (si está disponible) para imprimir a PDF vía Chrome DevTools.
    """
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        contenido = resp.content or b""
        content_type = (resp.headers.get("content-type") or "").lower()
        if contenido.startswith(b"%PDF") or "pdf" in content_type:
            os.makedirs(os.path.dirname(destino_pdf), exist_ok=True)
            with open(destino_pdf, "wb") as f:
                f.write(contenido)
            print(f"{tag} PDF descargado -> {destino_pdf}")
            return True
        print(f"{tag} Respuesta no es PDF (content-type: {content_type}), intentando imprimir con navegador.")
    except Exception as e:
        print(f"{tag} Error descargando PDF vía requests: {e}")

    if not driver:
        print(f"{tag} No hay navegador disponible para imprimir el PDF.")
        return False

    try:
        os.makedirs(os.path.dirname(destino_pdf), exist_ok=True)
    except Exception:
        pass
    return _imprimir_certificado_con_navegador(url, destino_pdf, driver)


def descargar_certificado_habilidad_a_carpeta(rut, carpeta_certificados, driver=None, nombre_archivo="CertificadoHabilidad.pdf"):
    rut_normalizado = _normalizar_rut(rut)
    if not rut_normalizado:
        print(f"[CERT] RUT no válido o ausente para certificado: {rut}")
        return False
    destino_pdf = os.path.join(carpeta_certificados, nombre_archivo)
    url = f"{CERT_BASE_URL}/{rut_normalizado}"
    return descargar_pdf_a_archivo(url, destino_pdf, driver=driver, tag="[CERT]")


def descargar_declaracion_jurada_licitacion_a_carpeta(
    codigo_licitacion,
    rut,
    carpeta_certificados,
    driver=None,
    nombre_archivo="DeclaracionJurada.pdf",
):
    """
    Descarga la declaración jurada específica de licitación desde:
      https://proveedor.mercadopublico.cl/dj-requisitos/{codigo}/{rut}
    y la guarda como PDF (requests o impresión con navegador).
    """
    rut_normalizado = _normalizar_rut(rut)
    if not rut_normalizado:
        print(f"[DJ] RUT no válido o ausente para declaración jurada (licitación): {rut}")
        return False
    codigo = (str(codigo_licitacion) or "").strip()
    if not codigo:
        print("[DJ] Código de licitación vacío para declaración jurada.")
        return False
    destino_pdf = os.path.join(carpeta_certificados, nombre_archivo)
    url = f"{DECLARACION_JURADA_LICITACION_BASE_URL}/{codigo}/{rut_normalizado}"
    return descargar_pdf_a_archivo(url, destino_pdf, driver=driver, tag="[DJ]")


def imprimir_pagina_actual_a_pdf(
    destino_pdf,
    driver,
    tag="[PDF]",
    full_page=False,
    prefer_css_page_size=True,
):
    """
    Guarda el estado actual del navegador como PDF usando Chrome DevTools.
    Útil para modales/vistas SPA sin URL descargable.
    """
    if not driver:
        return False
    try:
        os.makedirs(os.path.dirname(destino_pdf), exist_ok=True)
    except Exception:
        pass
    try:
        try:
            WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:
            pass
        time.sleep(1.0)
        params = {"printBackground": True}
        if prefer_css_page_size:
            params["preferCSSPageSize"] = True
        if full_page:
            try:
                metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                content_size = (metrics or {}).get("contentSize") or {}
                width_px = content_size.get("width")
                height_px = content_size.get("height")
                if not width_px or not height_px:
                    size = driver.execute_script(
                        "return {"
                        "width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),"
                        "height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"
                        "};"
                    )
                    if size:
                        width_px = size.get("width")
                        height_px = size.get("height")
                if width_px and height_px:
                    params.update(
                        {
                            "paperWidth": max(1, float(width_px) / 96.0),
                            "paperHeight": max(1, float(height_px) / 96.0),
                            "marginTop": 0,
                            "marginBottom": 0,
                            "marginLeft": 0,
                            "marginRight": 0,
                        }
                    )
            except Exception:
                pass
        resultado_pdf = driver.execute_cdp_cmd("Page.printToPDF", params)
        data_base64 = resultado_pdf.get("data") if isinstance(resultado_pdf, dict) else None
        if not data_base64:
            raise RuntimeError("Chrome no entregó datos para el PDF")
        with open(destino_pdf, "wb") as f:
            f.write(base64.b64decode(data_base64))
        print(f"{tag} PDF generado -> {destino_pdf}")
        return True
    except Exception as e:
        print(f"{tag} Error al generar PDF: {e}")
        return False


def _imprimir_certificado_con_navegador(url, destino_pdf, driver):
    try:
        handle_original = driver.current_window_handle
    except Exception:
        handle_original = None

    nueva_ventana = False
    original_url = None
    try:
        original_url = driver.current_url
    except Exception:
        pass

    try:
        driver.switch_to.new_window('tab')
        nueva_ventana = True
    except Exception:
        nueva_ventana = False

    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:
            pass
        time.sleep(2)
        resultado_pdf = driver.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})
        data_base64 = resultado_pdf.get("data") if isinstance(resultado_pdf, dict) else None
        if not data_base64:
            raise RuntimeError("Chrome no entregó datos para el PDF")
        with open(destino_pdf, "wb") as f:
            f.write(base64.b64decode(data_base64))
        print(f"[CERT] Certificado generado con navegador -> {destino_pdf}")
        return True
    except Exception as e:
        print(f"[CERT] Error al generar PDF con navegador: {e}")
        return False
    finally:
        try:
            if nueva_ventana:
                driver.close()
                if handle_original:
                    driver.switch_to.window(handle_original)
            elif original_url:
                driver.get(original_url)
        except Exception:
            pass


def descargar_comprobante_oferta_compra_agil_por_proveedor(proveedor, carpeta_proveedor, driver):
    """
    Abre "Ver detalle" del proveedor (modal/vista) y guarda un PDF como ComprobanteOferta.pdf
    en carpeta_proveedor/CERTIFICADOS.
    """
    if not driver or not proveedor or not carpeta_proveedor:
        return False

    wait = WebDriverWait(driver, 25)
    carpeta_certificados = os.path.join(carpeta_proveedor, "CERTIFICADOS")
    os.makedirs(carpeta_certificados, exist_ok=True)
    destino_pdf = os.path.join(carpeta_certificados, "ComprobanteOferta.pdf")

    def _buscar_enlace_ver_detalle():
        idx_ver_detalle = proveedor.get("idx_ver_detalle")
        rut_obj = _normalizar_rut(proveedor.get("rut")) or (proveedor.get("rut") or "").strip()
        rut_key = (rut_obj or "").strip().upper().replace(".", "").replace(" ", "")
        nombre_key = _normalizar_texto_busqueda(proveedor.get("nombre"))

        try:
            driver.execute_script("window.scrollTo(0, 0);")
        except Exception:
            pass
        time.sleep(0.2)

        last_y = None

        for _ in range(12):
            enlaces = driver.find_elements(By.XPATH, "//a[normalize-space()='Ver detalle']")
            if not enlaces:
                enlaces = driver.find_elements(By.XPATH, "//a[contains(normalize-space(),'Ver detalle')]")

            # 1) Preferir match por RUT/nombre (evita depender del índice).
            if enlaces and (rut_key or nombre_key):
                for enlace in enlaces:
                    tarjeta = None
                    for xp in (
                        "./ancestor::*[.//a[contains(@href,'proveedor.mercadopublico.cl/ficha')]][1]",
                        "./ancestor::*[self::div or self::section or self::article][1]",
                    ):
                        try:
                            tarjeta = enlace.find_element(By.XPATH, xp)
                            break
                        except Exception:
                            tarjeta = None

                    texto_tarjeta = ""
                    try:
                        texto_tarjeta = (tarjeta.text or "").strip() if tarjeta else ""
                    except Exception:
                        texto_tarjeta = ""

                    if rut_key:
                        texto_rut = texto_tarjeta.replace(".", "").replace(" ", "").upper()
                        if rut_key in texto_rut:
                            return enlace
                    if nombre_key and texto_tarjeta:
                        if nombre_key in _normalizar_texto_busqueda(texto_tarjeta):
                            return enlace

            # 2) Luego intentar por índice (si existe y está en rango).
            if idx_ver_detalle is not None and enlaces and 0 <= idx_ver_detalle < len(enlaces):
                return enlaces[idx_ver_detalle]

            # 3) Scroll incremental para casos con lazy-render / virtualización.
            try:
                y = driver.execute_script("return window.scrollY") or 0
                if last_y is not None and y == last_y:
                    break
                last_y = y
                driver.execute_script("window.scrollBy(0, 700);")
            except Exception:
                break
            time.sleep(0.4)

        # Fallback al XPath conocido (último recurso).
        try:
            return driver.find_element(
                By.XPATH,
                "/html/body/div[1]/div/main/div[2]/div[1]/div/div[2]/div/div/div[7]/div/div[1]/a",
            )
        except Exception:
            return None

    elemento_ver_detalle = None
    click_ok = False
    ultimo_error_click = None
    origin_handle = None
    before_handles = set()
    prev_url = ""
    idx_hint = proveedor.get("idx_ver_detalle")
    rut_hint = _normalizar_rut(proveedor.get("rut")) or (proveedor.get("rut") or "").strip()
    nombre_hint = proveedor.get("nombre") or ""

    for intento in range(1, 7):
        try:
            elemento_ver_detalle = _buscar_enlace_ver_detalle()
            if not elemento_ver_detalle:
                print(
                    f"[VOUCHER_CA] No se encontró enlace 'Ver detalle' para proveedor "
                    f"{proveedor.get('nombre')} ({proveedor.get('rut')}) (intento {intento}/3)."
                )
                time.sleep(0.6)
                continue

            # Capturar contexto ANTES del click para detectar navegación/ventanas nuevas.
            try:
                origin_handle = driver.current_window_handle
            except Exception:
                origin_handle = None
            try:
                before_handles = set(driver.window_handles or [])
            except Exception:
                before_handles = set()
            try:
                prev_url = driver.current_url or ""
            except Exception:
                prev_url = ""

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento_ver_detalle)
            except Exception:
                pass

            try:
                try:
                    wait.until(EC.element_to_be_clickable(elemento_ver_detalle))
                except Exception:
                    pass
                if not _safe_click(driver, elemento_ver_detalle):
                    # Fallback JS (evita stale elements).
                    if not _js_click_ver_detalle(driver, idx=idx_hint, rut=rut_hint, nombre=nombre_hint):
                        raise RuntimeError("No se pudo hacer click en 'Ver detalle'")
            except StaleElementReferenceException as exc:
                ultimo_error_click = exc
                if _js_click_ver_detalle(driver, idx=idx_hint, rut=rut_hint, nombre=nombre_hint):
                    click_ok = True
                    ultimo_error_click = None
                    break
                time.sleep(0.6)
                continue
            except Exception as exc:
                ultimo_error_click = exc
                if _js_click_ver_detalle(driver, idx=idx_hint, rut=rut_hint, nombre=nombre_hint):
                    click_ok = True
                    ultimo_error_click = None
                    break
                time.sleep(0.6)
                continue

            # Click exitoso: salir del loop de reintentos
            click_ok = True
            ultimo_error_click = None
            break
        except Exception as exc:
            ultimo_error_click = exc
            time.sleep(0.6)
            continue

    if not click_ok:
        if ultimo_error_click:
            print(f"[VOUCHER_CA] Click 'Ver detalle' falló para {proveedor.get('nombre')} ({proveedor.get('rut')}): {ultimo_error_click}")
        return False

    modo_detalle = "modal_or_same"
    try:
        WebDriverWait(driver, 6).until(lambda d: len(d.window_handles) > len(before_handles))
        nuevos = set(driver.window_handles or []) - before_handles
        if nuevos:
            nuevo_handle = next(iter(nuevos))
            driver.switch_to.window(nuevo_handle)
            modo_detalle = "new_window"
    except TimeoutException:
        try:
            if prev_url and (driver.current_url or "") != prev_url:
                modo_detalle = "same_tab_nav"
        except Exception:
            pass

    _wait_ready(driver, timeout=20)

    # Esperar que cargue el modal/detalle
    try:
        wait.until(
            lambda d: (
                d.find_elements(
                    By.XPATH,
                    "//p[contains(normalize-space(),'Adjuntos de la cotización') or contains(normalize-space(),'Adjuntos de la cotizacion')]",
                )
                or d.find_elements(
                    By.XPATH,
                    "//*[contains(normalize-space(),'Cotización enviada') or contains(normalize-space(),'Cotizacion enviada')]",
                )
                or d.find_elements(
                    By.XPATH,
                    "//button[contains(normalize-space(),'Cerrar') or contains(normalize-space(),'Volver') or contains(normalize-space(),'Atrás')]",
                )
            )
        )
    except TimeoutException:
        time.sleep(1.5)

    try:
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass

    # Importante: preferCSSPageSize=True (como en test_comprobanteorden.py) suele ser más estable que
    # forzar un "full_page" con paperWidth/paperHeight enormes.
    ok = imprimir_pagina_actual_a_pdf(
        destino_pdf,
        driver,
        tag="[VOUCHER_CA]",
        full_page=False,
        prefer_css_page_size=True,
    )

    # Cerrar detalle según el modo detectado (método inspirado en test_comprobanteorden.py).
    if modo_detalle == "new_window":
        try:
            driver.close()
        except Exception:
            pass
        if origin_handle:
            try:
                driver.switch_to.window(origin_handle)
            except Exception:
                pass
        _wait_ready(driver, timeout=15)
    elif modo_detalle == "same_tab_nav":
        if prev_url:
            try:
                driver.get(prev_url)
            except Exception:
                pass
        _wait_ready(driver, timeout=15)
    else:
        try:
            boton_cerrar = driver.find_element(
                By.XPATH,
                "//button[contains(normalize-space(),'Cerrar') or contains(normalize-space(),'Volver') or contains(normalize-space(),'Atrás')]",
            )
            driver.execute_script("arguments[0].click();", boton_cerrar)
        except Exception:
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
            except Exception:
                pass

    time.sleep(0.5)
    return bool(ok)


def descargar_comprobantes_oferta_compra_agil(codigo_ca, driver, base_dir="Descargas"):
    """
    Recorre proveedores de una compra ágil, abre 'Ver detalle' y guarda ComprobanteOferta.pdf
    en la carpeta CERTIFICADOS de cada proveedor.
    """
    if not driver:
        return False

    carpeta_base = resolver_carpeta_base(base_dir, "ComprasAgiles", codigo_ca)
    os.makedirs(carpeta_base, exist_ok=True)

    # Mapa por RUT desde manifest (si existe) para guardar en la misma carpeta usada por API
    manifest_by_rut = {}
    try:
        ruta_manifest = os.path.join(carpeta_base, MANIFEST_ADJUNTOS_FILENAME)
        if os.path.exists(ruta_manifest):
            with open(ruta_manifest, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            for p in data.get("proveedores") or []:
                rut = _normalizar_rut(p.get("rut")) or (p.get("rut") or "").strip()
                carpeta = p.get("carpeta")
                if rut and carpeta:
                    manifest_by_rut[rut] = carpeta
    except Exception:
        manifest_by_rut = {}

    # Asegurar que estamos en el resumen (lista de proveedores)
    if not navegar_a_compra_agil(codigo_ca, driver):
        print("[VOUCHER_CA] No se pudo navegar al resumen de compra ágil.")
        return False

    proveedores = obtener_proveedores_ca(driver) or []
    if not proveedores:
        print("[VOUCHER_CA] No se encontraron proveedores en la UI para imprimir comprobantes.")
        return False

    ok_any = False
    max_intentos_por_proveedor = 4
    for prov in proveedores:
        rut = _normalizar_rut(prov.get("rut")) or (prov.get("rut") or "").strip()
        carpeta_prov = None
        if rut and rut in manifest_by_rut:
            carpeta_prov = manifest_by_rut[rut]
        if not carpeta_prov:
            nombre = limpiar_nombre_archivo(prov.get("nombre") or "Proveedor")
            carpeta_prov = os.path.join(carpeta_base, nombre)
        try:
            os.makedirs(carpeta_prov, exist_ok=True)
        except Exception:
            pass

        try:
            destino_pdf = os.path.join(carpeta_prov, "CERTIFICADOS", "ComprobanteOferta.pdf")
            if _archivo_listo(destino_pdf):
                ok_any = True
                continue

            ok = False
            for intento in range(1, max_intentos_por_proveedor + 1):
                try:
                    # Ir siempre al resumen antes de cada intento para evitar DOM inestable/stale.
                    if not navegar_a_compra_agil(codigo_ca, driver):
                        time.sleep(0.8)
                        continue
                    try:
                        WebDriverWait(driver, 20).until(
                            lambda d: len(
                                d.find_elements(By.XPATH, "//a[contains(normalize-space(),'Ver detalle')]")
                            )
                            > 0
                        )
                    except Exception:
                        pass

                    ok = descargar_comprobante_oferta_compra_agil_por_proveedor(prov, carpeta_prov, driver)
                except Exception as exc:
                    print(
                        f"[VOUCHER_CA] Error intento {intento}/{max_intentos_por_proveedor} "
                        f"para {prov.get('nombre')} ({prov.get('rut')}): {exc}"
                    )
                    ok = False

                if ok and _archivo_listo(destino_pdf):
                    ok_any = True
                    break

                # Limpieza mínima antes de reintentar
                try:
                    body = driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.ESCAPE)
                except Exception:
                    pass
                time.sleep(0.8)

            if not ok or not _archivo_listo(destino_pdf):
                print(
                    f"[VOUCHER_CA] No se pudo generar ComprobanteOferta.pdf para "
                    f"{prov.get('nombre')} ({prov.get('rut')})."
                )
        except Exception as exc:
            print(f"[VOUCHER_CA] Error imprimiendo comprobante para {prov.get('nombre')} ({prov.get('rut')}): {exc}")
            continue

    return ok_any


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
        rut = _extraer_rut_de_record(record) or _extraer_rut_desde_texto(label)
        candidates.append({"id": identifier_str, "label": label, "rut": rut})
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

def crear_zip_carpeta(ruta_carpeta, ruta_zip):
    """
    Crea un archivo ZIP con el contenido de una carpeta completa.

    Args:
        ruta_carpeta (str): Ruta a la carpeta a comprimir
        ruta_zip (str): Ruta final del ZIP a generar

    Returns:
        str: Ruta del archivo ZIP creado, o None si falla
    """
    try:
        if not ruta_carpeta or not os.path.isdir(ruta_carpeta):
            print(f"[ZIP] Carpeta no existe: {ruta_carpeta}")
            return None

        os.makedirs(os.path.dirname(ruta_zip), exist_ok=True)
        ruta_zip_abs = os.path.abspath(ruta_zip)
        ruta_carpeta_abs = os.path.abspath(ruta_carpeta)

        with zipfile.ZipFile(ruta_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(ruta_carpeta):
                for file in files:
                    ruta_archivo = os.path.join(root, file)
                    if os.path.abspath(ruta_archivo) == ruta_zip_abs:
                        continue
                    nombre_en_zip = os.path.relpath(ruta_archivo, ruta_carpeta_abs)
                    zipf.write(ruta_archivo, nombre_en_zip)

        print(f"[ZIP] ZIP creado: {ruta_zip}")
        return ruta_zip
    except Exception as e:
        print(f"[ZIP] Error al crear ZIP para carpeta {ruta_carpeta}: {str(e)}")
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

def _limpiar_nombre_proyecto(codigo, nombre):
    nombre = " ".join((nombre or "").split()).strip()
    if not nombre:
        return ""
    codigo_str = (str(codigo) or "").strip()
    codigo_norm = codigo_str.lower()

    if codigo_norm and nombre.lower().startswith(codigo_norm):
        nombre = nombre[len(codigo_str):].strip(" -_/()[]")
    if codigo_norm and nombre.lower().endswith(codigo_norm):
        nombre = nombre[: -len(codigo_str)].strip(" -_/()[]")

    frases_genericas = {
        "detalle de la cotizacion",
        "detalle de la cotización",
        "detalle cotizacion",
        "detalle cotización",
    }
    nombre_norm = nombre.lower()
    for frase in frases_genericas:
        if nombre_norm == frase:
            return ""
        if nombre_norm.startswith(f"{frase} "):
            nombre = nombre[len(frase) :].strip(" -_/()[]")
            nombre_norm = nombre.lower()
        if nombre_norm.endswith(f" {frase}"):
            nombre = nombre[: -len(frase)].strip(" -_/()[]")
            nombre_norm = nombre.lower()

    if codigo_norm and nombre.lower().startswith(codigo_norm):
        nombre = nombre[len(codigo_str):].strip(" -_/()[]")
    if codigo_norm and nombre.lower().endswith(codigo_norm):
        nombre = nombre[: -len(codigo_str)].strip(" -_/()[]")

    if nombre.lower() in frases_genericas:
        return ""
    return nombre

def construir_nombre_carpeta_base(codigo, nombre_proyecto=None):
    codigo_str = (str(codigo) or "").strip()
    nombre = _limpiar_nombre_proyecto(codigo_str, nombre_proyecto)
    if nombre:
        base = f"{codigo_str} {nombre}".strip()
    else:
        base = codigo_str
    base = limpiar_nombre_archivo(base)
    return base or codigo_str or "sin_codigo"

def resolver_carpeta_base(base_dir, subdir, codigo, nombre_proyecto=None):
    base_dir = base_dir or "Descargas"
    subdir = subdir or ""
    codigo_str = (str(codigo) or "").strip()
    nombre = (nombre_proyecto or "").strip()
    carpeta_root = os.path.join(base_dir, subdir) if subdir else base_dir
    if nombre:
        carpeta = construir_nombre_carpeta_base(codigo_str, nombre)
        return os.path.join(carpeta_root, carpeta)
    if not codigo_str:
        return carpeta_root
    if not os.path.isdir(carpeta_root):
        return os.path.join(carpeta_root, codigo_str)
    candidatos = []
    try:
        for nombre_dir in os.listdir(carpeta_root):
            if nombre_dir == codigo_str:
                pass
            elif nombre_dir.startswith(f"{codigo_str} "):
                pass
            elif nombre_dir.startswith(f"{codigo_str}_"):
                pass
            else:
                continue
            ruta = os.path.join(carpeta_root, nombre_dir)
            if os.path.isdir(ruta):
                candidatos.append(ruta)
    except Exception:
        return exacta
    if not candidatos:
        return os.path.join(carpeta_root, codigo_str)
    def _rank(ruta):
        base = os.path.basename(ruta)
        if base.startswith(f"{codigo_str} "):
            return (0, base)
        if base.startswith(f"{codigo_str}_"):
            return (1, base)
        if base == codigo_str:
            return (2, base)
        return (3, base)
    candidatos.sort(key=_rank)
    return candidatos[0]

def _extraer_nombre_proyecto_compra_info(info_data):
    if not isinstance(info_data, dict):
        return ""
    payload = info_data.get("payload") or info_data
    def _probe(obj):
        if not isinstance(obj, dict):
            return ""
        for key in (
            "nombreSolicitud",
            "nombreCompra",
            "nombre",
            "titulo",
            "nombreLicitacion",
            "nombreAdquisicion",
            "nombreProyecto",
            "descripcion",
            "name",
            "title",
        ):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""
    nombre = _probe(payload)
    if nombre:
        return nombre
    for key in ("solicitud", "detalle", "compra", "adquisicion", "proceso", "cotizacion", "resumen"):
        try:
            nombre = _probe(payload.get(key))
        except Exception:
            nombre = ""
        if nombre:
            return nombre
    return ""

def _extraer_nombre_compra_agil_desde_ui(driver, codigo=None):
    if not driver:
        return ""

    def _limpiar(texto):
        texto = " ".join((texto or "").split()).strip()
        if not texto:
            return ""
        if codigo:
            texto = _limpiar_nombre_proyecto(codigo, texto)
        return texto.strip()

    def _es_candidato(texto):
        if not texto:
            return False
        if len(texto) < 3:
            return False
        if len(texto) > 180:
            return False
        lower = texto.lower()
        if "cotizacion" in lower or "cotización" in lower:
            return False
        return True

    xpaths = [
        "//h1[normalize-space()]",
        "//h2[normalize-space()]",
        "//div[contains(@class,'title') and normalize-space()]",
        "//span[contains(@class,'title') and normalize-space()]",
    ]
    for xp in xpaths:
        try:
            elem = driver.find_element(By.XPATH, xp)
        except Exception:
            continue
        texto = _limpiar(elem.text or "")
        if _es_candidato(texto):
            return texto

    label_xpaths = [
        "//p[normalize-space()='Nombre' or starts-with(normalize-space(),'Nombre')]/following-sibling::*[1]",
        "//p[normalize-space()='Titulo' or normalize-space()='Título']/following-sibling::*[1]",
        "//p[normalize-space()='Objeto' or starts-with(normalize-space(),'Objeto')]/following-sibling::*[1]",
        "//span[normalize-space()='Nombre' or starts-with(normalize-space(),'Nombre')]/following-sibling::*[1]",
        "//span[normalize-space()='Titulo' or normalize-space()='Título']/following-sibling::*[1]",
        "//span[normalize-space()='Objeto' or starts-with(normalize-space(),'Objeto')]/following-sibling::*[1]",
    ]
    for xp in label_xpaths:
        try:
            elem = driver.find_element(By.XPATH, xp)
        except Exception:
            continue
        texto = _limpiar(elem.text or "")
        if _es_candidato(texto):
            return texto

    try:
        candidatos = driver.find_elements(By.CSS_SELECTOR, "p.MuiTypography-root.MuiTypography-body2")
    except Exception:
        candidatos = []
    for elem in candidatos:
        texto = _limpiar(elem.text or "")
        if _es_candidato(texto):
            return texto

    try:
        candidatos = driver.find_elements(By.CSS_SELECTOR, "p.MuiTypography-root")
    except Exception:
        candidatos = []
    for elem in candidatos:
        texto = _limpiar(elem.text or "")
        if _es_candidato(texto):
            return texto

    return ""


def crear_zips_proveedores(codigo_ca, base_dir="Descargas"):
    """
    Recorre las carpetas de proveedores de una compra ágil y genera un ZIP por cada una.
    Ignora la carpeta 'Adjuntos' (adjuntos generales).
    """
    carpeta_base = resolver_carpeta_base(base_dir, "ComprasAgiles", codigo_ca)
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
