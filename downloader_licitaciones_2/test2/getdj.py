import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import os

def setup_driver():
    """Configure Chrome driver with PDF printing capabilities"""
    chrome_options = Options()
    
    # Configuración para imprimir PDFs
    settings = {
        "recentDestinations": [{
            "id": "Save as PDF",
            "origin": "local",
            "account": ""
        }],
        "selectedDestinationId": "Save as PDF",
        "version": 2,
        "isHeaderFooterEnabled": False,
        "isLandscapeEnabled": False
    }
    
    prefs = {
        'printing.print_preview_sticky_settings.appState': settings,
        'savefile.default_directory': os.getcwd()
    }
    
    chrome_options.add_experimental_option('prefs', prefs)
    chrome_options.add_argument('--kiosk-printing')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--start-maximized')
    
    # Inicializar driver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver

def wait_for_page_load(driver, timeout=30):
    """Wait for page to be completely loaded"""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )
    
    # Esperar adicional para contenido dinámico
    time.sleep(3)
    
    # Scroll para cargar contenido lazy-loaded
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

def save_as_pdf(driver, filename):
    """Save current page as PDF"""
    print(f"Guardando {filename}...")
    
    # Ejecutar comando de impresión a PDF
    pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
        "printBackground": True,
        "landscape": False,
        "paperWidth": 8.27,  # A4 width in inches
        "paperHeight": 11.69,  # A4 height in inches
        "marginTop": 0.4,
        "marginBottom": 0.4,
        "marginLeft": 0.4,
        "marginRight": 0.4,
        "displayHeaderFooter": False,
        "preferCSSPageSize": True,
        "generateDocumentOutline": False,
        "generateTaggedPDF": False
    })
    
    # Guardar PDF
    with open(filename, 'wb') as file:
        import base64
        file.write(base64.b64decode(pdf_data['data']))
    
    print(f"✓ PDF guardado: {filename}")

def main():
    """Main function to download both pages as PDFs"""
    
    urls = {
        "declaracion_jurada.pdf": "https://proveedor.mercadopublico.cl/dj-requisitos/728-1-LE26/76.576.059-3",
        "ficha_proveedor.pdf": "https://proveedor.mercadopublico.cl/ficha/76.576.059-3"
    }
    
    driver = None
    
    try:
        print("Iniciando navegador...")
        driver = setup_driver()
        
        for filename, url in urls.items():
            print(f"\n{'='*60}")
            print(f"Procesando: {url}")
            print(f"{'='*60}")
            
            # Cargar página
            driver.get(url)
            
            # Esperar carga completa
            print("Esperando carga de la página...")
            wait_for_page_load(driver)
            
            # Guardar como PDF
            save_as_pdf(driver, filename)
            
            # Pausa entre páginas
            time.sleep(2)
        
        print(f"\n{'='*60}")
        print("✓ Proceso completado exitosamente")
        print(f"{'='*60}")
        print(f"Archivos guardados en: {os.getcwd()}")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
    finally:
        if driver:
            print("\nCerrando navegador...")
            driver.quit()

if __name__ == "__main__":
    main()
