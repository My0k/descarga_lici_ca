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

if __name__ == "__main__":
    # Función principal para pruebas
    print("Módulo descarga_ca.py - Descarga de adjuntos de compras ágiles")
    print("Este módulo debe ser importado y usado desde app.py")
