# Book Translation CLI

A Python CLI tool that translates Project Gutenberg books from English to Romanian using a local Ollama TranslateGemma model.

## Features

- Translates HTML while preserving complete structure
- Chunk-based processing with checkpointing for resumable translations
- Automatic Gutenberg boilerplate detection and skipping
- Inline tag preservation (em, strong, a, etc.) using delimiter markers
- Progress bar with optional debug output
- Telegram notifications on completion/interruption/error

## Installation

Run the install script to set up the alias:

```bash
./install.sh
```

This will:
- Check dependencies
- Create a `translate-book` alias in your `.bashrc`

After running the script, open a new terminal or run `source ~/.bashrc` to use the alias.

## Requirements

- Python 3.x
- Ollama running locally with TranslateGemma model
- Dependencies: `pip install -r requirements.txt`

## Usage

After installation, use the `translate-book` alias:

```bash
# Basic translation
translate-book pg1342.html

# With custom output
translate-book pg1342.html -o pride_prejudice_ro.html

# Resume interrupted translation
translate-book pg1342.html --resume

# Dry run to estimate chunks and time
translate-book pg1342.html --dry-run

# Enable debug output
translate-book pg1342.html --debug

# Use different model
translate-book pg1342.html --model translategemma:12b
```

## Command Options

| Option | Description |
|--------|-------------|
| `input_file` | Path to source HTML file |
| `-o, --output` | Output HTML file path (default: `{input}_ro.html`) |
| `-m, --model` | Ollama model name (default: `translategemma:27b`) |
| `--ollama-url` | Ollama base URL (default: `http://localhost:11434`) |
| `--temperature` | Temperature for translation (default: 0.3) |
| `--num-ctx` | Context window size (default: 8192) |
| `--checkpoint` | Path to checkpoint JSON file |
| `--resume` | Resume from existing checkpoint |
| `--debug` | Enable debug logging to stderr |
| `--dry-run` | Parse and count chunks without translating |
| `--skip-boilerplate` | Skip Gutenberg header/footer (default: on) |
| `--force` | Overwrite output file without prompting |

## How It Works

1. Parses HTML and extracts translatable text nodes
2. Groups text into chunks (paragraphs, headings, list items, etc.)
3. Sends each chunk to Ollama for translation
4. Preserves inline formatting using `｜｜｜` delimiters
5. Reconstructs HTML with translated text
6. Saves checkpoint after each chunk for resumability

## Post-Processing to EPUB

```bash
pandoc translated_book.html -o translated_book.epub --metadata title="Book Title"
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run translation
python3 translate_book.py book.html
```

## License

MIT
