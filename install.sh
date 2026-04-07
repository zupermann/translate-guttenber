#!/bin/bash
# Installation script for the book tooling CLIs
# Creates venv, installs dependencies, and sets up global command symlinks

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [[ "$(basename "$SHELL")" == "zsh" ]]; then
    RC_FILE="$HOME/.zshrc"
else
    RC_FILE="$HOME/.bashrc"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Installing book tooling CLIs..."
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: Python 3 is not installed. Please install Python 3 first.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✓${NC} Python 3 found: $PYTHON_VERSION"

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}ERROR: pip3 is not installed. Please install pip first.${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} pip3 found"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓${NC} Virtual environment created at $VENV_DIR"
else
    echo ""
    echo -e "${YELLOW}Virtual environment already exists at $VENV_DIR${NC}"
fi

# Activate virtual environment and install dependencies
echo ""
echo "Installing dependencies in virtual environment..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓${NC} Dependencies installed"
deactivate

chmod +x "$SCRIPT_DIR/translate-book-wrapper"
chmod +x "$SCRIPT_DIR/generate-audiobook-wrapper"
chmod +x "$SCRIPT_DIR/book-pipeline-wrapper"
echo -e "${GREEN}✓${NC} Wrapper scripts are executable"

# Add to PATH via the active shell rc file if not already there
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

for CMD in translate-book generate-audiobook book-pipeline; do
    if [ -L "$INSTALL_DIR/$CMD" ] || [ -f "$INSTALL_DIR/$CMD" ]; then
        rm -f "$INSTALL_DIR/$CMD"
    fi
done

ln -s "$SCRIPT_DIR/translate-book-wrapper" "$INSTALL_DIR/translate-book"
ln -s "$SCRIPT_DIR/generate-audiobook-wrapper" "$INSTALL_DIR/generate-audiobook"
ln -s "$SCRIPT_DIR/book-pipeline-wrapper" "$INSTALL_DIR/book-pipeline"
echo -e "${GREEN}✓${NC} Symlinks created in $INSTALL_DIR"

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo "" >> "$RC_FILE"
    echo "# Add ~/.local/bin to PATH" >> "$RC_FILE"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$RC_FILE"
    echo -e "${GREEN}✓${NC} Added ~/.local/bin to PATH in $RC_FILE"
fi

echo ""
echo "========================================"
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo -e "${YELLOW}Important:${NC} Run the following to activate:"
echo ""
printf "  ${GREEN}source %s${NC}\n" "$RC_FILE"
echo ""
echo "Then use from any directory:"
echo ""
printf "  ${GREEN}translate-book book.html${NC}\n"
printf "  ${GREEN}generate-audiobook translated_book_ro.html${NC}\n"
printf "  ${GREEN}book-pipeline book.html${NC}\n"
echo ""
echo "The tools will use the virtual environment automatically."
echo "========================================"
