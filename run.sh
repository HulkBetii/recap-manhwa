#!/bin/bash

# Base directory is script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Check if .venv exists
if [ -d ".venv" ]; then
    echo "Activating virtual environment (.venv)..."
    source .venv/bin/activate
fi

stop_server_8000() {
    echo "Checking port 8000..."
    PID=$(lsof -t -i :8000)
    if [ -n "$PID" ]; then
        echo "Port 8000 is in use by PID(s): $PID. Killing process..."
        kill -9 $PID
        echo "Port 8000 is now free."
    else
        echo "Port 8000 is clean."
    fi
}

run_diagnostics() {
    echo "========================================="
    echo " Checking PyTorch & GPU status..."
    echo "========================================="
    python3 -c "
import torch
print('PyTorch version :', torch.__version__)
print('CUDA available  :', torch.cuda.is_available())
print('MPS available   :', hasattr(torch.backends, 'mps') and torch.backends.mps.is_available())
if torch.cuda.is_available():
    print('GPU Device Name :', torch.cuda.get_device_name(0))
    print('VRAM Available  :', round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), 'GB')
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    print('GPU Device Name : Apple Silicon (MPS)')
else:
    print('WARNING: PyTorch is NOT utilizing GPU/CUDA/MPS. Running on CPU instead.')
"
    echo "========================================="
}

show_menu() {
    clear
    echo "==================================================="
    echo "  Manhwa Recap Tool - macOS Startup Manager"
    echo "==================================================="
    echo "  1. Start Server (Production Mode)"
    echo "  2. Start Server (Development Mode - Auto reload)"
    echo "  3. Stop Server (Free port 8000)"
    echo "  4. Run PyTorch GPU/CUDA Diagnostics"
    echo "  5. Exit"
    echo "==================================================="
}

while true; do
    show_menu
    read -p "Enter choice (1-5): " CHOICE
    case $CHOICE in
        1)
            stop_server_8000
            echo "Starting server in Production Mode..."
            python3 app.py
            read -p "Press Enter to continue"
            ;;
        2)
            stop_server_8000
            echo "Starting server in Development Mode..."
            uvicorn app:app --host 127.0.0.1 --port 8000 --reload \
                --reload-exclude "downloads/*" \
                --reload-exclude "static/*" \
                --reload-exclude "*.json" \
                --reload-exclude "*.log"
            read -p "Press Enter to continue"
            ;;
        3)
            stop_server_8000
            read -p "Press Enter to continue"
            ;;
        4)
            run_diagnostics
            read -p "Press Enter to continue"
            ;;
        5)
            echo "Goodbye!"
            exit 0
            ;;
        *)
            ;;
    esac
done
