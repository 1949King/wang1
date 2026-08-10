"""
插件商店模块 (PluginStore)
==========================
支持插件和 Skill 商品的浏览、安装、管理
"""

import os
import json
import shutil
import zipfile
import time
import threading
import requests
from typing import Optional, Dict, List, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ItemType(Enum):
    """商品类型"""
    PLUGIN = "plugin"
    SKILL = "skill"


class ItemCategory(Enum):
    """商品分类"""
    VIDEO_PROCESSING = "视频处理"
    AI_TOOLS = "AI工具"
    EXPORT_TOOLS = "导出工具"
    OPERATION_TOOLS = "运营工具"
    SUBTITLE_TOOLS = "字幕工具"
    AUDIO_TOOLS = "音频工具"
    EFFECT_TOOLS = "特效工具"
    OTHER = "其他"


@dataclass
class StoreItem:
    """商店商品"""
    id: str
    name: str
    type: ItemType
    category: ItemCategory
    version: str
    author: str
    description: str
    icon: str = ""
    price: float = 0.0
    is_free: bool = True
    rating: float = 0.0
    downloads: int = 0
    tags: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    changelog: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    min_version: str = "1.0.0"
    created_at: str = ""
    updated_at: str = ""
    download_url: str = ""
    local_path: str = ""
    is_installed: bool = False
    is_official: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "category": self.category.value,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "icon": self.icon,
            "price": self.price,
            "is_free": self.is_free,
            "rating": self.rating,
            "downloads": self.downloads,
            "tags": self.tags,
            "min_version": self.min_version,
            "download_url": self.download_url,
            "is_installed": self.is_installed,
            "is_official": self.is_official
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoreItem':
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=ItemType(data.get("type", "plugin")),
            category=ItemCategory(data.get("category", "其他")),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            icon=data.get("icon", ""),
            price=data.get("price", 0.0),
            is_free=data.get("is_free", True),
            rating=data.get("rating", 0.0),
            downloads=data.get("downloads", 0),
            tags=data.get("tags", []),
            min_version=data.get("min_version", "1.0.0"),
            download_url=data.get("download_url", ""),
            is_installed=data.get("is_installed", False),
            is_official=data.get("is_official", False)
        )


