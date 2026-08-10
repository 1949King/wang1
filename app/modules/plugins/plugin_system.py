import os
import importlib.util
import subprocess
import glob
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# 避免循环导入，稍后动态加载
FullVideoEditorPlugin = None

# 插件接口规范（抽象基类）
class BasePlugin(ABC):
    """所有插件必须继承的基类，定义统一接口"""
    
    @abstractmethod
    def get_name(self) -> str:
        """返回插件名称（必须实现）"""
        pass
    
    @abstractmethod
    def run(self, *args, **kwargs):
        """插件的核心执行逻辑（必须实现）"""
        pass

# 插件存储
plugins = {}
plugin_versions = {}
plugin_categories = {}
plugin_configs = {}
loaded_plugins = []  # 存储已加载的插件实例

# 插件分类
default_plugin_categories = {
    "视频处理": ["视频剪辑", "视频合并", "视频信息读取"],
    "AI功能": ["自动去重优化"],
    "工具": []
}

def register_plugin(name, category="工具", version="1.0.0"):
    def decorator(func):
        plugins[name] = func
        plugin_versions[name] = version
        plugin_categories[name] = category
        plugin_configs[name] = {}
        return func
    return decorator

@register_plugin("自动去重优化", "AI功能")
def plugin_auto_duplicate():
    import random
    offset_x = random.randint(-6, 6)
    offset_y = random.randint(-4, 4)
    hue_value = random.randint(-4, 4)
    return offset_x, offset_y, hue_value

