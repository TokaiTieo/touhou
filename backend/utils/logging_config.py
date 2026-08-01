"""Application logging with bounded local files and privacy-aware defaults."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(data_dir: Path, debug: bool = False) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(handler, "_touhou_handler", False) for handler in root.handlers):
        file_handler = RotatingFileHandler(
            log_dir / "touhou.log",
            maxBytes=1_500_000,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler._touhou_handler = True
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
