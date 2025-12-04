@echo off
setlocal

REM Crear/usar entorno virtual local
if not exist "%~dp0venv" (
    echo Creando entorno virtual...
    python -m venv "%~dp0venv"
)

call "%~dp0venv\Scripts\activate.bat"
if errorlevel 1 (
    echo No se pudo activar el entorno virtual.
    exit /b 1
)

REM Instalar dependencias del proyecto
if exist "%~dp0requirements.txt" (
    echo Instalando dependencias desde requirements.txt...
    pip install --upgrade pip
    pip install -r "%~dp0requirements.txt"
) else (
    echo No se encontro requirements.txt, se omite la instalacion de dependencias.
)

REM Asegurar PyQt para compatibilidad en Windows (Tkinter ya viene con Python)
pip install --upgrade PyQt5 PyQt5-Qt5 PyQt5-sip

REM Ejecutar la aplicacion
python "%~dp0app.py"

endlocal
