#!/usr/bin/env python3
import argparse
import base64
import io
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

try:
    from PIL import Image
except ImportError:  # pragma: no cover - runtime dependency
    Image = None


DETAIL_LINK_XPATH = "//a[normalize-space()='Ver detalle']"


def build_driver(headless: bool) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)


def wait_ready(driver: webdriver.Chrome, timeout: int = 20) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def safe_click(driver: webdriver.Chrome, element) -> None:
    try:
        element.click()
    except (ElementClickInterceptedException, StaleElementReferenceException):
        driver.execute_script("arguments[0].click();", element)


def capture_full_page_png(driver: webdriver.Chrome) -> bytes:
    try:
        result = driver.execute_cdp_cmd(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "fromSurface": True,
            },
        )
        return base64.b64decode(result["data"])
    except Exception:
        return driver.get_screenshot_as_png()


def screenshot_pdf(driver: webdriver.Chrome, output_path: Path) -> None:
    if Image is None:
        raise RuntimeError(
            "Pillow is not installed. Install it with: pip install pillow"
        )
    png_bytes = capture_full_page_png(driver)
    image = Image.open(io.BytesIO(png_bytes))
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    image.save(output_path, "PDF", resolution=100.0)


def print_to_pdf(driver: webdriver.Chrome, output_path: Path) -> None:
    result = driver.execute_cdp_cmd(
        "Page.printToPDF",
        {"printBackground": True, "preferCSSPageSize": True},
    )
    output_path.write_bytes(base64.b64decode(result["data"]))


def sanitize(text: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return "".join(ch if ch in allowed else "_" for ch in text)


def open_detail_by_index(
    driver: webdriver.Chrome, index: int, timeout: int = 6
) -> tuple[str, str]:
    elements = driver.find_elements(By.XPATH, DETAIL_LINK_XPATH)
    if index >= len(elements):
        return "missing", driver.current_url

    element = elements[index]
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.3)

    before_handles = set(driver.window_handles)
    prev_url = driver.current_url
    safe_click(driver, element)

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.window_handles) > len(before_handles)
        )
        new_handle = (set(driver.window_handles) - before_handles).pop()
        driver.switch_to.window(new_handle)
        wait_ready(driver)
        return "new_window", prev_url
    except TimeoutException:
        if driver.current_url != prev_url:
            wait_ready(driver)
            return "same_tab_nav", prev_url
        return "modal_or_same", prev_url


def close_detail_view(
    driver: webdriver.Chrome, mode: str, previous_url: str, origin_handle: str
) -> None:
    if mode == "new_window":
        driver.close()
        driver.switch_to.window(origin_handle)
        return
    if mode == "same_tab_nav":
        driver.get(previous_url)
        wait_ready(driver)
        return
    if mode == "modal_or_same":
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
        except Exception:
            pass
        time.sleep(0.4)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Descarga PDFs desde la vista de detalle de resumen cotizacion."
    )
    parser.add_argument("codigo", nargs="?", help="Codigo de cotizacion")
    parser.add_argument("--headless", action="store_true", help="Ejecuta sin UI")
    parser.add_argument(
        "--out", default="salidas", help="Directorio base para los PDFs"
    )
    args = parser.parse_args()

    codigo = (args.codigo or input("Ingrese codigo de cotizacion: ")).strip()
    if not codigo:
        print("Codigo vacio.")
        return 1

    out_dir = Path(args.out) / sanitize(codigo)
    out_dir.mkdir(parents=True, exist_ok=True)

    driver = build_driver(args.headless)
    try:
        base_url = "https://compra-agil.mercadopublico.cl"
        url = f"{base_url}/resumen-cotizacion/{codigo}"
        driver.get(base_url)
        wait_ready(driver)
        if not args.headless:
            input(
                "Navegador abierto. Inicie sesion y presione Enter para continuar..."
            )
        driver.get(url)
        wait_ready(driver)

        WebDriverWait(driver, 20).until(
            lambda d: len(d.find_elements(By.XPATH, DETAIL_LINK_XPATH)) > 0
        )
        total = len(driver.find_elements(By.XPATH, DETAIL_LINK_XPATH))
        print(f"Encontrados {total} botones 'Ver detalle'.")

        if total == 0:
            return 1

        origin_handle = driver.current_window_handle
        mode, prev_url = open_detail_by_index(driver, 0)
        if mode == "missing":
            return 1

        name = "detalle_01"
        print_path = out_dir / f"{name}_print.pdf"

        try:
            print_to_pdf(driver, print_path)
            print(f"Generado: {print_path}")
        finally:
            close_detail_view(driver, mode, prev_url, origin_handle)
            wait_ready(driver)
            time.sleep(0.5)

        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
