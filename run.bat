@echo off
setlocal

REM Crear/usar entorno virtual local
if not exist "%~dp0venv" (
    echo [INFO] Creando entorno virtual en "%~dp0venv%"
    echo [INFO] PATH actual:
    echo %PATH%
    echo [INFO] Buscando python...
    where python
    if errorlevel 1 (
        echo [ERROR] No se encontro "python" en el PATH.
        pause
        exit /b 1
    )

    echo [INFO] Version de Python:
    python --version

    echo [DEBUG] Ejecutando: python -m venv "%~dp0venv%"
    python -m venv "%~dp0venv%"
    if errorlevel 1 (
        echo [ERROR] Fallo al crear el entorno virtual.
        pause
        exit /b %ERRORLEVEL%
    )
)

call "%~dp0venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] No se pudo activar el entorno virtual.
    pause
    exit /b 1
)

REM Instalar dependencias del proyecto
if exist "%~dp0requirements.txt" (
    echo [INFO] Instalando dependencias desde requirements.txt...
    pip install --upgrade pip
    pip install -r "%~dp0requirements.txt"
) else (
    echo [WARN] No se encontro requirements.txt, se omite la instalacion de dependencias.
)

REM Asegurar PyQt para compatibilidad en Windows (Tkinter ya viene con Python)
echo [INFO] Asegurando instalacion de PyQt5...
pip install --upgrade PyQt5 PyQt5-Qt5 PyQt5-sip

REM Ejecutar la aplicacion
echo [INFO] Lanzando aplicacion: app.py
python "%~dp0app.py"

echo [INFO] Proceso finalizado. Pulse una tecla para cerrar.
pause

endlocal
