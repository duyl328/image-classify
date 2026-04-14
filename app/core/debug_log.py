from __future__ import annotations

import atexit
import faulthandler
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from app.config import DB_DIR

DEBUG_LOG_PATH: Path = DB_DIR / "debug.log"

_LOCK = threading.Lock()
_FAULTHANDLER_STREAM = None


def _ensure_dir() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)


def reset_debug_log() -> None:
    _ensure_dir()
    DEBUG_LOG_PATH.write_text("", encoding="utf-8")


def log_debug(event: str, **fields: object) -> None:
    _ensure_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    parts = [
        timestamp,
        f"pid={os.getpid()}",
        f"thread={threading.current_thread().name}",
        event,
    ]
    for key, value in fields.items():
        parts.append(f"{key}={value!r}")
    line = " | ".join(parts)

    with _LOCK:
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    print(f"[debug] {line}", flush=True)


def log_current_exception(event: str) -> None:
    _ensure_dir()
    details = traceback.format_exc()
    log_debug(event, exception=details.strip().splitlines()[-1] if details else "unknown")
    with _LOCK:
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(details)
            if not details.endswith("\n"):
                handle.write("\n")


def install_debug_hooks() -> None:
    global _FAULTHANDLER_STREAM

    reset_debug_log()
    _ensure_dir()
    _FAULTHANDLER_STREAM = DEBUG_LOG_PATH.open("a", encoding="utf-8")
    faulthandler.enable(file=_FAULTHANDLER_STREAM, all_threads=True)

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        log_debug("sys.excepthook", exc_type=getattr(exc_type, "__name__", str(exc_type)), exc=str(exc_value))
        traceback.print_exception(exc_type, exc_value, exc_tb, file=_FAULTHANDLER_STREAM)
        _FAULTHANDLER_STREAM.flush()
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _threading_excepthook(args) -> None:
        log_debug(
            "threading.excepthook",
            exc_type=getattr(args.exc_type, "__name__", str(args.exc_type)),
            exc=str(args.exc_value),
            thread=getattr(args.thread, "name", "unknown"),
        )
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=_FAULTHANDLER_STREAM)
        _FAULTHANDLER_STREAM.flush()
        threading.__excepthook__(args)

    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook
    atexit.register(_on_exit)
    log_debug("debug_hooks_installed", log_path=str(DEBUG_LOG_PATH))


def _on_exit() -> None:
    log_debug("process_exit")
    if _FAULTHANDLER_STREAM is not None:
        _FAULTHANDLER_STREAM.flush()
