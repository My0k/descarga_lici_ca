import argparse
import configparser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import webbrowser
import json
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading
import descarga_ca
import genera_xls_ca
import descarga_lici
import genera_xls_lici
import genera_ficha_proveedor
import flujo_licitacion
import scrape_cuadro

class DescargadorLicitacionesApp:
    def __init__(self, root, modo="debug"):
        self.root = root
        self.modo = modo or "debug"
        self.modo_prod = self.modo == "prod"
        titulo = "Descargador de Licitaciones - MercadoPublico.cl"
        if self.modo == "test":
            titulo += " [TEST]"
        self.root.title(titulo)
        
        # Configurar ventana para que se vea completa
        if self.modo_prod:
            self.root.geometry("620x520")
            self.root.minsize(600, 480)
        else:
            self.root.geometry("700x650")
            self.root.minsize(650, 600)
        self.root.configure(bg='#f4f6f8')
        
        # Variables
        self.tipo_proceso = tk.StringVar(value="licitacion")
        self.codigo = tk.StringVar()
        self.navegador_iniciado = False
        self.driver = None
        self.token_guardado = False
        self._token_poll_after_id = None
        self._compra_agil_clicked = False
        self.continuar_sin_login = tk.BooleanVar(value=self.modo == "test")
        self.test_lici_url_directa = tk.BooleanVar(value=self.modo == "test")
        self.test_lici_desde_url = tk.BooleanVar(value=False)
        self.test_lici_url_valor = tk.StringVar(
            value="https://mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?qs=lMJBTBVx1W3Vzd7cnoBDUw=="
        )
        self.base_descargas_dir = tk.StringVar(
            value=self._cargar_base_descargas() or os.path.abspath("Descargas")
        )
        
        self.setup_ui()
        if self.modo_prod:
            self._ajustar_ventana_prod()
        else:
            self.centrar_ventana()
        if self.modo == "test":
            self.status_var.set("Modo test activo: continuar sin login esta habilitado por defecto.")
    
    def centrar_ventana(self):
        """Centra la ventana en la pantalla"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _ajustar_ventana_prod(self):
        """Ajusta el tamaño para que el contenido se vea completo en modo prod."""
        if not hasattr(self, "_scrollable_frame"):
            self.centrar_ventana()
            return
        self.root.update_idletasks()
        req_w = self._scrollable_frame.winfo_reqwidth()
        req_h = self._scrollable_frame.winfo_reqheight()
        width = req_w + 60
        height = req_h + 80
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        max_w = max(300, screen_w - 80)
        max_h = max(300, screen_h - 80)
        width = min(width, max_w)
        height = min(height, max_h)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(width, height)
        
    def setup_ui(self):
        mostrar_debug = not self.modo_prod
        # Estilo
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configurar colores del tema (sobrio + institucional INH)
        colors = {
            "bg": "#f4f6f8",
            "card": "#ffffff",
            "text": "#1f2a44",
            "muted": "#5f6c7b",
            "blue": "#003580",
            "red": "#DA291C",
            "teal": "#009DAE",
            "border": "#d7dde3",
            "status_bg": "#eef2f6",
        }
        self.colors = colors
        self.root.configure(bg=colors["bg"])

        style.configure(
            'Title.TLabel',
            font=('Segoe UI', 16, 'bold'),
            background=colors["card"],
            foreground=colors["blue"]
        )
        style.configure(
            'Subtitle.TLabel',
            font=('Segoe UI', 10),
            background=colors["bg"],
            foreground=colors["muted"]
        )
        style.configure(
            'Section.TLabel',
            font=('Segoe UI', 12, 'bold'),
            background=colors["bg"],
            foreground=colors["blue"]
        )
        style.configure('Custom.TButton', font=('Segoe UI', 10), padding=(12, 6))
        style.configure(
            'Custom.TRadiobutton',
            font=('Segoe UI', 10),
            background=colors["bg"],
            foreground=colors["text"]
        )
        style.configure(
            'Custom.TCheckbutton',
            font=('Segoe UI', 9),
            background=colors["bg"],
            foreground=colors["text"]
        )
        style.configure(
            'Status.TLabel',
            background=colors["status_bg"],
            foreground=colors["text"],
            font=('Segoe UI', 9)
        )
        
        # Frame principal con scrollbar
        canvas = tk.Canvas(self.root, bg=colors["bg"])
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=colors["bg"])
        self._canvas = canvas
        self._scrollable_frame = scrollable_frame
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Frame principal
        main_frame = tk.Frame(scrollable_frame, bg=colors["bg"], padx=40, pady=30)
        main_frame.pack(fill='both', expand=True)
        
        # Encabezado institucional
        header_frame = tk.Frame(
            main_frame,
            bg=colors["card"],
            highlightbackground=colors["border"],
            highlightthickness=1
        )
        header_frame.pack(fill='x', pady=(0, 20))

        header_band = tk.Frame(header_frame, bg=colors["blue"], height=8)
        header_band.pack(fill='x', side='top')
        header_accent = tk.Frame(header_band, bg=colors["red"], width=90)
        header_accent.pack(side='left', fill='y')

        header_content = tk.Frame(header_frame, bg=colors["card"], padx=18, pady=14)
        header_content.pack(fill='x')

        logo_path = Path(__file__).with_name("logo.png")
        self.logo_image = None
        if logo_path.exists():
            try:
                self.logo_image = tk.PhotoImage(file=str(logo_path))
                if self.logo_image.width() > 220:
                    factor = max(1, int(self.logo_image.width() / 220))
                    self.logo_image = self.logo_image.subsample(factor, factor)
            except tk.TclError:
                self.logo_image = None

        if self.logo_image:
            logo_label = tk.Label(header_content, image=self.logo_image, bg=colors["card"])
        else:
            logo_label = tk.Label(
                header_content,
                text="INH",
                bg=colors["card"],
                fg=colors["blue"],
                font=('Segoe UI', 18, 'bold')
            )
        logo_label.grid(row=0, column=0, rowspan=2, sticky='w', padx=(0, 14))

        title_label = ttk.Label(
            header_content,
            text="Descargador de Licitaciones",
            style='Title.TLabel'
        )
        title_label.grid(row=0, column=1, sticky='w')

        subtitle_label = tk.Label(
            header_content,
            text="Instituto Nacional de Hidráulica - MercadoPublico.cl",
            bg=colors["card"],
            fg=colors["teal"],
            font=('Segoe UI', 10, 'bold')
        )
        subtitle_label.grid(row=1, column=1, sticky='w', pady=(4, 0))

        # Separador
        separator1 = ttk.Separator(main_frame, orient='horizontal')
        separator1.pack(fill='x', pady=(0, 20))
        
        # Sección de navegador
        nav_frame = tk.Frame(main_frame, bg=colors["bg"])
        nav_frame.pack(fill='x', pady=(0, 25))
        
        nav_label = ttk.Label(nav_frame, text="1. Inicializar Navegador", style='Section.TLabel')
        nav_label.pack(anchor='w', pady=(0, 10))
        
        nav_desc = ttk.Label(
            nav_frame,
            text="Inicie el navegador, ingrese a su cuenta en MercadoPublico.cl y presione 'Continuar'",
            style='Subtitle.TLabel',
            wraplength=500
        )
        nav_desc.pack(anchor='w', pady=(0, 15))
        
        self.btn_navegador = ttk.Button(nav_frame, text="🌐 Iniciar Navegador", 
                                       command=self.iniciar_navegador, style='Custom.TButton')
        self.btn_navegador.pack(anchor='w')
        
        self.btn_continuar = ttk.Button(nav_frame, text="✓ Continuar", 
                                       command=self.continuar_proceso, 
                                       state='disabled', style='Custom.TButton')
        self.btn_continuar.pack(anchor='w', pady=(10, 0))

        self.btn_cerrar_navegador = ttk.Button(
            nav_frame,
            text="⏹ Cerrar navegador",
            command=self.cerrar_navegador,
            state='disabled',
            style='Custom.TButton',
        )
        self.btn_cerrar_navegador.pack(anchor='w', pady=(10, 0))

        if mostrar_debug:
            self.chk_sin_login = ttk.Checkbutton(
                nav_frame,
                text="Continuar sin login (solo pruebas, no captura token)",
                variable=self.continuar_sin_login,
                style='Custom.TCheckbutton'
            )
            self.chk_sin_login.pack(anchor='w', pady=(10, 0))
        
        # Separador
        separator2 = ttk.Separator(main_frame, orient='horizontal')
        separator2.pack(fill='x', pady=(25, 25))
        
        # Sección de selección de proceso
        proceso_frame = tk.Frame(main_frame, bg=colors["bg"])
        proceso_frame.pack(fill='x', pady=(0, 25))
        
        proceso_label = ttk.Label(
            proceso_frame,
            text="2. Seleccionar Tipo de Proceso",
            style='Section.TLabel'
        )
        proceso_label.pack(anchor='w', pady=(0, 15))
        
        # Radio buttons para tipo de proceso
        radio_frame = tk.Frame(proceso_frame, bg=colors["bg"])
        radio_frame.pack(anchor='w', pady=(0, 15))
        
        rb_licitacion = ttk.Radiobutton(radio_frame, text="📋 Licitación", 
                                       variable=self.tipo_proceso, value="licitacion",
                                       style='Custom.TRadiobutton')
        rb_licitacion.pack(side='left', padx=(0, 30))
        
        rb_compra_agil = ttk.Radiobutton(radio_frame, text="⚡ Compra Ágil", 
                                        variable=self.tipo_proceso, value="compra_agil",
                                        style='Custom.TRadiobutton')
        rb_compra_agil.pack(side='left')
        
        # Campo de código
        codigo_label = ttk.Label(
            proceso_frame,
            text="Código del Proceso:",
            font=('Segoe UI', 10, 'bold'),
            background=colors["bg"],
            foreground=colors["text"]
        )
        codigo_label.pack(anchor='w', pady=(0, 5))
        
        self.entry_codigo = ttk.Entry(proceso_frame, textvariable=self.codigo, 
                                     font=('Segoe UI', 11), width=30)
        self.entry_codigo.pack(anchor='w', pady=(0, 20))

        carpeta_label = ttk.Label(
            proceso_frame,
            text="Carpeta de descargas:",
            font=('Segoe UI', 10, 'bold'),
            background=colors["bg"],
            foreground=colors["text"]
        )
        carpeta_label.pack(anchor='w', pady=(0, 5))

        carpeta_row = tk.Frame(proceso_frame, bg=colors["bg"])
        carpeta_row.pack(anchor='w', pady=(0, 20), fill='x')
        self.entry_carpeta = ttk.Entry(
            carpeta_row,
            textvariable=self.base_descargas_dir,
            font=('Segoe UI', 10),
            width=40
        )
        self.entry_carpeta.pack(side='left', padx=(0, 8), fill='x', expand=True)
        self.btn_elegir_carpeta = ttk.Button(
            carpeta_row,
            text="📁",
            width=3,
            command=self.elegir_carpeta_descargas,
            style='Custom.TButton'
        )
        self.btn_elegir_carpeta.pack(side='left')
        self.btn_guardar_carpeta = ttk.Button(
            carpeta_row,
            text="Guardar",
            command=self.guardar_carpeta_descargas,
            style='Custom.TButton'
        )
        self.btn_guardar_carpeta.pack(side='left', padx=(8, 0))
        
        # Separador
        separator3 = ttk.Separator(main_frame, orient='horizontal')
        separator3.pack(fill='x', pady=(25, 25))
        
        # Botón de flujo completo
        flujo_frame = tk.Frame(main_frame, bg=colors["bg"])
        flujo_frame.pack(fill='x', pady=(0, 25))
        
        flujo_label = ttk.Label(
            flujo_frame,
            text="3. Ejecutar flujo completo",
            style='Section.TLabel'
        )
        flujo_label.pack(anchor='w', pady=(0, 10))
        
        flujo_desc = ttk.Label(
            flujo_frame,
            text=(
                "Ejecuta el flujo completo para la licitación o compra ágil seleccionada:\n"
                "1) Descarga de adjuntos de todos los proveedores\n"
                "2) Generación de fichas de proveedor\n"
                "3) Generación del Excel de resumen"
            ),
            style='Subtitle.TLabel',
            wraplength=500
        )
        flujo_desc.pack(anchor='w', pady=(0, 15))
        
        self.btn_flujo_completo = ttk.Button(
            flujo_frame,
            text="▶ Ejecutar flujo completo",
            command=self.ejecutar_flujo_completo,
            state='disabled',
            style='Custom.TButton'
        )
        self.btn_flujo_completo.pack(anchor='w')
        
        # Separador
        separator4 = ttk.Separator(main_frame, orient='horizontal')
        if mostrar_debug:
            separator4.pack(fill='x', pady=(25, 25))
        
        # Botones de acción individuales (debug)
        action_frame = tk.Frame(main_frame, bg=colors["bg"])
        if mostrar_debug:
            action_frame.pack(fill='x')
        
        action_label = ttk.Label(
            action_frame,
            text="4. Acciones individuales (debug)",
            style='Section.TLabel'
        )
        action_label.pack(anchor='w', pady=(0, 15))
        
        buttons_frame = tk.Frame(action_frame, bg=colors["bg"])
        buttons_frame.pack(anchor='w')
        
        self.btn_descargar = ttk.Button(buttons_frame, text="📥 Descargar Adjuntos", 
                                       command=self.descargar_adjuntos, 
                                       state='disabled', style='Custom.TButton')
        self.btn_descargar.pack(side='left', padx=(0, 15))
        
        self.btn_generar_excel = ttk.Button(buttons_frame, text="📊 Generar Excel", 
                                           command=self.generar_excel, 
                                           state='disabled', style='Custom.TButton')
        self.btn_generar_excel.pack(side='left', padx=(0, 15))
        
        self.btn_ficha_proveedor = ttk.Button(buttons_frame, text="📄 Ficha Proveedor", 
                                             command=self.generar_ficha_proveedor, 
                                             state='disabled', style='Custom.TButton')
        self.btn_ficha_proveedor.pack(side='left')

        self.btn_test_flujo_lici = ttk.Button(
            buttons_frame,
            text="🧪 Testear descarga adjuntos (licitación)",
            command=self.testear_flujo_licitacion,
            state='disabled',
            style='Custom.TButton'
        )
        self.btn_test_flujo_lici.pack(side='left', padx=(15, 0))

        self.chk_test_lici_directo = ttk.Checkbutton(
            buttons_frame,
            text="Usar enlace directo (evita login)",
            variable=self.test_lici_url_directa,
            style='Custom.TCheckbutton'
        )
        self.chk_test_lici_directo.pack(side='left', padx=(10, 0))

        self.chk_test_lici_desde_url = ttk.Checkbutton(
            buttons_frame,
            text="Testear licitación desde URL",
            variable=self.test_lici_desde_url,
            style='Custom.TCheckbutton'
        )
        self.chk_test_lici_desde_url.pack(side='left', padx=(10, 0))

        self.entry_test_lici_url = ttk.Entry(
            action_frame,
            textvariable=self.test_lici_url_valor,
            font=('Segoe UI', 9),
            width=65
        )
        self.entry_test_lici_url.pack(anchor='w', pady=(6, 0))
        
        # Status bar
        self.status_var = tk.StringVar(value="Listo - Inicie el navegador para comenzar")
        status_frame = tk.Frame(self.root, bg=colors["status_bg"], height=30)
        status_frame.pack(fill='x', side='bottom')
        status_frame.pack_propagate(False)
        
        status_label = ttk.Label(status_frame, textvariable=self.status_var, style='Status.TLabel')
        status_label.pack(pady=5)
        
    def iniciar_navegador(self):
        """Inicia el navegador web con Selenium"""
        try:
            print("[DEBUG] iniciar_navegador: iniciando Chrome...")
            self.status_var.set("Iniciando navegador...")
            
            # Configurar opciones de Chrome
            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")
            # Perfil persistente para reutilizar sesión (cookies/localStorage)
            profile_dir = os.path.join(self._ruta_sesion_dir(), "chrome_profile")
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
            chrome_options.add_argument(f"--user-data-dir={profile_dir}")
            # Activar logs de rendimiento para capturar headers de red (incluye Authorization)
            chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
            
            # Iniciar el navegador
            self.driver = webdriver.Chrome(options=chrome_options)
            print("[DEBUG] iniciar_navegador: driver creado")
            self.driver.get("https://mercadopublico.cl/Home")
            print("[DEBUG] iniciar_navegador: cargada https://mercadopublico.cl/Home")

            # Intentar restaurar cookies de sesión previa
            cookies_ok = self._restaurar_sesion_cookies()
            if cookies_ok:
                print("[DEBUG] iniciar_navegador: cookies restauradas, refrescando Home")
                try:
                    self.driver.get("https://mercadopublico.cl/Home")
                except Exception as e:
                    print(f"[DEBUG] iniciar_navegador: error refrescando tras restaurar cookies: {e}")
            
            self.navegador_iniciado = True
            self.token_guardado = False
            self._compra_agil_clicked = False
            print("[DEBUG] iniciar_navegador: navegador_iniciado=True, token_guardado=False")
            self.btn_navegador.configure(state='disabled')
            self.btn_continuar.configure(state='normal')
            self.btn_cerrar_navegador.configure(state='normal')
            
            self.status_var.set("Navegador iniciado - Ingrese a su cuenta y presione 'Continuar'")

            # Si el usuario marcó continuar sin login, habilitar acciones de inmediato
            if self.continuar_sin_login.get():
                print("[DEBUG] iniciar_navegador: modo sin login activo, habilitando acciones sin token")
                self._detener_poll_token()
                self._habilitar_acciones_sin_login()
            
            # Iniciar monitoreo automático del token de Compra Ágil
            print("[DEBUG] iniciar_navegador: iniciando monitoreo automático de token")
            self._iniciar_monitoreo_token_automatico()
            
            messagebox.showinfo("Navegador Iniciado", 
                               "Navegador iniciado correctamente.\n\n"
                               "Por favor:\n"
                               "1. Ingrese a su cuenta en MercadoPublico.cl\n"
                               "2. Una vez logueado, presione el botón 'Continuar'")
            
        except Exception as e:
            print(f"[DEBUG] iniciar_navegador: error al iniciar navegador: {e}")
            messagebox.showerror("Error", f"Error al iniciar el navegador:\n{str(e)}")
            self.status_var.set("Error al iniciar navegador")

    def cerrar_navegador(self):
        """Cierra el navegador Selenium y deja el programa listo para iniciar nuevamente."""
        if self._token_poll_after_id is not None:
            try:
                self.root.after_cancel(self._token_poll_after_id)
            except Exception:
                pass
            self._token_poll_after_id = None

        if self.driver:
            # Intentar persistir cookies de la sesión antes de cerrar el navegador
            try:
                self._guardar_sesion_cookies()
            except Exception as e:
                print(f"[DEBUG] cerrar_navegador: error guardando cookies antes de cerrar: {e}")
            try:
                self.driver.quit()
            except Exception:
                pass

        self.driver = None
        self.navegador_iniciado = False
        self.token_guardado = False
        self._compra_agil_clicked = False

        self.btn_navegador.configure(state='normal')
        self.btn_continuar.configure(state='disabled')
        self.btn_cerrar_navegador.configure(state='disabled')
        self._set_estado_botones_accion('disabled')
        self.status_var.set("Listo - Inicie el navegador para comenzar")
    
    def continuar_proceso(self):
        """Continúa con el proceso después del login y guarda el token de API"""
        if not self.navegador_iniciado:
            print("[DEBUG] continuar_proceso: navegador no iniciado")
            messagebox.showwarning("Advertencia", "Debe iniciar el navegador primero")
            return

        if self.continuar_sin_login.get():
            # Modo rápido: no esperamos token ni login
            print("[DEBUG] continuar_proceso: modo 'continuar sin login' activado, se omite captura de token")
            self._detener_poll_token()
            self._habilitar_acciones_sin_login()
            return
        
        # Intentar una captura final del token si aún no se ha guardado
        if self.token_guardado:
            print("[DEBUG] continuar_proceso: token ya guardado anteriormente")
            self.status_var.set(
                "Token de sesión ya capturado y guardado en 'token' para uso de las APIs"
            )
        else:
            print("[DEBUG] continuar_proceso: intentando captura final de token...")
            token_guardado = self.capturar_y_guardar_token_desde_selenium()
            if token_guardado:
                print("[DEBUG] continuar_proceso: token capturado correctamente en captura final")
                self.status_var.set(
                    "Token de sesión capturado y guardado en 'token' para uso de las APIs"
                )
                self._guardar_sesion_cookies()
            else:
                print("[DEBUG] continuar_proceso: no se pudo capturar token en captura final")
                # No bloquea el flujo si no se encuentra el token, pero se informa al usuario
                self.status_var.set(
                    "No se pudo detectar automáticamente el token. "
                    "El flujo continuará, pero las APIs que dependen del token pueden fallar."
                )
                messagebox.showwarning(
                    "Token no detectado",
                    "No se pudo obtener automáticamente el token de autenticación desde el navegador.\n\n"
                    "Asegúrese de haber iniciado sesión en MercadoPublico y haber abierto al menos una vista "
                    "de Compra Ágil / Licitación antes de presionar 'Continuar'.\n\n"
                    "Si utiliza APIs que leen el archivo 'token', verifique o actualice manualmente su contenido.",
                )
            
        # Habilitar los botones de acción
        self.btn_flujo_completo.configure(state='normal')
        self.btn_descargar.configure(state='normal')
        self.btn_generar_excel.configure(state='normal')
        self.btn_ficha_proveedor.configure(state='normal')
        self.btn_test_flujo_lici.configure(state='normal' if self.tipo_proceso.get() == "licitacion" else 'disabled')
        
        if self.modo_prod:
            self.status_var.set(
                "Listo para procesar - Ingrese el código y ejecute el flujo completo"
            )
            messagebox.showinfo(
                "Listo",
                "Sistema listo para procesar.\n\n"
                "Ahora puede:\n"
                "• Seleccionar el tipo de proceso\n"
                "• Ingresar el código\n"
                "• Ejecutar el flujo completo"
            )
        else:
            self.status_var.set(
                "Listo para procesar - Ingrese el código y ejecute el flujo completo o las acciones individuales"
            )
            messagebox.showinfo(
                "Listo",
                "Sistema listo para procesar.\n\n"
                "Ahora puede:\n"
                "• Seleccionar el tipo de proceso\n"
                "• Ingresar el código\n"
                "• Ejecutar el flujo completo (recomendado)\n"
                "• O usar las acciones individuales para debug"
            )

    def capturar_y_guardar_token_desde_selenium(self):
        """
        Intenta extraer el token JWT desde el contexto del navegador interceptando las llamadas a la API
        de Compra Ágil (Authorization header) y lo guarda en el archivo 'token' con el prefijo 'Bearer '
        para ser usado por las APIs.
        """
        if not self.driver:
            print("[DEBUG] capturar_y_guardar_token_desde_selenium: no hay driver")
            return False

        # 1) Intentar primero desde los logs de rendimiento (Network.requestWillBeSent)
        print("[DEBUG] capturar_y_guardar_token_desde_selenium: intentando obtener token desde logs de performance")
        token_crudo = self._obtener_token_desde_logs_performance()
        print(f"[DEBUG] capturar_y_guardar_token_desde_selenium: token_crudo_desde_logs={repr(token_crudo)[:120]}")

        # 2) Si no se encontró en logs, intentar vía hook JS en fetch/XMLHttpRequest
        if not token_crudo:
            print("[DEBUG] capturar_y_guardar_token_desde_selenium: intentando obtener token desde _obtener_token_desde_navegador()")
            token_crudo = self._obtener_token_desde_navegador()
            print(f"[DEBUG] capturar_y_guardar_token_desde_selenium: token_crudo_desde_js={repr(token_crudo)[:120]}")

        if not token_crudo:
            print("[DEBUG] capturar_y_guardar_token_desde_selenium: no se encontró token por ningún método")
            return False

        token_formateado = token_crudo.strip()
        if not token_formateado.lower().startswith("bearer "):
            token_formateado = f"Bearer {token_formateado}"

        try:
            with open("token", "w", encoding="utf-8") as f:
                f.write(token_formateado)
            self.token_guardado = True
            print("[DEBUG] capturar_y_guardar_token_desde_selenium: token guardado en archivo 'token'")
            return True
        except Exception as e:
            print(f"[DEBUG] capturar_y_guardar_token_desde_selenium: error al escribir archivo 'token': {e}")
            return False

    def _obtener_token_desde_logs_performance(self):
        """
        Revisa los logs de rendimiento de Chrome (Network.requestWillBeSent)
        y busca peticiones a servicios-compra-agil.mercadopublico.cl con header Authorization.
        Devuelve el último token visto o None.
        """
        if not self.driver:
            print("[DEBUG] _obtener_token_desde_logs_performance: no hay driver")
            return None

        try:
            logs = self.driver.get_log("performance")
        except Exception as e:
            print(f"[DEBUG] _obtener_token_desde_logs_performance: error al obtener logs de performance: {e}")
            return None

        if not logs:
            print("[DEBUG] _obtener_token_desde_logs_performance: logs de performance vacíos")
            return None

        print(f"[DEBUG] _obtener_token_desde_logs_performance: {len(logs)} entradas de performance recibidas")

        token_encontrado = None

        # Revisar desde el final (las peticiones más recientes primero)
        for entry in reversed(logs):
            try:
                mensaje_raw = entry.get("message")
                if not mensaje_raw:
                    continue
                envoltura = json.loads(mensaje_raw)
                mensaje = envoltura.get("message", {})
                metodo = mensaje.get("method")
                if metodo != "Network.requestWillBeSent":
                    continue
                params = mensaje.get("params", {})
                request = params.get("request", {})
                url = request.get("url", "")
                if "servicios-compra-agil.mercadopublico.cl" not in url:
                    continue
                headers = request.get("headers", {})
                auth = headers.get("Authorization") or headers.get("authorization")
                if auth:
                    print(f"[DEBUG] _obtener_token_desde_logs_performance: Authorization encontrado para url={url}")
                    token_encontrado = auth
                    break
            except Exception as e:
                print(f"[DEBUG] _obtener_token_desde_logs_performance: error procesando entrada de log: {e}")
                continue

        if not token_encontrado:
            print("[DEBUG] _obtener_token_desde_logs_performance: no se encontró Authorization en los logs")
        else:
            print(f"[DEBUG] _obtener_token_desde_logs_performance: token_encontrado={repr(token_encontrado)[:120]}")

        return token_encontrado

    def _obtener_token_desde_navegador(self):
        """
        Instala (si es necesario) un hook en fetch/XMLHttpRequest para capturar el header Authorization
        cuando la página llama a https://servicios-compra-agil.mercadopublico.cl, y devuelve el último
        token visto (sin modificar archivo).
        """
        if not self.driver:
            print("[DEBUG] _obtener_token_desde_navegador: no hay driver")
            return None

        script_hook_y_token = """
            (function() {
                function storeAuth(value) {
                    if (!value || typeof value !== 'string') return;
                    var v = value.trim();
                    if (!v) return;
                    var lower = v.toLowerCase();
                    if (lower.indexOf('bearer ') !== 0 && v.indexOf('.') === -1) return;
                    window.__MP_CA_AUTH_TOKEN__ = v;
                }

                function shouldInspect(input) {
                    try {
                        var url = null;
                        if (typeof input === 'string') {
                            url = input;
                        } else if (input && typeof input.url === 'string') {
                            url = input.url;
                        }
                        if (!url) return false;
                        return url.indexOf('servicios-compra-agil.mercadopublico.cl') !== -1;
                    } catch (e) {
                        return false;
                    }
                }

                function extractFromHeaders(headers) {
                    if (!headers) return;
                    try {
                        if (typeof headers.get === 'function') {
                            var h = headers.get('Authorization') || headers.get('authorization');
                            if (h) {
                                storeAuth(h);
                            }
                            if (window.__MP_CA_AUTH_TOKEN__ && window.__MP_CA_AUTH_TOKEN__.length) return;
                            if (typeof headers.forEach === 'function') {
                                headers.forEach(function(v, k) {
                                    if (k && typeof k === 'string' && k.toLowerCase() === 'authorization') {
                                        storeAuth(v);
                                    }
                                });
                            }
                        } else if (Array.isArray(headers)) {
                            for (var i = 0; i < headers.length; i++) {
                                var entry = headers[i];
                                if (!entry) continue;
                                var name = entry[0];
                                var val = entry[1];
                                if (name && typeof name === 'string' && name.toLowerCase() === 'authorization') {
                                    storeAuth(val);
                                }
                            }
                        } else if (typeof headers === 'object') {
                            var cand = headers['Authorization'] || headers['authorization'];
                            if (cand) {
                                storeAuth(cand);
                            }
                            if (window.__MP_CA_AUTH_TOKEN__ && window.__MP_CA_AUTH_TOKEN__.length) return;
                            for (var key in headers) {
                                if (!Object.prototype.hasOwnProperty.call(headers, key)) continue;
                                if (key && typeof key === 'string' && key.toLowerCase() === 'authorization') {
                                    storeAuth(headers[key]);
                                }
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
                                    if (init && init.headers) {
                                        extractFromHeaders(init.headers);
                                    }
                                    if (!window.__MP_CA_AUTH_TOKEN__ && input && input.headers) {
                                        extractFromHeaders(input.headers);
                                    }
                                }
                            } catch (e) {}
                            return originalFetch.apply(this, arguments);
                        };
                    }

                    if (window.XMLHttpRequest && window.XMLHttpRequest.prototype) {
                        var originalOpen = window.XMLHttpRequest.prototype.open;
                        var originalSetRequestHeader = window.XMLHttpRequest.prototype.setRequestHeader;

                        window.XMLHttpRequest.prototype.open = function(method, url) {
                            try {
                                this.__mp_ca_should_inspect__ = false;
                                if (typeof url === 'string' &&
                                    url.indexOf('servicios-compra-agil.mercadopublico.cl') !== -1) {
                                    this.__mp_ca_should_inspect__ = true;
                                }
                            } catch (e) {}
                            return originalOpen.apply(this, arguments);
                        };

                        window.XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
                            try {
                                if (this.__mp_ca_should_inspect__ &&
                                    name && typeof name === 'string' &&
                                    name.toLowerCase() === 'authorization') {
                                    storeAuth(value);
                                }
                            } catch (e) {}
                            return originalSetRequestHeader.apply(this, arguments);
                        };
                    }
                }

                return window.__MP_CA_AUTH_TOKEN__ || null;
            })();
        """

        token_encontrado = None

        try:
            try:
                ventana_original = self.driver.current_window_handle
                print(f"[DEBUG] _obtener_token_desde_navegador: ventana_original={ventana_original}")
            except Exception as e:
                print(f"[DEBUG] _obtener_token_desde_navegador: no se pudo obtener ventana_original: {e}")
                ventana_original = None

            try:
                handles = self.driver.window_handles
                print(f"[DEBUG] _obtener_token_desde_navegador: window_handles={handles}")
            except Exception as e:
                print(f"[DEBUG] _obtener_token_desde_navegador: no se pudieron obtener window_handles: {e}")
                handles = []

            if not handles and ventana_original:
                handles = [ventana_original]

            for handle in handles:
                try:
                    print(f"[DEBUG] _obtener_token_desde_navegador: probando handle={handle}")
                    self.driver.switch_to.window(handle)
                    resultado = self.driver.execute_script(script_hook_y_token)
                    print(f"[DEBUG] _obtener_token_desde_navegador: resultado script en {handle}={repr(resultado)[:200]}")
                    if isinstance(resultado, str) and resultado.strip():
                        token_encontrado = resultado.strip()
                        print("[DEBUG] _obtener_token_desde_navegador: token encontrado en este handle")
                        break
                except Exception as e:
                    print(f"[DEBUG] _obtener_token_desde_navegador: error ejecutando script en {handle}: {e}")
                    continue
        finally:
            try:
                if ventana_original:
                    print(f"[DEBUG] _obtener_token_desde_navegador: volviendo a ventana_original={ventana_original}")
                    self.driver.switch_to.window(ventana_original)
            except Exception as e:
                print(f"[DEBUG] _obtener_token_desde_navegador: error al volver a ventana_original: {e}")

        print(f"[DEBUG] _obtener_token_desde_navegador: token_encontrado={repr(token_encontrado)[:120]}")
        return token_encontrado

    def _iniciar_monitoreo_token_automatico(self):
        """Comienza a intentar detectar el token en segundo plano usando el mainloop de Tkinter."""
        if not self.driver:
            print("[DEBUG] _iniciar_monitoreo_token_automatico: no hay driver, no se programa monitoreo")
            return
        if self.continuar_sin_login.get():
            print("[DEBUG] _iniciar_monitoreo_token_automatico: modo sin login, no se programa monitoreo de token")
            return
        self.token_guardado = False
        print("[DEBUG] _iniciar_monitoreo_token_automatico: programando primer poll de token en 3000ms")
        self._programar_poll_token(3000)

    def _programar_poll_token(self, delay_ms=5000):
        if not self.driver or self.token_guardado:
            print(f"[DEBUG] _programar_poll_token: no se programa poll (driver={bool(self.driver)}, token_guardado={self.token_guardado})")
            return
        try:
            print(f"[DEBUG] _programar_poll_token: programando _poll_token_automatico en {delay_ms}ms")
            if self._token_poll_after_id is not None:
                try:
                    self.root.after_cancel(self._token_poll_after_id)
                except Exception:
                    pass
                self._token_poll_after_id = None
            self._token_poll_after_id = self.root.after(delay_ms, self._poll_token_automatico)
        except tk.TclError as e:
            print(f"[DEBUG] _programar_poll_token: TclError al programar poll: {e}")

    def _poll_token_automatico(self):
        """Intento periódico de captura automática del token mientras el navegador está abierto."""
        if not self.driver or self.token_guardado:
            print(f"[DEBUG] _poll_token_automatico: cancelado (driver={bool(self.driver)}, token_guardado={self.token_guardado})")
            return
        if self.continuar_sin_login.get():
            print("[DEBUG] _poll_token_automatico: modo sin login, se detiene el monitoreo de token")
            return

        print("[DEBUG] _poll_token_automatico: intentando captura automática de token...")
        self._intentar_click_compra_agil()
        if self.capturar_y_guardar_token_desde_selenium():
            try:
                self.status_var.set(
                    "Token de Compra Ágil detectado automáticamente y guardado en 'token'."
                )
                messagebox.showinfo(
                    "Token detectado",
                    "Se detectó automáticamente el token de autenticación para Compra Ágil.\n"
                    "El archivo 'token' ha sido actualizado para las APIs."
                )
                print("[DEBUG] _poll_token_automatico: token detectado y mensaje mostrado")
            except tk.TclError as e:
                print(f"[DEBUG] _poll_token_automatico: TclError al mostrar mensaje de token detectado: {e}")
        else:
            delay_ms = 1000 if not self._compra_agil_clicked else 2000
            print(f"[DEBUG] _poll_token_automatico: todavía no se detecta token, reintentando en {delay_ms}ms")
            self._programar_poll_token(delay_ms)

    def _intentar_click_compra_agil(self):
        """
        Si aparece el botón "Compra Ágil" en el portal, lo presiona una vez para gatillar
        llamadas a la API y facilitar la captura automática del token.
        """
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
            print("[DEBUG] _intentar_click_compra_agil: clic en 'Compra Ágil' ejecutado")
            return True
        except Exception as e:
            print(f"[DEBUG] _intentar_click_compra_agil: error intentando click: {e}")
            return False
    
    def validar_codigo(self):
        """Valida que se haya ingresado un código"""
        if not self.codigo.get().strip():
            messagebox.showwarning("Código requerido", "Por favor ingrese un código de proceso")
            return False
        return True
    
    def _set_estado_botones_accion(self, estado):
        """Habilita o deshabilita los botones de acción"""
        self.btn_flujo_completo.configure(state=estado)
        self.btn_descargar.configure(state=estado)
        self.btn_generar_excel.configure(state=estado)
        self.btn_ficha_proveedor.configure(state=estado)
        if estado == 'normal' and self.tipo_proceso.get() != "licitacion":
            self.btn_test_flujo_lici.configure(state='disabled')
        else:
            self.btn_test_flujo_lici.configure(state=estado)

    # =========================
    # Sesión / cookies
    # =========================
    def _habilitar_acciones_sin_login(self):
        self.token_guardado = False
        self.status_var.set("Modo sin login: acciones habilitadas (token no capturado)")
        self.btn_flujo_completo.configure(state='normal')
        self.btn_descargar.configure(state='normal')
        self.btn_generar_excel.configure(state='normal')
        self.btn_ficha_proveedor.configure(state='normal')
        self.btn_test_flujo_lici.configure(state='normal' if self.tipo_proceso.get() == "licitacion" else 'disabled')
        self.btn_continuar.configure(state='disabled')

    def _detener_poll_token(self):
        if self._token_poll_after_id is not None:
            try:
                self.root.after_cancel(self._token_poll_after_id)
            except Exception:
                pass
            self._token_poll_after_id = None

    def _ruta_config(self):
        return os.path.join(os.getcwd(), "config.conf")

    def _limpiar_path_config(self, valor):
        if not valor:
            return ""
        valor = str(valor).strip()
        if (valor.startswith('"') and valor.endswith('"')) or (valor.startswith("'") and valor.endswith("'")):
            valor = valor[1:-1]
        return valor.strip()

    def _es_ruta_windows(self, valor):
        return len(valor) >= 2 and valor[1] == ":"

    def _cargar_config(self):
        ruta = self._ruta_config()
        config = configparser.ConfigParser()
        if os.path.exists(ruta):
            try:
                config.read(ruta)
            except Exception:
                return {}
        data = {}
        if config.has_option("PATH", "download_path"):
            raw = config.get("PATH", "download_path", fallback="").strip()
            base_dir = self._limpiar_path_config(raw)
            if base_dir:
                data["base_descargas_dir"] = base_dir
        return data

    def _guardar_config(self, data):
        try:
            ruta = self._ruta_config()
            config = configparser.ConfigParser()
            if os.path.exists(ruta):
                try:
                    config.read(ruta)
                except Exception:
                    config = configparser.ConfigParser()
            if not config.has_section("PATH"):
                config.add_section("PATH")
            base_dir = self._limpiar_path_config(data.get("base_descargas_dir", ""))
            if base_dir:
                config.set("PATH", "download_path", f"\"{base_dir}\"")
            with open(ruta, "w", encoding="utf-8") as f:
                config.write(f)
        except Exception:
            pass

    def _cargar_base_descargas(self):
        data = self._cargar_config()
        base_dir = data.get("base_descargas_dir")
        if base_dir:
            return base_dir
        return None

    def _normalizar_base_descargas(self):
        base_dir = (self.base_descargas_dir.get() or "").strip() or os.path.abspath("Descargas")
        base_dir = self._limpiar_path_config(base_dir)
        if self._es_ruta_windows(base_dir):
            normalizado = base_dir
        else:
            normalizado = os.path.abspath(base_dir)
        self.base_descargas_dir.set(normalizado)
        return normalizado

    def _guardar_base_descargas(self):
        base_dir = self._normalizar_base_descargas()
        data = self._cargar_config()
        data["base_descargas_dir"] = base_dir
        self._guardar_config(data)

    def elegir_carpeta_descargas(self):
        actual = (self.base_descargas_dir.get() or "").strip() or os.path.abspath("Descargas")
        try:
            initial = actual if os.path.isdir(actual) else os.getcwd()
        except Exception:
            initial = os.getcwd()

        carpeta = filedialog.askdirectory(
            title="Seleccionar carpeta de descargas",
            initialdir=initial,
            mustexist=False
        )
        if not carpeta:
            return
        self.base_descargas_dir.set(os.path.abspath(carpeta))
        if hasattr(self, "status_var"):
            self.status_var.set("Carpeta de descargas seleccionada")

    def guardar_carpeta_descargas(self):
        self._guardar_base_descargas()
        if hasattr(self, "status_var"):
            self.status_var.set("Carpeta de descargas guardada")

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
            data = {
                "timestamp": time.time(),
                "cookies": cookies,
            }
            with open(self._ruta_cookies(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[DEBUG] Cookies guardadas en {self._ruta_cookies()} ({len(cookies)} cookies)")
            return True
        except Exception as e:
            print(f"[DEBUG] Error guardando cookies: {e}")
            return False

    def _restaurar_sesion_cookies(self):
        ruta = self._ruta_cookies()
        if not os.path.exists(ruta):
            print("[DEBUG] No hay cookies previas para restaurar.")
            return False
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies") or []
        except Exception as e:
            print(f"[DEBUG] Error leyendo cookies guardadas: {e}")
            return False

        if not cookies:
            print("[DEBUG] Archivo de cookies vacío.")
            return False

        # Agrupar por dominio y agregarlas
        dominios = sorted({c.get("domain") for c in cookies if c.get("domain")})
        print(f"[DEBUG] Restaurando cookies para dominios: {dominios}")
        for dom in dominios:
            if not dom:
                continue
            url = f"https://{dom.lstrip('.')}/"
            try:
                self.driver.get(url)
            except Exception as e:
                print(f"[DEBUG] No se pudo navegar a {url} para setear cookies: {e}")
                continue
            for c in cookies:
                if c.get("domain") != dom:
                    continue
                cookie = {k: v for k, v in c.items() if k in {"name", "value", "domain", "path", "expiry", "secure", "httpOnly", "sameSite"}}
                if "path" not in cookie:
                    cookie["path"] = "/"
                if "expiry" in cookie:
                    try:
                        cookie["expiry"] = int(cookie["expiry"])
                    except Exception:
                        cookie.pop("expiry", None)
                try:
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    print(f"[DEBUG] No se pudo agregar cookie {cookie.get('name')} para dominio {dom}: {e}")
                    continue
        try:
            self.driver.get("https://mercadopublico.cl/Home")
        except Exception:
            pass
        return True
    
    def ejecutar_flujo_completo(self):
        """Ejecuta el flujo completo: descarga adjuntos, ficha(s) y Excel"""
        if not self.validar_codigo():
            return
        
        if not self.navegador_iniciado:
            messagebox.showwarning("Advertencia", "Debe iniciar el navegador primero")
            return
        
        codigo = self.codigo.get().strip()
        tipo = self.tipo_proceso.get()
        base_dir = self._normalizar_base_descargas()
        
        self.status_var.set(f"Ejecutando flujo completo para {tipo}: {codigo}...")
        
        # Deshabilitar botones durante el proceso
        self._set_estado_botones_accion('disabled')
        
        def proceso_flujo():
            try:
                # Paso 1: descargar adjuntos de todos los proveedores
                if tipo == "licitacion":
                    # TODO: implementar flujo completo para licitación
                    messagebox.showinfo("Función pendiente", "Flujo completo para licitación aún no implementado.")
                    self.status_var.set("Flujo licitación pendiente")
                    return

                # Compra ágil: usar API para descarga
                resultado_descarga = descarga_ca.descargar_compra_agil_api(
                    codigo,
                    driver=self.driver,
                    base_dir=base_dir
                )
                if not resultado_descarga:
                    messagebox.showerror("Error", f"Error durante la descarga de {tipo}: {codigo}")
                    self.status_var.set("Error en la descarga")
                    return

                # Paso 2: crear ZIP unico del proceso
                try:
                    carpeta = descarga_ca.resolver_carpeta_base(base_dir, "ComprasAgiles", codigo)
                    zip_destino = os.path.join(os.path.dirname(carpeta), f"{os.path.basename(carpeta)}.zip")
                    zip_path = descarga_ca.crear_zip_carpeta(carpeta, zip_destino)
                    if zip_path:
                        print(f"[ZIP] ZIP generado para compra agil {codigo}: {zip_path}")
                except Exception as e:
                    print(f"[ZIP] Error al crear ZIP: {e}")

                # Paso 3: generar Excel (reutiliza el mismo botón de excel)
                ruta_excel = genera_xls_ca.generar_excel_compra_agil(
                    codigo,
                    self.driver,
                    base_dir=base_dir,
                    carpeta_base=carpeta,
                )

                if ruta_excel:
                    messagebox.showinfo(
                        "Flujo completado",
                        f"Flujo completado exitosamente para {tipo}: {codigo}\n\n"
                        f"Excel generado en:\n{ruta_excel}"
                    )
                    self.status_var.set(f"Flujo completado para {tipo}: {codigo}")
                    if messagebox.askyesno("Abrir Excel", "¿Desea abrir el archivo Excel generado?"):
                        os.startfile(ruta_excel) if os.name == 'nt' else os.system(f'xdg-open \"{ruta_excel}\"')
                else:
                    messagebox.showerror("Error", f"Error al generar Excel para {tipo}: {codigo}")
                    self.status_var.set("Error al generar Excel")
            
            except Exception as e:
                messagebox.showerror("Error", f"Error inesperado en el flujo completo: {str(e)}")
                self.status_var.set("Error en el flujo completo")
            finally:
                # Rehabilitar botones
                self._set_estado_botones_accion('normal')
    
    def descargar_adjuntos(self):
        """Descarga los adjuntos del proceso"""
        if not self.validar_codigo():
            return
            
        codigo = self.codigo.get().strip()
        tipo = self.tipo_proceso.get()
        base_dir = self._normalizar_base_descargas()
        
        self.status_var.set(f"Descargando adjuntos para {tipo}: {codigo}...")
        
        # Deshabilitar botones durante el proceso
        self._set_estado_botones_accion('disabled')
        
        def proceso_descarga():
            try:
                if tipo == "licitacion":
                    # TODO: Llamar a descarga_lici.py cuando esté implementado
                    messagebox.showinfo("Función pendiente", "Descarga de licitación - Función por implementar")
                    resultado = False
                else:
                    # Llamar a descarga_ca.py usando API y token guardado
                    resultado = descarga_ca.descargar_compra_agil_api(
                        codigo,
                        driver=self.driver,
                        base_dir=base_dir
                    )
                
                if resultado:
                    destino = os.path.join(
                        base_dir,
                        f"{tipo.replace('_', ' ').title()}s",
                        codigo
                    )
                    messagebox.showinfo("Descarga Completada", 
                                       f"Descarga completada exitosamente para {tipo}: {codigo}\n\n"
                                       f"Los archivos se guardaron en:\n{destino}")
                    self.status_var.set(f"Descarga completada para {tipo}: {codigo}")
                else:
                    messagebox.showerror("Error", f"Error durante la descarga de {tipo}: {codigo}")
                    self.status_var.set("Error en la descarga")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Error inesperado: {str(e)}")
                self.status_var.set("Error en la descarga")
            finally:
                # Rehabilitar botones
                self._set_estado_botones_accion('normal')
        
        # Ejecutar en hilo separado para no bloquear la interfaz
        thread = threading.Thread(target=proceso_descarga)
        thread.daemon = True
        thread.start()
    
    def generar_excel(self):
        """Genera el archivo Excel del proceso"""
        if not self.validar_codigo():
            return
            
        codigo = self.codigo.get().strip()
        tipo = self.tipo_proceso.get()
        base_dir = self._normalizar_base_descargas()
        
        self.status_var.set(f"Generando Excel para {tipo}: {codigo}...")
        
        # Deshabilitar botones durante el proceso
        self._set_estado_botones_accion('disabled')
        
        def proceso_excel():
            try:
                if tipo == "licitacion":
                    # TODO: Llamar a genera_xls_lici.py cuando esté implementado
                    messagebox.showinfo("Función pendiente", "Generación Excel licitación - Función por implementar")
                    ruta_excel = None
                else:
                    # Llamar a genera_xls_ca.py
                    ruta_excel = genera_xls_ca.generar_excel_compra_agil(
                        codigo,
                        self.driver,
                        base_dir=base_dir
                    )
                
                if ruta_excel:
                    messagebox.showinfo("Excel Generado", 
                                       f"Excel generado exitosamente para {tipo}: {codigo}\n\n"
                                       f"Archivo guardado en:\n{ruta_excel}")
                    self.status_var.set(f"Excel generado para {tipo}: {codigo}")
                    
                    # Preguntar si desea abrir el archivo
                    if messagebox.askyesno("Abrir Excel", "¿Desea abrir el archivo Excel generado?"):
                        os.startfile(ruta_excel) if os.name == 'nt' else os.system(f'xdg-open "{ruta_excel}"')
                else:
                    messagebox.showerror("Error", f"Error al generar Excel para {tipo}: {codigo}")
                    self.status_var.set("Error al generar Excel")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Error inesperado: {str(e)}")
                self.status_var.set("Error al generar Excel")
            finally:
                # Rehabilitar botones
                self._set_estado_botones_accion('normal')
        
        # Ejecutar en hilo separado para no bloquear la interfaz
        thread = threading.Thread(target=proceso_excel)
        thread.daemon = True
        thread.start()

    def testear_flujo_licitacion(self):
        """Descarga adjuntos de licitación usando la lógica de scrape_cuadro.py (debug)."""
        if not self.navegador_iniciado or not self.driver:
            messagebox.showwarning("Advertencia", "Debe iniciar el navegador primero")
            return

        # En debug, permitir probar con URL directa sin exigir código.
        if not self.test_lici_desde_url.get() and self.tipo_proceso.get() != "licitacion":
            messagebox.showwarning("Solo licitación", "Seleccione 'Licitación' para testear la descarga.")
            return
        if not self.test_lici_desde_url.get() and not self.validar_codigo():
            return

        codigo = self.codigo.get().strip()
        base_dir = self._normalizar_base_descargas()
        self.status_var.set(f"Testeando descarga de adjuntos: {codigo or 'URL directa'}...")
        self._set_estado_botones_accion('disabled')

        def proceso_test():
            try:
                url_directa = None
                if self.test_lici_desde_url.get():
                    url_directa = self.test_lici_url_valor.get().strip()
                    if not url_directa:
                        messagebox.showwarning(
                            "URL requerida",
                            "Ingrese la URL de la licitación a probar o desmarque la opción 'Testear licitación desde URL'."
                        )
                        return
                elif self.test_lici_url_directa.get():
                    url_directa = "https://mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?qs=JjO5zKqb+2R21IMjm8Gxkg=="

                # Construir URL si viene de código
                if not url_directa:
                    url_directa = flujo_licitacion.obtener_url_licitacion(codigo, self.driver)
                    if not url_directa:
                        messagebox.showerror(
                            "No se encontró licitación",
                            "No se pudo obtener la URL de la licitación desde el código ingresado."
                        )
                        self.status_var.set("No se pudo obtener URL de licitación")
                        return

                destino = os.path.join(base_dir, "Licitaciones", codigo or "sin_codigo")
                # Descargar usando el mismo flujo que scrape_cuadro.py, pero guardando en la estructura de Descargas/Licitaciones/{codigo}
                resultado = scrape_cuadro.descargar_adjuntos_desde_url(
                    url_directa,
                    self.driver,
                    codigo=codigo or None,
                    download_dir=destino
                )
                ok = bool(resultado.get("ok"))
                descargados = resultado.get("descargados", 0)
                carpeta_destino = resultado.get("download_dir", "adjuntos")
                if ok:
                    messagebox.showinfo(
                        "Test licitación",
                        f"Descarga de adjuntos completada.\n\n"
                        f"Archivos descargados: {descargados}\n"
                        f"Carpeta: {carpeta_destino}"
                    )
                    self.status_var.set("Test licitación OK")
                else:
                    errores = "\n".join(resultado.get("errores") or [])
                    messagebox.showerror(
                        "Test licitación",
                        f"No se pudieron descargar los adjuntos.\n{errores}"
                    )
                    self.status_var.set("Fallo test licitación")
            except Exception as e:
                messagebox.showerror("Error", f"Error en test licitación: {e}")
                self.status_var.set("Error en test licitación")
            finally:
                self._set_estado_botones_accion('normal')

        thread = threading.Thread(target=proceso_test, daemon=True)
        thread.start()

    def _probar_flujo_licitacion(self, codigo_lici):
        driver = self.driver
        wait = WebDriverWait(driver, 20)

        def esperar_nueva_ventana(handles_prev, timeout=15):
            try:
                WebDriverWait(driver, timeout).until(lambda d: len(d.window_handles) > len(handles_prev))
                for h in driver.window_handles:
                    if h not in handles_prev:
                        return h
            except Exception:
                return None
            return None

        print(f"[TEST LICITACION] Abriendo buscador para código {codigo_lici}")
        driver.get("https://mercadopublico.cl/Procurement/Modules/RFB/SearchAcquisitions.aspx")

        try:
            campo_codigo = wait.until(EC.presence_of_element_located((By.ID, "txt_Nombre")))
            campo_codigo.clear()
            campo_codigo.send_keys(codigo_lici)
        except Exception as e:
            print(f"[TEST LICITACION] No se encontró campo de código: {e}")
            return False

        try:
            btn_buscar = wait.until(EC.element_to_be_clickable((By.ID, "buttonSearchByAll")))
            btn_buscar.click()
        except Exception as e:
            print(f"[TEST LICITACION] No se pudo hacer click en Buscar: {e}")
            return False

        # Abrir la licitación desde el resultado
        enlace_licitacion = None
        try:
            enlace_licitacion = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, f"//a[contains(@id,'hlkNumAcquisition') and normalize-space(text())='{codigo_lici}']")
                )
            )
        except Exception:
            try:
                enlace_licitacion = wait.until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//a[contains(@id,'hlkNumAcquisition')]")
                    )
                )
            except Exception as e:
                print(f"[TEST LICITACION] No se encontró enlace de licitación: {e}")
                return False

        handles_prev = driver.window_handles[:]
        try:
            driver.execute_script("arguments[0].click();", enlace_licitacion)
        except Exception:
            try:
                enlace_licitacion.click()
            except Exception as e:
                print(f"[TEST LICITACION] Click en licitación falló: {e}")
                return False

        nuevo_handle = esperar_nueva_ventana(handles_prev)
        if nuevo_handle:
            driver.switch_to.window(nuevo_handle)

        # Click en Cuadro de Ofertas
        try:
            btn_cuadro = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//input[contains(@id,'imgCuadroOferta')]"))
            )
        except Exception as e:
            print(f"[TEST LICITACION] No se encontró botón Cuadro de Ofertas: {e}")
            return False

        handles_prev = driver.window_handles[:]
        try:
            driver.execute_script("arguments[0].click();", btn_cuadro)
        except Exception:
            try:
                btn_cuadro.click()
            except Exception as e:
                print(f"[TEST LICITACION] Click en Cuadro de Ofertas falló: {e}")
                return False

        nuevo_handle = esperar_nueva_ventana(handles_prev)
        if nuevo_handle:
            driver.switch_to.window(nuevo_handle)

        # Abrir Anexos Administrativos del primer proveedor disponible
        try:
            btn_admin = WebDriverWait(driver, 25).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id*='_GvImgbAdministrativeAttachment']"))
            )
        except Exception as e:
            print(f"[TEST LICITACION] No se encontró botón de Anexos Administrativos: {e}")
            return False

        handles_prev = driver.window_handles[:]
        try:
            driver.execute_script("arguments[0].click();", btn_admin)
        except Exception:
            try:
                btn_admin.click()
            except Exception as e:
                print(f"[TEST LICITACION] Click en Anexos Administrativos falló: {e}")
                return False

        nuevo_handle = esperar_nueva_ventana(handles_prev)
        if nuevo_handle:
            driver.switch_to.window(nuevo_handle)

        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception:
            pass

        print("[TEST LICITACION] Anexos Administrativos abiertos.")
        return True
    
    def generar_ficha_proveedor(self):
        """Genera la ficha del proveedor"""
        if not self.validar_codigo():
            return
            
        codigo = self.codigo.get().strip()
        
        self.status_var.set(f"Generando ficha de proveedor para: {codigo}...")
        
        # Aquí se llamará a genera_ficha_proveedor.py (acción individual de debug)
        messagebox.showinfo(
            "Función pendiente",
            "Generación ficha proveedor - Función por implementar en genera_ficha_proveedor.py"
        )
    
    def on_closing(self):
        """Maneja el cierre de la aplicación"""
        try:
            try:
                self._guardar_sesion_cookies()
            except Exception:
                pass
            try:
                self._guardar_base_descargas()
            except Exception:
                pass
            self.cerrar_navegador()
        except Exception:
            pass
        self.root.destroy()

def _parse_args():
    parser = argparse.ArgumentParser(description="Frontend con modos debug/test/prod para descargas MercadoPublico.")
    parser.add_argument(
        "--modo",
        choices=["debug", "test", "prod"],
        default="debug",
        help="Selecciona el modo de arranque de la interfaz (debug por defecto).",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Atajo para iniciar en modo test (equivalente a --modo test).",
    )
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Atajo para iniciar en modo prod (equivalente a --modo prod).",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    if getattr(args, "prod", False):
        modo = "prod"
    elif getattr(args, "test", False):
        modo = "test"
    else:
        modo = args.modo
    root = tk.Tk()
    app = DescargadorLicitacionesApp(root, modo=modo)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
