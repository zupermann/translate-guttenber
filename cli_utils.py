"""Shared helpers for CLI entry points."""

import argparse
import os
import subprocess


def notify_telegram(message: str) -> None:
    """Send a Telegram notification using the system alias."""
    try:
        subprocess.run(
            [os.path.expanduser("~/.local/bin/telegram-notify"), message],
            shell=False,
            check=False,
            capture_output=True,
        )
    except Exception:
        # Notification failures should never block the main workflow.
        pass


def positive_int(value: str) -> int:
    """Argparse helper for positive integers."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
