# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
python main.py
```

Requires Python 3.11+. The virtual environment is at `.venv/`. No build step needed.

There are no tests or linting configs in this project.

## Architecture

A local PyQt6 desktop tool that scans photo directories, extracts CLIP embeddings, clusters photos by visual similarity, and lets the user batch-process groups (delete/move/review). All destructive operations are staged in memory and only executed on final confirmation.

### Data flow

```
Directories
  → ScanWorker (QThread)
      scanner.py   — os.scandir, yields FileInfo without reading file contents
      embedder.py  — CLIP ViT-B/32 on CUDA; checks SQLite cache first; also
                     computes pHash + Laplacian sharpness in the same PIL open
  → ClusterWorker (QThread)
      clusterer.py — PCA (sklearn, 512→50 dims) then HDBSCAN (sklearn)
                     reduced_matrix cached on Clusterer instance for fast re-cluster
  → MainWindow._on_cluster_complete
      deduplicator.py — pHash Hamming distance, Union-Find grouping
      GroupPanel / GridPanel / ActionPanel — three-panel UI
  → ActionQueue (in-memory)
      action_queue.py — staged delete/move/review; execute() uses send2trash
```

### Key architectural constraints

**Embedder lives in the main thread.** `self._embedder = Embedder(self._cache)` is created in `MainWindow.__init__` and passed to `ScanWorker`. This is intentional: CUDA context cleanup on QThread exit causes `0xC0000409` (Windows stack buffer overrun) if the model is owned by the worker thread.

**PCA instead of UMAP.** `umap-learn` uses numba JIT, which registers Windows thread-local storage. When the QThread exits, Windows TLS cleanup triggers `0xC0000409`. sklearn's PCA is pure numpy — no numba, no crash.

**SQLite is embedding cache only.** One table: `image_cache(cache_key, path, embedding BLOB, phash, sharpness)`. Cache key is `"{abs_path}|{mtime}|{filesize}"` — no file content read. Cluster results, staged actions, and session state are all in-memory only.

**Windows inode bug.** `os.stat().st_ino` is 0 for all files on Windows. The scanner skips inode deduplication when `st_ino == 0` to avoid treating every file after the first as a symlink loop.

### UI state machine

`MainWindow` uses a `QStackedWidget` with three pages:
- `index 0` — Launch page (directory picker)
- `index 1` — Analysis progress page
- `index 2` — Work page (three-panel layout)

`AppState` enum drives transitions: `LAUNCH → ANALYZING → WORKING`.

### Granularity slider

Maps slider value to HDBSCAN `min_cluster_size` with an inverted scale (left=coarse=large min_cluster_size, right=fine=small). On change, `ClusterWorker` re-runs with `reuse_reduced=True`, which skips PCA and only re-runs HDBSCAN on the cached `reduced_matrix` — typically completes in under a second.

### Config

All tunable constants are in `app/config.py`. Notable ones:
- `CLIP_LOCAL_WEIGHTS` — path to local ViT-B-32.pt (avoids network download)
- `PCA_N_COMPONENTS = 50`, `PCA_SKIP_THRESHOLD = 52`
- `SLIDER_DEFAULT = 30` (maps to `min_cluster_size = 75`)
- `DB_PATH = ~/.image_classify/image_cache.db`

### Debug logging

`app/core/debug_log.py` writes structured events to `~/.image_classify/debug.log`. Call `log_debug("event_name", key=value)` anywhere. `install_debug_hooks()` (called in `main()`) also enables `faulthandler` for native crashes and installs `sys.excepthook` / `threading.excepthook`.
