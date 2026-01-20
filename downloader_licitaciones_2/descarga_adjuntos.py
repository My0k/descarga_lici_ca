import os
import time

from selenium import webdriver
from selenium.common.exceptions import WebDriverException


URL = (
    "https://www.mercadopublico.cl/Procurement/Modules/RFB/"
    "DetailsAcquisition.aspx?idlicitacion=728-1-LE26"
)
DOWNLOAD_DIR = os.path.join(os.getcwd(), "descargas")


def setup_driver(download_dir):
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-popup-blocking")
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=options)


def wait_for_new_window(driver, baseline_handles, timeout_s=20):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        handles = set(driver.window_handles)
        new_handles = handles - baseline_handles
        if new_handles:
            return new_handles.pop()
        time.sleep(0.5)
    return None


def wait_for_download(download_dir, before_files, timeout_s=120):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        current_files = set(os.listdir(download_dir))
        new_files = current_files - before_files
        if new_files:
            if any(name.endswith(".crdownload") for name in current_files):
                time.sleep(0.5)
                continue
            return new_files
        time.sleep(0.5)
    return set()


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    try:
        driver = setup_driver(DOWNLOAD_DIR)
    except WebDriverException as exc:
        raise SystemExit(f"No se pudo iniciar ChromeDriver: {exc}") from exc

    try:
        driver.get(URL)

        print("presiona cuadro ofertas")
        input()

        baseline_handles = set(driver.window_handles)
        print("ahora presiona anexos administrativos")
        input()
        new_handle = wait_for_new_window(driver, baseline_handles)
        if new_handle:
            driver.switch_to.window(new_handle)

        before_files = set(os.listdir(DOWNLOAD_DIR))
        print("presiona Ver para descargar un adjunto")
        input()

        new_files = wait_for_download(DOWNLOAD_DIR, before_files)
        if new_files:
            print(f"Descarga completada: {', '.join(sorted(new_files))}")
        else:
            print("No se detecto descarga dentro del tiempo de espera.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
