#!/usr/bin/env python3
"""
Script para descargar páginas de Mercado Público como PDF.
Usa Playwright en modo headless para renderizar completamente el JavaScript.
"""

import asyncio
from playwright.async_api import async_playwright
from pathlib import Path


async def descargar_pagina_como_pdf(url: str, nombre_archivo: str, timeout_ms: int = 30000):
    """
    Descarga una página web como PDF después de esperar que renderice completamente.
    
    Args:
        url: URL de la página a descargar
        nombre_archivo: Nombre del archivo PDF de salida
        timeout_ms: Tiempo máximo de espera en milisegundos
    """
    async with async_playwright() as p:
        # Usar Chromium en modo headless
        browser = await p.chromium.launch(headless=True)
        
        # Crear contexto con viewport amplio para capturar todo el contenido
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='es-CL'
        )
        
        page = await context.new_page()
        
        print(f"Navegando a: {url}")
        
        try:
            # Navegar a la página y esperar que la red esté inactiva
            await page.goto(url, wait_until='networkidle', timeout=timeout_ms)
            
            # Esperar adicional para asegurar que todo el JS termine de ejecutarse
            await page.wait_for_load_state('domcontentloaded')
            await page.wait_for_load_state('networkidle')
            
            # Esperar un poco más para componentes dinámicos
            await asyncio.sleep(3)
            
            # Opcional: esperar elementos específicos si los conoces
            # await page.wait_for_selector('selector-del-contenido-principal', timeout=10000)
            
            print(f"Página cargada. Generando PDF: {nombre_archivo}")
            
            # Generar PDF con configuración para capturar página completa
            await page.pdf(
                path=nombre_archivo,
                format='A4',
                print_background=True,
                margin={
                    'top': '10mm',
                    'bottom': '10mm',
                    'left': '10mm',
                    'right': '10mm'
                },
                scale=0.8  # Escala para que quepa mejor el contenido
            )
            
            print(f"✓ PDF guardado: {nombre_archivo}")
            
        except Exception as e:
            print(f"✗ Error procesando {url}: {e}")
            raise
        finally:
            await browser.close()


async def main():
    """Función principal que descarga las dos páginas solicitadas."""
    
    # Directorio de salida
    output_dir = Path("./pdfs_mercado_publico")
    output_dir.mkdir(exist_ok=True)
    
    # URLs a descargar
    paginas = [
        {
            'url': 'https://proveedor.mercadopublico.cl/dj-requisitos/728-1-LE26/76.576.059-3',
            'archivo': output_dir / 'declaracion_jurada_76576059-3.pdf'
        },
        {
            'url': 'https://proveedor.mercadopublico.cl/ficha/76.576.059-3',
            'archivo': output_dir / 'ficha_proveedor_76576059-3.pdf'
        }
    ]
    
    print("=" * 60)
    print("Descargador de páginas de Mercado Público a PDF")
    print("=" * 60)
    
    for pagina in paginas:
        print(f"\nProcesando: {pagina['url']}")
        await descargar_pagina_como_pdf(
            url=pagina['url'],
            nombre_archivo=str(pagina['archivo']),
            timeout_ms=60000  # 60 segundos de timeout
        )
    
    print("\n" + "=" * 60)
    print("Proceso completado.")
    print(f"PDFs guardados en: {output_dir.absolute()}")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
