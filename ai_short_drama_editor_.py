import os
import subprocess
import threading
import queue
import random
import time
import re
import gc
import sys
import platform
import traceback
import signal

# 导入Timeline类
try:
    from app.modules.common.timeline.track_canvas import Timeline
except ImportError:
    Timeline = None

# 设置 Qt 平台插件目录
try:
    import PyQt5
    qt_plugins_dir = os.path.join(os.path.dirname(PyQt5.__file__), 'Qt5', 'plugins')
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(qt_plugins_dir, 'platforms')
except ImportError:
    pass

# 延迟导入Tkinter模块，减少启动时间
tk = None
ttk = None
filedialog = None
messagebox = None
scrolledtext = None

# 延迟导入网络相关模块
requests = None
json = None

# 延迟导入系统监控模块
psutil = None

# 延迟导入日期时间模块
from datetime import datetime

# 延迟导入函数
def lazy_import():
    global tk, ttk, filedialog, messagebox, scrolledtext
    global requests, json
    global psutil
    
    if tk is None:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, scrolledtext
    
    if requests is None:
        import requests
        import json
    
    if psutil is None:
        import psutil

# 预加载必要模块（仅在需要时）
def preload_modules():
    """预加载必要模块，避免运行时卡顿"""
    import threading
    def _preload():
        time.sleep(1)  # 延迟1秒，让主界面先加载
        lazy_import()
    
    thread = threading.Thread(target=_preload, daemon=True)
    thread.start()

# 导入模块
from app.utils.hardware import detect_hardware, detect_gpu_encoder
from ai_tools.model_manager import model_manager, API_KEYS
from plugin.plugin_system import PluginManager as PluginManagerFromPluginSystem, plugins, plugin_versions, plugin_categories, plugin_configs, loaded_plugins, default_plugin_categories
from app.utils.performance import performance_monitor
from app.utils.cache_system import cache_system
from app.utils.error_handling import setup_exception_handler
from core.proxy_manager import proxy_manager

# Agent系统导入
try:
    from core.agent_system import (
        AgentManager, AgentTask, TaskPriority,
        initialize_agent_system, shutdown_agent_system
    )
    AGENT_SYSTEM_AVAILABLE = True
except ImportError:
    AGENT_SYSTEM_AVAILABLE = False
    print("警告: Agent系统不可用")

# Agent面板导入
try:
    from app.modules.common.agent_panel import AgentPanel, add_agent_button_to_toolbar
    AGENT_PANEL_AVAILABLE = True
except ImportError:
    AGENT_PANEL_AVAILABLE = False

# 轨道/时间轴、音频、字幕、AI 剪辑、导出增强（不改 UI 布局，仅增强能力）
try:
    from core import timeline_features
except ImportError:
    timeline_features = None
try:
    from core import audio_enhancements
except ImportError:
    audio_enhancements = None
try:
    from core import subtitle_enhancements
except ImportError:
    subtitle_enhancements = None
try:
    from core import ai_clip_features
except ImportError:
    ai_clip_features = None
try:
    from core import export_enhancements
except ImportError:
    export_enhancements = None
try:
    from core import oauth_qr_flow
except ImportError:
    oauth_qr_flow = None

# 检测硬件配置
hardware_config = detect_hardware()

# ===================== 核心配置 =====================
# 尝试使用moviepy的FFmpeg
import os
import sys
import subprocess