@register_plugin("视频信息读取", "视频处理")
def plugin_get_video_info(video_path, ffmpeg_executable):
    try:
        result = subprocess.run(
            [ffmpeg_executable, "-i", video_path],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        output = result.stderr
        # 更安全地获取时长信息
        duration_lines = [l for l in output.splitlines() if "Duration" in l]
        if not duration_lines:
            # 尝试从其他输出格式获取
            import re
            duration_match = re.search(r"Duration: (\d+:\d+:\d+\.\d+)", output)
            if not duration_match:
                raise ValueError("无法获取视频时长")
            dur_str = duration_match.group(1)
        else:
            dur_str = duration_lines[0].split()[1].split(",")[0]
        
        hh, mm, ss = dur_str.split(":")
        total_sec = int(float(hh)*3600 + float(mm)*60 + float(ss))
        size_mb = round(os.path.getsize(video_path) / (1024*1024), 2)
        return f"{total_sec}s | {size_mb}MB"
    except Exception as e:
        print(f"获取视频信息失败: {e}")
        try:
            # 至少返回文件大小
            size_mb = round(os.path.getsize(video_path) / (1024*1024), 2)
            return f"未知 | {size_mb}MB"
        except Exception as e:
            logger.debug(f"获取视频文件大小失败，返回未知: {e}")
            return "未知"

@register_plugin("视频剪辑", "视频处理")
def plugin_video_clip(input_path, output_path, start_time, duration, speed=1.0, gpu_encoder="libx264", ffmpeg_executable="ffmpeg.exe"):
    try:
        cmd = [
            ffmpeg_executable,
            "-i", input_path,
            "-ss", str(start_time),
            "-t", str(duration),
            "-filter:v", f"setpts={1/speed}*PTS",
            "-filter:a", f"atempo={speed}",
            "-c:v", gpu_encoder,
            "-c:a", "aac",
            "-b:a", "128k",
            "-y",
            output_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        # 修复：此前不检查 returncode，ffmpeg 报错也会 return True（假成功）
        if result.returncode != 0 or not os.path.exists(output_path):
            stderr = (result.stderr or b"").decode("utf-8", errors="ignore")[-500:]
            print(f"视频剪辑失败: ffmpeg 返回码 {result.returncode}\n{stderr}")
            return False
        return True
    except Exception as e:
        print(f"视频剪辑失败: {e}")
        return False

@register_plugin("视频合并", "视频处理")
def plugin_video_merge(input_files, output_path, gpu_encoder="libx264", ffmpeg_executable="ffmpeg.exe"):
    try:
        # 创建文件列表
        list_file = "filelist.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for file in input_files:
                f.write(f"file '{file}'\n")
        
        cmd = [
            ffmpeg_executable,
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c:v", gpu_encoder,
            "-c:a", "copy",
            "-y",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        # 清理列表文件
        if os.path.exists(list_file):
            os.remove(list_file)
        
        # 修复：此前不检查 returncode，ffmpeg 报错也会 return True（假成功）
        if result.returncode != 0 or not os.path.exists(output_path):
            stderr = (result.stderr or b"").decode("utf-8", errors="ignore")[-500:]
            print(f"视频合并失败: ffmpeg 返回码 {result.returncode}\n{stderr}")
            return False
        return True
    except Exception as e:
        print(f"视频合并失败: {e}")
        return False

# 插件管理类
class PluginManager:
    def __init__(self, output_dir="短剧AI剪辑输出"):
        self.plugins_dir = os.path.join(output_dir, "plugins")
        os.makedirs(self.plugins_dir, exist_ok=True)
        self.installed_plugins = {}
        self.loaded_plugins = []
        self.load_installed_plugins()
    
    def load_installed_plugins(self):
        """加载已安装的插件"""
        plugin_files = glob.glob(os.path.join(self.plugins_dir, "*.py"))
        for plugin_file in plugin_files:
            try:
                plugin_name = os.path.basename(plugin_file).replace(".py", "")
                self.installed_plugins[plugin_name] = plugin_file
            except Exception as e:
                print(f"加载插件失败: {e}")
    
    def install_plugin(self, plugin_name, plugin_code):
        """安装新插件（通过安全沙箱执行）"""
        plugin_file = os.path.join(self.plugins_dir, f"{plugin_name}.py")
        
        try:
            # 1. 安全扫描：检测危险代码模式
            from .plugin_sandbox import validate_plugin_code, create_sandbox_globals
            is_safe, error_msg = validate_plugin_code(plugin_code)
            if not is_safe:
                logger.warning(f"插件 '{plugin_name}' 安全扫描未通过: {error_msg}")
                return False
            
            # 2. 写入文件
            with open(plugin_file, "w", encoding="utf-8") as f:
                f.write(plugin_code)
            
            # 3. 读取代码
            with open(plugin_file, "r", encoding="utf-8") as f:
                plugin_code = f.read()
            
            # 4. 在受限沙箱中执行插件代码
            local_vars = {}
            sandbox_globals = create_sandbox_globals({
                'plugins': plugins,
                'plugin_versions': plugin_versions,
                'plugin_categories': plugin_categories,
                'plugin_configs': plugin_configs,
                'register_plugin': register_plugin,
                'BasePlugin': BasePlugin,
            })
            
            try:
                exec(plugin_code, sandbox_globals, local_vars)
            except Exception as exec_err:
                logger.error(f"插件 '{plugin_name}' 执行失败: {exec_err}")
                if os.path.exists(plugin_file):
                    os.remove(plugin_file)
                return False
            
            # 5. 检查插件是否成功注册
            plugin_registered = False
            for name in local_vars:
                if callable(local_vars[name]) and name == plugin_name:
                    plugin_registered = True
                    break
            
            if plugin_name in plugins:
                plugin_registered = True
            
            if plugin_registered:
                self.installed_plugins[plugin_name] = plugin_file
                logger.info(f"插件 '{plugin_name}' 安装成功")
                return True
            else:
                logger.warning(f"插件 '{plugin_name}' 注册失败，未在全局plugins字典中找到")
                if os.path.exists(plugin_file):
                    os.remove(plugin_file)
                return False
        except Exception as e:
            logger.error(f"安装插件 '{plugin_name}' 失败: {e}")
            if os.path.exists(plugin_file):
                os.remove(plugin_file)
            return False
    
    def import_plugin(self, plugin_file):
        """导入插件（含接口校验）"""
        try:
            # 1. 动态加载插件模块
            module_name = os.path.splitext(os.path.basename(plugin_file))[0]
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if not spec or not spec.loader:
                raise ImportError("无法解析插件文件")
            
            plugin_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(plugin_module)

            # 2. 查找插件类（约定：插件模块中需有一个类继承BasePlugin）
            plugin_class = None
            for attr_name in dir(plugin_module):
                attr = getattr(plugin_module, attr_name)
                if (
                    isinstance(attr, type)          # 是类
                    and issubclass(attr, BasePlugin)# 继承自基类
                    and attr != BasePlugin          # 不是基类本身
                ):
                    plugin_class = attr
                    break

            if not plugin_class:
                raise ValueError(f"插件中未找到继承自BasePlugin的有效类")

            # 3. 实例化插件并存储
            plugin_instance = plugin_class()
            self.loaded_plugins.append(plugin_instance)
            loaded_plugins.append(plugin_instance)
            return True, f"插件「{plugin_instance.get_name()}」导入成功！"
        except Exception as e:
            return False, f"插件导入出错：{str(e)}"
    
    def run_plugins(self):
        """运行所有已加载的插件"""
        if not self.loaded_plugins:
            return "没有已加载的插件"
        
        result = []
        for plugin in self.loaded_plugins:
            try:
                # 调用插件的统一接口run()
                output = plugin.run()
                result.append(f"「{plugin.get_name()}」运行结果：{output}")
            except Exception as e:
                result.append(f"「{plugin.get_name()}」运行失败：{str(e)}")
        
        return "\n".join(result)
    
    def uninstall_plugin(self, plugin_name):
        """卸载插件"""
        try:
            if plugin_name in self.installed_plugins:
                plugin_file = self.installed_plugins[plugin_name]
                if os.path.exists(plugin_file):
                    os.remove(plugin_file)
                del self.installed_plugins[plugin_name]
            
            # 从全局插件字典中移除
            if plugin_name in plugins:
                del plugins[plugin_name]
            if plugin_name in plugin_versions:
                del plugin_versions[plugin_name]
            if plugin_name in plugin_categories:
                del plugin_categories[plugin_name]
            if plugin_name in plugin_configs:
                del plugin_configs[plugin_name]
            
            # 从已加载插件列表中移除
            self.loaded_plugins = [p for p in self.loaded_plugins if p.get_name() != plugin_name]
            global loaded_plugins
            loaded_plugins = [p for p in loaded_plugins if p.get_name() != plugin_name]
            
            return True
        except Exception as e:
            print(f"卸载插件失败: {e}")
            return False
    
    def update_plugin(self, plugin_name, plugin_code):
        """更新插件"""
        try:
            # 先卸载旧插件
            self.uninstall_plugin(plugin_name)
            # 再安装新插件
            return self.install_plugin(plugin_name, plugin_code)
        except Exception as e:
            print(f"更新插件失败: {e}")
            return False
    
    def get_plugin_info(self, plugin_name):
        """获取插件信息"""
        if plugin_name not in plugins:
            return None
        
        return {
            "name": plugin_name,
            "version": plugin_versions.get(plugin_name, "1.0.0"),
            "category": plugin_categories.get(plugin_name, "工具"),
            "config": plugin_configs.get(plugin_name, {})
        }
    
    def list_plugins(self, category=None):
        """列出插件"""
        if category:
            return [name for name, cat in plugin_categories.items() if cat == category]
        return list(plugins.keys())

# 动态导入FullVideoEditorPlugin，避免循环导入
try:
    from .full_video_editor import FullVideoEditorPlugin
except ImportError:
    print("警告: 无法导入FullVideoEditorPlugin")
