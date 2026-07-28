#!/bin/bash
set -e

echo "=========================================="
echo "  FreelanceRadar v2.1.0"
echo "  Starting up..."
echo "=========================================="
echo ""

# Print environment info (non-sensitive)
echo "System info:"
echo "  Python: $(python --version 2>&1)"
echo "  Playwright: $(python -m playwright --version 2>&1 || echo 'N/A')"
echo "  DB_PATH: ${DB_PATH:-default}"
echo "  Monitor interval: ${MONITOR_INTERVAL_MINUTES:-15} min"
echo ""

# Run database migrations
echo "Running database migrations..."
python db/init_db.py
echo "Database ready."
echo ""

# Create required directories
mkdir -p /app/data /app/logs /app/debug
echo "Directories created."

echo ""
echo "=========================================="
echo "  Starting FreelanceRadar bot..."
echo "=========================================="

# Execute the main command
exec "$@"
