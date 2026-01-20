@echo off
setlocal EnableDelayedExpansion

REM Preparar entorno virtual
if not exist "%~dp0venv" (
    echo [INFO] Creando entorno virtual en "%~dp0venv%"
    where python
    if errorlevel 1 (
        echo [ERROR] No se encontro "python" en el PATH.
        pause
        exit /b 1
    )
    python --version
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

REM Instalar dependencias
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

REM Ejecutar en modo test (front de debug con atajos)
echo [INFO] Lanzando app.py en modo test
python "%~dp0app.py" --modo test

echo [INFO] Proceso finalizado. Pulse una tecla para cerrar.
pause

endlocal
