"""
Logging utility for MEOWBOARD.
"""
import logging
import sys
from pathlib import Path


def setup_logger(name: str = "meowboard", level: int = logging.INFO) -> logging.Logger:
    """Configures and returns a structured logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(threadName)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Optional file handler in ~/.meowboard/meowboard.log
    try:
        log_dir = Path.home() / ".meowboard"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "meowboard.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        # Fallback to console only if directory or file cannot be created
        pass

    logger.propagate = False
    return logger


logger = setup_logger()
