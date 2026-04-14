# 照片整理工具

本地运行的照片批量整理工具。导入一批照片后，工具自动分析图片内容，将照片按视觉相似度分成若干组，方便你按组快速决策——保留、删除、移动或标记待复查。所有危险操作在最终确认前不会执行。

## 功能概览

- 自动按视觉内容分组（CLIP 语义特征 + HDBSCAN 聚类）
- 粒度滑杆：随时调整分组粗细，秒级响应
- 近重复检测：自动找出连拍、压缩版等相似图片
- 批量操作：整组删除 / 移动 / 标记，也支持多选单独处理
- 点击预览：全屏查看，左右键切换，预览时可直接操作
- 暂存机制：所有操作先进队列，最终统一确认后才执行
- 删除走系统回收站，可恢复

---

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（已测试）|
| Python | 3.11 或更高 |
| GPU | 推荐 NVIDIA GPU（CUDA），无 GPU 也可运行但提特征较慢 |
| 显存 | 建议 4GB 以上 |
| 内存 | 建议 8GB 以上（处理 5000 张时约占用 2-3GB）|

---

## 安装步骤

### 1. 克隆项目

```bash
git clone <仓库地址>
cd image-classify
```

### 2. 创建虚拟环境

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. 安装 PyTorch（GPU 版）

先用 `nvidia-smi` 查看驱动支持的最高 CUDA 版本，然后选择对应命令：

```bash
# CUDA 12.8（推荐，支持 RTX 40/50 系）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# CUDA 12.1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# CUDA 11.8
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# 无 GPU（纯 CPU，提特征较慢）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

验证 GPU 是否可用：

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 预期输出：True  NVIDIA GeForce ...
```

### 4. 安装其他依赖

```bash
pip install -r requirements.txt
pip install git+https://github.com/openai/CLIP.git
```

### 5. 下载 CLIP 模型权重

CLIP 模型权重文件约 338MB，需手动下载后放到指定位置。

**下载地址：**

```
https://openaipublic.azureedge.net/clip/models/40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt
```

**放置位置：**

```
image-classify/
└── model/
    └── clip/
        └── ViT-B-32.pt     ← 放这里
```

```bash
# 手动创建目录
mkdir -p model/clip
# 然后将下载的 ViT-B-32.pt 移动到 model/clip/ 目录下
```

> 如果不放本地，程序启动时会尝试从 OpenAI 服务器自动下载，但国内网络可能较慢或失败。

---

## 运行

```bash
python main.py
```

首次启动会有约 2-3 秒的初始化，之后窗口出现即可使用。

---

## 使用流程

### 第一步：选择目录

启动后在首页添加一个或多个照片目录，可配置：

- **递归子目录**：是否扫描子文件夹（默认开启）
- **包含视频**：是否同时处理视频文件
- **跳过小文件**：默认跳过小于 50KB 的文件

点击「开始分析」。

### 第二步：等待分析

分析分三个阶段，进度实时显示：

1. **扫描文件** — 快速，通常几秒内完成
2. **提取特征** — 用 CLIP 模型分析每张图片，GPU 下约 1-3 分钟（5000 张）
3. **自动分组** — PCA 降维 + HDBSCAN 聚类，通常 10-30 秒

> 第二次分析同一批照片时，已提取的特征会从缓存读取，速度大幅提升。

### 第三步：按组处理

分析完成后进入三栏工作区：

- **左栏**：分组列表，点击切换当前组
- **中栏**：当前组的缩略图，点击可全屏预览
- **右栏**：操作按钮

**调整分组粒度：** 顶部滑杆向左（粗）→ 组更少；向右（细）→ 组更多。松手后自动重新分组。

**批量操作：**
- 整组操作：直接点右栏按钮，作用于当前组全部图片
- 多选操作：Ctrl + 点击 或框选，再点右栏按钮

**近重复处理：** 左栏顶部会显示「近重复」组，点进去可逐组处理，自动推荐保留清晰度最高的一张。

### 第四步：确认执行

底部状态栏实时显示待执行操作数量。点击「执行所有操作」后：

1. 弹出确认弹窗，展示操作详情
2. 有删除操作时需勾选确认复选框
3. 点击「确认执行」后才真正操作文件

> 删除操作会将文件移入系统回收站，不是永久删除，可以从回收站恢复。

---

## 缓存说明

提取的图片特征会缓存到本地 SQLite 数据库：

```
~/.image_classify/image_cache.db
```

缓存以 `文件路径 + 修改时间 + 文件大小` 为 key。只要文件没有变动，下次分析同一批照片时会直接跳过提特征步骤。

如需清除缓存，直接删除该文件即可。

---

## 支持的文件格式

| 类型 | 格式 |
|---|---|
| 图片 | JPG、JPEG、PNG、WebP、BMP、TIFF、HEIC、HEIF |
| 视频（可选）| MP4、MOV、AVI、MKV、WMV、FLV、M4V |

---

## 常见问题

**Q：提特征很慢，一张要好几秒？**

检查 GPU 是否正确识别：
```bash
python -c "import torch; print(torch.cuda.is_available())"
```
如果输出 `False`，说明安装的是 CPU 版 PyTorch，需要按上面步骤重装 GPU 版。

**Q：HEIC 格式图片无法识别？**

确认已安装 `pillow-heif`：
```bash
pip install pillow-heif
```

**Q：想清除所有缓存重新分析？**

删除 `~/.image_classify/image_cache.db` 文件即可。

**Q：调试日志在哪里？**

```
~/.image_classify/debug.log
```

程序崩溃时可查看此文件获取详细错误信息。

---

## 项目结构（简要）

```
image-classify/
├── main.py                  # 入口
├── requirements.txt
├── model/clip/ViT-B-32.pt   # 模型权重（需手动下载）
└── app/
    ├── config.py            # 所有可调参数
    ├── core/                # 业务逻辑（扫描、提特征、聚类、操作队列）
    ├── workers/             # QThread 封装
    └── ui/                  # 界面（主窗口、三个面板、弹窗、组件）
```
