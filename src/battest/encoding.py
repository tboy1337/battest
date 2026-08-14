"""Console encoding and byte decoding helpers."""

from __future__ import annotations

import ctypes
import sys

from charset_normalizer import from_bytes

from battest.logging_config import get_logger

LOGGER = get_logger("encoding")


def console_encoding() -> str:
    """Return the console output code page encoding name."""
    if sys.platform != "win32":
        return "utf-8"
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return "utf-8"
    code_page = int(windll.kernel32.GetConsoleOutputCP())
    if code_page in {0, 65001}:
        return "utf-8"
    return f"cp{code_page}"


def decode_output(data: bytes, encoding: str) -> str:
    """Decode process output, falling back to charset-normalizer."""
    if not data:
        return ""
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        LOGGER.info("decode failed with %s; trying charset-normalizer", encoding)
        detected = from_bytes(data).best()
        if detected is None:
            return data.decode(encoding, errors="replace")
        return str(detected)
