"""
LUT 加载与应用系统 (LUTLoader)
================================
对标 Shotcut 的 3D LUT 支持。

特性:
- 支持 .cube 格式 (Adobe 标准)
- 支持 .3dl 格式
- 解析为 33x33x33 或 17x17x17 3D LUT 立方体
- 应用: 三线性插值到 RGB 像素
- 强度调节 (0-100%)
- 内置预设: Cinema, Vivid, Vintage, B&W
"""
import os
import re
import logging
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import math

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger("AI短剧编辑器.lut")


@dataclass
class LUT3D:
    """3D LUT 数据"""
    name: str
    size: int                       # 立方体边长 (e.g. 33)
    data: Optional["np.ndarray"]    # shape = (size, size, size, 3)
    title: str = ""
    domain_min: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    domain_max: Tuple[float, float, float] = (1.0, 1.0, 1.0)

    def apply(self, rgb: "np.ndarray", intensity: float = 1.0) -> "np.ndarray":
        """
        应用 LUT 到 RGB 数组 (shape: H, W, 3) in [0, 1]
        使用三线性插值
        """
        if self.data is None or not HAS_NUMPY:
            return rgb
        if intensity <= 0:
            return rgb
        intensity = min(1.0, intensity)
        size = self.size
        # 将 RGB 映射到 [0, size-1]
        idx = rgb * (size - 1)
        idx = np.clip(idx, 0, size - 1)
        r0 = np.floor(idx[..., 0]).astype(int)
        g0 = np.floor(idx[..., 1]).astype(int)
        b0 = np.floor(idx[..., 2]).astype(int)
        r1 = np.clip(r0 + 1, 0, size - 1)
        g1 = np.clip(g0 + 1, 0, size - 1)
        b1 = np.clip(b0 + 1, 0, size - 1)
        dr = idx[..., 0] - r0
        dg = idx[..., 1] - g0
        db = idx[..., 2] - b0
        # 三线性插值
        c000 = self.data[r0, g0, b0]
        c001 = self.data[r0, g0, b1]
        c010 = self.data[r0, g1, b0]
        c011 = self.data[r0, g1, b1]
        c100 = self.data[r1, g0, b0]
        c101 = self.data[r1, g0, b1]
        c110 = self.data[r1, g1, b0]
        c111 = self.data[r1, g1, b1]
        c00 = c000 * (1 - db[..., None]) + c001 * db[..., None]
        c01 = c010 * (1 - db[..., None]) + c011 * db[..., None]
        c10 = c100 * (1 - db[..., None]) + c101 * db[..., None]
        c11 = c110 * (1 - db[..., None]) + c111 * db[..., None]
        c0 = c00 * (1 - dg[..., None]) + c01 * dg[..., None]
        c1 = c10 * (1 - dg[..., None]) + c11 * dg[..., None]
        result = c0 * (1 - dr[..., None]) + c1 * dr[..., None]
        # 强度混合
        if intensity < 1.0:
            result = rgb * (1 - intensity) + result * intensity
        return np.clip(result, 0, 1)


