import json
import time
from datetime import datetime, timezone

from selenium import webdriver
from selenium.common.exceptions import WebDriverException


URL = (
    "https://www.mercadopublico.cl/Procurement/Modules/RFB/"
    "DetailsAcquisition.aspx?idlicitacion=728-1-LE26"
)
OUT_FILE = "endpoints_log.json"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-popup-blocking")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=options)


def drain_network_logs(driver, window_handle):
    entries = driver.get_log("performance")
    endpoints = []
    for entry in entries:
        try:
            message = json.loads(entry["message"])
        except (KeyError, json.JSONDecodeError):
            continue
        params = message.get("message", {})
        method = params.get("method", "")
        payload = params.get("params", {})
        if method == "Network.requestWillBeSent":
            request = payload.get("request", {})
            url = request.get("url")
            http_method = request.get("method")
            if url:
                endpoints.append(
                    {
                        "event": method,
                        "url": url,
                        "http_method": http_method,
                        "type": payload.get("type"),
                        "timestamp": entry.get("timestamp"),
                        "window_handle": window_handle,
                    }
                )
        elif method == "Network.responseReceived":
            response = payload.get("response", {})
            url = response.get("url")
            if url:
                endpoints.append(
                    {
                        "event": method,
                        "url": url,
                        "status": response.get("status"),
                        "mime_type": response.get("mimeType"),
                        "type": payload.get("type"),
                        "timestamp": entry.get("timestamp"),
                        "window_handle": window_handle,
                    }
                )
    return endpoints


def wait_for_new_window(driver, baseline_handles, timeout_s=20):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        handles = set(driver.window_handles)
        new_handles = handles - baseline_handles
        if new_handles:
            return new_handles.pop()
        time.sleep(0.5)
    return None


def record_step(driver, step_name, window_handle, data, sleep_s=2):
    time.sleep(sleep_s)
    endpoints = drain_network_logs(driver, window_handle)
    data["steps"].append(
        {
            "name": step_name,
            "timestamp": utc_now_iso(),
            "window_handle": window_handle,
            "endpoints": endpoints,
        }
    )


def main():
    data = {"start_url": URL, "started_at": utc_now_iso(), "steps": []}
    try:
        driver = setup_driver()
    except WebDriverException as exc:
        raise SystemExit(f"No se pudo iniciar ChromeDriver: {exc}") from exc

    try:
        driver.get(URL)
        record_step(driver, "page_load", driver.current_window_handle, data)

        print("presiona cuadro ofertas")
        input()
        record_step(driver, "click_cuadro_ofertas", driver.current_window_handle, data)

        baseline_handles = set(driver.window_handles)
        print("ahora presiona anexos administrativos")
        input()
        new_handle = wait_for_new_window(driver, baseline_handles)
        if new_handle:
            driver.switch_to.window(new_handle)
        record_step(
            driver,
            "click_anexos_administrativos",
            driver.current_window_handle,
            data,
        )

        print("presiona Ver para descargar un adjunto")
        input()
        record_step(driver, "click_ver_descargar_adjunto", driver.current_window_handle, data)

    finally:
        data["finished_at"] = utc_now_iso()
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            driver.quit()
        except Exception:
            pass

    print(f"Endpoints guardados en {OUT_FILE}")


if __name__ == "__main__":
    main()
