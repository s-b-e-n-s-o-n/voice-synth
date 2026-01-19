#!/usr/bin/env bash
#
# voice-synth installer
# One-liner: curl -sL https://raw.githubusercontent.com/s-b-e-n-s-o-n/voice-synth/feature/bubbletea-tui/install.sh | bash
#
set -e

# ANSI colors
PURPLE='\033[38;5;99m'
GREEN='\033[38;5;82m'
DIM='\033[38;5;245m'
RESET='\033[0m'

echo ""
echo -e "${PURPLE}╔════════════════════════════════════════╗${RESET}"
echo -e "${PURPLE}║${RESET}                                        ${PURPLE}║${RESET}"
echo -e "${PURPLE}║${RESET}      ${PURPLE}Voice Synthesizer${RESET} Installer       ${PURPLE}║${RESET}"
echo -e "${PURPLE}║${RESET}                                        ${PURPLE}║${RESET}"
echo -e "${PURPLE}╚════════════════════════════════════════╝${RESET}"
echo ""

# Detect OS and architecture
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

# Map architecture names
case "$ARCH" in
    x86_64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) echo -e "${PURPLE}!${RESET} Unsupported architecture: $ARCH"; exit 1 ;;
esac

# Only macOS arm64 binary available for now
if [[ "$OS" != "darwin" || "$ARCH" != "arm64" ]]; then
    echo -e "${PURPLE}!${RESET} Currently only macOS ARM64 is supported."
    echo -e "${DIM}  Build from source: go build -o voice-synth-tui .${RESET}"
    exit 1
fi

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${PURPLE}!${RESET} Python 3 is required but not installed."
    echo -e "${DIM}  Install from https://python.org${RESET}"
    exit 1
fi

INSTALL_DIR="$HOME/voice-synth"
BINARY_URL="https://github.com/s-b-e-n-s-o-n/voice-synth/releases/download/v0.5.0-alpha/voice-synth-tui"
PIPELINE_URL="https://raw.githubusercontent.com/s-b-e-n-s-o-n/voice-synth/feature/bubbletea-tui/pipeline.py"

# Create install directory
mkdir -p "$INSTALL_DIR"

echo -e "${DIM}Downloading binary...${RESET}"
curl -sL "$BINARY_URL" -o "$INSTALL_DIR/voice-synth-tui"
chmod +x "$INSTALL_DIR/voice-synth-tui"

echo -e "${DIM}Downloading pipeline...${RESET}"
curl -sL "$PIPELINE_URL" -o "$INSTALL_DIR/pipeline.py"

echo -e "${GREEN}✓${RESET} Installed to ${DIM}$INSTALL_DIR${RESET}"
echo ""

# Launch
echo -e "${DIM}Launching...${RESET}"
echo ""
cd "$INSTALL_DIR"
exec ./voice-synth-tui