class PluginStore:
    """插件商店"""
    
    _instance: Optional['PluginStore'] = None
    _lock = threading.Lock()
    
    STORE_URL = "https://store.aishortdrama.com/api"
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._items: Dict[str, StoreItem] = {}
        self._installed_items: Dict[str, StoreItem] = {}
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self._data_dir = os.path.join(base_dir, "data", "store")
        self._plugins_dir = os.path.join(base_dir, "plugins", "external")
        self._skills_dir = os.path.join(base_dir, "skills", "custom")
        
        os.makedirs(self._data_dir, exist_ok=True)
        os.makedirs(self._plugins_dir, exist_ok=True)
        os.makedirs(self._skills_dir, exist_ok=True)
        
        self._load_local_items()
        self._load_installed_items()
        
        # 初始化官方商品
        init_official_items(self)
    
    def _load_local_items(self):
        """加载本地商品数据"""
        items_file = os.path.join(self._data_dir, "items.json")
        if os.path.exists(items_file):
            try:
                with open(items_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item_data in data.get("items", []):
                    item = StoreItem.from_dict(item_data)
                    self._items[item.id] = item
            except Exception as e:
                logger.warning(f"加载商品数据失败: {e}")
    
    def _save_local_items(self):
        """保存本地商品数据"""
        items_file = os.path.join(self._data_dir, "items.json")
        data = {
            "items": [item.to_dict() for item in self._items.values()],
            "updated_at": datetime.now().isoformat()
        }
        with open(items_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load_installed_items(self):
        """加载已安装商品"""
        installed_file = os.path.join(self._data_dir, "installed.json")
        if os.path.exists(installed_file):
            try:
                with open(installed_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for item_data in data.get("items", []):
                    item = StoreItem.from_dict(item_data)
                    item.is_installed = True
                    self._installed_items[item.id] = item
                    if item.id in self._items:
                        self._items[item.id].is_installed = True
            except Exception as e:
                logger.warning(f"加载已安装商品失败: {e}")
    
    def _save_installed_items(self):
        """保存已安装商品"""
        installed_file = os.path.join(self._data_dir, "installed.json")
        data = {
            "items": [item.to_dict() for item in self._installed_items.values()],
            "updated_at": datetime.now().isoformat()
        }
        with open(installed_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def fetch_store_items(self, force: bool = False) -> List[StoreItem]:
        """从商店获取商品列表"""
        if not force and self._items:
            return list(self._items.values())
        
        try:
            response = requests.get(
                f"{self.STORE_URL}/items",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                for item_data in data.get("items", []):
                    item = StoreItem.from_dict(item_data)
                    if item.id in self._installed_items:
                        item.is_installed = True
                    self._items[item.id] = item
                self._save_local_items()
        except Exception as e:
            logger.warning(f"获取商店商品失败: {e}")
        
        return list(self._items.values())
    
    def get_items(
        self,
        item_type: Optional[ItemType] = None,
        category: Optional[ItemCategory] = None,
        search: str = "",
        installed_only: bool = False
    ) -> List[StoreItem]:
        """获取商品列表"""
        items = list(self._items.values())
        
        if installed_only:
            items = [item for item in items if item.is_installed]
        
        if item_type:
            items = [item for item in items if item.type == item_type]
        
        if category:
            items = [item for item in items if item.category == category]
        
        if search:
            search_lower = search.lower()
            items = [
                item for item in items
                if search_lower in item.name.lower()
                or search_lower in item.description.lower()
                or any(search_lower in tag.lower() for tag in item.tags)
            ]
        
        return items
    
    def get_item(self, item_id: str) -> Optional[StoreItem]:
        """获取单个商品"""
        return self._items.get(item_id)
    
    def install_item(
        self,
        item_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[bool, str]:
        """安装商品"""
        item = self._items.get(item_id)
        if not item:
            return False, "商品不存在"
        
        if item.is_installed:
            return False, "已安装"
        
        try:
            if progress_callback:
                progress_callback(10, "准备下载...")
            
            if item.download_url:
                response = requests.get(item.download_url, stream=True, timeout=300)
                
                if response.status_code != 200:
                    return False, "下载失败"
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                temp_file = os.path.join(self._data_dir, f"{item_id}.zip")
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size and progress_callback:
                            progress = int(10 + (downloaded / total_size) * 60)
                            progress_callback(progress, "下载中...")
                
                if progress_callback:
                    progress_callback(70, "解压安装...")
                
                target_dir = self._plugins_dir if item.type == ItemType.PLUGIN else self._skills_dir
                install_dir = os.path.join(target_dir, item.id)
                
                with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                    zip_ref.extractall(install_dir)
                
                os.remove(temp_file)
            else:
                # 修复：此前没有 download_url 时，只建一个空目录 + 写个
                # metadata.json 占位文件，就标记 is_installed=True 并返回
                # "安装成功"——目录里根本没有任何真实插件/技能代码，用户装完
                # 打开会发现什么都用不了。官方内置商品走 init_official_items
                # 直接解析到 app/plugins 下的真实路径，不会经过这条分支；
                # 会走到这里的都是没有真实安装包的商品，如实报告失败。
                if progress_callback:
                    progress_callback(0, "安装失败：无可下载的安装包")
                return False, "该商品暂无可下载的安装包，无法完成安装"
            
            if progress_callback:
                progress_callback(90, "完成安装...")
            
            item.is_installed = True
            item.local_path = install_dir
            self._installed_items[item_id] = item
            self._save_installed_items()
            
            if progress_callback:
                progress_callback(100, "安装完成")
            
            return True, "安装成功"
            
        except Exception as e:
            logger.error(f"安装商品失败: {e}")
            return False, f"安装失败: {str(e)}"
    
    def uninstall_item(self, item_id: str) -> Tuple[bool, str]:
        """卸载商品"""
        if item_id not in self._installed_items:
            return False, "未安装"
        
        item = self._installed_items[item_id]
        
        try:
            if item.local_path and os.path.exists(item.local_path):
                shutil.rmtree(item.local_path)
            
            del self._installed_items[item_id]
            
            if item_id in self._items:
                self._items[item_id].is_installed = False
            
            self._save_installed_items()
            
            return True, "卸载成功"
            
        except Exception as e:
            logger.error(f"卸载商品失败: {e}")
            return False, f"卸载失败: {str(e)}"
    
    def import_item_from_file(self, file_path: str, item_type: ItemType) -> Tuple[bool, str]:
        """从文件导入商品"""
        try:
            if not os.path.exists(file_path):
                return False, "文件不存在"
            
            target_dir = self._plugins_dir if item_type == ItemType.PLUGIN else self._skills_dir
            
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    temp_dir = os.path.join(self._data_dir, "temp_import")
                    os.makedirs(temp_dir, exist_ok=True)
                    zip_ref.extractall(temp_dir)
                    
                    extracted = os.listdir(temp_dir)
                    if len(extracted) == 1:
                        extracted_dir = os.path.join(temp_dir, extracted[0])
                    else:
                        extracted_dir = temp_dir
                    
                    metadata_file = os.path.join(extracted_dir, "metadata.json")
                    if os.path.exists(metadata_file):
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        
                        item_id = metadata.get("id", f"imported_{int(time.time())}")
                        target_path = os.path.join(target_dir, item_id)
                        
                        if os.path.exists(target_path):
                            shutil.rmtree(target_path)
                        
                        shutil.move(extracted_dir, target_path)
                        
                        item = StoreItem(
                            id=item_id,
                            name=metadata.get("name", "导入商品"),
                            type=item_type,
                            category=ItemCategory.OTHER,
                            version=metadata.get("version", "1.0.0"),
                            author=metadata.get("author", "本地导入"),
                            description=metadata.get("description", ""),
                            local_path=target_path,
                            is_installed=True
                        )
                        
                        self._items[item_id] = item
                        self._installed_items[item_id] = item
                        self._save_local_items()
                        self._save_installed_items()
                        
                        return True, f"导入成功: {item.name}"
                    else:
                        shutil.rmtree(temp_dir)
                        return False, "缺少 metadata.json 文件"
            else:
                return False, "不支持的文件格式"
                
        except Exception as e:
            logger.error(f"导入商品失败: {e}")
            return False, f"导入失败: {str(e)}"
    
    def get_categories(self) -> List[ItemCategory]:
        """获取所有分类"""
        return list(ItemCategory)
    
    def rate_item(self, item_id: str, rating: float, comment: str = "") -> bool:
        """评价商品"""
        if item_id not in self._items:
            return False
        
        ratings_file = os.path.join(self._data_dir, "ratings.json")
        ratings = {}
        
        if os.path.exists(ratings_file):
            with open(ratings_file, 'r', encoding='utf-8') as f:
                ratings = json.load(f)
        
        if item_id not in ratings:
            ratings[item_id] = []
        
        ratings[item_id].append({
            "rating": rating,
            "comment": comment,
            "timestamp": datetime.now().isoformat()
        })
        
        with open(ratings_file, 'w', encoding='utf-8') as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)
        
        return True


# >>> FROZEN:plugin-store-catalog:official BEGIN
# 历史上架但仓库中不存在的虚构条目（清理用）
FAKE_OFFICIAL_IDS = {
    "auto-clip",
    "subtitle-gen",
    "drama-remix",
    "matrix-publish",
    # plugins_module.STORE_PLUGINS 旧硬编码名对应的猜测 id
    "batch-export-pro",
    "ai-tts",
    "smart-watermark",
    "dynamic-subtitle",
    "bgm-match",
    "video-enhance",
    "data-dashboard-pro",
    "ai-script",
    "green-screen",
    "subtitle-proof",
    "audio-denoise",
    "keyframe-anim",
}

# 仅收录 app/plugins 下真实存在、可被 PluginManager 加载的插件
# local_path 相对项目根；is_installed=True 表示已随安装包内置
OFFICIAL_ITEMS = [
    StoreItem(
        id="drama-finder",
        name="短剧筛选",
        type=ItemType.PLUGIN,
        category=ItemCategory.OPERATION_TOOLS,
        version="1.1.1",
        author="官方",
        description="多平台热门短剧筛选：封面卡片墙 + 详情预览；静态缓存优先，可选 Playwright 真爬。",
        icon="🎭",
        is_free=True,
        is_official=True,
        is_installed=True,
        local_path="app/plugins/drama_finder_plugin",
        tags=["短剧", "筛选", "榜单", "佣金", "可视化"],
    ),
    StoreItem(
        id="ai-effects-plugin",
        name="AI特效制作",
        type=ItemType.PLUGIN,
        category=ItemCategory.AI_TOOLS,
        version="1.0.0",
        author="拾光剪影官方",
        description="深度学习特效：风格迁移、背景替换、超分、美颜、物体移除（需 torch/opencv）。",
        icon="🎨",
        is_free=True,
        is_official=True,
        is_installed=True,
        local_path="app/plugins/ai_effects_plugin",
        tags=["AI", "特效", "风格迁移", "超分辨率"],
    ),
    # —— 风格特效（单文件）——
    StoreItem(
        id="effect-action", name="动作特效", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="动作场景动感特效，增强视觉冲击力。",
        icon="💥", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/effect_action.py", tags=["特效", "动作"],
    ),
    StoreItem(
        id="effect-comedy", name="喜剧特效", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="喜剧风格色彩与氛围特效。",
        icon="😄", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/effect_comedy.py", tags=["特效", "喜剧"],
    ),
    StoreItem(
        id="effect-dark-tone", name="暗调特效", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="暗调冷色氛围特效。",
        icon="🌑", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/effect_dark_tone.py", tags=["特效", "暗调"],
    ),
    StoreItem(
        id="effect-gold-rush", name="金光特效", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="金色光泽高光特效。",
        icon="✨", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/effect_gold_rush.py", tags=["特效", "金光"],
    ),
    StoreItem(
        id="effect-highlight", name="高亮特效", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="画面高光增强特效。",
        icon="💡", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/effect_highlight.py", tags=["特效", "高亮"],
    ),
    StoreItem(
        id="effect-horror", name="恐怖特效", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="恐怖片冷调压抑氛围特效。",
        icon="👻", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/effect_horror.py", tags=["特效", "恐怖"],
    ),
    StoreItem(
        id="effect-soft-light", name="柔光特效", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="柔光梦幻氛围特效。",
        icon="🌸", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/effect_soft_light.py", tags=["特效", "柔光"],
    ),
    # —— 转场 ——
    StoreItem(
        id="transition-fade", name="淡入淡出", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="经典淡入淡出转场。",
        icon="🌅", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_fade.py", tags=["转场"],
    ),
    StoreItem(
        id="transition-slide", name="滑动转场", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="画面滑动过渡转场。",
        icon="↔️", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_slide.py", tags=["转场"],
    ),
    StoreItem(
        id="transition-dissolve", name="溶解转场", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="帧间溶解过渡转场。",
        icon="🌫️", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_dissolve.py", tags=["转场"],
    ),
    StoreItem(
        id="transition-flip", name="翻转转场", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="画面翻转过渡转场。",
        icon="🔄", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_flip.py", tags=["转场"],
    ),
    StoreItem(
        id="transition-glitch", name="故障转场", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="故障抖动风格转场。",
        icon="📺", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_glitch.py", tags=["转场"],
    ),
    StoreItem(
        id="transition-spin", name="旋转转场", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="旋转过渡转场。",
        icon="🌀", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_spin.py", tags=["转场"],
    ),
    StoreItem(
        id="transition-wipe", name="擦除转场", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="擦除过渡转场。",
        icon="🧹", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_wipe.py", tags=["转场"],
    ),
    StoreItem(
        id="transition-zoom", name="缩放转场", type=ItemType.PLUGIN,
        category=ItemCategory.EFFECT_TOOLS, version="1.0.0", author="官方",
        description="从中心放大/缩小过渡转场。",
        icon="🔍", is_free=True, is_official=True, is_installed=True,
        local_path="app/plugins/transition_zoom.py", tags=["转场"],
    ),
]


def _resolve_plugin_path(rel: str) -> str:
    """解析插件路径。

    __file__ = app/modules/lego/plugin_store.py → 上三级为 app/。
    rel 形如 app/plugins/xxx 或 plugins/xxx。
    """
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    project_root = os.path.dirname(app_dir)
    rel = (rel or "").replace("\\", "/").lstrip("./")
    if rel.startswith("app/"):
        return os.path.normpath(os.path.join(project_root, rel))
    return os.path.normpath(os.path.join(app_dir, rel))


def init_official_items(store):
    """用磁盘真实插件覆盖官方目录，剔除虚构上架项。"""
    # 1) 清除虚构官方条目
    for fid in FAKE_OFFICIAL_IDS:
        store._items.pop(fid, None)
        store._installed_items.pop(fid, None)

    # 2) 按本地路径是否存在写入/更新真实插件
    for item in OFFICIAL_ITEMS:
        abs_path = _resolve_plugin_path(item.local_path) if item.local_path else ""
        exists = bool(abs_path and os.path.exists(abs_path))
        if not exists:
            logger.warning("商店目录跳过（文件不存在）: %s -> %s", item.id, item.local_path)
            continue
        item.is_installed = True
        item.local_path = abs_path
        store._items[item.id] = item
        store._installed_items[item.id] = item

    # 3) 清理：官方标记但既无 local_path 又不在 OFFICIAL_ITEMS 的残留
    official_ids = {i.id for i in OFFICIAL_ITEMS}
    stale = [
        iid for iid, it in list(store._items.items())
        if it.is_official and iid not in official_ids and not (it.local_path and os.path.exists(it.local_path))
    ]
    for iid in stale:
        store._items.pop(iid, None)
        store._installed_items.pop(iid, None)

    store._save_local_items()
    store._save_installed_items()
    logger.info(
        "插件商店已同步真实目录: %d 项（内置已安装）",
        sum(1 for i in store._items.values() if i.is_official),
    )
# <<< FROZEN:plugin-store-catalog:official END


plugin_store = PluginStore()
