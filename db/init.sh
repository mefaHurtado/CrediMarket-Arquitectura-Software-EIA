#!/bin/sh
set -eu
# Se ejecuta una vez al crear el volumen de PostgreSQL. Contraseñas solo por variables.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v pp="$DB_PRODUCTS_PASSWORD" -v pc="$DB_CLIENTS_PASSWORD" \
  -v pl="$DB_LOANS_PASSWORD" -v pi="$DB_INVENTORY_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE products_user LOGIN PASSWORD %L', :'pp') \gexec
SELECT format('CREATE ROLE clients_user LOGIN PASSWORD %L', :'pc') \gexec
SELECT format('CREATE ROLE loans_user LOGIN PASSWORD %L', :'pl') \gexec
SELECT format('CREATE ROLE inventory_user LOGIN PASSWORD %L', :'pi') \gexec
CREATE DATABASE products_db OWNER products_user;
CREATE DATABASE clients_db OWNER clients_user;
CREATE DATABASE loans_db OWNER loans_user;
CREATE DATABASE inventory_db OWNER inventory_user;
SQL
