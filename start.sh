#!/bin/bash
# Render deployment startup script
# Installs dependencies and runs the FastAPI server with uvicorn

set -e

echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Initializing database..."
python3 -c "from server import init_database; init_database()"

echo "Starting FastAPI server on 0.0.0.0:${PORT:-8000}"
exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4
