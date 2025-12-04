@echo off
echo ========================================
echo  Descargador de Licitaciones - MercadoPublico.cl
echo ========================================
echo.

echo Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado o no esta en el PATH
    echo Por favor instale Python desde https://python.org
    pause
    exit /b 1
)

echo Python encontrado correctamente.
echo.

echo Verificando pip...
pip --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: pip no esta disponible
    pause
    exit /b 1
)

echo pip encontrado correctamente.
echo.

echo Instalando/actualizando dependencias...
echo.

pip install --upgrade pip
pip install selenium
pip install tkinter
pip install openpyxl
pip install pandas
pip install requests
pip install beautifulsoup4
pip install webdriver-manager

echo.
echo ========================================
echo  Instalacion completada
echo ========================================
echo.

echo Iniciando aplicacion...
echo.

python app.py

echo.
echo Aplicacion cerrada.
pause
