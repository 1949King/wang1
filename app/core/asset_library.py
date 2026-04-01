import os
import json
from modules.utils.logger import logger

class AssetLibrary:
    def __init__(self, library_path=None):
        self.library_path = library_path or os.path.join(os.getcwd(), "asset_library")
        self.assets = []
        self.categories = set()
        self.thumbnails_path = os.path.join(self.library_path, "thumbnails")
        self.initialize_library()
    
    def initialize_library(self):
        """初始化素材库"""
        # 创建素材库目录
        os.makedirs(self.library_path, exist_ok=True)
        
        # 创建缩略图目录
        os.makedirs(self.thumbnails_path, exist_ok=True)
        
        # 创建分类目录
        default_categories = ["视频", "音频", "图片", "字幕", "特效"]
        for category in default_categories:
            category_path = os.path.join(self.library_path, category)
            os.makedirs(category_path, exist_ok=True)
            self.categories.add(category)
        
        logger.info(f"素材库初始化成功，路径: {self.library_path}")
        logger.info(f"缩略图目录: {self.thumbnails_path}")
        logger.info(f"默认分类: {list(self.categories)}")
    
    def add_asset(self, asset_path, category, tags=None, metadata=None):
        """添加素材到库中"""
        if not os.path.exists(asset_path):
            logger.error(f"素材文件不存在: {asset_path}")
            return False
        
        # 验证分类
        if category not in self.categories:
            # 创建新分类目录
            category_path = os.path.join(self.library_path, category)
            os.makedirs(category_path, exist_ok=True)
            self.categories.add(category)
            logger.info(f"创建新分类: {category}")
        
        # 生成素材ID
        asset_id = len(self.assets) + 1
        asset_name = os.path.basename(asset_path)
        
        # 获取素材类型（从文件扩展名判断）
        asset_type = os.path.splitext(asset_name)[1].lower().lstrip('.')
        
        # 生成缩略图路径
        thumbnail_name = f"{asset_id}_{asset_name}.jpg"
        thumbnail_path = os.path.join(self.thumbnails_path, thumbnail_name)
        
        # 构建素材信息
        asset_info = {
            "id": asset_id,
            "name": asset_name,
            "path": asset_path,
            "category": category,
            "type": asset_type,
            "tags": tags or [],
            "metadata": metadata or {},
            "thumbnail": thumbnail_path,
            "added_time": os.path.getctime(asset_path)
        }
        
        # 添加到素材列表
        self.assets.append(asset_info)
        
        # 生成缩略图（这里只是创建路径，实际生成需要图像处理库）
        # 后续可以添加实际的缩略图生成逻辑
        logger.info(f"素材添加成功: {asset_name} (分类: {category}, 类型: {asset_type})")
        logger.info(f"缩略图路径: {thumbnail_path}")
        return True
    
    def search_assets(self, keyword, category=None, search_by=None):
        """搜索素材
        
        Args:
            keyword: 搜索关键词
            category: 分类筛选（可选）
            search_by: 搜索方式，可选值："name"（按文件名）、"tags"（按标签）、"type"（按类型）、None（全部）
        """
        results = []
        
        for asset in self.assets:
            # 按分类筛选
            if category and asset["category"] != category:
                continue
            
            # 按关键词搜索
            match = False
            
            if search_by == "name" or search_by is None:
                if keyword.lower() in asset["name"].lower():
                    match = True
            
            if not match and (search_by == "tags" or search_by is None):
                if any(keyword.lower() in tag.lower() for tag in asset["tags"]):
                    match = True
            
            if not match and (search_by == "type" or search_by is None):
                if "type" in asset and keyword.lower() in asset["type"].lower():
                    match = True
            
            if match:
                results.append(asset)
        
        logger.info(f"搜索完成，找到 {len(results)} 个素材")
        return results
    
    def get_assets_by_category(self, category):
        """按分类获取素材"""
        results = [asset for asset in self.assets if asset["category"] == category]
        logger.info(f"分类 {category} 下有 {len(results)} 个素材")
        return results
    
    def get_all_categories(self):
        """获取所有分类"""
        return list(self.categories)
    
    def update_asset_metadata(self, asset_id, metadata):
        """更新素材元数据"""
        for asset in self.assets:
            if asset["id"] == asset_id:
                asset["metadata"].update(metadata)
                logger.info(f"素材元数据更新成功: {asset['name']}")
                return True
        
        logger.error(f"素材不存在: ID={asset_id}")
        return False
    
    def remove_asset(self, asset_id):
        """从库中移除素材"""
        for i, asset in enumerate(self.assets):
            if asset["id"] == asset_id:
                removed_asset = self.assets.pop(i)
                logger.info(f"素材移除成功: {removed_asset['name']}")
                return True
        
        logger.error(f"素材不存在: ID={asset_id}")
        return False
    
    def export_library(self, export_path):
        """导出素材库配置"""
        library_config = {
            "library_path": self.library_path,
            "categories": list(self.categories),
            "assets": self.assets
        }
        
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(library_config, f, ensure_ascii=False, indent=2)
        
        logger.info(f"素材库导出成功: {export_path}")
        return True
    
    def import_library(self, import_path):
        """导入素材库配置"""
        if not os.path.exists(import_path):
            logger.error(f"导入文件不存在: {import_path}")
            return False
        
        with open(import_path, "r", encoding="utf-8") as f:
            library_config = json.load(f)
        
        # 恢复配置
        self.library_path = library_config.get("library_path", self.library_path)
        self.categories = set(library_config.get("categories", []))
        self.assets = library_config.get("assets", [])
        
        # 确保目录结构存在
        self.initialize_library()
        
        logger.info(f"素材库导入成功: {import_path}")
        logger.info(f"导入素材数量: {len(self.assets)}")
        logger.info(f"导入分类数量: {len(self.categories)}")
        return True
    
    def create_category(self, category_name):
        """创建自定义分类"""
        if category_name in self.categories:
            logger.warning(f"分类已存在: {category_name}")
            return False
        
        # 创建分类目录
        category_path = os.path.join(self.library_path, category_name)
        os.makedirs(category_path, exist_ok=True)
        self.categories.add(category_name)
        
        logger.info(f"自定义分类创建成功: {category_name}")
        return True
    
    def delete_category(self, category_name):
        """删除分类"""
        if category_name not in self.categories:
            logger.error(f"分类不存在: {category_name}")
            return False
        
        # 检查分类下是否有素材
        category_assets = self.get_assets_by_category(category_name)
        if category_assets:
            logger.warning(f"分类 {category_name} 下还有 {len(category_assets)} 个素材，无法删除")
            return False
        
        # 删除分类目录
        category_path = os.path.join(self.library_path, category_name)
        if os.path.exists(category_path):
            try:
                os.rmdir(category_path)
            except Exception as e:
                logger.error(f"删除分类目录失败: {e}")
                return False
        
        # 从分类集合中移除
        self.categories.remove(category_name)
        logger.info(f"分类删除成功: {category_name}")
        return True
    
    def add_tag_to_asset(self, asset_id, tag):
        """为素材添加标签"""
        for asset in self.assets:
            if asset["id"] == asset_id:
                if tag not in asset["tags"]:
                    asset["tags"].append(tag)
                    logger.info(f"为素材 {asset['name']} 添加标签: {tag}")
                else:
                    logger.warning(f"素材 {asset['name']} 已存在标签: {tag}")
                return True
        
        logger.error(f"素材不存在: ID={asset_id}")
        return False
    
    def remove_tag_from_asset(self, asset_id, tag):
        """从素材移除标签"""
        for asset in self.assets:
            if asset["id"] == asset_id:
                if tag in asset["tags"]:
                    asset["tags"].remove(tag)
                    logger.info(f"从素材 {asset['name']} 移除标签: {tag}")
                else:
                    logger.warning(f"素材 {asset['name']} 不存在标签: {tag}")
                return True
        
        logger.error(f"素材不存在: ID={asset_id}")
        return False
    
    def get_all_tags(self):
        """获取所有标签"""
        all_tags = set()
        for asset in self.assets:
            for tag in asset.get("tags", []):
                all_tags.add(tag)
        
        logger.info(f"素材库中共有 {len(all_tags)} 个标签")
        return list(all_tags)
    
    def get_assets_by_tag(self, tag):
        """按标签获取素材"""
        results = [asset for asset in self.assets if tag in asset.get("tags", [])]
        logger.info(f"标签 {tag} 下有 {len(results)} 个素材")
        return results