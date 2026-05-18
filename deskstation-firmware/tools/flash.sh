#!/usr/bin/env bash
# Convenience: build + flash + monitor.
# Usage: bash tools/flash.sh [/dev/ttyACM0]
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"

if ! command -v idf.py >/dev/null 2>&1; then
    echo "ERROR: idf.py not found. Did you source ESP-IDF export.sh?"
    echo "  . ~/esp/esp-idf/export.sh"
    exit 1
fi

idf.py -p "${PORT}" build flash monitor