class LUTLoader:
    """
    LUT 加载器 (单例)
    - 解析 .cube / .3dl 文件
    - 内置预设
    - 缓存
    """

    _instance: Optional["LUTLoader"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self._cache: Dict[str, LUT3D] = {}
        self._presets: Dict[str, LUT3D] = {}
        self._user: Dict[str, LUT3D] = {}  # key → LUT（导入的 .cube/.3dl）
        self._init_builtin_presets()

    def _init_builtin_presets(self):
        """初始化内置预设（与调色页 LUT 下拉中文名映射对齐）。"""
        if not HAS_NUMPY:
            return
        cinema = self._build_color_matrix_preset([
            (1.0, 0.95, 0.85),
        ], name="Cinema Warm")
        self._presets["cinema_warm"] = cinema

        vivid = self._build_color_matrix_preset([
            (1.15, 1.0, 0.95),
        ], name="Vivid")
        self._presets["vivid"] = vivid

        vintage = self._build_color_matrix_preset([
            (1.0, 0.9, 0.7),
        ], name="Vintage")
        self._presets["vintage"] = vintage

        bw = self._build_color_matrix_preset([
            (0.299, 0.587, 0.114),
        ], name="B&W", grayscale=True)
        self._presets["bw"] = bw

        teal = self._build_color_matrix_preset([
            (0.85, 1.05, 1.15),
        ], name="Teal Orange")
        self._presets["teal_orange"] = teal

        jp = self._build_color_matrix_preset([
            (1.05, 1.02, 1.08),
        ], name="JP Fresh")
        self._presets["jp_fresh"] = jp

        cyber = self._build_color_matrix_preset([
            (1.2, 0.85, 1.25),
        ], name="Cyberpunk")
        self._presets["cyberpunk"] = cyber

        waste = self._build_color_matrix_preset([
            (1.1, 0.95, 0.75),
        ], name="Wasteland")
        self._presets["wasteland"] = waste

        candy = self._build_color_matrix_preset([
            (1.2, 1.1, 1.15),
        ], name="Candy")
        self._presets["candy"] = candy

        night = self._build_color_matrix_preset([
            (0.75, 0.85, 1.2),
        ], name="Night Blue")
        self._presets["night_blue"] = night

    def _build_color_matrix_preset(self, transforms: List[Tuple[float, float, float]],
                                    name: str = "preset", size: int = 17,
                                    grayscale: bool = False) -> LUT3D:
        """构建简单色彩矩阵预设"""
        if not HAS_NUMPY:
            return LUT3D(name=name, size=size, data=None)
        data = np.zeros((size, size, size, 3), dtype=np.float32)
        scale = size - 1
        for r in range(size):
            for g in range(size):
                for b in range(size):
                    rf, gf, bf = r / scale, g / scale, b / scale
                    if grayscale and transforms:
                        tr, tg, tb = transforms[0]
                        gray = rf * tr + gf * tg + bf * tb
                        data[r, g, b, :] = min(1.0, gray)
                        continue
                    for tr, tg, tb in transforms:
                        nr = rf * tr
                        ng = gf * tg
                        nb = bf * tb
                        data[r, g, b, 0] = min(1.0, nr)
                        data[r, g, b, 1] = min(1.0, ng)
                        data[r, g, b, 2] = min(1.0, nb)
        return LUT3D(name=name, size=size, data=data)

    def load(self, path: str) -> Optional[LUT3D]:
        """
        从文件加载 LUT
        支持 .cube / .3dl 格式
        """
        if not os.path.exists(path):
            return None
        if path in self._cache:
            return self._cache[path]

        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == '.cube':
                lut = self._load_cube(path)
            elif ext == '.3dl':
                lut = self._load_3dl(path)
            else:
                logger.warning(f"不支持的 LUT 格式: {ext}")
                return None
            if lut:
                self._cache[path] = lut
            return lut
        except Exception as e:
            logger.error(f"加载 LUT 失败: {e}")
            return None

    def _load_cube(self, path: str) -> Optional[LUT3D]:
        """解析 .cube 格式 (Adobe 标准)"""
        title = ""
        size = 0
        domain_min = (0.0, 0.0, 0.0)
        domain_max = (1.0, 1.0, 1.0)
        values: List[Tuple[float, float, float]] = []

        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('TITLE'):
                    title = line.split('"')[1] if '"' in line else line.split(' ', 1)[1]
                    continue
                if line.startswith('LUT_3D_SIZE'):
                    size = int(line.split()[-1])
                    continue
                if line.startswith('DOMAIN_MIN'):
                    parts = [float(x) for x in line.split()[1:4]]
                    domain_min = tuple(parts)
                    continue
                if line.startswith('DOMAIN_MAX'):
                    parts = [float(x) for x in line.split()[1:4]]
                    domain_max = tuple(parts)
                    continue
                # RGB 数据
                parts = line.split()
                if len(parts) == 3:
                    try:
                        r, g, b = float(parts[0]), float(parts[1]), float(parts[2])
                        values.append((r, g, b))
                    except ValueError:
                        continue

        if size == 0 or len(values) != size ** 3:
            logger.warning(f"CUBE 文件不完整: size={size}, got {len(values)} values")
            return None

        # 重组为 3D 数组
        if not HAS_NUMPY:
            return LUT3D(name=os.path.basename(path), size=size, data=None,
                         title=title, domain_min=domain_min, domain_max=domain_max)

        data = np.array(values, dtype=np.float32).reshape(size, size, size, 3)
        return LUT3D(
            name=os.path.basename(path),
            size=size,
            data=data,
            title=title or os.path.basename(path),
            domain_min=domain_min,
            domain_max=domain_max,
        )

    def _load_3dl(self, path: str) -> Optional[LUT3D]:
        """解析 .3dl 格式 (简化版)"""
        # .3dl 是 1D LUT 集合, 这里仅做基础支持
        title = os.path.basename(path)
        size = 17  # 默认
        values: List[Tuple[float, float, float]] = []
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 3:
                    try:
                        r, g, b = float(parts[0]), float(parts[1]), float(parts[2])
                        values.append((r, g, b))
                    except ValueError:
                        continue
        if not values:
            return None
        if not HAS_NUMPY:
            return LUT3D(name=title, size=size, data=None)
        # 假设 17x17x17
        size = round(len(values) ** (1/3))
        if size ** 3 != len(values):
            size = 17
        data = np.array(values[:size**3], dtype=np.float32).reshape(size, size, size, 3)
        return LUT3D(name=title, size=size, data=data)

    def register(self, key: str, lut: LUT3D) -> str:
        """注册用户 LUT（key 通常为绝对路径或自定义 id）。"""
        key = str(key or "").strip()
        if not key or lut is None:
            return ""
        self._user[key] = lut
        self._cache[key] = lut
        return key

    def register_file(self, path: str) -> Optional[LUT3D]:
        """加载并注册 .cube/.3dl；成功返回 LUT3D（name=文件名）。"""
        path = os.path.normpath(os.path.abspath(str(path or "")))
        if not path:
            return None
        lut = self.load(path)
        if lut is None:
            return None
        self.register(path, lut)
        return lut

    def get_preset(self, name: str) -> Optional[LUT3D]:
        """解析 LUT：内置预设 → 用户注册 → 文件路径 → 缓存。"""
        if not name or name in ("无", "none", "None"):
            return None
        key = str(name).strip()
        if key in self._presets:
            return self._presets[key]
        if key in self._user:
            return self._user[key]
        if key in self._cache:
            return self._cache[key]
        # 工程里可能存相对/绝对路径
        if os.path.isfile(key):
            return self.load(os.path.normpath(os.path.abspath(key)))
        # Windows 反斜杠 / 相对路径兜底
        try:
            alt = os.path.normpath(key)
            if os.path.isfile(alt):
                return self.load(os.path.abspath(alt))
        except Exception:
            logger.debug("LUT 路径兜底解析失败: %s", key, exc_info=True)
        return None

    def list_presets(self) -> List[str]:
        """列出所有预设（含已注册用户 LUT 的 key）。"""
        return list(self._presets.keys()) + list(self._user.keys())

    def clear_cache(self):
        """清空文件缓存（保留内置与已注册用户 LUT）。"""
        self._cache.clear()
        for k, lut in self._user.items():
            self._cache[k] = lut


# 全局实例
lut_loader = LUTLoader()
