#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "[ERROR] git no está instalado o no está en PATH."
  exit 1
fi

if [ ! -d ".git" ]; then
  echo "[ERROR] Esta carpeta no parece ser un repo git: $SCRIPT_DIR"
  exit 1
fi

CONF_FILE="$SCRIPT_DIR/git.conf"
if [ ! -f "$CONF_FILE" ]; then
  echo "[ERROR] No se encontró git.conf en: $CONF_FILE"
  exit 1
fi

ini_get() {
  local key="$1"
  awk -F'=' -v k="$key" '
    BEGIN { in=0 }
    /^[[:space:]]*\[/ { in=0 }
    /^[[:space:]]*\[GITHUB\][[:space:]]*$/ { in=1; next }
    in==1 && $1 ~ "^[[:space:]]*"k"[[:space:]]*$" {
      val=$2
      sub(/^[[:space:]]+/, "", val)
      sub(/[[:space:]]+$/, "", val)
      print val
      exit
    }
  ' "$CONF_FILE"
}

GIT_USER="$(ini_get user || true)"
GIT_PASS="$(ini_get pass || true)"
GIT_REPO="$(ini_get repo || true)"
GIT_BRANCH="$(ini_get branch || true)"

if [ -z "${GIT_REPO}" ] || [ -z "${GIT_BRANCH}" ]; then
  echo "[ERROR] git.conf incompleto: se requiere repo y branch."
  exit 1
fi

REMOTE_URL="https://github.com/${GIT_REPO}.git"

ASKPASS_FILE="$(mktemp 2>/dev/null || true)"
if [ -z "${ASKPASS_FILE}" ]; then
  ASKPASS_FILE="/tmp/git_askpass_$$.sh"
fi

cat >"$ASKPASS_FILE" <<'EOF'
#!/usr/bin/env sh
case "$1" in
  *Username*|*username*)
    printf "%s\n" "${GIT_CONF_USER:-}"
    ;;
  *Password*|*password*)
    printf "%s\n" "${GIT_CONF_PASS:-}"
    ;;
  *)
    printf "%s\n" "${GIT_CONF_PASS:-}"
    ;;
esac
EOF
chmod +x "$ASKPASS_FILE"

export GIT_CONF_USER="${GIT_USER}"
export GIT_CONF_PASS="${GIT_PASS}"

echo "[INFO] Actualizando repo en: $SCRIPT_DIR"
echo "[INFO] Repo: ${GIT_REPO} | Branch: ${GIT_BRANCH}"
echo "[WARN] Esto DESCARTA cambios locales (reset --hard + clean)."

GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="$ASKPASS_FILE" git fetch --prune "$REMOTE_URL" "$GIT_BRANCH"
git reset --hard FETCH_HEAD
git clean -fd

# Submódulos (si existen)
GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="$ASKPASS_FILE" git submodule sync --recursive || true
GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="$ASKPASS_FILE" git submodule update --init --recursive --force || true
git submodule foreach --recursive 'git reset --hard; git clean -fd' >/dev/null 2>&1 || true

rm -f "$ASKPASS_FILE" || true

echo "[INFO] Listo."

