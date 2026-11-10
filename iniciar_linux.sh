#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if ! command -v docker >/dev/null; then echo 'Instala Docker Engine/Desktop y Compose'; exit 1; fi
secret(){ openssl rand -hex 24; }
if [[ ! -f .env ]]; then
  POSTGRES_ADMIN_PASSWORD="$(secret)";DB_PRODUCTS_PASSWORD="$(secret)";DB_CLIENTS_PASSWORD="$(secret)";DB_LOANS_PASSWORD="$(secret)";DB_INVENTORY_PASSWORD="$(secret)"
  RABBIT_USER="credimarket";RABBIT_PASSWORD="$(secret)";JWT_SECRET="$(secret)";INTERNAL_TOKEN="$(secret)"
  DEMO_ADMIN_PASSWORD="$(secret)";DEMO_CLIENT_PASSWORD="$(secret)";DEMO_RISK_PASSWORD="$(secret)";DEMO_SECOND_PASSWORD="$(secret)"
  printf '%s\n' "POSTGRES_ADMIN_PASSWORD=$POSTGRES_ADMIN_PASSWORD" "DB_PRODUCTS_PASSWORD=$DB_PRODUCTS_PASSWORD" "DB_CLIENTS_PASSWORD=$DB_CLIENTS_PASSWORD" "DB_LOANS_PASSWORD=$DB_LOANS_PASSWORD" "DB_INVENTORY_PASSWORD=$DB_INVENTORY_PASSWORD" "RABBIT_USER=$RABBIT_USER" "RABBIT_PASSWORD=$RABBIT_PASSWORD" "JWT_SECRET=$JWT_SECRET" "INTERNAL_TOKEN=$INTERNAL_TOKEN" "DEMO_ADMIN_PASSWORD=$DEMO_ADMIN_PASSWORD" "DEMO_CLIENT_PASSWORD=$DEMO_CLIENT_PASSWORD" "DEMO_RISK_PASSWORD=$DEMO_RISK_PASSWORD" "DEMO_SECOND_PASSWORD=$DEMO_SECOND_PASSWORD" > .env
  chmod 600 .env
  printf '%s\n' 'CREDIMARKET - CUENTAS LOCALES, NO SUBIR A GIT' 'http://localhost:8080' "admin / $DEMO_ADMIN_PASSWORD" "cliente_demo / $DEMO_CLIENT_PASSWORD" "cliente_riesgo / $DEMO_RISK_PASSWORD" "cliente_dos / $DEMO_SECOND_PASSWORD" "RabbitMQ: credimarket / $RABBIT_PASSWORD" > ACCESOS_LOCALES.txt
  chmod 600 ACCESOS_LOCALES.txt
fi
docker compose up -d --build
docker compose ps
echo 'Abre http://localhost:8080 y consulta ACCESOS_LOCALES.txt'
