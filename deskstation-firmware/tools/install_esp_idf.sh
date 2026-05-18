#!/usr/bin/env bash
# One-shot installer for ESP-IDF v5.3 on Linux.
# Idempotent: re-running is safe.
set -euo pipefail

IDF_VERSION="v5.3"
IDF_DIR="${HOME}/esp/esp-idf"
TARGETS="esp32s3"

if [[ "$(uname)" != "Linux" ]]; then
    echo "ERROR: this script is for Linux only (you're on $(uname))."
    exit 1
fi

mkdir -p "${HOME}/esp"

if [[ -d "${IDF_DIR}/.git" ]]; then
    echo "ESP-IDF already cloned at ${IDF_DIR}, fetching ${IDF_VERSION}..."
    cd "${IDF_DIR}"
    git fetch origin
    git checkout "${IDF_VERSION}"
    git submodule update --init --recursive
else
    echo "Cloning ESP-IDF ${IDF_VERSION} into ${IDF_DIR}..."
    git clone --branch "${IDF_VERSION}" --recursive https://github.com/espressif/esp-idf.git "${IDF_DIR}"
fi

echo "Running ESP-IDF installer for targets: ${TARGETS}"
cd "${IDF_DIR}"
./install.sh "${TARGETS}"

echo ""
echo "==============================================================="
echo "ESP-IDF ${IDF_VERSION} installed at ${IDF_DIR}"
echo ""
echo "To activate, run in each new shell:"
echo "    . ${IDF_DIR}/export.sh"
echo ""
echo "Or add to ~/.bashrc:"
echo "    alias get_idf='. ${IDF_DIR}/export.sh'"
echo ""
echo "Verify with: idf.py --version"
echo "==============================================================="
