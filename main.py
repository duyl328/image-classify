"""Application entry point."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from app.core.debug_log import install_debug_hooks, log_debug
from app.ui.main_window import MainWindow


if sys.version_info < (3, 11):
    print("Error: Python 3.11 or newer is required.", file=sys.stderr)
    sys.exit(1)


def _warmup() -> None:
    log_debug("warmup_start")
    print("[startup] 初始化...", flush=True)

    import numpy as np
    from sklearn.cluster import HDBSCAN
    from sklearn.decomposition import PCA

    tiny = np.random.rand(10, 8).astype(np.float32)
    PCA(n_components=4).fit_transform(tiny)
    HDBSCAN(min_cluster_size=2, n_jobs=1, copy=True).fit_predict(tiny[:, :4])

    print("[startup] 就绪", flush=True)
    log_debug("warmup_done")


def main() -> None:
    install_debug_hooks()
    log_debug("main_enter", argv=sys.argv)
    _warmup()

    app = QApplication(sys.argv)
    app.aboutToQuit.connect(lambda: log_debug("qt_about_to_quit"))
    app.setApplicationName("image-classify")
    app.setOrganizationName("image-classify")

    log_debug("main_window_create_start")
    window = MainWindow()
    log_debug("main_window_create_done")
    window.show()
    log_debug("main_window_shown")

    exit_code = app.exec()
    log_debug("qt_event_loop_exited", exit_code=exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
