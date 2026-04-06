"""Progress bar and debug logging."""

import sys
import textwrap

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


class Display:
    """Handles progress display and debug output."""

    def __init__(self, total_chunks: int, debug: bool = False):
        """
        Initialize display.

        Args:
            total_chunks: Total number of chunks to process
            debug: Whether to show debug output
        """
        self.total = total_chunks
        self.debug = debug
        self.completed = 0
        self.total_tokens = 0
        self.total_seconds = 0.0
        self._pbar = None

        if TQDM_AVAILABLE:
            self._pbar = tqdm(
                total=total_chunks,
                unit='chunk',
                file=sys.stderr,
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
            )

    def update(self, chunk_index: int, element_type: str, source_text: str,
               translated_text: str, duration: float, tokens: int = 0) -> None:
        """
        Update progress.

        Args:
            chunk_index: Index of the completed chunk
            element_type: Type of element (p, h1, etc.)
            source_text: Original source text
            translated_text: Translated text
            duration: Time taken for this chunk
            tokens: Number of tokens processed
        """
        self.completed += 1
        self.total_seconds += duration
        self.total_tokens += tokens

        # Print debug output before updating bar
        if self.debug:
            debug_block = self._format_debug_block(
                chunk_index, element_type, source_text,
                translated_text, tokens, duration
            )
            if TQDM_AVAILABLE and self._pbar:
                from tqdm import tqdm as tqdm_class
                tqdm_class.write(debug_block, file=sys.stderr)
            else:
                print(debug_block, file=sys.stderr)

        # Update progress bar
        if TQDM_AVAILABLE and self._pbar:
            self._pbar.update(1)
        else:
            percent = (self.completed / self.total) * 100
            print(f"Progress: {self.completed}/{self.total} ({percent:.1f}%)",
                  file=sys.stderr, end='\r')

    def update_cached(self, chunk_index: int) -> None:
        """Update for a cached chunk (loaded from checkpoint)."""
        self.completed += 1

        if TQDM_AVAILABLE and self._pbar:
            self._pbar.update(1)
        else:
            percent = (self.completed / self.total) * 100
            print(f"Progress: {self.completed}/{self.total} ({percent:.1f}%) [cached]",
                  file=sys.stderr, end='\r')

    def _format_debug_block(self, chunk_index: int, element_type: str,
                            source_text: str, translated_text: str,
                            tokens: int, duration: float) -> str:
        """
        Format debug output block.

        Returns:
            Formatted side-by-side string with separator, EN/RO content
        """
        lines = []

        # Separator line with metadata
        separator = (
            f"{'━' * 60} "
            f"[chunk {chunk_index + 1}/{self.total}] "
            f"[{element_type}] "
            f"[{tokens} tokens] "
            f"[{duration:.1f}s]"
        )
        lines.append(separator)

        # EN section
        en_lines = self._wrap_with_prefix("EN │ ", source_text, width=80)
        lines.extend(en_lines)

        # Empty separator between EN and RO
        lines.append("")

        # RO section
        ro_lines = self._wrap_with_prefix("RO │ ", translated_text, width=80)
        lines.extend(ro_lines)

        # Empty line after chunk
        lines.append("")

        return '\n'.join(lines)

    def _wrap_with_prefix(self, prefix: str, text: str, width: int = 80) -> list:
        """
        Wrap text and prepend prefix to each line.

        Args:
            prefix: Prefix to add to each line
            text: Text to wrap
            width: Maximum line width

        Returns:
            List of wrapped lines with prefix
        """
        # Subtract prefix length from width
        wrap_width = width - len(prefix)

        # Wrap text
        wrapped = textwrap.fill(
            text,
            width=wrap_width,
            replace_whitespace=False,
            drop_whitespace=True
        )

        # Add prefix to each line
        lines = wrapped.split('\n')
        return [f"{prefix}{line}" for line in lines]

    def close(self) -> None:
        """Close the progress bar and print final stats."""
        if TQDM_AVAILABLE and self._pbar:
            self._pbar.close()
        else:
            print(file=sys.stderr)  # Newline after progress

        # Print final summary
        if self.completed > 0:
            avg_time = self.total_seconds / self.completed
            rate = self.total_tokens / self.total_seconds if self.total_seconds > 0 else 0

            print(f"\nCompleted {self.completed}/{self.total} chunks", file=sys.stderr)
            print(f"Total time: {self.total_seconds:.1f}s", file=sys.stderr)
            print(f"Average time per chunk: {avg_time:.2f}s", file=sys.stderr)
            if self.total_tokens > 0:
                print(f"Token rate: {rate:.1f} tok/s", file=sys.stderr)
