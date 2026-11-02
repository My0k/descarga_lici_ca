"""
Actualizador del Descargador MercadoPublico.

Baja la ultima version publicada en GitHub (ZIP del commit, sin necesitar git
instalado), reemplaza los archivos del programa y lo reinicia. Pensado para los
equipos Windows del INH, donde el programa se instala desde un ZIP y se abre con
run.bat.

No toca lo que es propio de cada equipo: el entorno virtual, el token, la sesion,
la configuracion, los registros ni las descargas (ver PROTEGIDOS).
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime

import requests

REPO = "My0k/descarga_lici_ca"
RAMA = "master"
API_ULTIMO_COMMIT = f"https://api.github.com/repos/{REPO}/commits/{RAMA}"
URL_ZIP = "https://codeload.github.com/" + REPO + "/zip/{sha}"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_VERSION = ".version_instalada.json"
CARPETA_RESPALDO = ".respaldo_actualizacion"

# Entradas de primer nivel que nunca se sobrescriben (en minusculas).
PROTEGIDOS = {
    "venv",
    ".venv",
    ".git",
    "sesion",
    "descargas",
    "licitaciones",
    "logs",
    "token",
    "config.conf",
    "git.conf",
    ARCHIVO_VERSION,
    CARPETA_RESPALDO,
}

# Archivos sin los cuales la version descargada no se instala.
OBLIGATORIOS = ("front_produccion.py", "run.bat", "requirements.txt")

CODIGO_SALIDA_REINICIO = 3
_HEADERS = {"User-Agent": "DescargadorMercadoPublico-Actualizador"}


class ErrorActualizacion(Exception):
    pass


# ---------------------------------------------------------------- versiones
def _fecha_legible(iso):
    try:
        fecha = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        return fecha.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso or ""


def _sha_desde_git():
    """Commit del checkout local (equipos de desarrollo, que no tienen ARCHIVO_VERSION)."""
    try:
        git_dir = os.path.join(APP_DIR, ".git")
        with open(os.path.join(git_dir, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(" ", 1)[1].strip()
        ruta_ref = os.path.join(git_dir, *ref.split("/"))
        if os.path.exists(ruta_ref):
            with open(ruta_ref, encoding="utf-8") as f:
                return f.read().strip()
        with open(os.path.join(git_dir, "packed-refs"), encoding="utf-8") as f:
            for linea in f:
                partes = linea.strip().split(" ")
                if len(partes) == 2 and partes[1] == ref:
                    return partes[0]
    except Exception:
        pass
    return ""


def version_local():
    """
    Version instalada: {"sha", "fecha", "mensaje"}. sha vacio si no se sabe (un
    equipo instalado desde el ZIP antes de que existiera el actualizador).
    """
    try:
        with open(os.path.join(APP_DIR, ARCHIVO_VERSION), encoding="utf-8") as f:
            datos = json.load(f)
        if datos.get("sha"):
            return datos
    except Exception:
        pass
    return {"sha": _sha_desde_git(), "fecha": "", "mensaje": ""}


def texto_version(version):
    sha = (version or {}).get("sha") or ""
    if not sha:
        return "Version: sin registro"
    fecha = _fecha_legible((version or {}).get("fecha"))
    return f"Version {sha[:7]}" + (f" ({fecha})" if fecha else "")


def consultar_ultima_version(timeout=20):
    """Ultimo commit publicado en GitHub: {"sha", "fecha", "mensaje"}."""
    try:
        resp = requests.get(
            API_ULTIMO_COMMIT,
            headers={**_HEADERS, "Accept": "application/vnd.github+json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ErrorActualizacion(f"No se pudo conectar con GitHub: {exc}") from exc
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise ErrorActualizacion(
            "GitHub limito las consultas desde esta red. Intente de nuevo en una hora."
        )
    if resp.status_code != 200:
        raise ErrorActualizacion(f"GitHub respondio HTTP {resp.status_code}.")
    datos = resp.json()
    commit = datos.get("commit") or {}
    return {
        "sha": datos.get("sha") or "",
        "fecha": ((commit.get("committer") or {}).get("date")) or "",
        "mensaje": (commit.get("message") or "").strip(),
    }


def hay_actualizacion(local, remota):
    return bool(remota.get("sha")) and (local or {}).get("sha") != remota.get("sha")


# --------------------------------------------------------------- instalacion
def _descargar_zip(sha, timeout=120):
    try:
        resp = requests.get(URL_ZIP.format(sha=sha), headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise ErrorActualizacion(f"No se pudo descargar la actualizacion: {exc}") from exc
    if resp.status_code != 200:
        raise ErrorActualizacion(f"La descarga de la actualizacion respondio HTTP {resp.status_code}.")
    try:
        return zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile as exc:
        raise ErrorActualizacion("El archivo descargado no es un ZIP valido.") from exc


def _extraer(zip_file, destino):
    """Extrae el ZIP y retorna la carpeta raiz del repositorio dentro de destino."""
    destino_abs = os.path.abspath(destino)
    for nombre in zip_file.namelist():
        ruta = os.path.abspath(os.path.join(destino_abs, nombre))
        if not ruta.startswith(destino_abs + os.sep):
            raise ErrorActualizacion(f"Ruta no valida en el ZIP: {nombre}")
    zip_file.extractall(destino_abs)
    raices = [e for e in os.listdir(destino_abs) if os.path.isdir(os.path.join(destino_abs, e))]
    if len(raices) != 1:
        raise ErrorActualizacion("El ZIP no tiene la estructura esperada.")
    raiz = os.path.join(destino_abs, raices[0])
    faltan = [o for o in OBLIGATORIOS if not os.path.isfile(os.path.join(raiz, o))]
    if faltan:
        raise ErrorActualizacion(f"A la version descargada le faltan archivos: {', '.join(faltan)}")
    return raiz


def _archivos_a_instalar(raiz):
    """Rutas relativas de los archivos del ZIP, sin los protegidos."""
    archivos = []
    for carpeta, subcarpetas, nombres in os.walk(raiz):
        rel_carpeta = os.path.relpath(carpeta, raiz)
        if rel_carpeta == ".":
            subcarpetas[:] = [s for s in subcarpetas if s.lower() not in PROTEGIDOS]
            nombres = [n for n in nombres if n.lower() not in PROTEGIDOS]
        for nombre in nombres:
            archivos.append(os.path.normpath(os.path.join(rel_carpeta, nombre)))
    return archivos


def _leer_bytes(ruta):
    try:
        with open(ruta, "rb") as f:
            return f.read()
    except OSError:
        return None


def instalar_version(remota, progreso=None):
    """
    Descarga e instala la version remota sobre APP_DIR. Si falla a mitad de camino,
    deja los archivos como estaban. Retorna {"archivos", "requirements_cambiaron"}.
    """
    def _avisar(texto):
        if progreso:
            try:
                progreso(texto)
            except Exception:
                pass

    sha = remota["sha"]
    _avisar("Descargando actualizacion...")
    zip_file = _descargar_zip(sha)

    with tempfile.TemporaryDirectory(prefix="actualizacion_") as temp:
        _avisar("Revisando archivos descargados...")
        raiz = _extraer(zip_file, temp)
        archivos = _archivos_a_instalar(raiz)
        req_antes = _leer_bytes(os.path.join(APP_DIR, "requirements.txt"))

        respaldo = os.path.join(APP_DIR, CARPETA_RESPALDO)
        shutil.rmtree(respaldo, ignore_errors=True)
        os.makedirs(respaldo, exist_ok=True)

        respaldados = []
        creados = []
        temporal = None
        _avisar(f"Instalando {len(archivos)} archivos...")
        try:
            for rel in archivos:
                origen = os.path.join(raiz, rel)
                destino = os.path.join(APP_DIR, rel)
                if os.path.isfile(destino):
                    copia = os.path.join(respaldo, rel)
                    os.makedirs(os.path.dirname(copia), exist_ok=True)
                    shutil.copy2(destino, copia)
                    respaldados.append(rel)
                else:
                    creados.append(rel)
                os.makedirs(os.path.dirname(destino) or APP_DIR, exist_ok=True)
                # Se copia a un temporal y se reemplaza de una vez: si se corta,
                # no queda un archivo a medio escribir.
                temporal = destino + ".actualizando"
                shutil.copy2(origen, temporal)
                os.replace(temporal, destino)
                temporal = None
        except Exception as exc:
            if temporal:
                try:
                    os.remove(temporal)
                except OSError:
                    pass
            for rel in respaldados:
                try:
                    shutil.copy2(os.path.join(respaldo, rel), os.path.join(APP_DIR, rel))
                except Exception:
                    pass
            for rel in creados:
                try:
                    os.remove(os.path.join(APP_DIR, rel))
                except Exception:
                    pass
            shutil.rmtree(respaldo, ignore_errors=True)
            raise ErrorActualizacion(
                f"No se pudo instalar la actualizacion ({exc}). Se restauro la version anterior."
            ) from exc

    req_despues = _leer_bytes(os.path.join(APP_DIR, "requirements.txt"))
    try:
        with open(os.path.join(APP_DIR, ARCHIVO_VERSION), "w", encoding="utf-8") as f:
            json.dump(
                {**remota, "instalado_en": datetime.now().isoformat(timespec="seconds")},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except OSError:
        pass
    shutil.rmtree(os.path.join(APP_DIR, CARPETA_RESPALDO), ignore_errors=True)
    return {"archivos": len(archivos), "requirements_cambiaron": req_antes != req_despues}


# ----------------------------------------------------------------- reinicio
def _procesos_windows():
    """{pid: (pid_padre, nombre_exe)} de todos los procesos (Windows)."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    procesos = {}
    try:
        entrada = PROCESSENTRY32W()
        entrada.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entrada))
        while ok:
            procesos[entrada.th32ProcessID] = (entrada.th32ParentProcessID, entrada.szExeFile.lower())
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entrada))
    finally:
        kernel32.CloseHandle(snapshot)
    return procesos


