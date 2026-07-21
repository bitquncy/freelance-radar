#!/bin/bash
set -e

echo "FreelanceRadar starting..."

# Run database migrations
echo "Running database migrations..."
python db/init_db.py

# Execute the main command
exec "$@"
