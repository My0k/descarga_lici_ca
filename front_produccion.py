import json
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

import descarga_ca
import flujo_licitacion
import genera_xls_ca
import genera_xls_lici


class DescargadorProduccionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Descargador MercadoPublico - Produccion")
        self.root.geometry("620x520")
        self.root.minsize(600, 480)

        self.tipo_proceso = tk.StringVar(value="compra_agil")
        self.codigo = tk.StringVar()

        self.driver = None
        self.navegador_iniciado = False
        self.token_guardado = False
        self._token_poll_after_id = None
        self._compra_agil_clicked = False

        self.status_var = tk.StringVar(value="Listo para iniciar navegador")
        self.token_estado = tk.StringVar(value="Token no detectado")

        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Custom.TButton", font=("Segoe UI", 10))

        container = tk.Frame(self.root, bg="#f7f7f7", padx=24, pady=20)
        container.pack(fill="both", expand=True)

        title = ttk.Label(container, text="Descargador MercadoPublico", style="Title.TLabel", background="#f7f7f7")
        title.pack(anchor="w", pady=(0, 4))
        subtitle = ttk.Label(
            container,
            text="Flujo simple para usuarios finales. Inicie el navegador, ingrese el codigo y procese.",
            background="#f7f7f7",
        )
        subtitle.pack(anchor="w", pady=(0, 16))

        # Bloque: navegador
        navegador_frame = tk.Frame(container, bg="#ffffff", padx=14, pady=14, bd=1, relief="solid")
        navegador_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(navegador_frame, text="1. Iniciar navegador", style="Section.TLabel", background="#ffffff").pack(
            anchor="w", pady=(0, 8)
        )
        ttk.Label(
            navegador_frame,
            text=(
                "Se abrira Chrome. Inicie sesion en MercadoPublico.cl. "
                "El sistema detecta el token automaticamente; no es necesario presionar Continuar."
            ),
            background="#ffffff",
            wraplength=540,
        ).pack(anchor="w", pady=(0, 10))

        btns_nav = tk.Frame(navegador_frame, bg="#ffffff")
        btns_nav.pack(anchor="w", pady=(0, 6))
        self.btn_iniciar_nav = ttk.Button(
            btns_nav, text="Iniciar navegador", command=self.iniciar_navegador, style="Custom.TButton"
        )
        self.btn_iniciar_nav.pack(side="left")

        self.btn_listo = ttk.Button(
            btns_nav,
            text="Ya inicie sesion",
            command=self.continuar_si_listo,
            state="disabled",
            style="Custom.TButton",
        )
        self.btn_listo.pack(side="left", padx=(8, 0))

        self.btn_cerrar_nav = ttk.Button(
            btns_nav,
            text="Cerrar navegador",
            command=self.cerrar_navegador,
            state="disabled",
            style="Custom.TButton",
        )
        self.btn_cerrar_nav.pack(side="left", padx=(8, 0))

        self.lbl_token = ttk.Label(navegador_frame, textvariable=self.token_estado, background="#ffffff")
        self.lbl_token.pack(anchor="w", pady=(6, 0))

        # Bloque: codigo
        codigo_frame = tk.Frame(container, bg="#ffffff", padx=14, pady=14, bd=1, relief="solid")
        codigo_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(codigo_frame, text="2. Seleccione tipo e ingrese codigo", style="Section.TLabel", background="#ffffff").pack(
            anchor="w", pady=(0, 8)
        )

        radios = tk.Frame(codigo_frame, bg="#ffffff")
        radios.pack(anchor="w", pady=(0, 10))
        ttk.Radiobutton(radios, text="Compra agil", variable=self.tipo_proceso, value="compra_agil").pack(
            side="left", padx=(0, 14)
        )
        ttk.Radiobutton(radios, text="Licitacion", variable=self.tipo_proceso, value="licitacion").pack(side="left")

        ttk.Label(codigo_frame, text="Codigo:", background="#ffffff").pack(anchor="w")
        self.entry_codigo = ttk.Entry(codigo_frame, textvariable=self.codigo, width=35, font=("Segoe UI", 11))
        self.entry_codigo.pack(anchor="w", pady=(4, 0))

        # Bloque: accion
        accion_frame = tk.Frame(container, bg="#ffffff", padx=14, pady=14, bd=1, relief="solid")
        accion_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(accion_frame, text="3. Procesar", style="Section.TLabel", background="#ffffff").pack(
            anchor="w", pady=(0, 8)
        )
        ttk.Label(
            accion_frame,
            text="Descargara adjuntos y generara un Excel automaticamente para el codigo ingresado.",
            background="#ffffff",
            wraplength=540,
        ).pack(anchor="w", pady=(0, 8))

        self.btn_procesar = ttk.Button(
            accion_frame, text="Procesar codigo", command=self.procesar_codigo, state="disabled", style="Custom.TButton"
        )
        self.btn_procesar.pack(anchor="w", pady=(4, 0))

        # Estado
        status_frame = tk.Frame(container, bg="#f7f7f7")
        status_frame.pack(fill="x", pady=(4, 0))
        ttk.Label(status_frame, textvariable=self.status_var, background="#f7f7f7").pack(anchor="w")

    # ---------------- Navegador ----------------
    def iniciar_navegador(self):
        if self.driver:
            return
        try:
            self.status_var.set("Iniciando navegador...")
            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")
            profile_dir = os.path.join(self._ruta_sesion_dir(), "chrome_profile")
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
            chrome_options.add_argument(f"--user-data-dir={profile_dir}")
            chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.get("https://mercadopublico.cl/Home")
            self._restaurar_sesion_cookies()

            self.navegador_iniciado = True
            self.btn_iniciar_nav.configure(state="disabled")
            self.btn_listo.configure(state="normal")
            self.btn_cerrar_nav.configure(state="normal")
            self.status_var.set("Navegador abierto. Inicie sesion y espere la deteccion de token.")
            self._compra_agil_clicked = False
            self.token_guardado = False
            self.token_estado.set("Token no detectado (intentando automaticamente)")
            self._iniciar_monitoreo_token_automatico()
            messagebox.showinfo(
                "Navegador iniciado",
                "Chrome se abrio. Inicie sesion en MercadoPublico.cl.\n"
                "El sistema detecta el token automaticamente y habilita el boton de procesar.",
            )
        except Exception as exc:
            self.status_var.set("Error al iniciar navegador")
            messagebox.showerror("Error", f"No se pudo iniciar el navegador:\n{exc}")

    def cerrar_navegador(self):
        if self._token_poll_after_id:
            try:
                self.root.after_cancel(self._token_poll_after_id)
            except Exception:
                pass
            self._token_poll_after_id = None

        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

        self.navegador_iniciado = False
        self.token_guardado = False
        self._compra_agil_clicked = False
        self.token_estado.set("Token no detectado")
        self.status_var.set("Listo para iniciar navegador")
        self.btn_iniciar_nav.configure(state="normal")
        self.btn_listo.configure(state="disabled")
        self.btn_cerrar_nav.configure(state="disabled")
        self.btn_procesar.configure(state="disabled")

    def continuar_si_listo(self):
        if not self.navegador_iniciado:
            messagebox.showwarning("Navegador requerido", "Inicie el navegador antes de continuar.")
            return

        token_ok = self.capturar_y_guardar_token_desde_selenium()
        if token_ok:
            self.token_estado.set("Token detectado y guardado.")
            self.token_guardado = True
        else:
            self.token_estado.set("No se detecto token. Puede seguir para licitacion; compra agil requiere token.")
        self._habilitar_acciones()
        self._guardar_sesion_cookies()

    # ---------------- Procesamiento ----------------
    def procesar_codigo(self):
        if not self.navegador_iniciado or not self.driver:
            messagebox.showwarning("Navegador requerido", "Inicie el navegador antes de procesar.")
            return

        codigo = self.codigo.get().strip()
        if not codigo:
            messagebox.showwarning("Codigo requerido", "Ingrese el codigo de la compra agil o licitacion.")
            return

        self.btn_procesar.configure(state="disabled")
        self.btn_listo.configure(state="disabled")
        self.status_var.set(f"Procesando {codigo}...")

        thread = threading.Thread(target=self._proceso_thread, args=(codigo, self.tipo_proceso.get()), daemon=True)
        thread.start()

    def _proceso_thread(self, codigo, tipo):
        try:
            if tipo == "compra_agil":
                self._proceso_compra_agil(codigo)
            else:
                self._proceso_licitacion(codigo)
        except Exception as exc:
            messagebox.showerror("Error", f"Error inesperado al procesar:\n{exc}")
            self.status_var.set("Error general")
        finally:
            self.btn_procesar.configure(state="normal")
            if self.navegador_iniciado:
                self.btn_listo.configure(state="normal")

    def _proceso_compra_agil(self, codigo):
        if not self.token_guardado:
            self.token_estado.set("Buscando token antes de procesar compra agil...")
            token_ok = self.capturar_y_guardar_token_desde_selenium()
            self.token_guardado = token_ok
        if not self.token_guardado:
            messagebox.showwarning(
                "Token requerido",
                "No se detecto token de sesion. Para compra agil es necesario iniciar sesion y esperar la deteccion.",
            )
            self.status_var.set("Token no disponible para compra agil")
            return

        self.status_var.set(f"Descargando adjuntos de compra agil {codigo}...")
        ok = descarga_ca.descargar_compra_agil_api(codigo, driver=self.driver)
        if not ok:
            messagebox.showerror("Descarga", "No se pudieron descargar los adjuntos de la compra agil.")
            self.status_var.set("Fallo descarga compra agil")
            return

        try:
            descarga_ca.crear_zips_proveedores(codigo)
        except Exception:
            pass

        self.status_var.set("Generando Excel de compra agil...")
        ruta_excel = genera_xls_ca.generar_excel_compra_agil(codigo, self.driver)
        if ruta_excel:
            self.status_var.set(f"Flujo completado: {codigo}")
            messagebox.showinfo(
                "Proceso completado",
                f"Compra agil {codigo} procesada.\n\nExcel generado en:\n{ruta_excel}",
            )
        else:
            self.status_var.set("Excel no generado")
            messagebox.showwarning(
                "Excel",
                "La descarga termino pero el Excel no se genero correctamente.",
            )

    def _proceso_licitacion(self, codigo):
        self.status_var.set(f"Descargando adjuntos de licitacion {codigo}...")
        resumen = flujo_licitacion.test_flujo_licitacion(codigo, self.driver, carpeta_base="Descargas/Licitaciones")
        manifest_path = self._guardar_manifest_licitacion(codigo, resumen)

        if not resumen.get("ok"):
            errores = "\n".join(resumen.get("errores") or [])
            messagebox.showwarning(
                "Licitacion",
                f"No se pudieron descargar adjuntos de la licitacion.\n{errores}",
            )
            self.status_var.set("Fallo descarga licitacion")
            return

        try:
            self._zip_proveedores(resumen, codigo)
        except Exception:
            pass

        self.status_var.set("Generando Excel de licitacion...")
        ruta_excel = genera_xls_lici.generar_excel_licitacion(codigo, resumen=resumen, manifest_path=manifest_path)
        if ruta_excel:
            self.status_var.set(f"Flujo completado: {codigo}")
            messagebox.showinfo(
                "Proceso completado",
                f"Licitacion {codigo} procesada.\n\nExcel generado en:\n{ruta_excel}",
            )
        else:
            self.status_var.set("Excel no generado")
            messagebox.showwarning(
                "Excel",
                "La descarga termino pero el Excel no se genero correctamente.",
            )

    # ---------------- Token helpers ----------------
    def capturar_y_guardar_token_desde_selenium(self):
        if not self.driver:
            return False

        token_crudo = self._obtener_token_desde_logs_performance()
        if not token_crudo:
            token_crudo = self._obtener_token_desde_navegador()

        if not token_crudo:
            return False

        token_formateado = token_crudo.strip()
        if not token_formateado.lower().startswith("bearer "):
            token_formateado = f"Bearer {token_formateado}"

        try:
            with open("token", "w", encoding="utf-8") as f:
                f.write(token_formateado)
            self.token_guardado = True
            self.token_estado.set("Token detectado y guardado.")
            return True
        except Exception:
            return False

    def _obtener_token_desde_logs_performance(self):
        if not self.driver:
            return None
        try:
            logs = self.driver.get_log("performance")
        except Exception:
            return None

        for entry in reversed(logs or []):
            try:
                mensaje_raw = entry.get("message")
                if not mensaje_raw:
                    continue
                envoltura = json.loads(mensaje_raw)
                mensaje = envoltura.get("message", {})
                if mensaje.get("method") != "Network.requestWillBeSent":
                    continue
                request = mensaje.get("params", {}).get("request", {})
                url = request.get("url", "")
                if "servicios-compra-agil.mercadopublico.cl" not in url:
                    continue
                headers = request.get("headers", {})
                auth = headers.get("Authorization") or headers.get("authorization")
                if auth:
                    return auth
            except Exception:
                continue
        return None

    def _obtener_token_desde_navegador(self):
        if not self.driver:
            return None

        script = """
            (function() {
                function storeAuth(value) {
                    if (!value || typeof value !== 'string') return;
                    var v = value.trim();
                    if (!v) return;
                    if (v.toLowerCase().indexOf('bearer ') !== 0 && v.indexOf('.') === -1) return;
                    window.__MP_CA_AUTH_TOKEN__ = v;
                }
                function shouldInspect(input) {
                    try {
                        var url = null;
                        if (typeof input === 'string') url = input;
                        else if (input && typeof input.url === 'string') url = input.url;
                        if (!url) return false;
                        return url.indexOf('servicios-compra-agil.mercadopublico.cl') !== -1;
                    } catch (e) { return false; }
                }
                function extract(headers) {
                    if (!headers) return;
                    try {
                        if (typeof headers.get === 'function') {
                            var h = headers.get('Authorization') || headers.get('authorization');
                            if (h) storeAuth(h);
                            if (window.__MP_CA_AUTH_TOKEN__ && headers.forEach) {
                                headers.forEach(function(v, k) {
                                    if (k && typeof k === 'string' && k.toLowerCase() === 'authorization') {
                                        storeAuth(v);
                                    }
                                });
                            }
                        } else if (Array.isArray(headers)) {
                            for (var i = 0; i < headers.length; i++) {
                                var entry = headers[i] || [];
                                if (entry[0] && entry[0].toLowerCase() === 'authorization') storeAuth(entry[1]);
                            }
                        } else if (typeof headers === 'object') {
                            var cand = headers['Authorization'] || headers['authorization'];
                            if (cand) storeAuth(cand);
                            for (var key in headers) {
                                if (!Object.prototype.hasOwnProperty.call(headers, key)) continue;
                                if (key && key.toLowerCase() === 'authorization') storeAuth(headers[key]);
                            }
                        }
                    } catch (e) {}
                }
                if (!window.__MP_CA_TOKEN_HOOK_INSTALLED__) {
                    window.__MP_CA_TOKEN_HOOK_INSTALLED__ = true;
                    window.__MP_CA_AUTH_TOKEN__ = window.__MP_CA_AUTH_TOKEN__ || null;
                    if (window.fetch) {
                        var originalFetch = window.fetch;
                        window.fetch = function(input, init) {
                            try {
                                if (shouldInspect(input)) {
                                    if (init && init.headers) extract(init.headers);
                                    if (!window.__MP_CA_AUTH_TOKEN__ && input && input.headers) extract(input.headers);
                                }
                            } catch (e) {}
                            return originalFetch.apply(this, arguments);
                        };
                    }
                    if (window.XMLHttpRequest && window.XMLHttpRequest.prototype) {
                        var originalOpen = window.XMLHttpRequest.prototype.open;
                        var originalSetHeader = window.XMLHttpRequest.prototype.setRequestHeader;
                        window.XMLHttpRequest.prototype.open = function(method, url) {
                            try {
                                this.__mp_ca_should_inspect__ = false;
                                if (typeof url === 'string' && url.indexOf('servicios-compra-agil.mercadopublico.cl') !== -1) {
                                    this.__mp_ca_should_inspect__ = true;
                                }
                            } catch (e) {}
                            return originalOpen.apply(this, arguments);
                        };
                        window.XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
                            try {
                                if (this.__mp_ca_should_inspect__ && name && name.toLowerCase() === 'authorization') {
                                    storeAuth(value);
                                }
                            } catch (e) {}
                            return originalSetHeader.apply(this, arguments);
                        };
                    }
                }
                return window.__MP_CA_AUTH_TOKEN__ || null;
            })();
        """

        token_encontrado = None
        try:
            handles = self.driver.window_handles
        except Exception:
            handles = []

        for handle in handles:
            try:
                self.driver.switch_to.window(handle)
                resultado = self.driver.execute_script(script)
                if isinstance(resultado, str) and resultado.strip():
                    token_encontrado = resultado.strip()
                    break
            except Exception:
                continue
        return token_encontrado

    def _iniciar_monitoreo_token_automatico(self):
        if not self.driver:
            return
        self._programar_poll_token(3000)

    def _programar_poll_token(self, delay_ms=4000):
        if not self.driver or self.token_guardado:
            return
        if self._token_poll_after_id:
            try:
                self.root.after_cancel(self._token_poll_after_id)
            except Exception:
                pass
        self._token_poll_after_id = self.root.after(delay_ms, self._poll_token_automatico)

    def _poll_token_automatico(self):
        if not self.driver or self.token_guardado:
            return
        self._intentar_click_compra_agil()
        if self.capturar_y_guardar_token_desde_selenium():
            self._habilitar_acciones()
            self.status_var.set("Token detectado automaticamente. Puede procesar codigos.")
            messagebox.showinfo("Token detectado", "El token se detecto automaticamente. Puede continuar.")
            return
        self._programar_poll_token(2000)

    def _intentar_click_compra_agil(self):
        if not self.driver or self._compra_agil_clicked:
            return False
        xpath_compra_agil = "/html/body/form/section[2]/div/div/div/div[1]/nav/div[1]/ul/li[6]/a"
        try:
            elementos = self.driver.find_elements("xpath", xpath_compra_agil)
            if not elementos:
                return False
            elemento = elementos[0]
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
            except Exception:
                pass
            try:
                elemento.click()
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", elemento)
                except Exception:
                    return False
            self._compra_agil_clicked = True
            return True
        except Exception:
            return False

    # ---------------- Sesion helpers ----------------
    def _ruta_sesion_dir(self):
        ruta = os.path.join(os.getcwd(), "sesion")
        os.makedirs(ruta, exist_ok=True)
        return ruta

    def _ruta_cookies(self):
        return os.path.join(self._ruta_sesion_dir(), "cookies.json")

    def _guardar_sesion_cookies(self):
        if not self.driver:
            return False
        try:
            cookies = self.driver.get_cookies()
            data = {"timestamp": time.time(), "cookies": cookies}
            with open(self._ruta_cookies(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _restaurar_sesion_cookies(self):
        ruta = self._ruta_cookies()
        if not os.path.exists(ruta):
            return False
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies") or []
        except Exception:
            return False

        if not cookies:
            return False

        dominios = sorted({c.get("domain") for c in cookies if c.get("domain")})
        for dom in dominios:
            if not dom:
                continue
            url = f"https://{dom.lstrip('.')}/"
            try:
                self.driver.get(url)
            except Exception:
                continue
            for c in cookies:
                if c.get("domain") != dom:
                    continue
                cookie = {
                    k: v
                    for k, v in c.items()
                    if k in {"name", "value", "domain", "path", "expiry", "secure", "httpOnly", "sameSite"}
                }
                cookie.setdefault("path", "/")
                if "expiry" in cookie:
                    try:
                        cookie["expiry"] = int(cookie["expiry"])
                    except Exception:
                        cookie.pop("expiry", None)
                try:
                    self.driver.add_cookie(cookie)
                except Exception:
                    continue
        try:
            self.driver.get("https://mercadopublico.cl/Home")
        except Exception:
            pass
        return True

    # ---------------- Utilidades licitacion ----------------
    def _guardar_manifest_licitacion(self, codigo, resumen):
        try:
            carpeta = os.path.join("Descargas", "Licitaciones", codigo)
            os.makedirs(carpeta, exist_ok=True)
            ruta = os.path.join(carpeta, "manifest_licitacion.json")
            data = resumen or {}
            data["codigo"] = codigo
            data["generado_en"] = time.time()
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return ruta
        except Exception:
            return None

    def _zip_proveedores(self, resumen, codigo):
        proveedores = resumen.get("proveedores") or []
        for prov in proveedores:
            carpeta = prov.get("carpeta")
            if not carpeta or not os.path.isdir(carpeta):
                continue
            nombre_base = os.path.basename(carpeta.rstrip(os.sep))
            try:
                descarga_ca.crear_zip_proveedor(carpeta, nombre_base)
            except Exception:
                continue

    # ---------------- Misc ----------------
    def _habilitar_acciones(self):
        self.btn_procesar.configure(state="normal")
        self.btn_listo.configure(state="normal")

    def on_closing(self):
        try:
            self.cerrar_navegador()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = DescargadorProduccionApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
