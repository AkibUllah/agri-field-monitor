#!/usr/bin/env bash
# Codespaces start hook: bring up web + scheduler + PostgreSQL, migrate and seed demo data.
set -euo pipefail
cd "$(dirname "$0")/.."

# Requests arrive through the Codespaces HTTPS proxy under a *.app.github.dev host.
if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  HOST="${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
  export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,web,${HOST}"
  export DJANGO_CSRF_TRUSTED_ORIGINS="https://${HOST}"
fi

docker compose up -d --build

echo "waiting for the API on :8000 ..."
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/health/ >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# seed_demo is idempotent (update_or_create), so it is safe on every start.
docker compose exec -T web python manage.py seed_demo
docker compose exec -T web python manage.py awd_check || true

cat <<'MSG'

Agri Field Monitor is up.
  GraphiQL:   forwarded port 8000, path /graphql/   (set header Authorization: Bearer <token>)
  Token:      POST /api/v1/auth/token/ with {"username":"agent","password":"agent1234"}
  Admin:      forwarded port 8000, path /admin/     (agent / agent1234)
MSG
