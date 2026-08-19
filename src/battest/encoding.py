"""Console encoding and byte decoding helpers."""

from __future__ import annotations

import ctypes
import sys

from charset_normalizer import from_bytes

from battest.logging_config import get_logger

LOGGER = get_logger("encoding")


def _named_code_page(code_page: int) -> str | None:
    """Return a Python encoding name for a Windows code page, if usable."""
    if code_page == 65001:
        return "utf-8"
    if code_page <= 0:
        return None
    return f"cp{code_page}"


def console_encoding() -> str:
    """Return the console output code page encoding name."""
    if sys.platform != "win32":
        LOGGER.debug("console encoding utf-8 (non-Windows)")
        return "utf-8"
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        LOGGER.debug("console encoding utf-8 (no windll)")
        return "utf-8"
    kernel = windll.kernel32
    output_cp = int(kernel.GetConsoleOutputCP())
    chosen = _named_code_page(output_cp)
    if chosen is not None:
        LOGGER.debug("console encoding %s (GetConsoleOutputCP=%s)", chosen, output_cp)
        return chosen
    oem = int(kernel.GetOEMCP())
    chosen = _named_code_page(oem)
    if chosen is not None:
        LOGGER.debug("GetConsoleOutputCP is 0; using OEM CP %s (%s)", oem, chosen)
        return chosen
    acp = int(kernel.GetACP())
    chosen = _named_code_page(acp)
    if chosen is not None:
        LOGGER.debug("GetConsoleOutputCP is 0; using ACP %s (%s)", acp, chosen)
        return chosen
    LOGGER.debug("GetConsoleOutputCP is 0; OEM and ACP unavailable, using utf-8")
    return "utf-8"


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
