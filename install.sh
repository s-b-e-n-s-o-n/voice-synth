#!/usr/bin/env bash
#
# voice-synth installer
# One-liner: curl -sL https://raw.githubusercontent.com/s-b-e-n-s-o-n/voice-synth/main/install.sh | bash
#
set -e

# ANSI colors (no dependencies needed)
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

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${PURPLE}!${RESET} Python 3 is required but not installed."
    echo -e "${DIM}  Install from https://python.org or via Homebrew: brew install python${RESET}"
    exit 1
fi

# Download and extract
INSTALL_DIR="$HOME/voice-synth"

echo -e "${DIM}Downloading...${RESET}"
cd ~
rm -rf voice-synth-feature-textual-tui 2>/dev/null || true
curl -sL https://github.com/s-b-e-n-s-o-n/voice-synth/archive/feature/textual-tui.tar.gz | tar xz
rm -rf "$INSTALL_DIR" 2>/dev/null || true
mv voice-synth-feature-textual-tui "$INSTALL_DIR"

echo -e "${GREEN}✓${RESET} Installed to ${DIM}$INSTALL_DIR${RESET}"
echo ""

# Make executable
chmod +x "$INSTALL_DIR/voice-synth"

# Launch
echo -e "${DIM}Launching...${RESET}"
echo ""
cd "$INSTALL_DIR"
python3 ./voice-synth
