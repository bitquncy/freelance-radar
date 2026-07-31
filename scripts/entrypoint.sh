#!/bin/sh
set -eu

if [ "${ENVIRONMENT:-development}" = "production" ]; then
  case "${DATABASE_URL:-}" in
    postgresql*|postgres://*) ;;
    *) echo "Production DATABASE_URL must use PostgreSQL" >&2; exit 64 ;;
  esac
fi

mkdir -p "${DATA_DIR:-/app/data}" /app/logs
if [ "${RADAR_V2_ENABLED:-false}" = "true" ]; then
  python -m alembic upgrade head
fi
python db/init_db.py
exec "$@"
