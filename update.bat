@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist ".git" (
  echo [ERROR] Esta carpeta no parece ser un repo git: %SCRIPT_DIR%
  pause
  exit /b 1
)

if not exist "git.conf" (
  echo [ERROR] No se encontro git.conf en: %SCRIPT_DIR%git.conf
  pause
  exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%A in (`findstr /R /C:"^[ ]*[a-zA-Z][a-zA-Z0-9_]*[ ]*=" "git.conf"`) do (
  set "K=%%A"
  set "V=%%B"
  call :trim K
  call :trim V
  if /I "!K!"=="user" set "GIT_USER=!V!"
  if /I "!K!"=="pass" set "GIT_PASS=!V!"
  if /I "!K!"=="repo" set "GIT_REPO=!V!"
  if /I "!K!"=="branch" set "GIT_BRANCH=!V!"
)

if not defined GIT_REPO (
  echo [ERROR] git.conf incompleto: falta repo
  pause
  exit /b 1
)
if not defined GIT_BRANCH (
  echo [ERROR] git.conf incompleto: falta branch
  pause
  exit /b 1
)

set "REMOTE_URL=https://github.com/%GIT_REPO%.git"

set "ASKPASS_FILE=%TEMP%\\git_askpass_%RANDOM%%RANDOM%.cmd"
(
  echo @echo off
  echo setlocal EnableDelayedExpansion
  echo set "P=%%*"
  echo echo(%%P%% ^| findstr /I "Username" ^>nul ^&^& ^(
  echo   echo %%GIT_CONF_USER%%
  echo   exit /b 0
  echo ^)
  echo echo(%%P%% ^| findstr /I "Password" ^>nul ^&^& ^(
  echo   echo %%GIT_CONF_PASS%%
  echo   exit /b 0
  echo ^)
  echo echo %%GIT_CONF_PASS%%
) > "%ASKPASS_FILE%"

set "GIT_CONF_USER=%GIT_USER%"
set "GIT_CONF_PASS=%GIT_PASS%"

echo [INFO] Actualizando repo en: %SCRIPT_DIR%
echo [INFO] Repo: %GIT_REPO% ^| Branch: %GIT_BRANCH%
echo [WARN] Esto DESCARTA cambios locales (reset --hard + clean).

set "GIT_TERMINAL_PROMPT=0"
set "GIT_ASKPASS=%ASKPASS_FILE%"

git fetch --prune "%REMOTE_URL%" "%GIT_BRANCH%"
if errorlevel 1 goto :error

git reset --hard FETCH_HEAD
if errorlevel 1 goto :error

git clean -fd

rem Submodulos (si existen)
git submodule sync --recursive >nul 2>nul
git submodule update --init --recursive --force >nul 2>nul
git submodule foreach --recursive "git reset --hard & git clean -fd" >nul 2>nul

del /q "%ASKPASS_FILE%" >nul 2>nul
echo [INFO] Listo.
pause
exit /b 0

:error
echo [ERROR] Fallo la actualizacion.
del /q "%ASKPASS_FILE%" >nul 2>nul
pause
exit /b 1

:trim
setlocal EnableDelayedExpansion
set "s=!%~1!"
for /f "tokens=* delims= " %%a in ("!s!") do set "s=%%a"
:trim_tail
if "!s:~-1!"==" " set "s=!s:~0,-1!" & goto trim_tail
endlocal & set "%~1=%s%"
exit /b 0
