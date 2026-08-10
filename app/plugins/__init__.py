"""
插件包初始化
=============
特效 / 转场 / 短剧筛选等由 PluginManager 按文件或子包加载，
此处不做 eager import（避免依赖 core.plugin_loader 导致整包不可用）。
"""

__all__: list[str] = []
