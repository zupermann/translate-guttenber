#!/bin/bash
# Installation script for Book Translation CLI

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="$HOME/.bashrc"
ALIAS_NAME="translate-book"
ALIAS_CMD="alias $ALIAS_NAME='python3 $SCRIPT_DIR/translate_book.py'"

echo "Installing Book Translation CLI..."
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "ERROR: pip3 is not installed. Please install pip first."
    exit 1
fi

echo "✓ pip3 found"

# Install dependencies
echo ""
echo "Installing dependencies..."
if ! pip3 install -r "$SCRIPT_DIR/requirements.txt" --user 2>/dev/null; then
    echo ""
    echo "ERROR: Failed to install dependencies with --user flag."
    echo "This is common on systems with externally-managed Python environments."
    echo ""
    echo "Recommended solutions:"
    echo "  1. Create a virtual environment:"
    echo "     python3 -m venv venv && source venv/bin/activate"
    echo "     pip install -r requirements.txt"
    echo ""
    echo "  2. Use your system's package manager:"
    echo "     sudo apt install python3-beautifulsoup4 python3-requests python3-tqdm"
    echo ""
    echo "  3. If you understand the risks, use --break-system-packages:"
    echo "     pip3 install -r requirements.txt --break-system-packages"
    echo ""
    exit 1
fi
echo "✓ Dependencies installed"

# Check if alias already exists
echo ""
echo "Checking for existing alias..."
if grep -q "alias $ALIAS_NAME=" "$BASHRC" 2>/dev/null; then
    echo "Alias '$ALIAS_NAME' already exists in $BASHRC"
    echo "Updating alias to current directory..."
    sed -i "/alias $ALIAS_NAME=/c\\$ALIAS_CMD" "$BASHRC"
else
    echo "Adding alias to $BASHRC..."
    echo "" >> "$BASHRC"
    echo "# Book Translation CLI alias" >> "$BASHRC"
    echo "$ALIAS_CMD" >> "$BASHRC"
    echo "✓ Alias added"
fi

echo ""
echo "========================================"
echo "Installation complete!"
echo ""
echo "Open a new terminal or run: source ~/.bashrc"
echo ""
echo "Usage: translate-book <input.html>"
echo ""
echo "Examples:"
echo "  translate-book book.html"
echo "  translate-book book.html --resume"
echo "  translate-book book.html --dry-run"
echo "========================================"
