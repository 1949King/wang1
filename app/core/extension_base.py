"""
统一扩展抽象层 (Extension Base)
=============================
为 Skill / MCP Server 提供统一的抽象接口。

架构设计:
    Extension (抽象基类)
    ├── SkillExtension    → AI 技能 (skill_engine.py，含旧 PluginExtension 兼容)
    └── McpExtension     → MCP 服务 (Model Context Protocol)

统一接口:
    - get_info()     → 获取扩展元信息
    - get_tools()    → 获取可用工具/技能列表
    - run()          → 执行扩展
    - is_available() → 检查是否可用
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ExtensionType(str, Enum):
    """扩展类型枚举（已统一：插件并入技能，只留两类）"""
    SKILL = "skill"             # AI 技能（含原"传统插件"）
    MCP_SERVER = "mcp_server"   # MCP 服务


class ExtensionStatus(str, Enum):
    """扩展状态枚举"""
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    LOADING = "loading"


@dataclass
class ExtensionTool:
    """扩展工具/技能描述"""
    id: str
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    category: str = "通用"


@dataclass
class ExtensionInfo:
    """扩展元信息"""
    id: str
    name: str
    type: ExtensionType
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    icon: str = "📦"
    status: ExtensionStatus = ExtensionStatus.DISABLED
    enabled: bool = False
    path: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Extension(ABC):
    """
    统一扩展抽象基类

    所有扩展类型（Plugin/Skill/MCP）必须实现此接口。
    """

    def __init__(self, info: ExtensionInfo):
        self._info = info
        self._tools: List[ExtensionTool] = []
        self._initialized = False
        self._error: Optional[str] = None

    @property
    def info(self) -> ExtensionInfo:
        """获取扩展元信息"""
        return self._info

    @property
    def extension_type(self) -> ExtensionType:
        """获取扩展类型"""
        return self._info.type

    @property
    def is_enabled(self) -> bool:
        """是否已启用"""
        return self._info.enabled

    @property
    def is_available(self) -> bool:
        """是否可用（未报错）"""
        return self._initialized and self._error is None

    @property
    def error(self) -> Optional[str]:
        """获取错误信息"""
        return self._error

    def get_info(self) -> ExtensionInfo:
        """获取扩展元信息"""
        return self._info

    def get_tools(self) -> List[ExtensionTool]:
        """获取可用工具/技能列表"""
        return self._tools

    @abstractmethod
    def initialize(self) -> bool:
        """初始化扩展（加载依赖、建立连接等）"""
        pass

    @abstractmethod
    def run(self, tool_id: str, **kwargs) -> Any:
        """
        执行指定工具/技能

        Args:
            tool_id: 工具/技能 ID
            **kwargs: 传递给工具的参数

        Returns:
            执行结果
        """
        pass

    def enable(self) -> bool:
        """启用扩展"""
        if self.initialize():
            self._info.enabled = True
            self._info.status = ExtensionStatus.ENABLED
            return True
        return False

    def disable(self):
        """禁用扩展"""
        self._info.enabled = False
        self._info.status = ExtensionStatus.DISABLED


class PluginExtension(Extension):
    """
    插件适配器（已 deprecated：插件统一为 Skill，保留类只为兼容旧调用）

    将现有的 PluginManager 插件包装为统一接口。类型已统一为 SKILL。
    """

    def __init__(self, plugin_obj: Any):
        info = ExtensionInfo(
            id=getattr(plugin_obj, 'name', 'unknown'),
            name=getattr(plugin_obj, 'name', '未知技能'),
            type=ExtensionType.SKILL,  # 插件并入 Skill 体系
            version=getattr(plugin_obj, 'version', '1.0.0'),
            description=getattr(plugin_obj, 'description', ''),
            icon="⚡",
            tags=[getattr(plugin_obj, 'category', '视频处理')],
        )
        super().__init__(info)
        self._plugin_obj = plugin_obj

    def initialize(self) -> bool:
        """初始化插件（兼容旧接口）"""
        try:
            init_func = getattr(self._plugin_obj, 'initialize', None)
            if init_func and callable(init_func):
                init_func({"parent_widget": None})

            # 获取工具列表
            get_tools = getattr(self._plugin_obj, 'get_tools', None)
            if get_tools and callable(get_tools):
                tools_data = get_tools()
                if isinstance(tools_data, list):
                    for t in tools_data:
                        self._tools.append(ExtensionTool(
                            id=t.get('id', t.get('name', '')),
                            name=t.get('name', ''),
                            description=t.get('description', ''),
                            parameters=t.get('parameters', {}),
                        ))

            self._initialized = True
            self._error = None
            return True
        except Exception as e:
            self._error = str(e)
            return False

    def run(self, tool_id: str, **kwargs) -> Any:
        """运行插件"""
        if not self._initialized:
            return None

        # 兼容旧接口：如果插件有 run() 方法
        run_func = getattr(self._plugin_obj, 'run', None)
        if run_func and callable(run_func):
            try:
                return run_func(**kwargs)
            except Exception as e:
                self._error = str(e)
                return None

        return None


class SkillExtension(Extension):
    """
    AI 技能适配器

    将 skill_engine.py 中的 Skill 包装为统一接口。
    """

    def __init__(self, skill_obj: Any):
        info = ExtensionInfo(
            id=getattr(skill_obj, 'skill_id', 'unknown'),
            name=getattr(skill_obj, 'skill_name', '未知技能'),
            type=ExtensionType.SKILL,
            version=getattr(skill_obj, 'skill_version', '1.0.0'),
            description=getattr(skill_obj, 'skill_description', ''),
            icon="⚡",
            tags=[getattr(skill_obj, 'skill_category', '通用')],
        )
        super().__init__(info)
        self._skill_obj = skill_obj

    def initialize(self) -> bool:
        """初始化技能"""
        try:
            self._tools = [ExtensionTool(
                id=self._info.id,
                name=self._info.name,
                description=self._info.description,
            )]
            self._initialized = True
            self._error = None
            return True
        except Exception as e:
            self._error = str(e)
            return False

    def run(self, tool_id: str, **kwargs) -> Any:
        """执行技能"""
        if not self._initialized:
            return None

        try:
            # Skill 执行需要 context
            from .extensions_context import ExtensionsContext
            ctx = ExtensionsContext(inputs=kwargs)
            return self._skill_obj.execute(ctx)
        except Exception as e:
            self._error = str(e)
            return None


class McpExtension(Extension):
    """
    MCP 服务适配器

    包装 MCP 客户端连接，将远程 MCP Server 的工具暴露为统一接口。
    """

    def __init__(self, server_name: str, server_config: Dict[str, Any]):
        info = ExtensionInfo(
            id=f"mcp_{server_name.lower().replace(' ', '_')}",
            name=server_name,
            type=ExtensionType.MCP_SERVER,
            version="1.0.0",
            description=f"MCP 服务: {server_name}",
            icon="🔌",
            metadata=server_config,
        )
        super().__init__(info)
        self._client = None
        self._server_config = server_config

    def initialize(self) -> bool:
        """连接 MCP Server 并获取工具列表"""
        try:
            from .mcp_client import McpClientManager

            self._client = McpClientManager()
            success = self._client.connect(self._server_config)

            if success:
                # 获取远程工具列表
                mcp_tools = self._client.list_tools()
                self._tools = [ExtensionTool(
                    id=tool['name'],
                    name=tool['name'],
                    description=tool.get('description', ''),
                    parameters=tool.get('parameters', {}),
                    category=self._info.name,
                ) for tool in mcp_tools]

                self._initialized = True
                self._error = None
                return True
            else:
                self._error = self._client.last_error or "连接失败"
                return False
        except Exception as e:
            self._error = str(e)
            return False

    def run(self, tool_id: str, **kwargs) -> Any:
        """调用 MCP 工具"""
        if not self._initialized or not self._client:
            return None

        try:
            return self._client.call_tool(tool_id, kwargs)
        except Exception as e:
            self._error = str(e)
            return None

    def disconnect(self):
        """断开 MCP 连接"""
        if self._client:
            self._client.disconnect()
        self._initialized = False
        self._info.status = ExtensionStatus.DISABLED


class ExtensionsRegistry:
    """
    扩展注册表 - 统一管理所有扩展

    功能:
    - 注册/注销扩展
    - 按类型筛选
    - 查询扩展信息
    """

    def __init__(self):
        self._extensions: Dict[str, Extension] = {}
        self._listeners: List[Callable] = []

    def register(self, extension: Extension) -> str:
        """注册扩展"""
        ext_id = extension.info.id
        self._extensions[ext_id] = extension
        self._notify_listeners('registered', ext_id)
        return ext_id

    def unregister(self, ext_id: str) -> bool:
        """注销扩展"""
        if ext_id in self._extensions:
            ext = self._extensions[ext_id]
            if isinstance(ext, McpExtension):
                ext.disconnect()
            del self._extensions[ext_id]
            self._notify_listeners('unregistered', ext_id)
            return True
        return False

    def get(self, ext_id: str) -> Optional[Extension]:
        """获取扩展"""
        return self._extensions.get(ext_id)

    def list_all(self) -> List[Extension]:
        """列出所有扩展"""
        return list(self._extensions.values())

    def list_by_type(self, ext_type: ExtensionType) -> List[Extension]:
        """按类型列出扩展"""
        return [e for e in self._extensions.values() if e.extension_type == ext_type]

    def list_enabled(self) -> List[Extension]:
        """列出已启用的扩展"""
        return [e for e in self._extensions.values() if e.is_enabled]

    def add_listener(self, callback: Callable):
        """添加变更监听器"""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        """移除变更监听器"""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self, event: str, ext_id: str):
        """通知监听器"""
        for callback in self._listeners:
            try:
                callback(event, ext_id)
            except Exception as e:
                logger.debug(f"[ExtensionsRegistry] 通知监听器失败: {e}")


# 全局单例
_registry_instance: Optional[ExtensionsRegistry] = None


def get_extensions_registry() -> ExtensionsRegistry:
    """获取全局扩展注册表"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ExtensionsRegistry()
    return _registry_instance


def register_extension(extension: Extension) -> str:
    """便捷函数：注册扩展"""
    return get_extensions_registry().register(extension)


def unregister_extension(ext_id: str) -> bool:
    """便捷函数：注销扩展"""
    return get_extensions_registry().unregister(ext_id)


def list_extensions(ext_type: Optional[ExtensionType] = None) -> List[Extension]:
    """便捷函数：列出扩展"""
    registry = get_extensions_registry()
    if ext_type:
        return registry.list_by_type(ext_type)
    return registry.list_all()