# 先尝试从moviepy获取FFmpeg路径
FFMPEG = "ffmpeg.exe"
try:
    # 尝试直接导入imageio_ffmpeg
    try:
        import imageio_ffmpeg
        print(f"成功导入imageio_ffmpeg 版本: {imageio_ffmpeg.__version__}")
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"imageio_ffmpeg 路径: {ffmpeg_path}")
        if os.path.exists(ffmpeg_path):
            print(f"imageio_ffmpeg 存在: {ffmpeg_path}")
            FFMPEG = ffmpeg_path
        else:
            print(f"imageio_ffmpeg 不存在: {ffmpeg_path}")
    except Exception as e:
        print(f"无法获取imageio_ffmpeg: {e}")
        
    # 跳过winget安装，因为我们已经找到了FFmpeg
    print("✅ 已找到FFmpeg，跳过winget安装")
    print(f"使用FFmpeg路径: {FFMPEG}")
    
    # 验证FFmpeg是否可执行
    try:
        result = subprocess.run(
            [FFMPEG, "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("✅ FFmpeg验证成功！")
            print(f"FFmpeg版本: {result.stdout.splitlines()[0]}")
        else:
            print("❌ FFmpeg验证失败")
    except Exception as e:
        print(f"❌ FFmpeg验证失败: {e}")
        
except Exception as e:
    print(f"无法导入moviepy: {e}")

print(f"最终使用的FFmpeg路径: {FFMPEG}")

# 检查FFmpeg是否可执行
try:
    result = subprocess.run(
        [FFMPEG, "-version"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print("✅ FFmpeg 检查成功！")
        print(f"FFmpeg版本: {result.stdout[:100]}...")
    else:
        print(f"❌ FFmpeg 执行失败: {result.stderr}")
except Exception as e:
    print(f"❌ FFmpeg 检查失败: {e}")

OUTPUT_DIR = "短剧AI剪辑输出"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 素材库目录
ASSET_LIBRARY_DIR = os.path.join(OUTPUT_DIR, "asset_library")
os.makedirs(ASSET_LIBRARY_DIR, exist_ok=True)

# 素材分类目录
ASSET_CATEGORIES = ["videos", "audios", "images", "texts", "effects"]
for category in ASSET_CATEGORIES:
    category_dir = os.path.join(ASSET_LIBRARY_DIR, category)
    os.makedirs(category_dir, exist_ok=True)

# 根据硬件配置自动调整参数
MAX_PARALLEL = hardware_config["max_threads"]
DEFAULT_SPEED = 1.2
BGM_VOL = "-6dB"
MAX_BATCH_SIZE = hardware_config["max_batch_size"]
CACHE_SIZE = hardware_config["cache_size"]

# 线程管理
task_queue = []
running_task = 0
max_threads = MAX_PARALLEL
semaphore = threading.Semaphore(max_threads)
task_lock = threading.Lock()

# 线程池管理
class ThreadPool:
    """线程池管理类"""
    def __init__(self, max_workers=MAX_PARALLEL):
        self.max_workers = max_workers
        self.tasks = queue.Queue()  # 使用线程安全的队列
        self.workers = []
        self.running = False
    
    def start(self):
        """启动线程池"""
        self.running = True
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=True)
            worker.start()
            self.workers.append(worker)
    
    def _worker(self):
        """工作线程"""
        task_count = 0
        while self.running:
            try:
                # 使用阻塞的get()方法，避免轮询
                task = self.tasks.get(timeout=0.1)
                
                # 执行任务
                task()
                
                # 标记任务完成
                self.tasks.task_done()
                
                # 每执行5个任务进行一次垃圾回收
                task_count += 1
                if task_count >= 5:
                    gc.collect()
                    task_count = 0
            except queue.Empty:
                # 队列为空，继续循环
                continue
            except Exception as e:
                print(f"线程池工作线程错误: {e}")
    
    def submit(self, task):
        """提交任务到线程池"""
        self.tasks.put(task)
    
    def shutdown(self):
        """关闭线程池"""
        self.running = False
        # 等待所有任务完成
        self.tasks.join()
        for worker in self.workers:
            worker.join(timeout=1)

# 初始化线程池
thread_pool = ThreadPool()
thread_pool.start()

# 初始化插件管理器
plugin_manager = PluginManagerFromPluginSystem(OUTPUT_DIR)

# 检测GPU编码器
GPU_ENCODER = detect_gpu_encoder(FFMPEG)
print(f"使用GPU编码器: {GPU_ENCODER}")

# ===================== Olive Video Editor 集成 =====================
from integrations.olive import olive_editor

# 初始化Olive Video Editor集成
olive_integration = olive_editor

# ===================== 剪辑主任务 =====================
def process_video(video_path, mode, task_id, status_label, title_label, content_label, kw_label, info_label, progress_var, progress_label, export_settings=None):
    """处理单个视频"""
    global running_task
    temp_files = []
    try:
        semaphore.acquire()
        with task_lock:
            running_task += 1
        
        # 记录性能指标
        performance_monitor.record_metrics()
        
        # 默认导出设置
        if export_settings is None:
            export_settings = {
                "resolution": "1920x1080",
                "bitrate": "5M",
                "encoder": GPU_ENCODER,
                "format": "mp4"
            }
        
        base_name = os.path.basename(video_path)
        ext = export_settings["format"]
        output_name = f"[{mode}]_{task_id}_{os.path.splitext(base_name)[0]}.{ext}"
        output_path = os.path.join(OUTPUT_DIR, output_name)

        # 更新视频信息
        info_label.config(text=plugin_get_video_info(video_path))
        
        # 固定使用千问VL模型生成文案
        original_model = model_manager.current_model
        model_manager.switch_model("通义千问VL")
        title, content, keywords = model_manager.generate_content(video_path)  # 使用完整路径进行视频分析
        model_manager.switch_model(original_model)
        title_label.config(text=title)
        content_label.config(text=content)
        kw_label.config(text=keywords)

        # 使用Olive Video Editor处理视频
        progress_var.set(10)
        progress_label.config(text="创建Olive项目...")
        
        # 创建Olive项目
        project_name = f"project_{task_id}"
        project_path = olive_integration.create_project(project_name)
        
        progress_var.set(20)
        progress_label.config(text="导入媒体文件...")
        
        # 导入媒体文件
        olive_integration.import_media(project_path, [video_path])
        
        progress_var.set(30)
        progress_label.config(text="生成剪辑方案...")
        
        # 生成剪辑方案
        edit_params = {
            "mode": mode,
            "target_duration": 30 if mode == "30秒爆款引流" else 90 if mode == "90秒剧情解说" else 480,
            "speed": 1.3 if mode == "30秒爆款引流" else 1.1 if mode == "90秒剧情解说" else 1.0
        }
        
        progress_var.set(50)
        progress_label.config(text="编辑视频...")
        
        # 编辑视频
        olive_integration.edit_video(project_path, edit_params)
        
        progress_var.set(80)
        progress_label.config(text="导出视频...")
        
        # 导出视频
        if olive_integration.export_video(project_path, output_path, export_settings):
            progress_var.set(100)
            progress_label.config(text="剪辑完成！")
            status_label.config(text=f"已完成: {output_name} (使用Olive Video Editor)")
        else:
            status_label.config(text="剪辑失败: 导出失败")

    except Exception as e:
        print(f"处理视频失败: {e}")
        status_label.config(text="处理失败")
    finally:
        # 释放资源
        with task_lock:
            running_task -= 1
        semaphore.release()
        
        # 强制垃圾回收
        gc.collect()

def process_videos(video_paths, mode, task_id, status_label, title_label, content_label, kw_label, info_label, progress_var, progress_label, export_settings=None, audio_settings=None):
    """处理多个视频并合并"""
    global running_task
    try:
        semaphore.acquire()
        with task_lock:
            running_task += 1
        
        # 记录性能指标
        performance_monitor.record_metrics()
        
        total_videos = len(video_paths)
        
        # 默认导出设置
        if export_settings is None:
            export_settings = {
                "resolution": "1920x1080",
                "bitrate": "5M",
                "encoder": GPU_ENCODER,
                "format": "mp4"
            }
        
        # 固定使用千问VL模型生成文案
        original_model = model_manager.current_model
        model_manager.switch_model("通义千问VL")
        title, content, keywords = model_manager.generate_content(video_paths[0])  # 使用完整路径进行视频分析
        model_manager.switch_model(original_model)
        title_label.config(text=title)
        content_label.config(text=content)
        kw_label.config(text=keywords)

        # 使用Olive Video Editor处理多个视频
        progress_var.set(10)
        progress_label.config(text="创建Olive项目...")
        
        # 创建Olive项目
        project_name = f"project_{task_id}_multi"
        project_path = olive_integration.create_project(project_name)
        
        progress_var.set(20)
        progress_label.config(text="导入媒体文件...")
        
        # 导入所有媒体文件
        olive_integration.import_media(project_path, video_paths)
        
        progress_var.set(30)
        progress_label.config(text="生成剪辑方案...")
        
        # 生成剪辑方案
        edit_params = {
            "mode": mode,
            "target_duration": 30 if mode == "30秒爆款引流" else 90 if mode == "90秒剧情解说" else 480,
            "speed": 1.3 if mode == "30秒爆款引流" else 1.1 if mode == "90秒剧情解说" else 1.0,
            "total_videos": total_videos
        }
        
        progress_var.set(50)
        progress_label.config(text="编辑视频...")
        
        # 编辑视频
        olive_integration.edit_video(project_path, edit_params)
        
        progress_var.set(80)
        progress_label.config(text="导出视频...")
        
        # 导出设置
        ext = export_settings["format"]
        output_name = f"[{mode}]_{task_id}_合并视频.{ext}"
        output_path = os.path.join(OUTPUT_DIR, output_name)
        
        # 导出视频
        if olive_integration.export_video(project_path, output_path, export_settings):
            progress_var.set(100)
            progress_label.config(text="剪辑完成！")
            status_label.config(text=f"已完成: {output_name} (使用Olive Video Editor处理 {total_videos} 个视频)")
        else:
            status_label.config(text="剪辑失败: 导出失败")

    except Exception as e:
        print(f"处理多视频失败: {e}")
        status_label.config(text="处理失败")
    finally:
        # 释放资源
        with task_lock:
            running_task -= 1
        semaphore.release()
        
        # 强制垃圾回收
        gc.collect()

# ===================== 账号运营分析 =====================
class AccountAnalyzer:
    def __init__(self):
        self.data_dir = "运营数据"
        os.makedirs(self.data_dir, exist_ok=True)
    
    def add_video_data(self, video_id, title, views, likes, comments, shares, conversions):
        try:
            data = {
                "video_id": video_id,
                "title": title,
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "conversions": conversions,
                "timestamp": datetime.now().isoformat(),
                "like_rate": likes / views if views > 0 else 0,
                "comment_rate": comments / views if views > 0 else 0,
                "share_rate": shares / views if views > 0 else 0,
                "conversion_rate": conversions / views if views > 0 else 0
            }
            
            data_file = os.path.join(self.data_dir, f"{video_id}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"添加视频数据失败: {e}")
            return False
    
    def analyze_data(self):
        try:
            all_data = []
            for file in os.listdir(self.data_dir):
                if file.endswith(".json"):
                    file_path = os.path.join(self.data_dir, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            all_data.append(data)
                    except:
                        pass
            
            if not all_data:
                return {"error": "无数据"}
            
            # 计算平均值
            total_views = sum(d.get("views", 0) for d in all_data)
            total_likes = sum(d.get("likes", 0) for d in all_data)
            total_comments = sum(d.get("comments", 0) for d in all_data)
            total_shares = sum(d.get("shares", 0) for d in all_data)
            total_conversions = sum(d.get("conversions", 0) for d in all_data)
            
            avg_views = total_views / len(all_data)
            avg_likes = total_likes / len(all_data)
            avg_comments = total_comments / len(all_data)
            avg_shares = total_shares / len(all_data)
            avg_conversions = total_conversions / len(all_data)
            
            # 计算平均比率
            avg_like_rate = sum(d.get("like_rate", 0) for d in all_data) / len(all_data)
            avg_comment_rate = sum(d.get("comment_rate", 0) for d in all_data) / len(all_data)
            avg_share_rate = sum(d.get("share_rate", 0) for d in all_data) / len(all_data)
            avg_conversion_rate = sum(d.get("conversion_rate", 0) for d in all_data) / len(all_data)
            
            # 找出表现最好的视频
            top_views = sorted(all_data, key=lambda x: x.get("views", 0), reverse=True)[:3]
            top_conversions = sorted(all_data, key=lambda x: x.get("conversions", 0), reverse=True)[:3]
            top_conversion_rate = sorted(all_data, key=lambda x: x.get("conversion_rate", 0), reverse=True)[:3]
            
            return {
                "total_videos": len(all_data),
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "total_shares": total_shares,
                "total_conversions": total_conversions,
                "average_views": avg_views,
                "average_likes": avg_likes,
                "average_comments": avg_comments,
                "average_shares": avg_shares,
                "average_conversions": avg_conversions,
                "average_like_rate": avg_like_rate,
                "average_comment_rate": avg_comment_rate,
                "average_share_rate": avg_share_rate,
                "average_conversion_rate": avg_conversion_rate,
                "top_views": top_views,
                "top_conversions": top_conversions,
                "top_conversion_rate": top_conversion_rate
            }
        except Exception as e:
            print(f"分析数据失败: {e}")
            return {"error": str(e)}
    
    def generate_optimization_suggestions(self, analysis_data):
        if "error" in analysis_data:
            return "暂无数据，无法生成建议"
        
        suggestions = []
        
        # 基于数据生成建议
        if analysis_data["average_like_rate"] < 0.05:
            suggestions.append("建议优化视频内容质量，增加情感共鸣点")
        
        if analysis_data["average_comment_rate"] < 0.01:
            suggestions.append("建议在视频中设置互动问题，鼓励观众评论")
        
        if analysis_data["average_share_rate"] < 0.005:
            suggestions.append("建议增加视频的价值性和分享点")
        
        if analysis_data["average_conversion_rate"] < 0.001:
            suggestions.append("建议优化引导语和转化路径")
        
        if not suggestions:
            suggestions.append("数据表现良好，继续保持")
        
        return "\n".join(suggestions)

account_analyzer = AccountAnalyzer()

# ===================== OpenClow 自动化引擎 =====================
class OpenClowEngine:
    def __init__(self):
        """初始化OpenClow自动化引擎"""
        self.data_dir = "openclow_data"
        os.makedirs(self.data_dir, exist_ok=True)
        self.platforms = ["抖音", "快手", "视频号"]
        self.accounts = {}
        self.published_content = []
        self.reply_rules = []
        self.operation_data = []
    
    def collect_data(self, platform, account_id):
        """数据采集（抖音/快手/视频号）"""
        try:
            # 模拟数据采集过程
            print(f"开始采集{platform}账号{account_id}的数据...")
            # 模拟采集的数据
            collected_data = {
                "platform": platform,
                "account_id": account_id,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "views": random.randint(1000, 100000),
                    "likes": random.randint(100, 10000),
                    "comments": random.randint(10, 1000),
                    "shares": random.randint(5, 500),
                    "followers": random.randint(100, 50000)
                }
            }
            # 保存采集的数据
            data_file = os.path.join(self.data_dir, f"{platform}_{account_id}_{int(time.time())}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(collected_data, f, ensure_ascii=False, indent=2)
            print(f"{platform}账号{account_id}的数据采集完成")
            return collected_data
        except Exception as e:
            print(f"数据采集失败: {e}")
            return None
    
    def auto_publish(self, platform, account_id, content, schedule_time=None):
        """内容自动发布"""
        try:
            # 模拟内容发布过程
            publish_time = schedule_time if schedule_time else datetime.now().isoformat()
            print(f"开始发布内容到{platform}账号{account_id}...")
            # 创建发布记录
            publish_record = {
                "id": f"pub_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "content": content,
                "publish_time": publish_time,
                "status": "published",
                "timestamp": datetime.now().isoformat()
            }
            # 保存发布记录
            self.published_content.append(publish_record)
            # 保存到文件
            publish_file = os.path.join(self.data_dir, f"publish_{publish_record['id']}.json")
            with open(publish_file, "w", encoding="utf-8") as f:
                json.dump(publish_record, f, ensure_ascii=False, indent=2)
            print(f"内容已成功发布到{platform}账号{account_id}")
            return publish_record
        except Exception as e:
            print(f"内容发布失败: {e}")
            return None
    
    def smart_reply(self, platform, account_id, comment, keywords=None):
        """评论智能回复"""
        try:
            # 模拟智能回复过程
            print(f"处理{platform}账号{account_id}的评论...")
            reply = "感谢您的评论！"  # 默认回复，避免未绑定
            # 基于关键词生成回复
            if keywords:
                for keyword in keywords:
                    if keyword in comment:
                        # 查找匹配的回复规则
                        for rule in self.reply_rules:
                            if rule["keyword"] in comment:
                                reply = rule["reply"]
                                break
                        else:
                            reply = f"感谢您的评论！"
                        break
            else:
                reply = f"感谢您的评论！"
            # 创建回复记录
            reply_record = {
                "id": f"reply_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "comment": comment,
                "reply": reply,
                "timestamp": datetime.now().isoformat()
            }
            # 保存回复记录
            reply_file = os.path.join(self.data_dir, f"reply_{reply_record['id']}.json")
            with open(reply_file, "w", encoding="utf-8") as f:
                json.dump(reply_record, f, ensure_ascii=False, indent=2)
            print(f"已回复{platform}账号{account_id}的评论")
            return reply_record
        except Exception as e:
            print(f"智能回复失败: {e}")
            return None
    
    def write_back_data(self, platform, account_id, data):
        """运营数据回写"""
        try:
            # 模拟数据回写过程
            print(f"回写{platform}账号{account_id}的运营数据...")
            # 创建回写记录
            write_back_record = {
                "id": f"writeback_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
            # 保存回写记录
            self.operation_data.append(write_back_record)
            # 保存到文件
            write_back_file = os.path.join(self.data_dir, f"writeback_{write_back_record['id']}.json")
            with open(write_back_file, "w", encoding="utf-8") as f:
                json.dump(write_back_record, f, ensure_ascii=False, indent=2)
            print(f"{platform}账号{account_id}的运营数据回写完成")
            return write_back_record
        except Exception as e:
            print(f"数据回写失败: {e}")
            return None
    
    def generate_operation_suggestions(self, platform, account_id, data):
        """生成运营建议"""
        try:
            # 模拟生成运营建议
            print(f"为{platform}账号{account_id}生成运营建议...")
            # 基于数据生成建议
            suggestions = []
            # 分析数据
            views = data.get("views", 0)
            likes = data.get("likes", 0)
            comments = data.get("comments", 0)
            shares = data.get("shares", 0)
            followers = data.get("followers", 0)
            
            # 计算互动率
            if views > 0:
                interaction_rate = (likes + comments + shares) / views
            else:
                interaction_rate = 0
            
            # 基于数据生成建议
            if views < 10000:
                suggestions.append("建议增加内容发布频率，提高账号曝光度")
            if interaction_rate < 0.05:
                suggestions.append("建议在视频中增加互动元素，提高观众参与度")
            if comments < 100:
                suggestions.append("建议主动回复评论，增强粉丝粘性")
            if shares < 50:
                suggestions.append("建议创作更具分享价值的内容")
            if followers < 1000:
                suggestions.append("建议优化账号简介和封面，吸引更多关注")
            
            if not suggestions:
                suggestions.append("账号运营状况良好，继续保持现有策略")
            
            # 创建建议记录
            suggestion_record = {
                "id": f"suggestion_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "suggestions": suggestions,
                "timestamp": datetime.now().isoformat()
            }
            # 保存建议记录
            suggestion_file = os.path.join(self.data_dir, f"suggestion_{suggestion_record['id']}.json")
            with open(suggestion_file, "w", encoding="utf-8") as f:
                json.dump(suggestion_record, f, ensure_ascii=False, indent=2)
            print(f"已为{platform}账号{account_id}生成运营建议")
            return suggestion_record
        except Exception as e:
            print(f"生成运营建议失败: {e}")
            return None
    
    def add_reply_rule(self, keyword, reply):
        """添加回复规则"""
        rule = {
            "id": f"rule_{int(time.time())}",
            "keyword": keyword,
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        }
        self.reply_rules.append(rule)
        # 保存规则到文件
        rules_file = os.path.join(self.data_dir, "reply_rules.json")
        with open(rules_file, "w", encoding="utf-8") as f:
            json.dump(self.reply_rules, f, ensure_ascii=False, indent=2)
        return rule
    
    def get_published_content(self):
        """获取已发布的内容"""
        return self.published_content
    
    def get_operation_data(self):
        """获取运营数据"""
        return self.operation_data

# 初始化OpenClow引擎
openclow_engine = OpenClowEngine()

# ===================== UI界面 =====================
class AIShortDramaEditor:
    def __init__(self):
        # 确保所有必要模块都已导入
        lazy_import()
        
        self.root = tk.Tk()
        self.root.title("AI短剧编辑器 v3.0")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 700)
        
        # 初始化轨道列表
        self.tracks = []
        # 添加默认轨道
        self.tracks.append({"id": 1, "type": "video", "clips": [], "locked": False, "muted": False})
        self.tracks.append({"id": 2, "type": "audio", "clips": [], "locked": False, "muted": False})
        
        # 初始化速度变量
        self.speed_var = tk.StringVar(value="1.0x")
        
        # 初始化开源项目配置变量
        self.funclip_enabled_var = tk.BooleanVar(value=True)
        self.autoclip_enabled_var = tk.BooleanVar(value=True)
        self.videofusion_enabled_var = tk.BooleanVar(value=True)
        self.openclaw_enabled_var = tk.BooleanVar(value=True)
        
        # 初始化AI工具配置变量
        self.highlight_detection_var = tk.BooleanVar(value=True)
        self.subtitle_generation_var = tk.BooleanVar(value=True)
        self.intensity_threshold_var = tk.DoubleVar(value=0.6)
        self.denoise_var = tk.BooleanVar(value=True)
        self.stabilize_var = tk.BooleanVar(value=True)
        self.balance_audio_var = tk.BooleanVar(value=True)
        
        # 媒体文件路径映射
        self.media_paths = {}
        
        # 账号运营：已绑定账号列表（持久化到 bound_accounts.json）
        self.bound_accounts = []
        self._bound_accounts_file = os.path.join(OUTPUT_DIR, "config", "bound_accounts.json")
        self._load_bound_accounts()
        
        # 时间线设置
        self.timeline_zoom = 1.0  # 默认缩放级别
        self.zoom_levels = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]  # 缩放级别选项
        self.current_zoom_index = 2  # 默认使用1.0倍缩放
        
        # 界面设置
        # 加载保存的主题设置，如果不存在则根据时间自动设置
        self.load_theme_config()
        self.font_size = 14
        # 用户主题设置标志，用于跟踪用户是否手动切换了主题
        self.user_theme_set = False
        
        # 定时检查时间并自动切换主题
        self.schedule_theme_check()
        
        # 快捷键设置
        self.shortcuts = {
            "cut": "Ctrl+X",
            "copy": "Ctrl+C",
            "paste": "Ctrl+V",
            "delete": "Delete",
            "split": "Ctrl+B",
            "import": "Ctrl+I",
            "export": "Ctrl+E",
            "save": "Ctrl+S"
        }
        
        # 侧边栏设置
        self.sidebar_items = {
            "首页": True,
            "视频剪辑": True,
            "文案生成": True,
            "账号运营": True,
            "插件管理": True,
            "模型配置": True,
            "设置": True,
            "性能监控": True,
            "素材库": True
        }
        
        # 视频播放器设置
        self.use_optimized_player = False
        self.video_player_frame = None
        self.video_player = None
        self.current_preview_video = None  # 当前预览的视频路径
        # Canvas 视频播放状态（OpenCV 帧循环，保证导入视频能正常播放）
        self._video_cap = None
        self._is_playing = False
        self._playback_timer = None
        self._playback_position = 0.0
        
        # GPU加速设置
        self.use_gpu_acceleration = True
        self.cuda_available = False
        self._check_cuda_availability()
        
        # 加载开源项目配置
        self.load_open_source_config()
        
        # 设置深色主题
        self.set_dark_theme()
        
        # 创建主布局
        self.create_main_layout()
        
        # 初始化视频播放器
        self.init_video_player()
        
        # 初始化新的时间轴系统
        self.timeline_system = None
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 绑定窗口焦点事件，当窗口获得焦点时重新加载视频预览
        def on_focus_in(event):
            if hasattr(self, 'current_preview_video') and self.current_preview_video:
                # 检查视频文件是否仍然存在
                if os.path.exists(self.current_preview_video):
                    # 重新加载视频预览
                    self.preview_video(self.current_preview_video)
        
        self.root.bind('<FocusIn>', on_focus_in)
    
    def init_video_player(self):
        """初始化视频播放器"""
        try:
            # 尝试导入PyQt5模块
            from PyQt5.QtWidgets import QApplication
            import sys
            
            # 检查是否已有QApplication实例
            if not QApplication.instance():
                self.q_app = QApplication(sys.argv)
            else:
                self.q_app = QApplication.instance()
            
            # 标记使用新播放器
            self.use_optimized_player = True
            print("✓ 优化的视频播放器初始化成功")
        except Exception as e:
            print(f"无法加载优化的视频播放器: {e}")
            self.use_optimized_player = False
            print("✗ 使用默认视频预览方法")

    def load_open_source_config(self):
        """加载开源项目配置"""
        try:
            config_path = os.path.join(OUTPUT_DIR, "config", "open_source_config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    import json
                    config = json.load(f)
                    
                    # 更新配置变量
                    if "funclip_enabled" in config:
                        self.funclip_enabled_var.set(config["funclip_enabled"])
                    if "autoclip_enabled" in config:
                        self.autoclip_enabled_var.set(config["autoclip_enabled"])
                    if "videofusion_enabled" in config:
                        self.videofusion_enabled_var.set(config["Videofusion_enabled"])
                    if "openclaw_enabled" in config:
                        self.openclaw_enabled_var.set(config["openclaw_enabled"])
        except Exception as e:
            print(f"加载开源项目配置失败: {e}")
    
    def _check_cuda_availability(self):
        """检查CUDA是否可用"""
        try:
            import cv2
            print("🔍 开始检查CUDA可用性...")
            print(f"OpenCV版本: {cv2.__version__}")
            
            # 检查OpenCV是否支持CUDA
            if hasattr(cv2, 'cuda'):
                print("✅ OpenCV CUDA模块可用")
                try:
                    device_count = cv2.cuda.getCudaEnabledDeviceCount()
                    print(f"GPU数量: {device_count}")
                    if device_count > 0:
                        self.cuda_available = True
                        print("✅ CUDA可用，将使用GPU加速渲染")
                        # 打印GPU信息
                        for i in range(device_count):
                            try:
                                device_info = cv2.cuda.DeviceInfo(i)
                                print(f"   GPU {i}: {device_info.name()}")
                            except Exception as e:
                                print(f"   无法获取GPU {i}信息: {e}")
                    else:
                        self.cuda_available = False
                        print("⚠️ CUDA不可用，将使用CPU渲染")
                        print("可能原因: 驱动版本不匹配或CUDA未正确安装")
                except Exception as e:
                    self.cuda_available = False
                    print(f"⚠️ 获取GPU数量失败: {e}")
            else:
                self.cuda_available = False
                print("⚠️ OpenCV CUDA模块不可用")
        except Exception as e:
            self.cuda_available = False
            print(f"⚠️ 检查CUDA失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _create_video_capture(self, video_path):
        """创建视频捕获对象（支持GPU加速）"""
        import cv2
        
        if self.use_gpu_acceleration and self.cuda_available:
            try:
                # 尝试使用GPU加速的视频捕获
                print(f"🔧 尝试使用GPU加速打开视频: {video_path}")
                cap = cv2.VideoCapture(video_path, cv2.CAP_CUDA)
                if cap.isOpened():
                    print("✅ GPU加速视频捕获成功")
                    return cap
                else:
                    print("⚠️ GPU加速视频捕获失败，回退到CPU")
            except Exception as e:
                print(f"⚠️ GPU加速捕获出错: {e}，回退到CPU")
        
        # 使用CPU捕获
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            print(f"✅ CPU视频捕获成功")
        return cap
    
    def set_theme(self, theme):
        """切换主题"""
        self.current_theme = theme
        
        if theme == "dark":
            self.set_dark_theme()
        else:
            self.set_light_theme()
        
        # 标记为用户已设置主题
        self.user_theme_set = True
        
        # 保存主题设置
        self.save_theme_config()
        
        # 重新加载整个主布局
        for widget in self.root.winfo_children():
            widget.destroy()
        self.create_main_layout()
        
        # 刷新界面
        self.root.update_idletasks()
    
    def load_theme_config(self):
        """加载保存的主题配置"""
        try:
            config_dir = os.path.join(OUTPUT_DIR, "config")
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, "theme_config.json")
            
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "theme" in config:
                        self.current_theme = config["theme"]
                        # 标记为用户已设置主题
                        self.user_theme_set = True
                        return
            
            # 如果没有保存的配置，根据时间自动设置主题
            current_hour = datetime.now().hour
            if 7 <= current_hour < 19:
                # 白天使用浅色主题
                self.current_theme = "light"
            else:
                # 晚上使用深色主题
                self.current_theme = "dark"
            # 未保存配置，标记为用户未设置主题
            self.user_theme_set = False
        except Exception as e:
            print(f"加载主题配置失败: {e}")
            # 出错时默认根据时间设置主题
            current_hour = datetime.now().hour
            if 7 <= current_hour < 19:
                self.current_theme = "light"
            else:
                self.current_theme = "dark"
            # 出错时标记为用户未设置主题
            self.user_theme_set = False
    
    def save_theme_config(self):
        """保存主题配置"""
        try:
            config_dir = os.path.join(OUTPUT_DIR, "config")
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, "theme_config.json")
            
            config = {
                "theme": self.current_theme
            }
            
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存主题配置失败: {e}")
    
    def set_dark_theme(self):
        """设置深色主题"""
        self.root.configure(bg="#1a1a1a")
        
        # 创建自定义样式
        style = ttk.Style()
        style.theme_use("clam")
        
        # 配置样式
        style.configure(
            "TLabel",
            background="#1a1a1a",
            foreground="#ffffff",
            font=('微软雅黑', self.font_size)
        )
        style.configure(
            "TButton",
            background="#333333",
            foreground="#ffffff",
            padding=(10, 5),
            font=('微软雅黑', self.font_size),
            relief=tk.FLAT
        )
        style.map(
            "TButton",
            background=[('active', '#444444')],
            foreground=[('active', '#ffffff')]
        )
        style.configure(
            "Accent.TButton",
            background="#007acc",
            foreground="#ffffff",
            padding=(15, 8),
            font=('微软雅黑', self.font_size + 1, 'bold')
        )
        style.map(
            "Accent.TButton",
            background=[('active', '#0099ff')],
            foreground=[('active', '#ffffff')]
        )
        style.configure(
            "TEntry",
            fieldbackground="#2d2d2d",
            foreground="#ffffff",
            insertcolor="#ffffff",
            font=('微软雅黑', self.font_size),
            padding=(5, 3)
        )
        style.configure(
            "TCombobox",
            fieldbackground="#2d2d2d",
            foreground="#ffffff",
            font=('微软雅黑', self.font_size),
            padding=(5, 3)
        )
        style.configure(
            "TCombobox.Listbox",
            background="#2d2d2d",
            foreground="#ffffff",
            font=('微软雅黑', self.font_size)
        )
        style.configure(
            "TProgressbar",
            background="#007acc",
            troughcolor="#2d2d2d",
            thickness=10
        )
        style.configure(
            "TLabelframe",
            background="#1a1a1a",
            foreground="#ffffff",
            font=('微软雅黑', self.font_size + 1, 'bold')
        )
        style.configure(
            "TLabelframe.Label",
            background="#1a1a1a",
            foreground="#ffffff",
            font=('微软雅黑', self.font_size + 1, 'bold')
        )
        style.configure(
            "TListbox",
            background="#2d2d2d",
            foreground="#ffffff",
            font=('微软雅黑', self.font_size),
            selectbackground="#007acc",
            selectforeground="#ffffff"
        )
        style.configure(
            "TScrollbar",
            background="#333333",
            troughcolor="#1a1a1a",
            arrowcolor="#ffffff",
            thickness=20
        )
        style.map(
            "TScrollbar",
            background=[('active', '#444444')]
        )
    
    def set_light_theme(self):
        """设置浅色主题"""
        self.root.configure(bg="#ffffff")
        
        # 创建自定义样式
        style = ttk.Style()
        style.theme_use("clam")
        
        # 配置样式
        style.configure(
            "TLabel",
            background="#ffffff",
            foreground="#000000",
            font=('微软雅黑', self.font_size)
        )
        style.configure(
            "TButton",
            background="#ffffff",
            foreground="#000000",
            padding=(10, 5),
            font=('微软雅黑', self.font_size),
            relief=tk.FLAT
        )
        style.map(
            "TButton",
            background=[('active', '#f0f0f0')],
            foreground=[('active', '#000000')]
        )
        style.configure(
            "Accent.TButton",
            background="#007acc",
            foreground="#ffffff",
            padding=(15, 8),
            font=('微软雅黑', self.font_size + 1, 'bold')
        )
        style.map(
            "Accent.TButton",
            background=[('active', '#0099ff')],
            foreground=[('active', '#ffffff')]
        )
        style.configure(
            "TEntry",
            fieldbackground="#ffffff",
            foreground="#000000",
            insertcolor="#000000",
            font=('微软雅黑', self.font_size),
            padding=(5, 3)
        )
        style.configure(
            "TCombobox",
            fieldbackground="#ffffff",
            foreground="#000000",
            font=('微软雅黑', self.font_size),
            padding=(5, 3)
        )
        style.configure(
            "TCombobox.Listbox",
            background="#ffffff",
            foreground="#000000",
            font=('微软雅黑', self.font_size)
        )
        style.configure(
            "TProgressbar",
            background="#007acc",
            troughcolor="#f0f0f0",
            thickness=10
        )
        style.configure(
            "TLabelframe",
            background="#ffffff",
            foreground="#000000",
            font=('微软雅黑', self.font_size + 1, 'bold')
        )
        style.configure(
            "TLabelframe.Label",
            background="#ffffff",
            foreground="#000000",
            font=('微软雅黑', self.font_size + 1, 'bold')
        )
        style.configure(
            "TListbox",
            background="#ffffff",
            foreground="#000000",
            font=('微软雅黑', self.font_size),
            selectbackground="#007acc",
            selectforeground="#ffffff"
        )
        style.configure(
            "TScrollbar",
            background="#f0f0f0",
            troughcolor="#ffffff",
            arrowcolor="#000000",
            thickness=20
        )
        style.map(
            "TScrollbar",
            background=[('active', '#e0e0e0')]
        )
    
    def set_font_size(self, size):
        """设置字体大小"""
        self.font_size = size
        
        # 重新应用主题以更新字体大小
        self.set_theme(self.current_theme)
        
        # 刷新当前显示的内容
        if hasattr(self, 'content_frame'):
            # 获取当前显示的内容类型
            current_content = None
            for widget in self.content_frame.winfo_children():
                # 检查当前显示的是哪个页面
                if 'home_frame' in str(widget):
                    current_content = 'home'
                elif 'shortcut_frame' in str(widget):
                    current_content = 'shortcut'
                elif 'sidebar_frame' in str(widget):
                    current_content = 'sidebar'
                elif 'projects_frame' in str(widget):
                    current_content = 'projects'
                elif 'tutorial_frame' in str(widget):
                    current_content = 'tutorial'
                elif 'video_frame' in str(widget):
                    current_content = 'video_tutorial'
                elif 'faq_frame' in str(widget):
                    current_content = 'faq'
                elif 'cs_frame' in str(widget):
                    current_content = 'customer_service'
                elif 'scrollable_frame' in str(widget):
                    # 检查是否是视频剪辑工作区
                    for child in widget.winfo_children():
                        if 'frame' in str(child):
                            for grandchild in child.winfo_children():
                                if 'frame' in str(grandchild):
                                    for greatgrandchild in grandchild.winfo_children():
                                        if hasattr(greatgreatgrandchild, 'winfo_children'):
                                            for greatgreatgrandchild in greatgreatgrandchild.winfo_children():
                                                if isinstance(greatgreatgrandchild, tk.Frame) and greatgreatgrandchild.cget('bg') == '#252525':
                                                    # 检查是否有导入按钮
                                                    for btn in greatgreatgrandchild.winfo_children():
                                                        if isinstance(btn, tk.Button) and '导入' in btn.cget('text'):
                                                            current_content = 'video_editing'
                                                            break
                                            if current_content == 'video_editing':
                                                break
                                    if current_content == 'video_editing':
                                        break
                            if current_content == 'video_editing':
                                break
            
            # 重新显示当前内容
            if current_content == 'home':
                self.show_home_page()
            elif current_content == 'shortcut':
                self.show_shortcut_settings()
            elif current_content == 'sidebar':
                self.show_sidebar_settings()
            elif current_content == 'projects':
                # 尝试获取当前项目类型
                for widget in self.content_frame.winfo_children():
                    if hasattr(widget, 'winfo_children'):
                        for child in widget.winfo_children():
                            if isinstance(child, tk.Label) and child.cget('text') in ['最近草稿', '历史项目']:
                                self.show_projects_tab(child.cget('text'))
                                break
            elif current_content == 'tutorial':
                self.show_tutorials()
            elif current_content == 'video_tutorial':
                self.show_video_tutorials()
    
    def _load_bound_accounts(self):
        """加载已绑定的账号列表"""
        try:
            # 确保config目录存在
            config_dir = os.path.join(OUTPUT_DIR, "config")
            os.makedirs(config_dir, exist_ok=True)
            
            # 加载绑定的账号
            if os.path.exists(self._bound_accounts_file):
                with open(self._bound_accounts_file, "r", encoding="utf-8") as f:
                    import json
                    self.bound_accounts = json.load(f)
        except Exception as e:
            print(f"加载绑定账号失败: {e}")
            self.bound_accounts = []
    
    def schedule_theme_check(self):
        """定时检查时间并自动切换主题"""
        def check_theme():
            if not self.user_theme_set:
                current_hour = datetime.now().hour
                if 7 <= current_hour < 19:
                    new_theme = "light"
                else:
                    new_theme = "dark"
                
                if hasattr(self, 'current_theme') and self.current_theme != new_theme:
                    self.set_theme(new_theme)
            
            # 每小时检查一次
            self.root.after(3600000, check_theme)
        
        # 立即检查一次
        check_theme()
    
    def create_main_layout(self):
        """创建主布局"""
        # 创建主框架
        self.main_frame = tk.Frame(self.root, bg=self.root.cget('bg'))
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建侧边栏
        self.sidebar_frame = tk.Frame(self.main_frame, bg='#252525', width=200)
        self.sidebar_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        
        # 创建内容区域
        self.content_frame = tk.Frame(self.main_frame, bg=self.root.cget('bg'))
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 填充侧边栏内容
        self._fill_sidebar()
        
        # 默认显示首页
        self.show_home_page()
    
    def _fill_sidebar(self):
        """填充侧边栏内容"""
        # 侧边栏标题
        title_label = tk.Label(self.sidebar_frame, text="功能导航", bg='#252525', fg='white', font=('微软雅黑', 14, 'bold'))
        title_label.pack(pady=10, padx=10, anchor=tk.W)
        
        # 侧边栏按钮
        sidebar_buttons = [
            ("首页", self.show_home_page),
            ("视频剪辑", self.show_video_editing),
            ("文案生成", self.show_copywriting),
            ("账号运营", self.show_account_operations),
            ("插件管理", self.show_plugin_management),
            ("模型配置", self.show_model_config),
            ("设置", self.show_settings),
            ("性能监控", self.show_performance_monitor),
            ("素材库", self.show_asset_library)
        ]
        
        for text, command in sidebar_buttons:
            if text in self.sidebar_items and self.sidebar_items[text]:
                button = tk.Button(
                    self.sidebar_frame, 
                    text=text, 
                    command=command,
                    bg='#333333', 
                    fg='white',
                    font=('微软雅黑', 12),
                    relief=tk.FLAT,
                    padx=10,
                    pady=8
                )
                button.pack(fill=tk.X, padx=10, pady=5)
                button.bind('<Enter>', lambda e, b=button: b.config(bg='#444444'))
                button.bind('<Leave>', lambda e, b=button: b.config(bg='#333333'))
    
    def show_home_page(self):
        """显示首页"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建首页内容
        home_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        home_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(home_frame, text="AI短剧编辑器 v3.0", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 20, 'bold'))
        title_label.pack(pady=20)
        
        # 功能介绍
        features = [
            "✅ 支持本地运行（CPU运行）",
            "✅ 无需GPU",
            "✅ 支持多种AI模型",
            "✅ 自动提取文案 + 生成脚本",
            "✅ 智能定位高潮点",
            "✅ 添加BGM/贴纸"
        ]
        
        for feature in features:
            feature_label = tk.Label(home_frame, text=feature, bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 12))
            feature_label.pack(pady=5, anchor=tk.W, padx=20)
        
        # 快速操作按钮
        quick_actions_frame = tk.Frame(home_frame, bg=self.root.cget('bg'))
        quick_actions_frame.pack(pady=20)
        
        import_button = tk.Button(
            quick_actions_frame, 
            text="导入视频", 
            command=self.import_video,
            bg='#007acc', 
            fg='white',
            font=('微软雅黑', 12, 'bold'),
            padx=20,
            pady=10
        )
        import_button.pack(side=tk.LEFT, padx=10)
        
        edit_button = tk.Button(
            quick_actions_frame, 
            text="开始剪辑", 
            command=self.show_video_editing,
            bg='#007acc', 
            fg='white',
            font=('微软雅黑', 12, 'bold'),
            padx=20,
            pady=10
        )
        edit_button.pack(side=tk.LEFT, padx=10)
    
    def show_video_editing(self):
        """显示视频剪辑界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建视频剪辑界面
        edit_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        edit_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(edit_frame, text="视频剪辑", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
        
        # 导入按钮
        import_button = tk.Button(
            edit_frame, 
            text="导入视频", 
            command=self.import_video,
            bg='#333333', 
            fg='white',
            font=('微软雅黑', 12),
            padx=15,
            pady=8
        )
        import_button.pack(pady=10, anchor=tk.W, padx=20)
    
    def show_copywriting(self):
        """显示文案生成界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建文案生成界面
        copywriting_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        copywriting_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(copywriting_frame, text="文案生成", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
    
    def show_account_operations(self):
        """显示账号运营界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建账号运营界面
        account_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        account_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(account_frame, text="账号运营", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
    
    def show_plugin_management(self):
        """显示插件管理界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建插件管理界面
        plugin_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        plugin_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(plugin_frame, text="插件管理", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
    
    def show_model_config(self):
        """显示模型配置界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建模型配置界面
        model_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        model_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(model_frame, text="模型配置", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
    
    def show_settings(self):
        """显示设置界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建设置界面
        settings_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        settings_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(settings_frame, text="设置", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
    
    def show_performance_monitor(self):
        """显示性能监控界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建性能监控界面
        perf_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        perf_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(perf_frame, text="性能监控", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
    
    def show_asset_library(self):
        """显示素材库界面"""
        # 清空内容区域
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # 创建素材库界面
        asset_frame = tk.Frame(self.content_frame, bg=self.root.cget('bg'))
        asset_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(asset_frame, text="素材库", bg=self.root.cget('bg'), fg='white', font=('微软雅黑', 16, 'bold'))
        title_label.pack(pady=10, anchor=tk.W, padx=20)
    
    def import_video(self):
        """导入视频文件"""
        lazy_import()
        file_path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mp4 *.avi *.mov *.wmv *.flv *.mkv *.webm"), ("所有文件", "*.*")]
        )
        
        if file_path:
            print(f"导入视频: {file_path}")
    
    def on_closing(self):
        """窗口关闭事件"""
        self.root.destroy()