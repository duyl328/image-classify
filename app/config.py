"""
全局配置常量。所有魔法数字集中在此，不散落在各模块里。
"""
from pathlib import Path

# ── 支持的文件格式 ──────────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    '.jpg', '.jpeg', '.png', '.webp', '.bmp',
    '.tiff', '.tif', '.heic', '.heif',
})
VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v',
})

# ── 扫描过滤 ───────────────────────────────────────────────────────────────────
MIN_FILE_SIZE_KB: int = 50          # 跳过小于此大小的文件（单位 KB）

# ── 缩略图 ─────────────────────────────────────────────────────────────────────
THUMBNAIL_SIZE: tuple[int, int] = (220, 220)    # 主网格缩略图尺寸（px）
THUMBNAIL_CACHE_MB: int = 256                   # QPixmapCache 上限（MB）
GROUP_COVER_SIZE: tuple[int, int] = (56, 56)    # 左栏分组行里的小图尺寸（px）
GROUP_COVER_COUNT: int = 3                      # 左栏每组显示几张代表图

# ── CLIP 模型 ──────────────────────────────────────────────────────────────────
CLIP_MODEL_NAME: str = "ViT-B/32"
CLIP_BATCH_SIZE: int = 64           # 每次前向传播的图片数；OOM 时自动减半
EMBEDDING_DIM: int = 512            # ViT-B/32 输出维度

# 本地权重文件路径（优先使用；若文件不存在则 CLIP 自动走缓存下载）
# Windows 路径在 WSL 下映射为 /mnt/d/...
_PROJECT_ROOT: Path = Path(__file__).parent.parent
CLIP_LOCAL_WEIGHTS: Path = _PROJECT_ROOT / "model" / "clip" / "ViT-B-32.pt"

# ── 降维（PCA）────────────────────────────────────────────────────────────────
# 用 sklearn PCA 替代 UMAP：纯 numpy，无 numba，无 Windows 线程崩溃
PCA_N_COMPONENTS: int = 50          # 降维目标维度
PCA_SKIP_THRESHOLD: int = 52        # 图片数 <= 此值时跳过 PCA

# ── HDBSCAN 聚类 ───────────────────────────────────────────────────────────────
HDBSCAN_MIN_SAMPLES: int = 3

# ── 粒度滑杆 ── 映射到 HDBSCAN min_cluster_size ───────────────────────────────
SLIDER_MIN: int = 5                 # 滑杆最小值（对应 min_cluster_size 最大）
SLIDER_MAX: int = 100               # 滑杆最大值（对应 min_cluster_size 最小）
SLIDER_DEFAULT: int = 30            # 默认值（居中偏粗）
SLIDER_DEBOUNCE_MS: int = 400       # 防抖延迟（ms），避免拖动时频繁重聚类

# ── 近重复检测 ─────────────────────────────────────────────────────────────────
PHASH_THRESHOLD: int = 8            # pHash Hamming 距离阈值（<= 此值视为近重复）

# ── SQLite 缓存 ────────────────────────────────────────────────────────────────
DB_DIR: Path = Path.home() / ".image_classify"
DB_PATH: Path = DB_DIR / "image_cache.db"

# ── 预览导航 ───────────────────────────────────────────────────────────────────
PREVIEW_NAV_DEBOUNCE_MS: int = 150  # 预防快速连按方向键时的抖动

# ── 缩略图加载线程 ─────────────────────────────────────────────────────────────
THUMBNAIL_LOAD_THREADS: int = 4     # QThreadPool 并发数
