#!/usr/bin/env python3
"""
Descargador de adjuntos de licitaciones de Mercado Publico Chile.

Incluye:
- Declaracion Jurada
- Informacion de Proveedor
- Anexos Administrativos, Tecnicos, Economicos
- Garantias

IMPORTANTE: Requiere autenticacion manual y resolver CAPTCHAs.
"""

import argparse
import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


DEFAULT_LICITACION_URL = (
    "https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx"
    "?idlicitacion=728-1-LE26"
)


class MercadoPublicoDownloader:
    """Descarga adjuntos de licitaciones de Mercado Publico Chile."""

    BASE_URL = "https://www.mercadopublico.cl"
    PROVEEDOR_URL = "https://proveedor.mercadopublico.cl"

    # Tipos de anexos y sus carpetas
    ANEXO_TYPES = {
        "declaracion_jurada": "declaracion_jurada",
        "informacion_proveedor": "informacion_proveedor",
        "anexos_administrativos": "anexos_administrativos",
        "anexos_tecnicos": "anexos_tecnicos",
        "anexos_economicos": "anexos_economicos",
        "garantias": "garantias",
    }

    def __init__(self, download_folder="descargas"):
        self.download_folder = download_folder
        self.session = requests.Session()
        self.driver = None

    def setup_selenium(self, headless=False):
        """Configura el navegador Selenium."""
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        # Configurar carpeta de descargas
        prefs = {
            "download.default_directory": os.path.abspath(self.download_folder),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        }
        chrome_options.add_experimental_option("prefs", prefs)

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(10)

    def close(self):
        """Cierra el navegador."""
        if self.driver:
            self.driver.quit()

    def create_folder_structure(self, licitacion_id):
        """
        Crea la estructura de carpetas para una licitacion.
        """
        base_path = os.path.join(self.download_folder, licitacion_id)

        for folder_name in self.ANEXO_TYPES.values():
            folder_path = os.path.join(base_path, folder_name)
            os.makedirs(folder_path, exist_ok=True)

        return base_path

    def create_proveedor_subfolder(self, base_path, anexo_type, rut_proveedor):
        """Crea subcarpeta para un proveedor dentro de un tipo de anexo."""
        rut_clean = rut_proveedor.replace(".", "").replace("-", "_")
        folder_path = os.path.join(base_path, anexo_type, rut_clean)
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    def extract_licitacion_id(self, url):
        """Extrae el ID de la licitacion de la URL."""
        parsed = urlparse(url)

        if "DetailsAcquisition" in url:
            response = self.session.get(url)
            id_pattern = r"\d{3,4}-\d{1,2}-[A-Z]{2}\d{2}"
            match = re.search(id_pattern, response.text)
            if match:
                return match.group()

        if parsed.path:
            match = re.search(r"\d{3,4}-\d{1,2}-[A-Z]{2}\d{2}", parsed.path)
            if match:
                return match.group()

        return None

    def get_opening_frame_url(self, details_url):
        """Obtiene la URL del iframe OpeningFrame desde la pagina de detalles."""
        response = self.session.get(details_url)
        soup = BeautifulSoup(response.text, "html.parser")

        iframe = soup.find("iframe", {"name": "PopupFicha"})
        if iframe and iframe.get("src"):
            return urljoin(self.BASE_URL, iframe["src"])

        for element in soup.find_all(["input", "a"], href=True):
            href = element.get("href", "")
            if "OpeningFrame" in href:
                return urljoin(self.BASE_URL, href)

        return None

    def get_ofertas_data(self, opening_frame_url):
        """Extrae los datos de todas las ofertas del cuadro comparativo."""
        self.driver.get(opening_frame_url)
        time.sleep(3)

        ofertas = []

        try:
            table = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//table[contains(.,'Rut Proveedor')]"))
            )

            rows = table.find_elements(By.TAG_NAME, "tr")

            for row in rows[1:]:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 6:
                    oferta = {
                        "rut": cells[0].text.strip(),
                        "proveedor": cells[1].text.strip(),
                        "nombre_oferta": cells[2].text.strip(),
                        "total_oferta": cells[3].text.strip(),
                        "estado": cells[4].text.strip(),
                        "anexos": {},
                    }

                    anexos_cell = cells[-1]
                    images = anexos_cell.find_elements(By.CSS_SELECTOR, "img, input[type='image']")

                    anexo_names = list(self.ANEXO_TYPES.keys())

                    for i, element in enumerate(images[:6]):
                        if i < len(anexo_names):
                            onclick = element.get_attribute("onclick")
                            parent = element.find_element(By.XPATH, "./..")
                            href = parent.get_attribute("href") if parent.tag_name == "a" else None

                            oferta["anexos"][anexo_names[i]] = {
                                "onclick": onclick,
                                "href": href,
                                "element": element,
                            }

                    ofertas.append(oferta)

        except Exception as exc:
            print(f"Error extrayendo ofertas: {exc}")

        return ofertas

    def download_declaracion_jurada(self, licitacion_id, rut, output_folder):
        """Descarga la Declaracion Jurada de un proveedor."""
        url = f"{self.PROVEEDOR_URL}/dj-requisitos/{licitacion_id}/{rut}"

        try:
            self.driver.get(url)
            time.sleep(2)

            html_path = os.path.join(
                output_folder,
                f"declaracion_jurada_{rut.replace('.', '').replace('-', '_')}.html",
            )

            with open(html_path, "w", encoding="utf-8") as handle:
                handle.write(self.driver.page_source)

            print(f"Declaracion Jurada guardada: {html_path}")
            return True

        except Exception as exc:
            print(f"Error descargando declaracion jurada para {rut}: {exc}")
            return False

    def download_anexos(self, anexo_url, anexo_type, rut, output_folder):
        """Descarga anexos desde ViewBidAttachment.aspx."""
        try:
            self.driver.get(anexo_url)
            time.sleep(2)

            adjuntos = []

            try:
                table = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//table[contains(.,'Anexo')]"))
                )

                rows = table.find_elements(By.TAG_NAME, "tr")

                for row in rows[1:]:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 5:
                        adjunto = {
                            "checkbox": cells[0].find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                            if cells[0].find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
                            else None,
                            "nombre": cells[1].text.strip(),
                            "tipo": cells[2].text.strip(),
                            "descripcion": cells[3].text.strip(),
                            "tamano": cells[4].text.strip(),
                            "ver_button": cells[5].find_element(By.CSS_SELECTOR, "input[type='image']")
                            if len(cells) > 5 and cells[5].find_elements(By.CSS_SELECTOR, "input[type='image']")
                            else None,
                        }
                        adjuntos.append(adjunto)

            except Exception as exc:
                print(f"Error parseando tabla de adjuntos: {exc}")
                return []

            if adjuntos:
                print(f"\n{'=' * 50}")
                print(
                    f"Se encontraron {len(adjuntos)} adjuntos de tipo '{anexo_type}' para RUT {rut}"
                )
                print("Por favor, resuelva el CAPTCHA en el navegador y presione Enter...")
                print(f"{'=' * 50}\n")

                input("Presione Enter despues de resolver el CAPTCHA...")

                for adjunto in adjuntos:
                    if adjunto["checkbox"]:
                        try:
                            if not adjunto["checkbox"].is_selected():
                                adjunto["checkbox"].click()
                        except Exception:
                            pass

                try:
                    download_btn = self.driver.find_element(
                        By.XPATH,
                        "//input[@value='Descargar seleccionados'] | //button[contains(text(),'Descargar')]",
                    )
                    download_btn.click()

                    time.sleep(5)
                    print(f"Descarga iniciada para {anexo_type}")

                except Exception as exc:
                    print(f"Error al hacer clic en descargar: {exc}")

            return adjuntos

        except Exception as exc:
            print(f"Error descargando anexos {anexo_type} para {rut}: {exc}")
            return []

    def click_anexo_icon(self, oferta, anexo_type):
        """Hace clic en un icono de anexo y obtiene la URL resultante."""
        try:
            anexo_data = oferta["anexos"].get(anexo_type)
            if not anexo_data:
                return None

            element = anexo_data.get("element")
            if element:
                original_window = self.driver.current_window_handle

                element.click()
                time.sleep(2)

                if len(self.driver.window_handles) > 1:
                    for handle in self.driver.window_handles:
                        if handle != original_window:
                            self.driver.switch_to.window(handle)
                            new_url = self.driver.current_url
                            self.driver.close()
                            self.driver.switch_to.window(original_window)
                            return new_url

                return self.driver.current_url

        except Exception as exc:
            print(f"Error haciendo clic en {anexo_type}: {exc}")

        return None

    def download_licitacion(self, url):
        """Descarga todos los adjuntos de una licitacion."""
        print(f"Iniciando descarga de licitacion: {url}")

        self.setup_selenium(headless=False)

        try:
            self.driver.get(url)
            time.sleep(3)

            licitacion_id = self.extract_licitacion_id(url)
            if not licitacion_id:
                try:
                    title_element = self.driver.find_element(
                        By.XPATH, "//*[contains(text(), '-LE') or contains(text(), '-LP')]"
                    )
                    match = re.search(r"\d{3,4}-\d{1,2}-[A-Z]{2}\d{2}", title_element.text)
                    if match:
                        licitacion_id = match.group()
                except Exception:
                    pass

            if not licitacion_id:
                print("No se pudo extraer el ID de la licitacion")
                licitacion_id = "licitacion_desconocida"

            print(f"ID de licitacion: {licitacion_id}")

            base_path = self.create_folder_structure(licitacion_id)
            print(f"Carpeta de descargas: {base_path}")

            opening_url = self.get_opening_frame_url(url)

            if not opening_url:
                try:
                    cuadro_btn = self.driver.find_element(
                        By.XPATH,
                        "//input[contains(@href, 'OpeningFrame')] | //*[contains(text(), 'Cuadro Comparativo')]",
                    )
                    cuadro_btn.click()
                    time.sleep(2)
                    opening_url = self.driver.current_url
                except Exception:
                    print("No se encontro el cuadro de ofertas")
                    return

            print(f"URL del Cuadro de Ofertas: {opening_url}")

            ofertas = self.get_ofertas_data(opening_url)
            print(f"Se encontraron {len(ofertas)} ofertas")

            for i, oferta in enumerate(ofertas, 1):
                print(f"\n{'=' * 50}")
                print(
                    f"Procesando oferta {i}/{len(ofertas)}: {oferta['proveedor']} "
                    f"(RUT: {oferta['rut']})"
                )
                print(f"{'=' * 50}")

                rut = oferta["rut"]

                print("\n1. Descargando Declaracion Jurada...")
                dj_folder = os.path.join(base_path, self.ANEXO_TYPES["declaracion_jurada"])
                self.download_declaracion_jurada(licitacion_id, rut, dj_folder)

                print("\n2. Descargando Anexos Administrativos...")
                admin_folder = self.create_proveedor_subfolder(
                    base_path, self.ANEXO_TYPES["anexos_administrativos"], rut
                )
                admin_url = self.click_anexo_icon(oferta, "anexos_administrativos")
                if admin_url:
                    self.download_anexos(admin_url, "anexos_administrativos", rut, admin_folder)

                self.driver.get(opening_url)
                time.sleep(2)

                print("\n3. Descargando Anexos Tecnicos...")
                tech_folder = self.create_proveedor_subfolder(
                    base_path, self.ANEXO_TYPES["anexos_tecnicos"], rut
                )
                tech_url = self.click_anexo_icon(oferta, "anexos_tecnicos")
                if tech_url:
                    self.download_anexos(tech_url, "anexos_tecnicos", rut, tech_folder)

                self.driver.get(opening_url)
                time.sleep(2)

                print("\n4. Descargando Anexos Economicos...")
                econ_folder = self.create_proveedor_subfolder(
                    base_path, self.ANEXO_TYPES["anexos_economicos"], rut
                )
                econ_url = self.click_anexo_icon(oferta, "anexos_economicos")
                if econ_url:
                    self.download_anexos(econ_url, "anexos_economicos", rut, econ_folder)

                self.driver.get(opening_url)
                time.sleep(2)

                print("\n5. Descargando Garantias...")
                garant_folder = os.path.join(base_path, self.ANEXO_TYPES["garantias"])
                garant_url = self.click_anexo_icon(oferta, "garantias")
                if garant_url:
                    self.download_anexos(garant_url, "garantias", rut, garant_folder)

                self.driver.get(opening_url)
                time.sleep(2)

            print(f"\n{'=' * 50}")
            print("DESCARGA COMPLETADA")
            print(f"Archivos guardados en: {base_path}")
            print(f"{'=' * 50}\n")

        finally:
            self.close()


def main():
    parser = argparse.ArgumentParser(
        description="Descarga adjuntos de licitaciones de Mercado Publico"
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_LICITACION_URL,
        help=(
            "URL de la ficha de licitacion. "
            "Si se omite, se usara la licitacion 728-1-LE26."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default="descargas",
        help="Carpeta de salida (default: descargas)",
    )

    args = parser.parse_args()

    downloader = MercadoPublicoDownloader(download_folder=args.output)
    downloader.download_licitacion(args.url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
