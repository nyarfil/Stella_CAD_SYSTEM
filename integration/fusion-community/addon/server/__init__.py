"""Fusion360MCP Server Package — v2 (CustomEvent bridge architecture)"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_PATH = os.path.join(os.path.expanduser("~"), "fusion360mcp.log")

_logger = logging.getLogger("fusion360mcp")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

# Fusion reloads add-in modules in the same interpreter.  A handler from an
# earlier revision can therefore survive stop/run. Remove only handlers owned
# by this logger: old stdout handlers corrupt the official MCP script response,
# and duplicate handlers to this file multiply every log record.
for _handler in tuple(_logger.handlers):
    is_stdout_handler = isinstance(_handler, logging.StreamHandler) and not isinstance(
        _handler, logging.FileHandler
    )
    is_our_file_handler = isinstance(_handler, logging.FileHandler) and (
        os.path.abspath(_handler.baseFilename) == os.path.abspath(LOG_PATH)
    )
    if is_stdout_handler or is_our_file_handler:
        _logger.removeHandler(_handler)
        _handler.close()

# File handler — rotates at 2 MB, keeps 3 backups
_fh = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"))
_logger.addHandler(_fh)


def get_logger(name: str = None) -> logging.Logger:
    """Return a child logger.  ``get_logger("bridge")`` → ``fusion360mcp.bridge``."""
    if name:
        return _logger.getChild(name)
    return _logger
