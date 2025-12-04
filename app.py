import tkinter as tk
from tkinter import ttk, messagebox
import os
import webbrowser
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import threading
import descarga_ca
import genera_xls_ca
import descarga_lici
import genera_xls_lici
import genera_ficha_proveedor

class DescargadorLicitacionesApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Descargador de Licitaciones - MercadoPublico.cl")
        
        # Configurar ventana para que se vea completa
        self.root.geometry("700x650")
        self.root.minsize(650, 600)
        self.root.configure(bg='#f8f9fa')
        
        # Centrar la ventana en la pantalla
        self.centrar_ventana()
        
        # Variables
        self.tipo_proceso = tk.StringVar(value="licitacion")
        self.codigo = tk.StringVar()
        self.navegador_iniciado = False
        self.driver = None
        
        self.setup_ui()
    
    def centrar_ventana(self):
        """Centra la ventana en la pantalla"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
    def setup_ui(self):
        # Estilo
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configurar colores del tema
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'), 
                       background='#f8f9fa', foreground='#2c3e50')
        style.configure('Subtitle.TLabel', font=('Segoe UI', 10), 
                       background='#f8f9fa', foreground='#7f8c8d')
        style.configure('Custom.TButton', font=('Segoe UI', 10))
        style.configure('Custom.TRadiobutton', font=('Segoe UI', 10), 
                       background='#f8f9fa')
        
        # Frame principal con scrollbar
        canvas = tk.Canvas(self.root, bg='#f8f9fa')
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#f8f9fa')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Frame principal
        main_frame = tk.Frame(scrollable_frame, bg='#f8f9fa', padx=40, pady=30)
        main_frame.pack(fill='both', expand=True)
        
        # Título
        title_label = ttk.Label(main_frame, text="Descargador de Licitaciones", 
                               style='Title.TLabel')
        title_label.pack(pady=(0, 5))
        
        subtitle_label = ttk.Label(main_frame, text="MercadoPublico.cl - Automatización de descargas", 
                                  style='Subtitle.TLabel')
        subtitle_label.pack(pady=(0, 30))
        
        # Separador
        separator1 = ttk.Separator(main_frame, orient='horizontal')
        separator1.pack(fill='x', pady=(0, 25))
        
        # Sección de navegador
        nav_frame = tk.Frame(main_frame, bg='#f8f9fa')
        nav_frame.pack(fill='x', pady=(0, 25))
        
        nav_label = ttk.Label(nav_frame, text="1. Inicializar Navegador", 
                             font=('Segoe UI', 12, 'bold'), background='#f8f9fa')
        nav_label.pack(anchor='w', pady=(0, 10))
        
        nav_desc = ttk.Label(nav_frame, 
                            text="Inicie el navegador, ingrese a su cuenta en MercadoPublico.cl y presione 'Continuar'",
                            style='Subtitle.TLabel', wraplength=500)
        nav_desc.pack(anchor='w', pady=(0, 15))
        
        self.btn_navegador = ttk.Button(nav_frame, text="🌐 Iniciar Navegador", 
                                       command=self.iniciar_navegador, style='Custom.TButton')
        self.btn_navegador.pack(anchor='w')
        
        self.btn_continuar = ttk.Button(nav_frame, text="✓ Continuar", 
                                       command=self.continuar_proceso, 
                                       state='disabled', style='Custom.TButton')
        self.btn_continuar.pack(anchor='w', pady=(10, 0))
        
        # Separador
        separator2 = ttk.Separator(main_frame, orient='horizontal')
        separator2.pack(fill='x', pady=(25, 25))
        
        # Sección de selección de proceso
        proceso_frame = tk.Frame(main_frame, bg='#f8f9fa')
        proceso_frame.pack(fill='x', pady=(0, 25))
        
        proceso_label = ttk.Label(proceso_frame, text="2. Seleccionar Tipo de Proceso", 
                                 font=('Segoe UI', 12, 'bold'), background='#f8f9fa')
        proceso_label.pack(anchor='w', pady=(0, 15))
        
        # Radio buttons para tipo de proceso
        radio_frame = tk.Frame(proceso_frame, bg='#f8f9fa')
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
        codigo_label = ttk.Label(proceso_frame, text="Código del Proceso:", 
                                font=('Segoe UI', 10, 'bold'), background='#f8f9fa')
        codigo_label.pack(anchor='w', pady=(0, 5))
        
        self.entry_codigo = ttk.Entry(proceso_frame, textvariable=self.codigo, 
                                     font=('Segoe UI', 11), width=30)
        self.entry_codigo.pack(anchor='w', pady=(0, 20))
        
        # Separador
        separator3 = ttk.Separator(main_frame, orient='horizontal')
        separator3.pack(fill='x', pady=(25, 25))
        
        # Botón de flujo completo
        flujo_frame = tk.Frame(main_frame, bg='#f8f9fa')
        flujo_frame.pack(fill='x', pady=(0, 25))
        
        flujo_label = ttk.Label(flujo_frame, text="3. Ejecutar flujo completo", 
                               font=('Segoe UI', 12, 'bold'), background='#f8f9fa')
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
        separator4.pack(fill='x', pady=(25, 25))
        
        # Botones de acción individuales (debug)
        action_frame = tk.Frame(main_frame, bg='#f8f9fa')
        action_frame.pack(fill='x')
        
        action_label = ttk.Label(action_frame, text="4. Acciones individuales (debug)", 
                                font=('Segoe UI', 12, 'bold'), background='#f8f9fa')
        action_label.pack(anchor='w', pady=(0, 15))
        
        buttons_frame = tk.Frame(action_frame, bg='#f8f9fa')
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
        
        # Status bar
        self.status_var = tk.StringVar(value="Listo - Inicie el navegador para comenzar")
        status_frame = tk.Frame(self.root, bg='#ecf0f1', height=30)
        status_frame.pack(fill='x', side='bottom')
        status_frame.pack_propagate(False)
        
        status_label = ttk.Label(status_frame, textvariable=self.status_var, 
                                background='#ecf0f1', font=('Segoe UI', 9))
        status_label.pack(pady=5)
        
    def iniciar_navegador(self):
        """Inicia el navegador web con Selenium"""
        try:
            self.status_var.set("Iniciando navegador...")
            
            # Configurar opciones de Chrome
            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")
            
            # Iniciar el navegador
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.get("https://mercadopublico.cl/Home")
            
            self.navegador_iniciado = True
            self.btn_navegador.configure(state='disabled')
            self.btn_continuar.configure(state='normal')
            
            self.status_var.set("Navegador iniciado - Ingrese a su cuenta y presione 'Continuar'")
            
            messagebox.showinfo("Navegador Iniciado", 
                               "Navegador iniciado correctamente.\n\n"
                               "Por favor:\n"
                               "1. Ingrese a su cuenta en MercadoPublico.cl\n"
                               "2. Una vez logueado, presione el botón 'Continuar'")
            
        except Exception as e:
            messagebox.showerror("Error", f"Error al iniciar el navegador:\n{str(e)}")
            self.status_var.set("Error al iniciar navegador")
    
    def continuar_proceso(self):
        """Continúa con el proceso después del login"""
        if not self.navegador_iniciado:
            messagebox.showwarning("Advertencia", "Debe iniciar el navegador primero")
            return
            
        # Habilitar los botones de acción
        self.btn_flujo_completo.configure(state='normal')
        self.btn_descargar.configure(state='normal')
        self.btn_generar_excel.configure(state='normal')
        self.btn_ficha_proveedor.configure(state='normal')
        
        self.status_var.set("Listo para procesar - Ingrese el código y ejecute el flujo completo o las acciones individuales")
        
        messagebox.showinfo(
            "Listo",
            "Sistema listo para procesar.\n\n"
            "Ahora puede:\n"
            "• Seleccionar el tipo de proceso\n"
            "• Ingresar el código\n"
            "• Ejecutar el flujo completo (recomendado)\n"
            "• O usar las acciones individuales para debug"
        )
    
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
    
    def ejecutar_flujo_completo(self):
        """Ejecuta el flujo completo: descarga adjuntos, ficha(s) y Excel"""
        if not self.validar_codigo():
            return
        
        if not self.navegador_iniciado:
            messagebox.showwarning("Advertencia", "Debe iniciar el navegador primero")
            return
        
        codigo = self.codigo.get().strip()
        tipo = self.tipo_proceso.get()
        
        self.status_var.set(f"Ejecutando flujo completo para {tipo}: {codigo}...")
        
        # Deshabilitar botones durante el proceso
        self._set_estado_botones_accion('disabled')
        
        def proceso_flujo():
            try:
                # Paso 1: descargar adjuntos de todos los proveedores
                if tipo == "licitacion":
                    resultado_descarga = descarga_lici.descargar_licitacion(codigo, self.driver)
                else:
                    resultado_descarga = descarga_ca.descargar_compra_agil(codigo, self.driver)
                
                if not resultado_descarga:
                    messagebox.showerror("Error", f"Error durante la descarga de {tipo}: {codigo}")
                    self.status_var.set("Error en la descarga")
                    return
                
                # Paso 2: generar ficha(s) de proveedor
                # Nota: la lógica de generación de fichas aún debe implementarse
                try:
                    proveedores = []
                    if tipo == "compra_agil":
                        # Para compras ágiles podemos reutilizar la lógica de obtención de proveedores
                        proveedores = descarga_ca.obtener_proveedores_ca(self.driver)
                    
                    if proveedores:
                        for proveedor in proveedores:
                            rut = proveedor.get('rut')
                            if not rut:
                                continue
                            try:
                                genera_ficha_proveedor.generar_ficha_proveedor(
                                    rut_proveedor=rut,
                                    codigo_proceso=codigo,
                                    tipo_proceso=tipo,
                                    driver=self.driver
                                )
                            except Exception as e:
                                print(f"Error al generar ficha para proveedor {rut}: {e}")
                    else:
                        # Placeholder mientras se implementa la lógica completa
                        messagebox.showinfo(
                            "Fichas de proveedor",
                            "Generación de fichas de proveedor aún no implementada completamente.\n"
                            "Solo se ha ejecutado la descarga de adjuntos."
                        )
                except Exception as e:
                    print(f"Error en la etapa de fichas de proveedor: {e}")
                
                # Paso 3: generar Excel de resumen
                if tipo == "licitacion":
                    ruta_excel = genera_xls_lici.generar_excel_licitacion(codigo, self.driver)
                else:
                    ruta_excel = genera_xls_ca.generar_excel_compra_agil(codigo, self.driver)
                
                if ruta_excel:
                    messagebox.showinfo(
                        "Flujo completado",
                        f"Flujo completado exitosamente para {tipo}: {codigo}\n\n"
                        f"Excel generado en:\n{ruta_excel}"
                    )
                    self.status_var.set(f"Flujo completado para {tipo}: {codigo}")
                    
                    # Preguntar si desea abrir el archivo
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
                    # Llamar a descarga_ca.py
                    resultado = descarga_ca.descargar_compra_agil(codigo, self.driver)
                
                if resultado:
                    messagebox.showinfo("Descarga Completada", 
                                       f"Descarga completada exitosamente para {tipo}: {codigo}\n\n"
                                       f"Los archivos se guardaron en:\nDescargas/{tipo.replace('_', ' ').title()}s/{codigo}/")
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
                    ruta_excel = genera_xls_ca.generar_excel_compra_agil(codigo, self.driver)
                
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
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        self.root.destroy()

def main():
    root = tk.Tk()
    app = DescargadorLicitacionesApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
