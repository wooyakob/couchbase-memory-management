#!/bin/bash
# Run both backend and frontend dev servers
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "Starting Couchbase Memory Manager..."
echo ""

# Backend
cd "$ROOT/backend"
"$ROOT/backend/venv/bin/uvicorn" main:app --reload --host 0.0.0.0 --port 8010 &
BACKEND_PID=$!
echo "Backend → http://localhost:8010"

# Frontend
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!
echo "Frontend → http://localhost:5183"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
