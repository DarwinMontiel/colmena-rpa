#!/usr/bin/env bash
# Despliegue en Linux (Ubuntu/Debian): instala o actualiza una versión de Colmena RPA.
#   sudo ./deploy/linux/install.sh v2.0.0 [instancias]
set -euo pipefail

VERSION="${1:?uso: install.sh <tag-o-rama> [instancias]}"
INSTANCES="${2:-2}"
APP_DIR=/opt/colmena-rpa
ETC_DIR=/etc/colmena-rpa
SVC_USER=colmena
REPO=https://github.com/DarwinMontiel/colmena-rpa.git
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

id "$SVC_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$SVC_USER"
mkdir -p "$ETC_DIR"

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO" "$APP_DIR"
fi
git -C "$APP_DIR" fetch --tags --quiet
git -C "$APP_DIR" checkout --quiet "$VERSION"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet "$APP_DIR"
"$APP_DIR/.venv/bin/playwright" install --with-deps chromium
chown -R "$SVC_USER:$SVC_USER" "$APP_DIR" "$PLAYWRIGHT_BROWSERS_PATH"

for f in worker monitor; do
  [[ -f "$ETC_DIR/$f.env" ]] || cp "$APP_DIR/.env.example" "$ETC_DIR/$f.env"
  grep -q PLAYWRIGHT_BROWSERS_PATH "$ETC_DIR/$f.env" \
    || echo "PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH" >> "$ETC_DIR/$f.env"
done
chmod 640 "$ETC_DIR"/*.env && chgrp "$SVC_USER" "$ETC_DIR"/*.env

# Migraciones antes de reiniciar servicios (compatibles hacia atrás por diseño).
sudo -u "$SVC_USER" env APP_DIR="$APP_DIR" ENV_FILE="$ETC_DIR/worker.env" \
  bash -c 'set -a; source "$ENV_FILE"; cd "$APP_DIR" && .venv/bin/alembic upgrade head'

cp "$APP_DIR"/deploy/linux/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable colmena-monitor
systemctl restart colmena-monitor
# Reinicio escalonado: nunca quedan todas las obreras detenidas a la vez.
for i in $(seq 1 "$INSTANCES"); do
  systemctl enable "colmena-obrera@$i"
  systemctl restart "colmena-obrera@$i"
  sleep 5
done
systemctl --no-pager status colmena-monitor "colmena-obrera@*" | grep -E "●|Active" || true
echo "Desplegada la versión $VERSION con $INSTANCES obreras"
