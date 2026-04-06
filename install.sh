#!/bin/bash
# Installation script for Book Translation CLI
# Creates venv, installs dependencies, and sets up global alias

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="$HOME/.bashrc"
ALIAS_NAME="translate-book"
VENV_DIR="$SCRIPT_DIR/venv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Installing Book Translation CLI..."
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

# Deactivate
deactivate

# Create wrapper script that activates venv and runs the tool
WRAPPER_SCRIPT="$SCRIPT_DIR/translate-book-wrapper"
cat > "$WRAPPER_SCRIPT" << 'WRAPPER_EOF'
#!/bin/bash
# Wrapper script for translate-book
# Activates venv and runs the Python script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
python3 "$SCRIPT_DIR/translate_book.py" "$@"
WRAPPER_EOF

chmod +x "$WRAPPER_SCRIPT"
echo -e "${GREEN}✓${NC} Wrapper script created"

# Add to PATH via .bashrc if not already there
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

# Create symlink in ~/.local/bin
if [ -L "$INSTALL_DIR/translate-book" ]; then
    rm "$INSTALL_DIR/translate-book"
fi
ln -s "$WRAPPER_SCRIPT" "$INSTALL_DIR/translate-book"
echo -e "${GREEN}✓${NC} Symlink created in $INSTALL_DIR/translate-book"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo "" >> "$BASHRC"
    echo "# Add ~/.local/bin to PATH" >> "$BASHRC"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$BASHRC"
    echo -e "${GREEN}✓${NC} Added ~/.local/bin to PATH in $BASHRC"
fi

# Also add an alias for convenience
if grep -q "alias $ALIAS_NAME=" "$BASHRC" 2>/dev/null; then
    # Remove old alias
    sed -i "/alias $ALIAS_NAME=/d" "$BASHRC"
fi

# Add new alias that points to the wrapper
echo "" >> "$BASHRC"
echo "# Book Translation CLI alias" >> "$BASHRC"
echo "alias $ALIAS_NAME='$INSTALL_DIR/translate-book'" >> "$BASHRC"
echo -e "${GREEN}✓${NC} Alias added to $BASHRC"

echo ""
echo "========================================"
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo -e "${YELLOW}Important:${NC} Run the following to activate:"
echo ""
echo "  ${GREEN}source ~/.bashrc${NC}"
echo ""
echo "Then use from any directory:"
echo ""
echo "  ${GREEN}translate-book book.html${NC}"
echo "  ${GREEN}translate-book book.html --resume${NC}"
echo "  ${GREEN}translate-book book.html --dry-run${NC}"
echo ""
echo "The tool will use the virtual environment automatically."
echo "========================================"