def _cmd_que_ejecuta_run_bat():
    """
    PID del cmd.exe que abrio el programa con run.bat, o None. La cadena tipica es
    cmd.exe (run.bat) -> python.exe del venv (lanzador) -> python.exe real.
    """
    try:
        procesos = _procesos_windows()
    except Exception:
        return None
    pid = os.getpid()
    vistos = set()
    for _ in range(6):
        if pid in vistos or pid not in procesos:
            return None
        vistos.add(pid)
        padre, _nombre = procesos[pid]
        if padre in procesos and procesos[padre][1] == "cmd.exe":
            return padre
        pid = padre
    return None


def reiniciar_programa():
    """
    Abre de nuevo el programa (en Windows, con run.bat en una consola nueva, que
    ademas instala dependencias nuevas) y cierra la consola de la ejecucion actual.

    La consola vieja se cierra a proposito: cmd lee run.bat linea a linea mientras
    corre, y si el actualizador reemplazo ese archivo seguiria ejecutando lineas del
    archivo nuevo desde una posicion que ya no corresponde.

    El llamador debe terminar el proceso despues (codigo CODIGO_SALIDA_REINICIO).
    """
    run_bat = os.path.join(APP_DIR, "run.bat")
    front = os.path.join(APP_DIR, "front_produccion.py")
    if os.name == "nt":
        cmd_padre = _cmd_que_ejecuta_run_bat()
        flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
        if os.path.isfile(run_bat):
            subprocess.Popen(["cmd.exe", "/c", run_bat], cwd=APP_DIR, creationflags=flags)
        else:
            subprocess.Popen([sys.executable, front], cwd=APP_DIR, creationflags=flags)
        if cmd_padre:
            subprocess.run(
                ["taskkill", "/PID", str(cmd_padre), "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    else:
        subprocess.Popen([sys.executable, front], cwd=APP_DIR, start_new_session=True)
