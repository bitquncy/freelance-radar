#!/bin/sh
set -eu

if [ "${ENVIRONMENT:-development}" = "production" ]; then
  case "${DATABASE_URL:-}" in
    postgresql*|postgres://*) ;;
    *) echo "Production DATABASE_URL must use PostgreSQL" >&2; exit 64 ;;
  esac
  if [ -z "${REDIS_URL:-}" ]; then
    echo "Production REDIS_URL is required" >&2
    exit 64
  fi
  if [ "${BOT_REPLICAS:-1}" != "1" ]; then
    echo "Production BOT_REPLICAS must be 1 for polling and scheduled jobs" >&2
    exit 64
  fi
fi

python -m alembic upgrade head
python db/init_db.py
exec python main.py
