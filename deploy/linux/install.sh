#!/usr/bin/env bash
# Despliegue en Linux (Ubuntu/Debian): instala o actualiza una versión del orquestador.
#   sudo ./deploy/linux/install.sh v1.0.0
set -euo pipefail

VERSION="${1:?uso: install.sh <tag-o-rama>}"
APP_DIR=/opt/rpa-orchestrator
REPO=https://github.com/DarwinMontiel/rpa-orchestrator.git

id rpa &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin rpa
mkdir -p /etc/rpa-orchestrator

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO" "$APP_DIR"
fi
git -C "$APP_DIR" fetch --tags --quiet
git -C "$APP_DIR" checkout --quiet "$VERSION"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet "$APP_DIR"
PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright "$APP_DIR/.venv/bin/playwright" install --with-deps chromium
chown -R rpa:rpa "$APP_DIR" /opt/ms-playwright

for f in worker monitor; do
  [[ -f /etc/rpa-orchestrator/$f.env ]] || cp "$APP_DIR/.env.example" "/etc/rpa-orchestrator/$f.env"
  grep -q PLAYWRIGHT_BROWSERS_PATH "/etc/rpa-orchestrator/$f.env" \
    || echo "PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright" >> "/etc/rpa-orchestrator/$f.env"
done
chmod 640 /etc/rpa-orchestrator/*.env && chgrp rpa /etc/rpa-orchestrator/*.env

# Migraciones antes de reiniciar servicios (compatibles hacia atrás por diseño).
sudo -u rpa bash -c "set -a; source /etc/rpa-orchestrator/worker.env; cd $APP_DIR && .venv/bin/alembic upgrade head"

cp "$APP_DIR"/deploy/linux/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now rpa-monitor
systemctl restart rpa-monitor
# Reinicio escalonado: nunca quedan todos los workers detenidos a la vez.
for i in 1 2; do
  systemctl enable "rpa-worker@$i"
  systemctl restart "rpa-worker@$i"
  sleep 5
done
systemctl --no-pager status rpa-monitor "rpa-worker@*" | grep -E "●|Active"
echo "Desplegada la versión $VERSION"
