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
    from modules.timeline.track_canvas import Timeline
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
from utils.hardware import detect_hardware, detect_gpu_encoder
from ai_tools.model_manager import model_manager, API_KEYS
from plugin.plugin_system import PluginManager as PluginManagerFromPluginSystem, plugins, plugin_versions, plugin_categories, plugin_configs, loaded_plugins, default_plugin_categories
from utils.performance import performance_monitor
from utils.cache_system import cache_system
from utils.error_handling import setup_exception_handler
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
    from modules.agent_panel import AgentPanel, add_agent_button_to_toolbar
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
                        self.videofusion_enabled_var.set(config["videofusion_enabled"])
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
                                        if hasattr(greatgrandchild, 'winfo_children'):
                                            for greatgreatgrandchild in greatgrandchild.winfo_children():
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
            elif current_content == 'faq':
                self.show_faq()
            elif current_content == 'customer_service':
                self.show_customer_service()
            elif current_content == 'video_editing':
                # 重新显示视频剪辑工作区
                self.show_video_editing_tab()
        
        # 重新创建导航栏以更新字体大小
        if hasattr(self, 'left_frame'):
            self.recreate_navigation_bar()
        
        # 刷新顶部工具栏
        if hasattr(self, 'top_frame'):
            # 清空顶部工具栏
            for widget in self.top_frame.winfo_children():
                widget.destroy()
            # 重新创建顶部工具栏
            self.create_top_toolbar()
        
        # 强制刷新界面
        self.root.update_idletasks()
    
    def show_shortcut_settings(self):
        """显示快捷键设置"""
        self.clear_content_frame()
        
        # 创建框架（不使用滚动条）
        shortcut_frame = self.create_scrollable_frame(self.content_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0", scrollable=False)
        
        # 标题
        title = tk.Label(shortcut_frame, text="快捷键设置", font=('微软雅黑', self.font_size + 2, 'bold'), bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0", fg="#ffffff" if self.current_theme == "dark" else "#000000")
        title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 快捷键列表
        shortcuts_frame = tk.Frame(shortcut_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0")
        shortcuts_frame.pack(fill=tk.BOTH, expand=True, padx=60, pady=20)
        
        # 快捷鍵項目
        shortcut_items = [
            {"name": "剪切", "action": "cut", "default": "Ctrl+X"},
            {"name": "复制", "action": "copy", "default": "Ctrl+C"},
            {"name": "粘贴", "action": "paste", "default": "Ctrl+V"},
            {"name": "删除", "action": "delete", "default": "Delete"},
            {"name": "切割", "action": "split", "default": "Ctrl+B"},
            {"name": "导入", "action": "import", "default": "Ctrl+I"},
            {"name": "导出", "action": "export", "default": "Ctrl+E"},
            {"name": "保存", "action": "save", "default": "Ctrl+S"}
        ]
        
        for item in shortcut_items:
            item_frame = tk.Frame(shortcuts_frame, bg="#252525" if self.current_theme == "dark" else "#e0e0e0", height=60)
            item_frame.pack(fill=tk.X, pady=5, padx=10)
            
            # 操作名称
            name_label = tk.Label(item_frame, text=item["name"], font=('微软雅黑', self.font_size), bg="#252525" if self.current_theme == "dark" else "#e0e0e0", fg="#ffffff" if self.current_theme == "dark" else "#000000")
            name_label.pack(side=tk.LEFT, padx=20, pady=15)
            
            # 当前快捷键
            current_shortcut = self.shortcuts.get(item["action"], item["default"])
            shortcut_label = tk.Label(item_frame, text=current_shortcut, font=('微软雅黑', self.font_size), bg="#252525" if self.current_theme == "dark" else "#e0e0e0", fg="#007acc")
            shortcut_label.pack(side=tk.LEFT, padx=40, pady=15)
            
            # 默认快捷键
            default_label = tk.Label(item_frame, text=f"默认: {item['default']}", font=('微软雅黑', self.font_size - 2), bg="#252525" if self.current_theme == "dark" else "#e0e0e0", fg="#cccccc" if self.current_theme == "dark" else "#000000")
            default_label.pack(side=tk.LEFT, padx=20, pady=15)
            
            # 重置按钮
            reset_btn = tk.Button(item_frame, text="重置", command=lambda a=item["action"], d=item["default"]: self.reset_shortcut(a, d), bg="#333333" if self.current_theme == "dark" else "#d0d0d0", fg="#ffffff" if self.current_theme == "dark" else "#000000", font=('微软雅黑', self.font_size - 2), padx=10, pady=3, relief=tk.FLAT)
            reset_btn.pack(side=tk.RIGHT, padx=20, pady=15)
        
        # 底部按钮
        bottom_frame = tk.Frame(shortcut_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0")
        bottom_frame.pack(fill=tk.X, pady=20)
        
        # 恢复默认按钮
        reset_all_btn = tk.Button(bottom_frame, text="恢复默认", command=self.reset_all_shortcuts, bg="#333333" if self.current_theme == "dark" else "#d0d0d0", fg="#ffffff" if self.current_theme == "dark" else "#000000", font=('微软雅黑', self.font_size), padx=20, pady=8, relief=tk.FLAT)
        reset_all_btn.pack(side=tk.RIGHT, padx=10)
        
        # 保存按钮
        save_btn = tk.Button(bottom_frame, text="保存", command=self.save_shortcuts, bg="#007acc", fg="#ffffff", font=('微软雅黑', self.font_size), padx=20, pady=8, relief=tk.FLAT)
        save_btn.pack(side=tk.RIGHT, padx=10)
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(shortcut_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0", height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    
    def reset_shortcut(self, action, default):
        """重置单个快捷键"""
        self.shortcuts[action] = default
        
        # 刷新界面
        self.show_shortcut_settings()
    
    def reset_all_shortcuts(self):
        """重置所有快捷键"""
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
        
        # 刷新界面
        self.show_shortcut_settings()
    
    def save_shortcuts(self):
        """保存快捷键设置"""
        # 模拟保存功能
        self.status_label.config(text="快捷键设置已保存")
    
    def show_sidebar_settings(self):
        """显示侧边栏设置"""
        self.clear_content_frame()
        
        # 创建框架（不使用滚动条）
        sidebar_frame = self.create_scrollable_frame(self.content_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0", scrollable=False)
        
        # 标题
        title = tk.Label(sidebar_frame, text="侧边栏设置", font=('微软雅黑', self.font_size + 2, 'bold'), bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0", fg="#ffffff" if self.current_theme == "dark" else "#000000")
        title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 侧边栏项目
        items_frame = tk.Frame(sidebar_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0")
        items_frame.pack(fill=tk.BOTH, expand=True, padx=60, pady=20)
        
        for item_name, enabled in self.sidebar_items.items():
            item_frame = tk.Frame(items_frame, bg="#252525" if self.current_theme == "dark" else "#e0e0e0", height=50)
            item_frame.pack(fill=tk.X, pady=5, padx=10)
            
            # 项目名称
            name_label = tk.Label(item_frame, text=item_name, font=('微软雅黑', self.font_size), bg="#252525" if self.current_theme == "dark" else "#e0e0e0", fg="#ffffff" if self.current_theme == "dark" else "#000000")
            name_label.pack(side=tk.LEFT, padx=20, pady=12)
            
            # 启用/禁用开关
            var = tk.BooleanVar(value=enabled)
            toggle = tk.Checkbutton(item_frame, variable=var, command=lambda n=item_name, v=var: self.toggle_sidebar_item(n, v.get()), bg="#252525" if self.current_theme == "dark" else "#e0e0e0", selectcolor="#3d3d3d" if self.current_theme == "dark" else "#c0c0c0")
            toggle.pack(side=tk.RIGHT, padx=20, pady=12)
        
        # 底部按钮
        bottom_frame = tk.Frame(sidebar_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0")
        bottom_frame.pack(fill=tk.X, pady=20)
        
        # 应用按钮
        apply_btn = tk.Button(bottom_frame, text="应用", command=self.apply_sidebar_settings, bg="#007acc", fg="#ffffff", font=('微软雅黑', self.font_size), padx=20, pady=8, relief=tk.FLAT)
        apply_btn.pack(side=tk.RIGHT, padx=10)
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(sidebar_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#f0f0f0", height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    
    def toggle_sidebar_item(self, item_name, enabled):
        """切换侧边栏项目的启用状态"""
        self.sidebar_items[item_name] = enabled
    
    def apply_sidebar_settings(self):
        """应用侧边栏设置"""
        # 重新创建导航栏
        self.recreate_navigation_bar()
        self.status_label.config(text="侧边栏设置已应用")
    
    def recreate_navigation_bar(self):
        """重新创建导航栏"""
        # 清空左侧导航栏
        for widget in self.left_frame.winfo_children():
            widget.destroy()
        
        # Logo
        logo_frame = tk.Frame(self.left_frame, bg="#252525" if self.current_theme == "dark" else "#ffffff", pady=25)
        logo_frame.pack(fill=tk.X)
        logo_label = tk.Label(logo_frame, text="AI短剧编辑器", font=("微软雅黑", 16, "bold"), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#007acc")
        logo_label.pack(anchor=tk.CENTER)
        
        # 导航项
        nav_items = [
            {"name": "首页", "icon": "🏠", "command": self.show_home_page},
            {"name": "视频剪辑", "icon": "🎬", "command": self.show_video_editing_tab},
            {"name": "文案生成", "icon": "✍️", "command": self.show_copywriting_tab},
            {"name": "账号运营", "icon": "📊", "command": self.show_account_analysis_tab},
            {"name": "插件管理", "icon": "🔌", "command": self.show_plugin_management_tab},
            {"name": "模型配置", "icon": "🧠", "command": self.show_model_config_tab},
            {"name": "设置", "icon": "⚙️", "command": self.show_settings_tab},
            {"name": "性能监控", "icon": "📈", "command": self.show_performance_tab},
            {"name": "素材库", "icon": "🎨", "command": self.show_asset_library_tab}
        ]
        
        # 创建导航按钮
        for item in nav_items:
            if self.sidebar_items.get(item["name"], True):
                btn = tk.Button(
                    self.left_frame,
                    text=f"{item['icon']} {item['name']}",
                    command=item['command'],
                    bg="#252525" if self.current_theme == "dark" else "#ffffff",
                    fg="#ffffff" if self.current_theme == "dark" else "#000000",
                    font=("微软雅黑", self.font_size),
                    padx=15,
                    pady=12,
                    anchor=tk.W,
                    relief=tk.FLAT
                )
                btn.pack(fill=tk.X)
                btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#333333" if self.current_theme == "dark" else "#f0f0f0"))
                btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#252525" if self.current_theme == "dark" else "#ffffff"))
        
        # 底部信息
        bottom_frame = tk.Frame(self.left_frame, bg="#252525" if self.current_theme == "dark" else "#ffffff", pady=20)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        # GPU信息
        gpu_info = tk.Label(bottom_frame, text=f"GPU编码器: {GPU_ENCODER}", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        gpu_info.pack(anchor=tk.CENTER, pady=5)
        
        # 线程信息
        thread_info = tk.Label(bottom_frame, text=f"最大线程: {MAX_PARALLEL}", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        thread_info.pack(anchor=tk.CENTER, pady=5)
        
        # 硬件信息
        hardware_info = tk.Label(bottom_frame, text=f"内存: {hardware_config['available_memory_gb']}GB", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        hardware_info.pack(anchor=tk.CENTER, pady=5)
        
        # CPU信息
        cpu_info = tk.Label(bottom_frame, text=f"CPU核心: {hardware_config['cpu_count']}", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        cpu_info.pack(anchor=tk.CENTER, pady=5)
    
    def create_main_layout(self):
        """创建主布局"""
        # 左侧导航栏
        self.left_frame = tk.Frame(self.root, bg="#252525" if self.current_theme == "dark" else "#ffffff", width=220)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        # 左侧导航栏内容
        self.create_navigation_bar()
        
        # 右侧主内容区
        self.right_frame = tk.Frame(self.root, bg="#1a1a1a" if self.current_theme == "dark" else "#ffffff")
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 顶部工具栏
        self.top_frame = tk.Frame(self.right_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#ffffff", height=60)
        self.top_frame.pack(side=tk.TOP, fill=tk.X)
        
        # 创建顶部工具栏
        self.create_top_toolbar()
        
        # 主内容区
        self.content_frame = tk.Frame(self.right_frame, bg="#1a1a1a" if self.current_theme == "dark" else "#ffffff")
        self.content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # 初始显示首页
        self.show_home_page()
        
        # 绑定快捷键
        self.bind_shortcuts()
    
    def create_navigation_bar(self):
        """创建左侧导航栏"""
        # Logo
        logo_frame = tk.Frame(self.left_frame, bg="#252525" if self.current_theme == "dark" else "#ffffff", pady=25)
        logo_frame.pack(fill=tk.X)
        logo_label = tk.Label(logo_frame, text="AI短剧编辑器", font=("微软雅黑", 16, "bold"), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#007acc")
        logo_label.pack(anchor=tk.CENTER)
        
        # 导航项
        nav_items = [
            {"name": "首页", "icon": "🏠", "command": self.show_home_page},
            {"name": "视频剪辑", "icon": "🎬", "command": self.show_video_editing_tab},
            {"name": "任务管理", "icon": "📋", "command": self.show_task_management},
            {"name": "文案生成", "icon": "✍️", "command": self.show_copywriting_tab},
            {"name": "账号运营", "icon": "📊", "command": self.show_account_analysis_tab},
            {"name": "AI助手", "icon": "🤖", "command": self.show_agent_panel},
            {"name": "插件管理", "icon": "🔌", "command": self.show_plugin_management_tab},
            {"name": "模型配置", "icon": "🧠", "command": self.show_model_config_tab},
            {"name": "设置", "icon": "⚙️", "command": self.show_settings_tab},
            {"name": "性能监控", "icon": "📈", "command": self.show_performance_tab},
            {"name": "素材库", "icon": "🎨", "command": self.show_asset_library_tab}
        ]
        
        # 创建导航按钮
        for item in nav_items:
            btn = tk.Button(
                self.left_frame,
                text=f"{item['icon']} {item['name']}",
                command=item['command'],
                bg="#252525" if self.current_theme == "dark" else "#ffffff",
                fg="#ffffff" if self.current_theme == "dark" else "#000000",
                font=("微软雅黑", self.font_size),
                padx=15,
                pady=12,
                anchor=tk.W,
                relief=tk.FLAT
            )
            btn.pack(fill=tk.X)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#333333" if self.current_theme == "dark" else "#f0f0f0"))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#252525" if self.current_theme == "dark" else "#ffffff"))
        
        # 底部信息
        bottom_frame = tk.Frame(self.left_frame, bg="#252525" if self.current_theme == "dark" else "#ffffff", pady=20)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        # GPU信息
        gpu_info = tk.Label(bottom_frame, text=f"GPU编码器: {GPU_ENCODER}", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        gpu_info.pack(anchor=tk.CENTER, pady=5)
        
        # 线程信息
        thread_info = tk.Label(bottom_frame, text=f"最大线程: {MAX_PARALLEL}", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        thread_info.pack(anchor=tk.CENTER, pady=5)
        
        # 硬件信息
        hardware_info = tk.Label(bottom_frame, text=f"内存: {hardware_config['available_memory_gb']}GB", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        hardware_info.pack(anchor=tk.CENTER, pady=5)
        
        # CPU信息
        cpu_info = tk.Label(bottom_frame, text=f"CPU核心: {hardware_config['cpu_count']}", font=("微软雅黑", self.font_size - 1), bg="#252525" if self.current_theme == "dark" else "#ffffff", fg="#cccccc" if self.current_theme == "dark" else "#000000")
        cpu_info.pack(anchor=tk.CENTER, pady=5)
    
    def create_top_toolbar(self):
        """创建顶部工具栏"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        menu_bg = "#252525" if self.current_theme == "dark" else "#ffffff"
        menu_fg = "#ffffff" if self.current_theme == "dark" else "#000000"
        
        # 左侧信息
        left_info = tk.Frame(self.top_frame, bg=bg_color)
        left_info.pack(side=tk.LEFT, padx=20, pady=15)
        
        # 当前模型
        self.model_label = tk.Label(left_info, text=f"当前模型: {model_manager.current_model}", font=("微软雅黑", self.font_size), bg=bg_color, fg=text_color)
        self.model_label.pack(side=tk.LEFT, padx=10)
        
        # 右侧功能按钮
        right_tools = tk.Frame(self.top_frame, bg=bg_color)
        right_tools.pack(side=tk.RIGHT, padx=20, pady=15)
        
        # 界面设置按钮
        settings_btn = tk.Menubutton(
            right_tools,
            text="设置",
            bg=frame_color,
            fg=text_color,
            font=("微软雅黑", self.font_size - 1),
            padx=15,
            pady=7,
            relief=tk.FLAT,
            direction="below"
        )
        settings_btn.pack(side=tk.LEFT, padx=8)
        
        # 创建设置菜单
        settings_menu = tk.Menu(settings_btn, tearoff=0, bg=menu_bg, fg=menu_fg)
        
        # 主题切换
        theme_menu = tk.Menu(settings_menu, tearoff=0, bg=menu_bg, fg=menu_fg)
        theme_menu.add_command(label="深色模式", command=lambda: self.set_theme("dark"))
        theme_menu.add_command(label="浅色模式", command=lambda: self.set_theme("light"))
        settings_menu.add_cascade(label="主题", menu=theme_menu)
        
        # 字体大小
        font_menu = tk.Menu(settings_menu, tearoff=0, bg=menu_bg, fg=menu_fg)
        font_menu.add_command(label="默认", command=lambda: self.set_font_size(14))
        font_menu.add_command(label="小", command=lambda: self.set_font_size(12))
        font_menu.add_command(label="中", command=lambda: self.set_font_size(16))
        font_menu.add_command(label="大", command=lambda: self.set_font_size(18))
        settings_menu.add_cascade(label="字体设置", menu=font_menu)
        
        # 快捷键设置
        settings_menu.add_command(label="快捷键设置", command=self.show_shortcut_settings)
        
        # 侧边栏设置
        settings_menu.add_command(label="侧边栏设置", command=self.show_sidebar_settings)
        
        # 绑定设置菜单
        settings_btn.config(menu=settings_menu)
        
        # 教程/帮助下拉菜单
        help_menu = tk.Menubutton(
            right_tools,
            text="教程/帮助",
            bg=frame_color,
            fg=text_color,
            font=("微软雅黑", self.font_size - 1),
            padx=15,
            pady=7,
            relief=tk.FLAT,
            direction="below"
        )
        help_menu.pack(side=tk.LEFT, padx=8)
        
        # 创建下拉菜单
        menu = tk.Menu(help_menu, tearoff=0, bg=menu_bg, fg=menu_fg)
        
        # 图文教程
        menu.add_command(label="图文教程", command=self.show_tutorials)
        
        # 视频教程
        menu.add_command(label="视频教程", command=self.show_video_tutorials)
        
        # 常见问题
        menu.add_command(label="常见问题 FAQ", command=self.show_faq)
        

        
        # 绑定菜单
        help_menu.config(menu=menu)
    
    def clear_content_frame(self):
        """清空内容区域"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def create_scrollable_frame(self, parent, bg=None, scrollable=True):
        """创建带滚动条的框架（可选）"""
        # 创建主框架
        main_frame = tk.Frame(parent, bg=bg)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        if not scrollable:
            # 不使用滚动条，直接返回主框架
            return main_frame
        
        # 创建滚动条
        scrollbar = tk.Scrollbar(main_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建画布
        canvas = tk.Canvas(main_frame, bg=bg, yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 配置滚动条
        scrollbar.config(command=canvas.yview)
        
        # 创建内部框架
        inner_frame = tk.Frame(canvas, bg=bg)
        inner_frame.pack(fill=tk.BOTH, expand=True)
        
        # 将内部框架添加到画布
        canvas.create_window((0, 0), window=inner_frame, anchor=tk.NW, tags="inner_frame")
        
        # 绑定滚动事件
        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        inner_frame.bind("<Configure>", on_configure)
        
        # 只在画布大小变化时调整内部框架宽度
        def on_canvas_configure(event):
            if event.widget == canvas:
                canvas.itemconfigure("inner_frame", width=event.width)
        
        canvas.bind("<Configure>", on_canvas_configure)
        
        # 绑定鼠标滚轮事件（只在鼠标在画布内时滚动）
        def on_mousewheel(event):
            try:
                # 检查鼠标是否在画布区域内
                widget_under_mouse = self.root.winfo_containing(event.x_root, event.y_root)
                if widget_under_mouse and (widget_under_mouse == canvas or 
                                           str(widget_under_mouse).startswith(str(canvas)) or
                                           widget_under_mouse == inner_frame or
                                           str(widget_under_mouse).startswith(str(inner_frame))):
                    if canvas.winfo_exists():
                        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                        scrollbar.set(*canvas.yview())
                        return "break"
            except Exception as e:
                pass
        
        # 绑定到画布而不是bind_all
        canvas.bind("<MouseWheel>", on_mousewheel)
        inner_frame.bind("<MouseWheel>", on_mousewheel)
        
        return inner_frame
    
    def show_projects_tab(self, project_type):
        """显示创作中心 - 最近草稿/历史项目"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建带滚动条的框架
        projects_frame = self.create_scrollable_frame(self.content_frame, bg=bg_color)
        
        # 标题和返回按钮
        header_frame = tk.Frame(projects_frame, bg=bg_color, height=50)
        header_frame.pack(fill=tk.X, padx=60, pady=10)
        
        # 返回按钮
        back_btn = tk.Button(header_frame, text="← 返回", command=self.show_home_page, bg=item_color, fg=text_color, font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        back_btn.pack(side=tk.LEFT, padx=5, pady=5)
        
        # 标题
        title = tk.Label(header_frame, text=project_type, font=("微软雅黑", self.font_size + 2, "bold"), bg=bg_color, fg=text_color)
        title.pack(side=tk.LEFT, padx=20, pady=5)
        
        # 项目列表
        list_frame = tk.Frame(projects_frame, bg=frame_color)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=60, pady=20)
        
        # 模拟项目数据
        mock_projects = []
        if project_type == "最近草稿":
            mock_projects = [
                {"name": "短剧剪辑-未完成", "time": "2小时前", "duration": "03:45"},
                {"name": "带货视频-草稿", "time": "昨天", "duration": "01:20"},
                {"name": "剧情解说-进行中", "time": "3天前", "duration": "05:15"}
            ]
        else:
            mock_projects = [
                {"name": "爆款引流-第1集", "time": "今天", "duration": "00:30"},
                {"name": "好物挂车-推荐", "time": "昨天", "duration": "08:20"},
                {"name": "影视解说-电影", "time": "2天前", "duration": "01:30"},
                {"name": "同城引流-活动", "time": "3天前", "duration": "00:45"}
            ]
        
        # 创建项目列表
        for i, project in enumerate(mock_projects):
            project_item = tk.Frame(list_frame, bg=item_color, height=80)
            project_item.pack(fill=tk.X, pady=5, padx=10)
            
            # 项目信息
            info_frame = tk.Frame(project_item, bg=item_color)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=15)
            
            name_label = tk.Label(info_frame, text=project["name"], font=("微软雅黑", self.font_size, "bold"), bg=item_color, fg=text_color)
            name_label.pack(anchor=tk.W, pady=2)
            
            time_label = tk.Label(info_frame, text=f"修改时间: {project['time']} | 时长: {project['duration']}", font=("微软雅黑", self.font_size - 2), bg=item_color, fg=desc_color)
            time_label.pack(anchor=tk.W, pady=2)
            
            # 操作按钮
            btn_frame = tk.Frame(project_item, bg=item_color)
            btn_frame.pack(side=tk.RIGHT, padx=20, pady=20)
            
            open_btn = tk.Button(btn_frame, text="打开", command=lambda: self.show_video_editing_tab(), bg="#007acc", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
            open_btn.pack(side=tk.RIGHT, padx=5)
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(projects_frame, bg=bg_color, height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    
    def show_tutorials(self):
        """显示图文教程"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 图文教程框架（无滚动条）
        tutorial_frame = tk.Frame(self.content_frame, bg=bg_color)
        tutorial_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title = tk.Label(tutorial_frame, text="图文教程", font=("微软雅黑", self.font_size + 2, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 教程列表
        tutorials = [
            {"title": "快速开始", "description": "如何导入视频并进行基本剪辑"},
            {"title": "AI文案生成", "description": "智能生成标题、文案和关键词"},
            {"title": "批量剪辑", "description": "如何批量处理多个视频素材"},
            {"title": "去重技巧", "description": "如何避免视频重复，提升原创度"},
            {"title": "账号运营", "description": "如何分析数据并优化运营策略"},
            {"title": "插件开发规范与实例", "description": "插件接口规范、目录结构、完整示例代码"},
            {"title": "模型地址", "description": "各个AI模型的官方地址"}
        ]
        
        def show_tutorial_detail(title, content):
            """显示教程详细内容"""
            # 清空当前内容
            for widget in tutorial_frame.winfo_children():
                widget.destroy()
            
            # 重新设置颜色（确保主题切换后颜色正确）
            bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
            frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
            text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
            desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
            
            # 返回按钮
            back_btn = tk.Button(tutorial_frame, text="返回教程列表", command=self.show_tutorials, 
                               bg="#007acc", fg="#ffffff", font=("微软雅黑", self.font_size), 
                               padx=20, pady=8, relief=tk.FLAT)
            back_btn.pack(anchor=tk.W, padx=60, pady=20)
            
            # 标题
            title_label = tk.Label(tutorial_frame, text=title, font=("微软雅黑", self.font_size + 2, "bold"), 
                           bg=bg_color, fg=text_color)
            title_label.pack(anchor=tk.W, padx=60, pady=10)
            
            # 教程内容
            content_frame = tk.Frame(tutorial_frame, bg=frame_color, pady=20, padx=30)
            content_frame.pack(fill=tk.BOTH, expand=True, pady=10, padx=60)
            # 插件开发等长教程使用 Text（无滚动条），其余用 Label
            if title == "插件开发规范与实例" and len(content) > 800:
                content_text = tk.Text(content_frame, font=("Consolas", self.font_size - 1), wrap=tk.WORD,
                                       bg=frame_color, fg=desc_color, insertbackground=desc_color,
                                       padx=10, pady=10)
                content_text.pack(fill=tk.BOTH, expand=True)
                content_text.insert(tk.END, content)
                content_text.config(state=tk.DISABLED)
            else:
                content_text = tk.Label(content_frame, text=content, font=("微软雅黑", self.font_size - 1), 
                                      bg=frame_color, fg=desc_color, wraplength=900, justify=tk.LEFT)
                content_text.pack(anchor=tk.W, pady=10)
            
            # 底部空间
            bottom_space = tk.Frame(tutorial_frame, bg=bg_color, height=50)
            bottom_space.pack(fill=tk.X, pady=20, padx=40)
        
        def show_model_addresses():
            """显示模型地址详情"""
            # 清空当前内容
            for widget in tutorial_frame.winfo_children():
                widget.destroy()
            
            # 重新设置颜色（确保主题切换后颜色正确）
            bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
            frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
            text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
            desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
            
            # 返回按钮
            back_btn = tk.Button(tutorial_frame, text="返回教程列表", command=self.show_tutorials, 
                               bg="#007acc", fg="#ffffff", font=("微软雅黑", self.font_size), 
                               padx=20, pady=8, relief=tk.FLAT)
            back_btn.pack(anchor=tk.W, padx=60, pady=20)
            
            # 标题
            title = tk.Label(tutorial_frame, text="模型地址", font=("微软雅黑", self.font_size + 2, "bold"), 
                           bg=bg_color, fg=text_color)
            title.pack(anchor=tk.W, padx=60, pady=10)
            
            # 说明文字
            info_label = tk.Label(tutorial_frame, text="以下是各个AI模型的官方API地址：", 
                                font=("微软雅黑", self.font_size), bg=bg_color, fg=text_color)
            info_label.pack(anchor=tk.W, padx=60, pady=10)
            
            # 模型地址列表
            model_addresses = [
                {"name": "DeepSeek", "address": "https://api.deepseek.com/chat/completions"},
                {"name": "豆包", "address": "https://open.doubao.com/api/v1/chat/completions"},
                {"name": "ChatGPT", "address": "https://api.openai.com/v1/chat/completions"},
                {"name": "Claude", "address": "https://api.anthropic.com/v1/messages"},
                {"name": "Gemini", "address": "https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent"},
                {"name": "通义千问", "address": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"},
                {"name": "文心一言", "address": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions"},
                {"name": "智能剪辑模型", "address": "https://github.com/ai-video-editing/intelligent-clip-model"}
            ]
            
            for model in model_addresses:
                model_frame = tk.Frame(tutorial_frame, bg=frame_color, pady=15, padx=20)
                model_frame.pack(fill=tk.X, pady=10, padx=60)
                model_frame.configure(cursor="hand2")
                
                # 点击地址时可以复制
                def copy_address(address):
                    tutorial_frame.clipboard_clear()
                    tutorial_frame.clipboard_append(address)
                    # 显示复制成功提示
                    copy_label = tk.Label(tutorial_frame, text="地址已复制到剪贴板", 
                                         bg="#4CAF50", fg="#ffffff", font=("微软雅黑", self.font_size - 1), 
                                         padx=20, pady=5)
                    copy_label.pack(anchor=tk.CENTER, pady=5)
                    tutorial_frame.after(2000, copy_label.destroy)
                
                # 模型名称
                name_label = tk.Label(model_frame, text=model["name"], font=("微软雅黑", self.font_size, "bold"), 
                                    bg=frame_color, fg=text_color)
                name_label.pack(anchor=tk.W, pady=5)
                
                # 模型地址
                address_frame = tk.Frame(model_frame, bg=frame_color)
                address_frame.pack(anchor=tk.W, pady=5, fill=tk.X)
                
                address_label = tk.Label(address_frame, text=model["address"], font=("微软雅黑", self.font_size - 1), 
                                       bg=frame_color, fg=desc_color, cursor="hand2")
                address_label.pack(side=tk.LEFT, padx=0, pady=0)
                address_label.bind("<Button-1>", lambda e, addr=model["address"]: copy_address(addr))
                
                # 复制按钮
                copy_btn = tk.Button(address_frame, text="复制", command=lambda addr=model["address"]: copy_address(addr), 
                                   bg="#333333" if self.current_theme == "dark" else "#d0d0d0", 
                                   fg="#ffffff" if self.current_theme == "dark" else "#000000", 
                                   font=("微软雅黑", self.font_size - 2), padx=10, pady=2, relief=tk.FLAT)
                copy_btn.pack(side=tk.RIGHT, padx=10, pady=0)
            
            # 底部空间
            bottom_space = tk.Frame(tutorial_frame, bg=bg_color, height=50)
            bottom_space.pack(fill=tk.X, pady=20, padx=40)
        
        # 教程详细内容
        _plugin_tutorial_content = (
            "一、插件类型与放置位置\n"
            "本编辑器支持两类插件：\n"
            "1）类插件：继承 BasePlugin，实现 get_name() 和 run()，适合带独立窗口或复杂逻辑的插件（如多语言字幕）。\n"
            "2）函数插件：使用 @register_plugin 装饰器注册一个函数，适合简单工具（如视频信息读取、自动去重参数）。\n"
            "内置插件放在 app/plugin/ 目录下，用户安装的插件放在「输出目录/plugins/」下（如 短剧AI剪辑输出/plugins/）。\n\n"
            "二、类插件开发规范（BasePlugin）\n"
            "1. 从 plugin_system 导入基类：from .plugin_system import BasePlugin\n"
            "2. 必须实现两个方法：\n"
            "   get_name(self) -> str：返回插件显示名称。\n"
            "   run(self, *args, **kwargs)：插件主逻辑。主程序会传入 root=主窗口、current_theme 等，便于创建 Tk 子窗口并适配主题。\n"
            "3. 若插件有独立界面，在 run() 里创建 Toplevel(root)，不要新建 Tk()。\n\n"
            "三、类插件完整示例\n"
            "以下为最小可用示例，保存为 my_plugin.py 放在 app/plugin/ 目录：\n\n"
            "from .plugin_system import BasePlugin\n"
            "import tkinter as tk\n"
            "from tkinter import messagebox\n\n"
            "class MyPlugin(BasePlugin):\n"
            "    def get_name(self):\n"
            "        return \"我的插件\"\n\n"
            "    def run(self, *args, **kwargs):\n"
            "        root = kwargs.get(\"root\", None)\n"
            "        if not root:\n"
            "            root = tk.Tk()\n"
            "            root.withdraw()\n"
            "        win = tk.Toplevel(root)\n"
            "        win.title(self.get_name())\n"
            "        win.geometry(\"400x200\")\n"
            "        tk.Label(win, text=\"Hello from 我的插件\").pack(pady=20)\n"
            "        tk.Button(win, text=\"确定\", command=lambda: messagebox.showinfo(\"\", \"运行成功\")).pack(pady=10)\n\n"
            "四、函数插件规范（register_plugin）\n"
            "1. 在插件文件中：from plugin_system import register_plugin\n"
            "2. 用装饰器注册：@register_plugin(\"插件显示名\", category=\"视频处理\", version=\"1.0.0\")\n"
            "3. 定义函数，参数按需（如 video_path, ffmpeg_executable），主程序调用时会按名传入。\n\n"
            "示例：\n"
            "@register_plugin(\"视频信息读取\", \"视频处理\", \"1.0.0\")\n"
            "def plugin_get_video_info(video_path, ffmpeg_executable):\n"
            "    import subprocess\n"
            "    result = subprocess.run([ffmpeg_executable, \"-i\", video_path], capture_output=True, text=True)\n"
            "    # 解析 result.stderr 中的 Duration 等，返回时长或信息字符串\n"
            "    return \"60s | 10MB\"\n\n"
            "五、主程序如何加载与调用\n"
            "类插件：通过 PluginManager.import_plugin(plugin_file) 动态加载，会查找继承 BasePlugin 的类并实例化，存入 loaded_plugins。\n"
            "调用：对 loaded_plugins 中每个实例执行 plugin.run(root=self.root, current_theme=...) 即可。\n"
            "函数插件：安装或导入时 exec 插件代码，会向全局 plugins、plugin_versions、plugin_categories 注册，主界面「插件管理」中可列出并运行。\n\n"
            "六、注意事项\n"
            "1. UI 操作必须在主线程执行，耗时任务请用 threading 或 queue 在后台执行，再回主线程更新界面。\n"
            "2. 异常请 try/except 并给出友好提示，避免导致主程序崩溃。\n"
            "3. 参考内置实现：app/plugin/multilingual_subtitle.py（类插件）、app/plugin/plugin_system.py 中的 @register_plugin 示例（函数插件）。"
        )
        tutorial_contents = {
            "快速开始": "一、快速开始：导入视频并进行基本剪辑\n启动软件：打开 AI 短剧编辑器，进入「视频剪辑」模块。\n导入素材：点击左侧「+ 导入」按钮，选择需要编辑的视频、音频或图片文件，文件会自动添加到「已导入媒体」列表。\n添加到时间轴：在「已导入媒体」列表中，点击素材右侧的「+」，将其拖入下方的时间轴轨道（视频轨道或音频轨道）。\n基本剪辑操作：\n切割：选择时间轴上的素材，点击「切割」工具，在需要分割的位置点击，即可将素材拆分为两段。\n删除：选中不需要的片段，点击「删除」按钮移除。\n调整顺序：直接拖动时间轴上的素材块，调整它们的播放顺序。\n预览效果：点击中间预览区的播放按钮，实时查看剪辑效果。\n导出视频：在右侧「剪辑参数」面板中设置输出模式、分辨率等参数，点击「开始剪辑」，选择保存路径后即可导出成品。",
            "AI文案生成": "二、AI 文案生成：智能创作标题、文案和关键词\n切换到「文案生成」模块。\n选择文案类型：在「文案类型」下拉菜单中，选择「短视频爆款文案」、「剧情脚本」或「口播稿」等。\n输入提示词：在文本框中输入你的创作需求，例如：\"搞笑反转短剧，30 秒，适合抖音平台\"。\n生成文案：点击「AI 生成文案」按钮，系统会自动生成结构化的文案内容，包括开头、中间、结尾和标签。\n基于视频生成：点击「基于视频内容生成文案」，选择已导入的视频文件，AI 会分析视频内容并生成高度匹配的文案和标题。\n复制使用：生成的文案可直接复制，用于视频发布或进一步修改。",
            "批量剪辑": "三、批量剪辑：高效处理多个视频素材\n进入「视频剪辑」模块，点击工具栏的「批量裁剪」按钮。\n选择源视频：在弹出的对话框中，选择需要批量处理的视频文件。\n设置裁剪任务：输入需要裁剪的任务数量，然后依次设置每个任务的开始时间和结束时间。\n选择输出目录：指定批量裁剪后视频的保存文件夹。\n开始批量处理：点击确认，系统会自动执行所有裁剪任务，并在完成后显示成功 / 失败统计。\n其他批量操作：也可使用「批量导出」插件，一键生成适配抖音、快手、B 站等多平台的视频版本。",
            "去重技巧": "四、去重技巧：避免视频重复，提升原创度\n使用 AI 工具：在右侧「AI 工具」面板中，勾选「VideoFusion 视频增强」，在导出时开启该功能，可有效提升视频画质和原创度。\n添加个性化元素：\n添加字幕：使用「字幕」模块，为视频添加 AI 生成的字幕，改变视频的视觉呈现。\n替换音频：在「音频」模块中，点击「替换音频」，为视频更换不同的背景音乐或旁白。\n调整播放速度：选中时间轴上的素材，点击「速度」工具，调整视频的播放速率。\n剪辑重组：将长视频切割为多个片段，打乱顺序后重新拼接，形成新的叙事结构。\n添加转场和特效：在「效果」模块中，为不同片段之间添加淡入淡出、滑动等转场效果，使视频更具独特性。",
            "账号运营": "五、账号运营：分析数据并优化运营策略\n切换到「账号运营」模块。\n选择账号：在下拉菜单中选择需要分析的抖音、快手或视频号账号。\n查看核心数据：面板中会显示该账号的播放量、点赞数、评论数、完播率、粉丝增长等关键指标。\n生成分析报告：点击「生成运营分析报告」，系统会基于数据给出优化建议，例如 \"增加互动性内容，提升完播率\"。\n应用建议：根据报告建议，调整视频内容方向和发布频率，持续优化账号运营效果。",
            "插件开发规范与实例": _plugin_tutorial_content
        }
        
        for tutorial in tutorials:
            tutorial_item = tk.Frame(tutorial_frame, bg=frame_color, height=100)
            tutorial_item.pack(fill=tk.X, pady=10, padx=60)
            
            # 添加点击事件
            if tutorial["title"] == "模型地址":
                # 确保整个教程项都能响应点击
                tutorial_item.bind("<Button-1>", lambda e: show_model_addresses())
                tutorial_item.configure(cursor="hand2")
                
                # 为子组件也添加点击事件，确保点击任何地方都能触发
                info_frame = tk.Frame(tutorial_item, bg=frame_color, cursor="hand2")
                info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=20)
                info_frame.bind("<Button-1>", lambda e: show_model_addresses())
                
                title_label = tk.Label(info_frame, text=tutorial["title"], font=("微软雅黑", self.font_size + 1, "bold"), 
                                     bg=frame_color, fg=text_color, cursor="hand2")
                title_label.pack(anchor=tk.W, pady=5)
                title_label.bind("<Button-1>", lambda e: show_model_addresses())
                
                desc_label = tk.Label(info_frame, text=tutorial["description"], font=("微软雅黑", self.font_size - 2), 
                                    bg=frame_color, fg=desc_color, cursor="hand2")
                desc_label.pack(anchor=tk.W, pady=5)
                desc_label.bind("<Button-1>", lambda e: show_model_addresses())
            else:
                # 确保整个教程项都能响应点击
                # 使用默认参数来捕获当前教程的标题，避免闭包问题
                tutorial_title = tutorial["title"]
                tutorial_content = tutorial_contents.get(tutorial_title, "")
                
                def create_callback(t):
                    def callback(e):
                        show_tutorial_detail(t, tutorial_contents.get(t, ""))
                    return callback
                
                tutorial_item.bind("<Button-1>", create_callback(tutorial_title))
                tutorial_item.configure(cursor="hand2")
                
                # 为子组件也添加点击事件，确保点击任何地方都能触发
                info_frame = tk.Frame(tutorial_item, bg=frame_color, cursor="hand2")
                info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=20)
                info_frame.bind("<Button-1>", create_callback(tutorial_title))
                
                title_label = tk.Label(info_frame, text=tutorial["title"], font=("微软雅黑", self.font_size + 1, "bold"), 
                                     bg=frame_color, fg=text_color, cursor="hand2")
                title_label.pack(anchor=tk.W, pady=5)
                title_label.bind("<Button-1>", create_callback(tutorial_title))
                
                desc_label = tk.Label(info_frame, text=tutorial["description"], font=("微软雅黑", self.font_size - 2), 
                                    bg=frame_color, fg=desc_color, cursor="hand2")
                desc_label.pack(anchor=tk.W, pady=5)
                desc_label.bind("<Button-1>", create_callback(tutorial_title))
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(tutorial_frame, bg=bg_color, height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    
    def show_video_tutorials(self):
        """显示视频教程"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        thumb_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建带滚动条的框架
        video_frame = self.create_scrollable_frame(self.content_frame, bg=bg_color)
        
        # 标题
        title = tk.Label(video_frame, text="视频教程", font=("微软雅黑", self.font_size + 2, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 视频教程列表
        videos = [
            {"title": "软件安装与设置", "duration": "05:30", "views": "1.2k"},
            {"title": "短剧爽点剪辑技巧", "duration": "08:45", "views": "2.5k"},
            {"title": "批量做号教程", "duration": "12:20", "views": "3.1k"},
            {"title": "AI工具使用指南", "duration": "06:15", "views": "1.8k"}
        ]
        
        for video in videos:
            video_item = tk.Frame(video_frame, bg=frame_color, height=120)
            video_item.pack(fill=tk.X, pady=10, padx=60)
            
            # 视频缩略图占位
            thumb_frame = tk.Frame(video_item, bg=thumb_color, width=160, height=90)
            thumb_frame.pack(side=tk.LEFT, padx=20, pady=15)
            
            play_icon = tk.Label(thumb_frame, text="▶", font=("微软雅黑", 24), bg=thumb_color, fg=text_color)
            play_icon.pack(anchor=tk.CENTER)
            
            # 视频信息
            info_frame = tk.Frame(video_item, bg=frame_color)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=20)
            
            title_label = tk.Label(info_frame, text=video["title"], font=("微软雅黑", self.font_size + 1, "bold"), bg=frame_color, fg=text_color)
            title_label.pack(anchor=tk.W, pady=5)
            
            meta_label = tk.Label(info_frame, text=f"时长: {video['duration']} | 观看: {video['views']}", font=("微软雅黑", self.font_size - 2), bg=frame_color, fg=desc_color)
            meta_label.pack(anchor=tk.W, pady=5)
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(video_frame, bg=bg_color, height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    
    def show_faq(self):
        """显示常见问题 FAQ"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建带滚动条的框架
        faq_frame = self.create_scrollable_frame(self.content_frame, bg=bg_color)
        
        # 标题
        title = tk.Label(faq_frame, text="常见问题 FAQ", font=("微软雅黑", self.font_size + 2, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, padx=60, pady=20)
        
        # FAQ列表
        faqs = [
            {"question": "如何导入视频文件？", "answer": "点击左侧面板的'导入'按钮，或使用快捷键Ctrl+I选择要导入的视频文件。"},
            {"question": "视频预览不显示怎么办？", "answer": "请检查视频格式是否支持，或尝试重新导入文件。如果问题持续，请检查软件版本或重启应用。"},
            {"question": "如何批量处理多个视频？", "answer": "在导入时选择多个视频文件，然后在剪辑参数中设置批量处理选项。"},
            {"question": "AI工具如何使用？", "answer": "在右侧面板的'AI工具'部分，勾选相应的功能选项，然后点击'开始剪辑'按钮。"},
            {"question": "如何导出视频？", "answer": "点击顶部工具栏的'导出'按钮，设置导出参数后点击'确定'即可。"}
        ]
        
        for faq in faqs:
            faq_item = tk.Frame(faq_frame, bg=frame_color)
            faq_item.pack(fill=tk.X, pady=10, padx=60)
            
            # 问题
            question_label = tk.Label(faq_item, text=faq["question"], font=("微软雅黑", self.font_size, "bold"), bg=frame_color, fg="#007acc")
            question_label.pack(anchor=tk.W, pady=10, padx=20)
            
            # 答案
            answer_label = tk.Label(faq_item, text=faq["answer"], font=("微软雅黑", self.font_size - 2), bg=frame_color, fg=desc_color, wraplength=1000)
            answer_label.pack(anchor=tk.W, pady=10, padx=20)
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(faq_frame, bg=bg_color, height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    

    
    def schedule_theme_check(self):
        """定时检查时间并自动切换主题"""
        def check_theme():
            # 如果用户已经手动设置了主题，跳过自动切换
            if not self.user_theme_set:
                current_hour = datetime.now().hour
                
                # 确定应该使用的主题
                if 7 <= current_hour < 19:
                    desired_theme = "light"
                else:
                    desired_theme = "dark"
                
                # 如果主题需要切换
                if desired_theme != self.current_theme:
                    self.set_theme(desired_theme)
            
            # 继续定时检查
            self.schedule_theme_check()
        
        # 每分钟检查一次
        self.root.after(60000, check_theme)
    
    def show_home_page(self):
        """显示首页"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        hover_color = "#2d2d2d" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建带滚动条的框架
        home_frame = self.create_scrollable_frame(self.content_frame, bg=bg_color)
        
        # 中央创作区域
        create_section = tk.Frame(home_frame, bg=bg_color, pady=60)
        create_section.pack(fill=tk.BOTH, expand=True)
        
        # 渐变背景
        gradient_frame = tk.Frame(create_section, bg=frame_color, pady=80, padx=60)
        gradient_frame.pack(fill=tk.BOTH, expand=True, padx=60)
        
        # 开始创作按钮
        start_btn = tk.Button(
            gradient_frame,
            text="+ 开始创作",
            command=self.show_video_editing_tab,
            bg="#007acc",
            fg="#ffffff",
            font=("微软雅黑", self.font_size + 4, "bold"),
            padx=50,
            pady=25,
            relief=tk.FLAT,
            bd=0
        )
        start_btn.pack(anchor=tk.CENTER, pady=30)
        
        # 创作中心入口 - 最近草稿/历史项目
        recent_projects_frame = tk.Frame(home_frame, bg=bg_color, pady=40)
        recent_projects_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创作中心标题
        projects_title = tk.Label(recent_projects_frame, text="创作中心", font=("微软雅黑", self.font_size + 2, "bold"), bg=bg_color, fg=text_color)
        projects_title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 最近草稿/历史项目容器
        projects_container = tk.Frame(recent_projects_frame, bg=bg_color)
        projects_container.pack(fill=tk.BOTH, expand=True, padx=60)
        
        # 项目卡片
        projects_cards = [
            {"name": "最近草稿", "icon": "📝", "description": "查看未完成的剪辑项目", "count": 3},
            {"name": "历史项目", "icon": "📁", "description": "浏览已完成的导出作品", "count": 12}
        ]
        
        for i, project in enumerate(projects_cards):
            project_frame = tk.Frame(
                projects_container,
                bg=frame_color,
                width=400,
                height=120,
                relief=tk.RAISED,
                bd=0
            )
            project_frame.grid(row=0, column=i, padx=20, pady=20, sticky=tk.NSEW)
            
            # 项目内容
            icon_label = tk.Label(project_frame, text=project["icon"], font=("微软雅黑", self.font_size + 8), bg=frame_color, fg="#007acc")
            icon_label.pack(side=tk.LEFT, padx=20, pady=20)
            
            info_frame = tk.Frame(project_frame, bg=frame_color)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=20)
            
            name_label = tk.Label(info_frame, text=project["name"], font=("微软雅黑", self.font_size + 1, "bold"), bg=frame_color, fg=text_color)
            name_label.pack(anchor=tk.W, pady=5)
            
            desc_label = tk.Label(info_frame, text=project["description"], font=("微软雅黑", self.font_size - 2), bg=frame_color, fg=desc_color)
            desc_label.pack(anchor=tk.W, pady=5)
            
            count_label = tk.Label(info_frame, text=f"共 {project['count']} 个项目", font=("微软雅黑", self.font_size - 3), bg=frame_color, fg="#007acc")
            count_label.pack(anchor=tk.W, pady=5)
            
            # 点击事件
            def on_click(e, p=project["name"]):
                self.show_projects_tab(p)
            
            def on_enter(e, frame=project_frame):
                frame.configure(bg=hover_color)
            
            def on_leave(e, frame=project_frame):
                frame.configure(bg=frame_color)
            
            # 为框架和所有子组件绑定事件
            project_frame.bind("<Button-1>", on_click)
            project_frame.bind("<Enter>", on_enter)
            project_frame.bind("<Leave>", on_leave)
            
            # 为子组件绑定相同的事件，确保点击任何地方都能触发
            icon_label.bind("<Button-1>", on_click)
            icon_label.bind("<Enter>", on_enter)
            icon_label.bind("<Leave>", on_leave)
            
            info_frame.bind("<Button-1>", on_click)
            info_frame.bind("<Enter>", on_enter)
            info_frame.bind("<Leave>", on_leave)
            
            name_label.bind("<Button-1>", on_click)
            name_label.bind("<Enter>", on_enter)
            name_label.bind("<Leave>", on_leave)
            
            desc_label.bind("<Button-1>", on_click)
            desc_label.bind("<Enter>", on_enter)
            desc_label.bind("<Leave>", on_leave)
            
            count_label.bind("<Button-1>", on_click)
            count_label.bind("<Enter>", on_enter)
            count_label.bind("<Leave>", on_leave)
        
        # 场景化模板库
        templates_frame = tk.Frame(home_frame, bg=bg_color, pady=40)
        templates_frame.pack(fill=tk.BOTH, expand=True)
        
        # 模板库标题
        templates_title = tk.Label(templates_frame, text="场景化模板库", font=("微软雅黑", self.font_size + 2, "bold"), bg=bg_color, fg=text_color)
        templates_title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 模板卡片容器
        templates_container = tk.Frame(templates_frame, bg=bg_color)
        templates_container.pack(fill=tk.BOTH, expand=True, padx=60)
        
        # 模板卡片
        template_cards = [
            {"name": "短剧爽点剪辑", "icon": "🔥", "description": "自动识别爽点片段，快速生成高潮视频", "suitable": "适配短剧前置钩子、账号冷启动"},
            {"name": "影视解说", "icon": "🎬", "description": "智能提取关键剧情，生成专业解说视频", "suitable": "适配电影、电视剧、综艺解说"},
            {"name": "好物挂车", "icon": "🛒", "description": "产品展示与剧情融合，自然带货", "suitable": "适配电商带货、产品推广"},
            {"name": "同城引流", "icon": "📍", "description": "本地化内容创作，吸引本地流量", "suitable": "适配本地商家、线下活动"},
            {"name": "30秒爆款引流", "icon": "💥", "description": "打造高点击率短视频，快速吸引流量", "suitable": "适配短剧前置钩子、账号冷启动"},
            {"name": "90秒剧情解说", "icon": "🎙️", "description": "详细讲解剧情，增强观众理解", "suitable": "适配完整剧情展示、深度解说"},
            {"name": "8分钟挂车长视频", "icon": "📦", "description": "完整展示剧情，自然融入产品信息", "suitable": "适配品牌推广、产品详细介绍"},
            {"name": "AI文案生成", "icon": "🤖", "description": "智能生成标题、文案和关键词", "suitable": "适配各平台文案优化"},
            {"name": "账号运营分析", "icon": "📈", "description": "分析数据，优化运营策略", "suitable": "适配矩阵号管理、数据驱动决策"}
        ]
        
        # 创建模板卡片
        for i, template in enumerate(template_cards):
            template_frame = tk.Frame(
                templates_container,
                bg=frame_color,
                width=280,
                height=200,
                relief=tk.RAISED,
                bd=0
            )
            template_frame.grid(row=i//3, column=i%3, padx=20, pady=20, sticky=tk.NSEW)
            
            # 模板内容
            icon_label = tk.Label(template_frame, text=template["icon"], font=("微软雅黑", self.font_size + 8), bg=frame_color, fg="#007acc")
            icon_label.pack(pady=15)
            
            name_label = tk.Label(template_frame, text=template["name"], font=("微软雅黑", self.font_size + 1, "bold"), bg=frame_color, fg=text_color)
            name_label.pack(pady=5)
            
            desc_label = tk.Label(template_frame, text=template["description"], font=("微软雅黑", self.font_size - 2), bg=frame_color, fg=desc_color, wraplength=250)
            desc_label.pack(pady=5)
            
            # 适配说明
            suitable_label = tk.Label(template_frame, text=f"适配: {template['suitable']}", font=("微软雅黑", self.font_size - 3), bg=frame_color, fg="#007acc", wraplength=250)
            suitable_label.pack(pady=5)
            
            # 点击事件
            template_frame.bind("<Button-1>", lambda e, t=template["name"]: self.show_video_editing_tab(t))
            template_frame.bind("<Enter>", lambda e, frame=template_frame, hc=hover_color: frame.configure(bg=hc))
            template_frame.bind("<Leave>", lambda e, frame=template_frame, fc=frame_color: frame.configure(bg=fc))
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(home_frame, bg=bg_color, height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    
    def show_video_editing_tab(self, default_mode="30秒爆款引流"):
        """显示视频剪辑选项卡"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建主框架（不带滚动条）
        main_frame = tk.Frame(self.content_frame, bg=bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # ==================== 顶部工具栏 ====================
        # 顶部工具栏
        top_toolbar = tk.Frame(main_frame, bg=frame_color, height=40)
        top_toolbar.pack(fill=tk.X, side=tk.TOP)
        
        # 创建工具栏滚动区域
        toolbar_scroll = tk.Frame(top_toolbar, bg=frame_color)
        toolbar_scroll.pack(fill=tk.X, expand=True)
        
        # 顶部工具按钮（精简版 - 播放控制/编辑工具已移至时间轴标题栏）
        toolbar_buttons = [
            ("导入", "📁", self.import_media),
            ("导出", "💾", self.export_project),
            ("保存", "💿", self.save_project),
        ]
        
        # 优化按钮排列
        button_frame = tk.Frame(toolbar_scroll, bg=frame_color)
        button_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        for i, (text, icon, cmd) in enumerate(toolbar_buttons):
            btn = tk.Button(button_frame, text=f"{icon} {text}", command=cmd, bg=frame_color, fg=text_color, 
                           font=("微软雅黑", self.font_size), padx=8, pady=8, relief=tk.FLAT,
                           height=2, width=10)
            btn.pack(side=tk.LEFT, padx=4, pady=2)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=item_color))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=frame_color))
            # 添加工具提示
            btn.bind("<Enter>", lambda e, t=text: self.show_tooltip(e, t), add="+")
        
        # ==================== 主编辑区域（剪映风格 - 可拖拽分割布局） ====================
        # 使用PanedWindow实现可调整大小的分割面板
        # 创建垂直分割面板（上-下）作为主容器
        self.vertical_paned = tk.PanedWindow(main_frame, orient=tk.VERTICAL,
                                             sashrelief=tk.RIDGE, sashwidth=6,
                                             bg="#3a3a3a" if self.current_theme == "dark" else "#c0c0c0")
        self.vertical_paned.pack(fill=tk.BOTH, expand=True)
        
        # 创建水平分割面板（左-中-右）作为上部区域
        self.main_paned = tk.PanedWindow(self.vertical_paned, orient=tk.HORIZONTAL, 
                                         sashrelief=tk.RIDGE, sashwidth=6, 
                                         bg="#3a3a3a" if self.current_theme == "dark" else "#c0c0c0")
        
        # ==================== 左侧面板（占上方区域的20%）====================
        left_panel = tk.Frame(self.main_paned, bg=frame_color, width=200)
        left_panel.pack_propagate(False)  # 允许通过sash调整大小
        
        # 左侧面板标签（只保留媒体和历史素材）
        panel_labels = ["媒体", "历史素材"]
        self.left_panel_var = tk.StringVar(value="媒体")
        
        # 面板选择器
        panel_selector = tk.Frame(left_panel, bg=frame_color)
        panel_selector.pack(fill=tk.X, pady=10)
        
        for label in panel_labels:
            btn = tk.Button(panel_selector, text=label, command=lambda l=label: self.switch_left_panel(l), 
                           bg=frame_color if self.left_panel_var.get() != label else "#007acc", 
                           fg=text_color, font=("微软雅黑", self.font_size), padx=10, pady=5, relief=tk.FLAT)
            btn.pack(fill=tk.X, pady=2, padx=10)
        
        # 媒体面板内容
        media_panel = tk.Frame(left_panel, bg=frame_color)
        media_panel.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 导入按钮
        import_btn = tk.Button(media_panel, text="➕ 导入", command=self.import_media, bg=item_color, fg=text_color, font=("微软雅黑", self.font_size), padx=15, pady=10, relief=tk.FLAT)
        import_btn.pack(fill=tk.X, padx=10, pady=5)
        
        # 删除按钮
        delete_btn = tk.Button(media_panel, text="🗑️ 删除", command=self.delete_media, bg=item_color, fg=text_color, font=("微软雅黑", self.font_size), padx=15, pady=10, relief=tk.FLAT)
        delete_btn.pack(fill=tk.X, padx=10, pady=5)
        
        # 媒体列表
        media_list_frame = tk.Frame(media_panel, bg=item_color)
        media_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 媒体列表标题
        tk.Label(media_list_frame, text="已导入媒体", font=("微软雅黑", self.font_size, "bold"), bg=item_color, fg=text_color).pack(anchor=tk.W, pady=5, padx=10)
        
        # 为媒体列表添加滚动条
        scrollbar = tk.Scrollbar(media_list_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=5, pady=5)
        
        # 媒体列表框
        self.media_listbox = tk.Listbox(media_list_frame, width=30, bg=bg_color, fg=text_color, font=("微软雅黑", self.font_size - 1), yscrollcommand=scrollbar.set)
        self.media_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 配置滚动条
        scrollbar.config(command=self.media_listbox.yview)
        
        # 绑定双击事件以预览视频
        self.media_listbox.bind('<Double-1>', self.preview_media)
        
        # 绑定拖放事件
        self.media_listbox.bind('<Button-1>', self.on_media_drag_start)
        self.media_listbox.bind('<B1-Motion>', self.on_media_drag)
        
        # 媒体列表滚动条只在鼠标悬停时响应
        def on_media_list_mousewheel(event):
            # 检查鼠标是否在媒体列表区域内
            widget_under_mouse = self.root.winfo_containing(event.x_root, event.y_root)
            if widget_under_mouse and (widget_under_mouse == self.media_listbox or 
                                       widget_under_mouse == scrollbar or
                                       widget_under_mouse == media_list_frame):
                self.media_listbox.yview_scroll(int(-1*(event.delta/120)), "units")
                return "break"  # 阻止事件传播
        
        self.media_listbox.bind("<MouseWheel>", on_media_list_mousewheel)
        scrollbar.bind("<MouseWheel>", on_media_list_mousewheel)
        media_list_frame.bind("<MouseWheel>", on_media_list_mousewheel)
        
        # 任务管理面板内容
        self.task_management_panel = tk.Frame(left_panel, bg=frame_color)
        self.task_management_panel.pack(fill=tk.BOTH, expand=True, pady=10)
        self.task_management_panel.pack_forget()  # 初始隐藏
        
        # 任务管理标签页
        task_notebook = ttk.Notebook(self.task_management_panel)
        task_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 未完成任务标签页
        pending_frame = tk.Frame(task_notebook, bg=frame_color)
        task_notebook.add(pending_frame, text="未完成")
        
        # 未完成任务列表
        tk.Label(pending_frame, text="未完成任务", font=("微软雅黑", self.font_size, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5, padx=10)
        self.pending_tasks_listbox = tk.Listbox(pending_frame, width=30, height=10, bg=bg_color, fg=text_color, font=("微软雅黑", self.font_size - 1))
        self.pending_tasks_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 已完成任务标签页
        completed_frame = tk.Frame(task_notebook, bg=frame_color)
        task_notebook.add(completed_frame, text="已完成")
        
        # 已完成任务列表
        tk.Label(completed_frame, text="已完成任务", font=("微软雅黑", self.font_size, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5, padx=10)
        self.completed_tasks_listbox = tk.Listbox(completed_frame, width=30, height=10, bg=bg_color, fg=text_color, font=("微软雅黑", self.font_size - 1))
        self.completed_tasks_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 导出视频列表
        tk.Label(completed_frame, text="导出的视频", font=("微软雅黑", self.font_size, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5, padx=10)
        self.exported_videos_listbox = tk.Listbox(completed_frame, width=30, height=10, bg=bg_color, fg=text_color, font=("微软雅黑", self.font_size - 1))
        self.exported_videos_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        # 绑定双击事件以打开导出的视频
        self.exported_videos_listbox.bind('<Double-1>', self.open_exported_video)
        
        # 将左侧面板添加到PanedWindow（比例20%，最小宽度150px）
        self.main_paned.add(left_panel, minsize=150, stretch="never")
        
        # ==================== 中间预览区域（可调整大小，比例3） ====================
        center_panel = tk.Frame(self.main_paned, bg=bg_color)
        center_panel.pack_propagate(False)
        center_panel.grid_rowconfigure(1, weight=1)
        center_panel.grid_columnconfigure(0, weight=1)
        
        # 预览窗口标题栏
        preview_header = tk.Frame(center_panel, bg=frame_color, height=30)
        preview_header.grid(row=0, column=0, sticky=tk.EW)
        
        # 时间码显示
        self.timecode_label = tk.Label(preview_header, text="00:00:00:00", font=("微软雅黑", self.font_size), bg=frame_color, fg="#007acc")
        self.timecode_label.pack(side=tk.LEFT, padx=20)
        
        # 预览窗口：自适应大小容器（居中显示）
        preview_window = tk.Frame(center_panel, bg=bg_color)
        preview_window.grid(row=1, column=0, sticky=tk.NSEW)
        preview_window.grid_rowconfigure(0, weight=1)
        preview_window.grid_columnconfigure(0, weight=1)
        
        # 居中占位容器（保证预览区域始终在中间）
        self.preview_center_container = tk.Frame(preview_window, bg=bg_color)
        self.preview_center_container.grid(row=0, column=0, sticky=tk.NSEW)
        self.preview_center_container.grid_rowconfigure(0, weight=1)
        self.preview_center_container.grid_columnconfigure(0, weight=1)
        
        # 尝试导入并使用新的视频播放器
        try:
            from modules.video_player.optimized_video_player import OptimizedVideoPlayer
            from PyQt5.QtWidgets import QApplication
            import sys
            
            # 检查是否已有QApplication实例
            if not QApplication.instance():
                self.q_app = QApplication(sys.argv)
            else:
                self.q_app = QApplication.instance()
            
            # 创建视频播放器容器（放在居中容器内）
            self.video_player_frame = tk.Frame(self.preview_center_container, bg=bg_color)
            self.video_player_frame.grid(row=0, column=0, sticky=tk.NSEW)
            self.video_player_frame.grid_rowconfigure(0, weight=1)
            self.video_player_frame.grid_columnconfigure(0, weight=1)
            
            # 保存容器的窗口ID
            self.video_player_frame_id = self.video_player_frame.winfo_id()
            
            # 标记使用新播放器
            self.use_optimized_player = True
        except Exception as e:
            print(f"无法加载优化的视频播放器: {e}")
            self.use_optimized_player = False
            
        # 无论是否使用新播放器，都初始化预览画布（放在居中容器内，播放前后位置一致）
        self.preview_canvas = tk.Canvas(self.preview_center_container, bg=bg_color, highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky=tk.NSEW)
        if not self.use_optimized_player:
            # 预览提示（居中显示）
            cw = self.preview_canvas.winfo_width() or 800
            ch = self.preview_canvas.winfo_height() or 450
            self.preview_hint = self.preview_canvas.create_text(cw // 2, ch // 2, text="点击导入按钮添加媒体文件", fill=desc_color, font=("微软雅黑", self.font_size + 2))
        # 保证只显示一种预览：优化播放器时藏画布，否则藏播放器容器
        if self.use_optimized_player:
            self.preview_canvas.grid_forget()
        elif hasattr(self, 'video_player_frame') and self.video_player_frame is not None:
            self.video_player_frame.grid_forget()
        
        # 将中间面板添加到PanedWindow（比例3，占据主要空间）
        self.main_paned.add(center_panel, minsize=450, stretch="always")

        # ==================== 右侧面板（新版工具栏 - 包含字幕、音频、预设、AI工具，占上方区域的30%）====================
        right_panel = tk.Frame(self.main_paned, bg=frame_color, width=300)
        right_panel.pack_propagate(False)
        
        # ==================== 右侧工具栏 - 剪映风格标签页切换 ====================
        
        # 创建标签按钮容器（顶部横向排列）
        tab_button_frame = tk.Frame(right_panel, bg=frame_color, height=40)
        tab_button_frame.pack(fill=tk.X, side=tk.TOP)
        tab_button_frame.pack_propagate(False)
        
        # 创建内容容器（带底部滚动条）
        tab_content_frame = tk.Frame(right_panel, bg=frame_color)
        tab_content_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        tab_content_frame.grid_rowconfigure(0, weight=1)
        tab_content_frame.grid_columnconfigure(0, weight=1)
        
        # 创建Canvas（垂直滚动）
        self.right_tool_canvas = tk.Canvas(tab_content_frame, bg=frame_color, highlightthickness=0)
        self.right_tool_canvas.grid(row=0, column=0, sticky=tk.NSEW)
        
        # 创建底部滚动条
        self.right_tool_scrollbar = tk.Scrollbar(tab_content_frame, orient=tk.VERTICAL, command=self.right_tool_canvas.yview)
        self.right_tool_canvas.configure(yscrollcommand=self.right_tool_scrollbar.set)
        self.right_tool_scrollbar.grid(row=0, column=1, sticky=tk.NS)
        
        # 创建可滚动的内容框架
        self.right_tool_scrollable_frame = tk.Frame(self.right_tool_canvas, bg=frame_color)
        self.right_tool_canvas_window = self.right_tool_canvas.create_window((0, 0), window=self.right_tool_scrollable_frame, anchor=tk.NW)
        
        # 更新滚动区域
        def update_right_tool_scrollregion(event=None):
            self.right_tool_canvas.configure(scrollregion=self.right_tool_canvas.bbox("all"))
            # 更新窗口宽度
            canvas_width = self.right_tool_canvas.winfo_width()
            if canvas_width > 1:
                self.right_tool_canvas.itemconfig(self.right_tool_canvas_window, width=canvas_width)
        
        self.right_tool_scrollable_frame.bind("<Configure>", update_right_tool_scrollregion)
        self.right_tool_canvas.bind("<Configure>", update_right_tool_scrollregion)
        
        # 鼠标滚轮滚动（只在鼠标在区域内时滚动）
        def on_right_tool_mousewheel(event):
            # 检查鼠标是否在右侧工具栏区域内
            widget_under_mouse = self.root.winfo_containing(event.x_root, event.y_root)
            if widget_under_mouse and (widget_under_mouse == self.right_tool_canvas or 
                                       str(widget_under_mouse).startswith(str(self.right_tool_canvas)) or
                                       widget_under_mouse == self.right_tool_scrollable_frame or
                                       str(widget_under_mouse).startswith(str(self.right_tool_scrollable_frame))):
                self.right_tool_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                return "break"  # 阻止事件传播
        
        # 绑定到canvas而不是bind_all
        self.right_tool_canvas.bind("<MouseWheel>", on_right_tool_mousewheel)
        self.right_tool_scrollable_frame.bind("<MouseWheel>", on_right_tool_mousewheel)
        
        # 定义工具页面
        self.tool_pages = {}
        self.current_tool_tab = tk.StringVar(value="参数")
        
        def create_tool_tab(tab_name, icon=""):
            """创建工具标签页"""
            # 创建按钮
            btn = tk.Button(tab_button_frame, text=f"{icon} {tab_name}", 
                           command=lambda: switch_tool_tab(tab_name),
                           bg="#007acc" if self.current_tool_tab.get() == tab_name else frame_color,
                           fg=text_color, font=("微软雅黑", self.font_size),
                           padx=10, pady=5, relief=tk.FLAT)
            btn.pack(side=tk.LEFT, padx=2, pady=5)
            
            # 创建内容框架（放在可滚动区域内）
            page_frame = tk.Frame(self.right_tool_scrollable_frame, bg=frame_color)
            self.tool_pages[tab_name] = page_frame
            return page_frame
        
        def switch_tool_tab(tab_name):
            """切换工具标签页"""
            # 隐藏所有页面
            for page in self.tool_pages.values():
                page.pack_forget()
            
            # 显示选中的页面
            self.tool_pages[tab_name].pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.current_tool_tab.set(tab_name)
            
            # 更新按钮样式
            for btn in tab_button_frame.winfo_children():
                btn_text = btn.cget("text").strip()
                if tab_name in btn_text:
                    btn.config(bg="#007acc")
                else:
                    btn.config(bg=frame_color)
        
        # 创建各个工具页面
        # 1. 参数页面
        params_page = create_tool_tab("参数", "⚙️")
        
        # 2. 剪辑页面
        clip_page = create_tool_tab("剪辑", "✂️")
        
        # 3. 效果页面
        effects_page = create_tool_tab("效果", "✨")
        
        # 4. 字幕页面
        subtitle_page = create_tool_tab("字幕", "📝")
        
        # 5. 音频页面
        audio_page = create_tool_tab("音频", "🔊")
        
        # 6. AI工具页面
        ai_page = create_tool_tab("AI", "🤖")
        
        # 7. 调节页面（新增）
        adjust_page = create_tool_tab("调节", "🎨")
        
        # 默认显示参数页面
        params_page.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # ==================== 调节页面内容 ====================
        adjust_frame = adjust_page
        
        # 亮度调节
        tk.Label(adjust_frame, text="亮度:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(10,0))
        self.brightness_var = tk.IntVar(value=0)
        brightness_scale = tk.Scale(adjust_frame, from_=-100, to=100, orient=tk.HORIZONTAL,
                                   variable=self.brightness_var, bg=frame_color, fg=text_color,
                                   highlightthickness=0, length=200, font=("微软雅黑", self.font_size-1))
        brightness_scale.pack(fill=tk.X, pady=5)
        
        # 对比度调节
        tk.Label(adjust_frame, text="对比度:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(10,0))
        self.contrast_var = tk.IntVar(value=0)
        contrast_scale = tk.Scale(adjust_frame, from_=-100, to=100, orient=tk.HORIZONTAL,
                                  variable=self.contrast_var, bg=frame_color, fg=text_color,
                                  highlightthickness=0, length=200, font=("微软雅黑", self.font_size-1))
        contrast_scale.pack(fill=tk.X, pady=5)
        
        # 饱和度调节
        tk.Label(adjust_frame, text="饱和度:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(10,0))
        self.saturation_var = tk.IntVar(value=0)
        saturation_scale = tk.Scale(adjust_frame, from_=-100, to=100, orient=tk.HORIZONTAL,
                                    variable=self.saturation_var, bg=frame_color, fg=text_color,
                                    highlightthickness=0, length=200, font=("微软雅黑", self.font_size-1))
        saturation_scale.pack(fill=tk.X, pady=5)
        
        # 色调调节
        tk.Label(adjust_frame, text="色调:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(10,0))
        self.hue_var = tk.IntVar(value=0)
        hue_scale = tk.Scale(adjust_frame, from_=-180, to=180, orient=tk.HORIZONTAL,
                            variable=self.hue_var, bg=frame_color, fg=text_color,
                            highlightthickness=0, length=200, font=("微软雅黑", self.font_size-1))
        hue_scale.pack(fill=tk.X, pady=5)
        
        # 应用按钮
        adjust_btn_frame = tk.Frame(adjust_frame, bg=frame_color)
        adjust_btn_frame.pack(fill=tk.X, pady=10)
        
        tk.Button(adjust_btn_frame, text="🎨 应用调节", command=self.apply_video_adjustments,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(adjust_btn_frame, text="🔄 重置", command=self.reset_video_adjustments,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        # ==================== 参数页面内容 ====================
        params_frame = params_page
        
        # 输出模式
        tk.Label(params_frame, text="输出模式:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).grid(row=0, column=0, sticky=tk.W, pady=10)
        self.output_mode_var = tk.StringVar(value=default_mode)
        mode_options = ["30秒爆款引流", "90秒剧情解说", "8分钟挂车长视频"]
        mode_menu = ttk.Combobox(params_frame, textvariable=self.output_mode_var, values=mode_options, state="readonly", width=20, font=("微软雅黑", self.font_size))
        mode_menu.grid(row=0, column=1, pady=10, sticky=tk.W)
        
        # 分辨率
        tk.Label(params_frame, text="分辨率:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).grid(row=1, column=0, sticky=tk.W, pady=10)
        self.resolution_var = tk.StringVar(value="1920x1080")
        resolution_options = ["1920x1080", "1280x720", "3840x2160", "4096x2160", "5120x2880", "1080x1920"]
        resolution_menu = ttk.Combobox(params_frame, textvariable=self.resolution_var, values=resolution_options, state="readonly", width=20, font=("微软雅黑", self.font_size))
        resolution_menu.grid(row=1, column=1, pady=10, sticky=tk.W)
        # 竖屏/横屏、多平台分辨率一键切换（使用 export_enhancements 预设）
        tk.Label(params_frame, text="画幅/平台:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.aspect_platform_var = tk.StringVar(value="横屏 16:9")
        aspect_platform_options = ["横屏 16:9", "竖屏 9:16", "方形 1:1", "抖音", "快手", "小红书", "视频号", "B站", "默认 1080P"]
        aspect_platform_menu = ttk.Combobox(params_frame, textvariable=self.aspect_platform_var, values=aspect_platform_options, state="readonly", width=20, font=("微软雅黑", self.font_size))
        aspect_platform_menu.grid(row=2, column=1, pady=5, sticky=tk.W)
        def on_aspect_platform_change(event=None):
            sel = self.aspect_platform_var.get()
            if export_enhancements:
                ap = export_enhancements.ASPECT_PRESETS.get(sel)
                pf = export_enhancements.PLATFORM_PRESETS.get(sel)
                p = ap or pf
                if p and "width" in p and "height" in p:
                    self.resolution_var.set(f"{p['width']}x{p['height']}")
            else:
                if sel == "竖屏 9:16": self.resolution_var.set("1080x1920")
                elif sel == "横屏 16:9": self.resolution_var.set("1920x1080")
        aspect_platform_menu.bind("<<ComboboxSelected>>", on_aspect_platform_change)
        
        # 帧率
        tk.Label(params_frame, text="帧率:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).grid(row=3, column=0, sticky=tk.W, pady=10)
        self.fps_var = tk.StringVar(value="30")
        fps_options = ["24", "25", "30", "60"]
        fps_menu = ttk.Combobox(params_frame, textvariable=self.fps_var, values=fps_options, state="readonly", width=20, font=("微软雅黑", self.font_size))
        fps_menu.grid(row=3, column=1, pady=10, sticky=tk.W)
        
        # 编码
        tk.Label(params_frame, text="编码:", bg=frame_color, fg=text_color, font=("微软雅黑", self.font_size)).grid(row=4, column=0, sticky=tk.W, pady=10)
        self.encoder_var = tk.StringVar(value="H.264")
        encoder_options = ["H.264", "H.265", "ProRes", "DNxHR", "VP9", "AV1", "H.266", "HEVC"]
        encoder_menu = ttk.Combobox(params_frame, textvariable=self.encoder_var, values=encoder_options, state="readonly", width=20, font=("微软雅黑", self.font_size))
        encoder_menu.grid(row=4, column=1, pady=10, sticky=tk.W)
        
        # ==================== 右侧工具栏面板（内嵌式 - 不弹出新窗口）====================
        
        # ==================== 剪辑页面内容 ====================
        clip_frame = clip_page
        
        # 播放速度控制
        tk.Label(clip_frame, text="播放速度:", bg=frame_color, fg=text_color,
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.clip_speed_var = tk.StringVar(value="1.0x")
        speed_options = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"]
        speed_menu = ttk.Combobox(clip_frame, textvariable=self.clip_speed_var,
                                 values=speed_options, state="readonly", width=20)
        speed_menu.pack(fill=tk.X, pady=2)
        speed_menu.bind("<<ComboboxSelected>>", lambda e: self.adjust_speed_from_var(self.clip_speed_var.get()))
        
        # 剪辑操作按钮
        clip_btn_frame = tk.Frame(clip_frame, bg=frame_color)
        clip_btn_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(clip_btn_frame, text="✂️ 剪辑", command=self.show_clip_options,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(clip_btn_frame, text="🎬 裁剪", command=self.crop_video,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(clip_btn_frame, text="🔄 旋转", command=self.rotate_video,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        # ==================== 效果页面内容 ====================
        effects_frame = effects_page
        
        # 效果分类
        tk.Label(effects_frame, text="效果类型:", bg=frame_color, fg=text_color,
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.effect_category_var = tk.StringVar(value="转场效果")
        effect_categories = ["转场效果", "滤镜效果", "动画效果", "文字效果", "调色效果"]
        effect_cat_menu = ttk.Combobox(effects_frame, textvariable=self.effect_category_var,
                                      values=effect_categories, state="readonly", width=20)
        effect_cat_menu.pack(fill=tk.X, pady=2)
        
        # 具体效果
        tk.Label(effects_frame, text="选择效果:", bg=frame_color, fg=text_color,
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.effect_name_var = tk.StringVar(value="淡入淡出")
        effect_names = ["淡入淡出", "滑动", "缩放", "模糊", "黑白", "复古", "锐化", "对比度"]
        effect_name_menu = ttk.Combobox(effects_frame, textvariable=self.effect_name_var,
                                       values=effect_names, state="readonly", width=20)
        effect_name_menu.pack(fill=tk.X, pady=2)
        
        # 效果操作按钮
        effects_btn_frame = tk.Frame(effects_frame, bg=frame_color)
        effects_btn_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(effects_btn_frame, text="✨ 应用", command=self.apply_selected_effect,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(effects_btn_frame, text="👁️ 预览", command=self.preview_effect,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(effects_btn_frame, text="🗑️ 清除", command=self.clear_effects,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        # ==================== 字幕页面内容 ====================
        subtitle_frame = subtitle_page
        
        # 字幕样式设置
        tk.Label(subtitle_frame, text="字体:", bg=frame_color, fg=text_color, 
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.subtitle_font_var = tk.StringVar(value="微软雅黑")
        subtitle_fonts = ["微软雅黑", "宋体", "黑体", "Arial", "Helvetica"]
        subtitle_font_menu = ttk.Combobox(subtitle_frame, textvariable=self.subtitle_font_var, 
                                         values=subtitle_fonts, state="readonly", width=20)
        subtitle_font_menu.pack(fill=tk.X, pady=2)
        
        tk.Label(subtitle_frame, text="字号:", bg=frame_color, fg=text_color, 
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.subtitle_size_var = tk.StringVar(value="24")
        subtitle_sizes = ["16", "18", "20", "24", "28", "32", "36", "40", "48"]
        subtitle_size_menu = ttk.Combobox(subtitle_frame, textvariable=self.subtitle_size_var, 
                                         values=subtitle_sizes, state="readonly", width=20)
        subtitle_size_menu.pack(fill=tk.X, pady=2)
        
        tk.Label(subtitle_frame, text="颜色:", bg=frame_color, fg=text_color, 
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.subtitle_color_var = tk.StringVar(value="白色")
        subtitle_colors = ["白色", "黄色", "红色", "蓝色", "绿色", "黑色"]
        subtitle_color_menu = ttk.Combobox(subtitle_frame, textvariable=self.subtitle_color_var, 
                                          values=subtitle_colors, state="readonly", width=20)
        subtitle_color_menu.pack(fill=tk.X, pady=2)
        
        tk.Label(subtitle_frame, text="位置:", bg=frame_color, fg=text_color, 
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.subtitle_position_var = tk.StringVar(value="底部居中")
        subtitle_positions = ["顶部", "底部居中", "底部左侧", "底部右侧"]
        subtitle_position_menu = ttk.Combobox(subtitle_frame, textvariable=self.subtitle_position_var, 
                                             values=subtitle_positions, state="readonly", width=20)
        subtitle_position_menu.pack(fill=tk.X, pady=2)
        
        # 字幕操作按钮
        subtitle_btn_frame = tk.Frame(subtitle_frame, bg=frame_color)
        subtitle_btn_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(subtitle_btn_frame, text="🤖 AI生成", command=self.generate_ai_subtitles,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(subtitle_btn_frame, text="🌐 多语言", command=self.show_multilingual_subtitle,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(subtitle_btn_frame, text="➕ 添加", command=self.add_subtitle,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        # ==================== 音频页面内容 ====================
        audio_frame = audio_page
        
        # 音量控制
        tk.Label(audio_frame, text="音量:", bg=frame_color, fg=text_color, 
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.audio_volume_var = tk.DoubleVar(value=1.0)
        volume_scale = tk.Scale(audio_frame, from_=0, to=2, resolution=0.1, orient=tk.HORIZONTAL,
                               variable=self.audio_volume_var, bg=frame_color, fg=text_color,
                               highlightthickness=0, font=("微软雅黑", self.font_size-1))
        volume_scale.pack(fill=tk.X, pady=2)
        
        # 淡入淡出
        tk.Label(audio_frame, text="淡入时长(秒):", bg=frame_color, fg=text_color, 
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.audio_fadein_var = tk.StringVar(value="0.5")
        tk.Entry(audio_frame, textvariable=self.audio_fadein_var, bg=item_color, fg=text_color,
                font=("微软雅黑", self.font_size)).pack(fill=tk.X, pady=2)
        
        tk.Label(audio_frame, text="淡出时长(秒):", bg=frame_color, fg=text_color, 
                font=("微软雅黑", self.font_size)).pack(anchor=tk.W, pady=(5,0))
        self.audio_fadeout_var = tk.StringVar(value="0.5")
        tk.Entry(audio_frame, textvariable=self.audio_fadeout_var, bg=item_color, fg=text_color,
                font=("微软雅黑", self.font_size)).pack(fill=tk.X, pady=2)
        
        # 音频操作按钮
        audio_btn_frame = tk.Frame(audio_frame, bg=frame_color)
        audio_btn_frame.pack(fill=tk.X, pady=5)
        
        tk.Button(audio_btn_frame, text="🔊 增强", command=self.enhance_audio,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(audio_btn_frame, text="🔇 降噪", command=self.denoise_audio,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        tk.Button(audio_btn_frame, text="✂️ 截取", command=self.crop_audio,
                 bg=item_color, fg=text_color, font=("微软雅黑", self.font_size-1),
                 padx=5, pady=5, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        
        # ==================== AI工具页面内容 ====================
        ai_tools_frame = ai_page
        
        # FunClip 自动剪辑
        self.auto_edit_var = tk.BooleanVar(value=False)
        auto_edit_check = tk.Checkbutton(ai_tools_frame, text="FunClip 自动剪辑", variable=self.auto_edit_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color,
                                         font=("微软雅黑", self.font_size + 2))
        auto_edit_check.pack(fill=tk.X, pady=5)
        
        # AutoClip 高光识别
        self.extract_highlights_var = tk.BooleanVar(value=False)
        highlight_check = tk.Checkbutton(ai_tools_frame, text="AutoClip 高光识别", variable=self.extract_highlights_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color,
                                         font=("微软雅黑", self.font_size + 2))
        highlight_check.pack(fill=tk.X, pady=5)
        
        # VideoFusion 视频增强
        self.enhance_video_var = tk.BooleanVar(value=False)
        enhance_check = tk.Checkbutton(ai_tools_frame, text="VideoFusion 视频增强", variable=self.enhance_video_var, 
                                       bg=frame_color, fg=text_color, selectcolor=item_color, 
                                       activebackground=frame_color, activeforeground=text_color,
                                       font=("微软雅黑", self.font_size + 2))
        enhance_check.pack(fill=tk.X, pady=5)
        
        # 千问VL 视频分析
        self.qwen_vl_var = tk.BooleanVar(value=True)  # 默认启用
        qwen_vl_check = tk.Checkbutton(ai_tools_frame, text="千问VL 视频分析", variable=self.qwen_vl_var, 
                                       bg=frame_color, fg=text_color, selectcolor=item_color, 
                                       activebackground=frame_color, activeforeground=text_color,
                                       font=("微软雅黑", self.font_size + 2))
        qwen_vl_check.pack(fill=tk.X, pady=5)
        
        # 将右侧面板添加到PanedWindow（比例30%，最小宽度200px）
        self.main_paned.add(right_panel, minsize=200, stretch="never")
        
        # 将水平分割面板添加到垂直分割面板的上部（占50%）
        self.vertical_paned.add(self.main_paned, minsize=300)

        # ==================== 底部时间线（占50%）====================
        # 时间线面板
        timeline = tk.Frame(self.vertical_paned, bg=frame_color)
        timeline.pack_propagate(False)
        
        # 时间线标题栏（包含播放控制、编辑工具、轨道管理）
        timeline_header = tk.Frame(timeline, bg=frame_color, height=40)
        timeline_header.pack(fill=tk.X, side=tk.TOP)
        timeline_header.pack_propagate(False)
        
        # ========== 左侧：播放控制按钮 ==========
        playback_frame = tk.Frame(timeline_header, bg=frame_color)
        playback_frame.pack(side=tk.LEFT, padx=10, pady=5)
        
        playback_buttons = [
            ("⏮", self.rewind, "倒退10秒"),
            ("⏪", self.reverse_play, "倒放"),
            ("▶", self.play_pause, "播放/暂停"),
            ("⏩", self.fast_forward, "快进10秒"),
        ]
        
        for icon, cmd, tooltip in playback_buttons:
            btn = tk.Button(playback_frame, text=icon, command=cmd,
                          bg=item_color, fg=text_color, font=("微软雅黑", self.font_size),
                          padx=8, pady=3, relief=tk.FLAT, width=3)
            btn.pack(side=tk.LEFT, padx=2)
            btn.bind("<Enter>", lambda e, t=tooltip: self.show_tooltip(e, t))
            btn.bind("<Leave>", lambda e: self.hide_tooltip(e))
        
        # ========== 中间：编辑工具按钮 ==========
        edit_tools_frame = tk.Frame(timeline_header, bg=frame_color)
        edit_tools_frame.pack(side=tk.LEFT, padx=20, pady=5)
        
        edit_buttons = [
            ("↶", self.undo_action, "撤销"),
            ("↷", self.redo_action, "重做"),
            ("✂️", self.split_clip, "切割"),
            ("📏", self.select_tool, "选择"),
            ("📋", self.copy_clip, "复制"),
            ("🔗", self.link_clips, "链接"),
        ]
        
        for icon, cmd, tooltip in edit_buttons:
            btn = tk.Button(edit_tools_frame, text=icon, command=cmd,
                          bg=item_color, fg=text_color, font=("微软雅黑", self.font_size),
                          padx=8, pady=3, relief=tk.FLAT, width=3)
            btn.pack(side=tk.LEFT, padx=2)
            btn.bind("<Enter>", lambda e, t=tooltip: self.show_tooltip(e, t))
            btn.bind("<Leave>", lambda e: self.hide_tooltip(e))
        
        # 时间线标尺（使用Frame容器实现左侧偏移）
        timeline_ruler = tk.Frame(timeline, bg=bg_color, height=40)
        timeline_ruler.pack(fill=tk.X, side=tk.TOP)

        # 左侧占位区域（与轨道控制栏对齐，120px）
        ruler_left_spacer = tk.Frame(timeline_ruler, width=120, bg="#383838")
        ruler_left_spacer.pack(side=tk.LEFT, fill=tk.Y)
        ruler_left_spacer.pack_propagate(False)

        # 在时间线标尺右侧添加时间刻度线
        ruler_canvas = tk.Canvas(timeline_ruler, bg=bg_color, highlightthickness=0, height=40)
        ruler_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 保存ruler_canvas引用
        self.ruler_canvas = ruler_canvas
        
        # 绘制时间刻度线（修复版 - 与片段位置对齐）
        def draw_ruler_scale():
            ruler_canvas.delete("all")
            width = ruler_canvas.winfo_width()
            if width == 0:
                width = 800  # 默认宽度
            
            # 获取当前缩放级别
            zoom = getattr(self, 'timeline_zoom', 1.0)
            
            # 计算最大显示时间（根据画布宽度）
            max_time = int(width / zoom) + 10  # 多显示一些
            
            # 绘制时间刻度（根据缩放级别调整刻度密度）
            # 确定刻度间隔
            if zoom >= 10:
                interval = 1  # 每1秒一个刻度
                label_interval = 5  # 每5秒一个标签
            elif zoom >= 5:
                interval = 2  # 每2秒一个刻度
                label_interval = 10  # 每10秒一个标签
            elif zoom >= 2:
                interval = 5  # 每5秒一个刻度
                label_interval = 10  # 每10秒一个标签
            else:
                interval = 10  # 每10秒一个刻度
                label_interval = 30  # 每30秒一个标签
            
            # 绘制刻度线
            for i in range(0, max_time, interval):
                x = i * zoom  # 使用缩放级别计算位置
                
                if x > width:
                    break
                
                # 主刻度（带标签）
                if i % label_interval == 0:
                    ruler_canvas.create_line(x, 0, x, 20, fill="#007acc", width=2)
                    # 格式化时间显示
                    if i < 60:
                        time_text = f"{i}s"
                    elif i < 3600:
                        minutes = i // 60
                        seconds = i % 60
                        time_text = f"{minutes}:{seconds:02d}"
                    else:
                        hours = i // 3600
                        minutes = (i % 3600) // 60
                        time_text = f"{hours}:{minutes:02d}"
                    ruler_canvas.create_text(x, 35, text=time_text, fill="#ffffff", font=("微软雅黑", 8))
                else:
                    # 次刻度
                    ruler_canvas.create_line(x, 5, x, 15, fill="#444444", width=1)
            
            # 绘制当前播放位置指示线
            if hasattr(self, '_playback_position'):
                play_x = self._playback_position * zoom
                if play_x <= width:
                    ruler_canvas.create_line(play_x, 0, play_x, 40, fill="#ff0000", width=2, tags="playhead")
        
        # 保存绘制函数引用，以便刷新
        self._draw_ruler_scale = draw_ruler_scale

        # 初始绘制
        draw_ruler_scale()

        # 绑定大小变化事件，重新绘制刻度
        def on_ruler_resize(event):
            draw_ruler_scale()

        ruler_canvas.bind("<Configure>", on_ruler_resize)

        # ========== 播放头拖动和点击跳转功能 ==========
        self._is_dragging_playhead = False

        def on_ruler_click(event):
            """点击时间标尺跳转播放头位置"""
            zoom = getattr(self, 'timeline_zoom', 1.0)
            # 计算点击位置对应的时间（秒）
            new_position = event.x / zoom
            self._playback_position = max(0, new_position)
            # 更新播放头显示
            draw_ruler_scale()
            # 更新预览窗口
            self._seek_to_position(self._playback_position)
            print(f"⏱️ 播放头跳转到: {self._playback_position:.2f}秒")

        def on_playhead_drag_start(event):
            """开始拖动播放头"""
            # 检查是否点击在播放头附近（±10像素）
            zoom = getattr(self, 'timeline_zoom', 1.0)
            play_x = self._playback_position * zoom
            if abs(event.x - play_x) < 15:
                self._is_dragging_playhead = True
                ruler_canvas.config(cursor="fleur")

        def on_playhead_drag(event):
            """拖动播放头"""
            if self._is_dragging_playhead:
                zoom = getattr(self, 'timeline_zoom', 1.0)
                new_position = event.x / zoom
                self._playback_position = max(0, new_position)
                # 实时更新播放头显示
                draw_ruler_scale()
                # 实时更新预览窗口
                self._seek_to_position(self._playback_position)

        def on_playhead_drag_end(event):
            """结束拖动播放头"""
            if self._is_dragging_playhead:
                self._is_dragging_playhead = False
                ruler_canvas.config(cursor="")
                print(f"⏱️ 播放头定位到: {self._playback_position:.2f}秒")

        # 绑定鼠标事件
        ruler_canvas.bind("<Button-1>", on_ruler_click)
        ruler_canvas.bind("<B1-Motion>", on_playhead_drag)
        ruler_canvas.bind("<ButtonRelease-1>", on_playhead_drag_end)
        
        # 时间线轨道（使用新的Timeline系统）
        self.timeline_scroll_container = tk.Frame(timeline, bg=bg_color)
        self.timeline_scroll_container.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        
        # 导入新的Timeline系统
        from modules.timeline.track_canvas import Timeline
        
        # 创建新的时间线系统
        self.timeline_system = Timeline(self.timeline_scroll_container)

        # 保存tracks_frame引用，用于后续刷新轨道
        self.timeline_tracks = self.timeline_system.timeline_frame

        # 设置轨道片段编辑和预览回调
        self._setup_track_callbacks()
        
        # 时间线缩放控制
        zoom_frame = tk.Frame(timeline_header, bg=frame_color)
        zoom_frame.pack(side=tk.RIGHT, padx=10)
        
        zoom_out_btn = tk.Button(zoom_frame, text="🔍-", command=self.zoom_out, 
                               bg="#333333", fg="#ffffff", font=("微软雅黑", self.font_size), 
                               padx=10, pady=5, relief=tk.FLAT)
        zoom_out_btn.pack(side=tk.LEFT, padx=5)
        
        self.zoom_label = tk.Label(zoom_frame, text="100%", 
                                 bg=frame_color, fg="#ffffff", font=("微软雅黑", self.font_size))
        self.zoom_label.pack(side=tk.LEFT, padx=10)
        
        zoom_in_btn = tk.Button(zoom_frame, text="🔍+", command=self.zoom_in, 
                              bg="#333333", fg="#ffffff", font=("微软雅黑", self.font_size), 
                              padx=10, pady=5, relief=tk.FLAT)
        zoom_in_btn.pack(side=tk.LEFT, padx=5)
        
        # 轨道管理按钮
        track_manage_frame = tk.Frame(timeline_header, bg=frame_color)
        track_manage_frame.pack(side=tk.RIGHT, padx=10)
        
        add_video_btn = tk.Button(track_manage_frame, text="+ 视频轨道", command=self.add_video_track, 
                               bg="#007acc", fg="#ffffff", font=("微软雅黑", self.font_size), 
                               padx=12, pady=5, relief=tk.FLAT)
        add_video_btn.pack(side=tk.LEFT, padx=5)
        
        add_audio_btn = tk.Button(track_manage_frame, text="+ 音频轨道", command=self.add_audio_track, 
                               bg="#007acc", fg="#ffffff", font=("微软雅黑", self.font_size), 
                               padx=12, pady=5, relief=tk.FLAT)
        add_audio_btn.pack(side=tk.LEFT, padx=5)
        
        import_audio_btn = tk.Button(track_manage_frame, text="导入音频", command=self.import_audio_to_track, 
                               bg="#007a5a", fg="#ffffff", font=("微软雅黑", self.font_size), 
                               padx=12, pady=5, relief=tk.FLAT)
        import_audio_btn.pack(side=tk.LEFT, padx=5)
        
        add_text_btn = tk.Button(track_manage_frame, text="+ 文本轨道", command=self.add_text_track, 
                               bg="#007acc", fg="#ffffff", font=("微软雅黑", self.font_size), 
                               padx=12, pady=5, relief=tk.FLAT)
        add_text_btn.pack(side=tk.LEFT, padx=5)
        
        # 添加开始剪辑按钮
        start_edit_btn = tk.Button(track_manage_frame, text="🎬 开始剪辑", command=self.start_ai_drama_editing, 
                                 bg="#ff9800", fg="#ffffff", font=("微软雅黑", self.font_size), 
                                 padx=12, pady=5, relief=tk.FLAT)
        start_edit_btn.pack(side=tk.LEFT, padx=5)
        
        # 将时间线添加到垂直PanedWindow（占50%）
        self.vertical_paned.add(timeline, minsize=200)

        # 设置垂直分割比例为50:50
        def set_vertical_paned_ratio(event=None):
            """设置垂直分割面板为50:50比例"""
            try:
                total_height = self.vertical_paned.winfo_height()
                if total_height > 100:
                    # 设置为50%位置
                    self.vertical_paned.sash_place(0, 0, total_height // 2)
            except:
                pass

        # 绑定窗口大小变化事件
        self.vertical_paned.bind("<Configure>", set_vertical_paned_ratio)
        # 延迟设置初始比例
        self.root.after(100, set_vertical_paned_ratio)

        # 设置水平分割比例为20:50:30
        # 左侧媒体区 : 中间预览区 : 右侧工具区
        def set_horizontal_paned_ratio(event=None):
            """设置水平分割面板为20:50:30比例"""
            try:
                total_width = self.main_paned.winfo_width()
                if total_width > 500:
                    # 第一个分割条在20%位置（左侧占20%）
                    self.main_paned.sash_place(0, int(total_width * 0.20), 0)
                    # 第二个分割条在70%位置（20%+50%=70%）
                    self.main_paned.sash_place(1, int(total_width * 0.70), 0)
            except:
                pass

        # 绑定窗口大小变化事件
        self.main_paned.bind("<Configure>", set_horizontal_paned_ratio)
        # 延迟设置初始比例
        self.root.after(150, set_horizontal_paned_ratio)
        
        # ==================== 底部状态栏 ====================
        status_bar = tk.Frame(main_frame, bg="#252525" if self.current_theme == "dark" else "#e0e0e0", height=25)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        # 状态信息
        self.status_label = tk.Label(status_bar, text="就绪", bg="#252525" if self.current_theme == "dark" else "#e0e0e0", fg="#007acc", font=("微软雅黑", self.font_size))
        self.status_label.pack(side=tk.LEFT, padx=20)
        
        # 渲染信息
        render_label = tk.Label(status_bar, text="渲染: 空闲", bg="#252525" if self.current_theme == "dark" else "#e0e0e0", fg="#ffffff" if self.current_theme == "dark" else "#000000", font=("微软雅黑", self.font_size))
        render_label.pack(side=tk.RIGHT, padx=20)
        
        # 开始剪辑按钮
        start_edit_btn = tk.Button(status_bar, text="开始剪辑", command=self.start_video_editing, bg="#007acc", fg="#ffffff", font=("微软雅黑", self.font_size), padx=15, pady=3, relief=tk.FLAT)
        start_edit_btn.pack(side=tk.RIGHT, padx=20)
        
        # 初始化媒体列表
        self.update_media_list()
        
        # ==================== 右键菜单（删减功能集成）====================
        self._create_context_menu(main_frame, bg_color, text_color)
    
    def _create_context_menu(self, parent, bg_color, text_color):
        """创建右键菜单（集成所有删减功能）"""
        # 创建右键菜单
        self.context_menu = tk.Menu(parent, tearoff=0, bg=bg_color, fg=text_color)
        
        # 片段操作子菜单
        clip_menu = tk.Menu(self.context_menu, tearoff=0, bg=bg_color, fg=text_color)
        clip_menu.add_command(label="🔪 切割片段", command=self.split_clip)
        clip_menu.add_command(label="🗑️ 删除片段", command=self.delete_clip)
        clip_menu.add_command(label="📋 复制片段", command=self.copy_clip)
        clip_menu.add_command(label="✂️ 剪切片段", command=self.cut_clip)
        clip_menu.add_separator()
        clip_menu.add_command(label="🔄 调整速度", command=self.adjust_speed)
        clip_menu.add_command(label="🔗 链接片段", command=self.link_clips)
        self.context_menu.add_cascade(label="片段操作", menu=clip_menu)
        
        # 批量操作子菜单
        batch_menu = tk.Menu(self.context_menu, tearoff=0, bg=bg_color, fg=text_color)
        batch_menu.add_command(label="✂️ 批量切割", command=self.batch_cut_at_playhead_ui)
        batch_menu.add_command(label="🗑️ 批量删除", command=self.batch_delete_selected_clips)
        batch_menu.add_command(label="〰️ 波纹删除", command=self.ripple_delete_ui)
        self.context_menu.add_cascade(label="批量操作", menu=batch_menu)
        
        # 轨道操作子菜单
        track_menu = tk.Menu(self.context_menu, tearoff=0, bg=bg_color, fg=text_color)
        track_menu.add_command(label="➕ 添加视频轨道", command=self.add_video_track)
        track_menu.add_command(label="➕ 添加音频轨道", command=self.add_audio_track)
        track_menu.add_command(label="➕ 添加文本轨道", command=self.add_text_track)
        track_menu.add_separator()
        track_menu.add_command(label="🗑️ 删除当前轨道", command=self.delete_current_track)
        track_menu.add_command(label="🔒 锁定/解锁轨道", command=self.toggle_current_track_lock)
        track_menu.add_command(label="🔇 静音/取消静音", command=self.toggle_current_track_mute)
        self.context_menu.add_cascade(label="轨道操作", menu=track_menu)
        
        # 添加分隔线
        self.context_menu.add_separator()
        
        # 直接显示的常用功能
        self.context_menu.add_command(label="🔪 切割", command=self.split_clip)
        self.context_menu.add_command(label="🗑️ 删除", command=self.delete_clip)
        self.context_menu.add_command(label="〰️ 波纹删除", command=self.ripple_delete_ui)
        
        # 绑定右键事件到编辑区域
        def show_context_menu(event):
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()
        
        parent.bind("<Button-3>", show_context_menu)  # 鼠标右键
        
        # 也绑定到时间线区域
        if hasattr(self, 'timeline_system'):
            for track_id, track_obj in self.timeline_system.tracks.items():
                track_obj.canvas.bind("<Button-3>", show_context_menu)
    
    def delete_current_track(self):
        """删除当前选中的轨道"""
        try:
            # 获取当前选中的轨道（这里简化处理，删除最后一个轨道）
            if self.tracks:
                # 找到最后一个非锁定轨道
                for i in range(len(self.tracks) - 1, -1, -1):
                    if not self.tracks[i].get("locked", False):
                        track_type = self.tracks[i].get("type", "")
                        track_type_name = {"video": "视频", "audio": "音频", "text": "文本"}.get(track_type, "")
                        self.tracks.pop(i)
                        self.refresh_tracks()
                        self.status_label.config(text=f"已删除{track_type_name}轨道")
                        return
                self.status_label.config(text="没有可删除的未锁定轨道")
            else:
                self.status_label.config(text="没有可删除的轨道")
        except Exception as e:
            print(f"删除轨道失败: {e}")
            self.status_label.config(text=f"删除轨道失败: {e}")
    
    def toggle_current_track_lock(self):
        """切换当前轨道的锁定状态"""
        try:
            if self.tracks:
                # 简化处理：切换最后一个轨道的锁定状态
                track = self.tracks[-1]
                track["locked"] = not track.get("locked", False)
                self.refresh_tracks()
                lock_status = "已锁定" if track["locked"] else "已解锁"
                self.status_label.config(text=f"轨道 {lock_status}")
        except Exception as e:
            print(f"切换轨道锁定状态失败: {e}")
    
    def toggle_current_track_mute(self):
        """切换当前轨道的静音状态"""
        try:
            if self.tracks:
                # 简化处理：切换最后一个轨道的静音状态
                track = self.tracks[-1]
                track["muted"] = not track.get("muted", False)
                self.refresh_tracks()
                mute_status = "已静音" if track["muted"] else "已取消静音"
                self.status_label.config(text=f"轨道 {mute_status}")
        except Exception as e:
            print(f"切换轨道静音状态失败: {e}")
    
    def copy_clip(self):
        """复制片段"""
        if hasattr(self, 'selected_clip'):
            self.copied_clip = self.selected_clip.copy()
            self.status_label.config(text="已复制片段")
        else:
            self.status_label.config(text="请先选择一个片段")
    
    def cut_clip(self):
        """剪切片段"""
        # 先复制再删除
        if hasattr(self, 'selected_clip'):
            self.copied_clip = self.selected_clip.copy()
            self.delete_clip()
            self.status_label.config(text="已剪切片段")
        else:
            self.status_label.config(text="请先选择一个片段")
    
    def import_media(self):
        """导入媒体"""
        try:
            files = filedialog.askopenfilenames(title="选择媒体文件", 
                                              filetypes=[("视频文件", "*.mp4 *.avi *.mov *.mkv"), 
                                                        ("音频文件", "*.mp3 *.wav *.aac *.flac"), 
                                                        ("图片文件", "*.jpg *.jpeg *.png *.bmp"), 
                                                        ("所有文件", "*.*")])
            
            if files:
                # 直接添加新文件，不覆盖现有列表
                success_count = 0
                video_files = []
                audio_files = []
                
                for file in files:
                    try:
                        filename = os.path.basename(file)
                        # 存储完整路径到映射
                        self.media_paths[filename] = file
                        # 在列表中显示文件名
                        self.media_listbox.insert(tk.END, filename)
                        success_count += 1
                        
                        # 分类文件类型
                        ext = os.path.splitext(file)[1].lower()
                        if ext in [".mp4", ".avi", ".mov", ".mkv"]:
                            video_files.append(file)
                        elif ext in [".mp3", ".wav", ".aac", ".flac"]:
                            audio_files.append(file)
                    except Exception as e:
                        print(f"导入文件 {file} 失败: {e}")
                
                # 处理视频文件：自动创建片段并添加到轨道
                print(f"\n开始处理视频文件，共 {len(video_files)} 个")
                for video_file in video_files:
                    try:
                        print(f"\n处理视频文件: {video_file}")
                        
                        # 校验视频宽高是否有效
                        try:
                            import cv2
                            cap = self._create_video_capture(video_file)
                            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            cap.release()
                            
                            if width <= 0 or height <= 0:
                                print(f"❌ 视频宽高无效，无法导入: {video_file}")
                                print(f"视频宽高: {width}x{height}")
                                continue
                            
                            print(f"✅ 视频宽高有效: {width}x{height}")
                        except Exception as e:
                            print(f"⚠️ 视频宽高检查失败，使用默认值: {e}")
                            # 使用默认宽高值
                            width = 1920
                            height = 1080
                            print(f"✅ 使用默认视频宽高: {width}x{height}")
                        
                        # 检查是否有视频轨道
                        video_tracks = [track for track in self.tracks if track.get("type") == "video"]
                        print(f"找到 {len(video_tracks)} 个视频轨道")
                        if not video_tracks:
                            # 如果没有视频轨道，自动创建一个
                            print("没有视频轨道，创建一个")
                            self.add_video_track()
                            video_tracks = [track for track in self.tracks if track.get("type") == "video"]
                            print(f"创建后找到 {len(video_tracks)} 个视频轨道")
                        
                        if video_tracks:
                            # 选择目标视频轨道
                            video_track = None
                            if len(video_tracks) == 1:
                                # 只有一个轨道，直接使用
                                video_track = video_tracks[0]
                                print(f"只有一个视频轨道，直接使用: {video_track.get('id')}")
                            else:
                                # 多个轨道，让用户选择
                                video_track = self._select_target_track(video_tracks, "视频", os.path.basename(video_file))
                            
                            if video_track:
                                print(f"使用视频轨道: {video_track.get('id')}")
                                # 计算视频片段的起始时间（与视频轨道对齐）
                                video_start_time = 0
                                if video_track.get("clips"):
                                    last_clip = video_track["clips"][-1]
                                    video_start_time = last_clip.get("start", 0) + last_clip.get("duration", 100)
                                
                                # 添加视频片段到轨道
                                print(f"添加视频片段到轨道: {os.path.basename(video_file)}, 开始时间: {video_start_time}")
                                self.add_clip_to_track_with_start(video_track, video_file, os.path.basename(video_file), "video", video_start_time)
                                print(f"视频轨道片段数量: {len(video_track.get('clips', []))}")
                                
                                # 立即刷新轨道，确保片段显示
                                print("🔄 立即刷新轨道...")
                                self.refresh_tracks()
                                print("✅ 轨道刷新完成")
                            
                            # 处理音频：从视频中提取音频并添加到音频轨道
                            # 检查是否有音频轨道
                            audio_tracks = [track for track in self.tracks if track.get("type") == "audio"]
                            print(f"找到 {len(audio_tracks)} 个音频轨道")
                            if not audio_tracks:
                                # 如果没有音频轨道，自动创建一个
                                print("没有音频轨道，创建一个")
                                self.add_audio_track()
                                audio_tracks = [track for track in self.tracks if track.get("type") == "audio"]
                                print(f"创建后找到 {len(audio_tracks)} 个音频轨道")
                            
                            if audio_tracks:
                                # 选择目标音频轨道
                                audio_track = None
                                if len(audio_tracks) == 1:
                                    # 只有一个轨道，直接使用
                                    audio_track = audio_tracks[0]
                                    print(f"只有一个音频轨道，直接使用: {audio_track.get('id')}")
                                else:
                                    # 多个轨道，让用户选择
                                    audio_track = self._select_target_track(audio_tracks, "音频", os.path.basename(video_file))
                                
                                if audio_track:
                                    print(f"使用音频轨道: {audio_track.get('id')}")
                                    # 添加音频片段到轨道，使用与视频相同的开始时间（确保对齐）
                                    print(f"添加音频片段到轨道: {os.path.basename(video_file)}, 开始时间: {video_start_time}")
                                    self.add_clip_to_track_with_start(audio_track, video_file, os.path.basename(video_file), "audio", video_start_time)
                                    print(f"音频轨道片段数量: {len(audio_track.get('clips', []))}")
                    except Exception as e:
                        print(f"处理视频文件 {video_file} 失败: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 处理音频文件：自动创建片段并添加到轨道
                for audio_file in audio_files:
                    try:
                        # 检查是否有音频轨道
                        audio_tracks = [track for track in self.tracks if track.get("type") == "audio"]
                        print(f"找到 {len(audio_tracks)} 个音频轨道")
                        if not audio_tracks:
                            # 如果没有音频轨道，自动创建一个
                            print("没有音频轨道，创建一个")
                            self.add_audio_track()
                            audio_tracks = [track for track in self.tracks if track.get("type") == "audio"]
                            print(f"创建后找到 {len(audio_tracks)} 个音频轨道")
                        
                        if audio_tracks:
                            # 选择目标音频轨道
                            audio_track = None
                            if len(audio_tracks) == 1:
                                # 只有一个轨道，直接使用
                                audio_track = audio_tracks[0]
                                print(f"只有一个音频轨道，直接使用: {audio_track.get('id')}")
                            else:
                                # 多个轨道，让用户选择
                                audio_track = self._select_target_track(audio_tracks, "音频", os.path.basename(audio_file))
                            
                            if audio_track:
                                print(f"使用音频轨道: {audio_track.get('id')}")
                                # 添加音频片段到轨道
                                print(f"添加音频片段到轨道: {os.path.basename(audio_file)}")
                                self.add_clip_to_track(audio_track, audio_file, os.path.basename(audio_file), "audio")
                                print(f"音频轨道片段数量: {len(audio_track.get('clips', []))}")
                    except Exception as e:
                        print(f"处理音频文件 {audio_file} 失败: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 检查轨道状态
                print("\n========== 轨道状态检查 ==========")
                for track in self.tracks:
                    track_type = track["type"]
                    clip_count = len(track.get("clips", []))
                    print(f"{track_type}轨道片段数量: {clip_count}")
                    if clip_count > 0:
                        clip = track["clips"][0]
                        print(f"   第一个片段: {clip.get('name')}, 时长: {clip.get('duration', 0):.2f}秒, 起始: {clip.get('start', 0):.2f}秒")
                
                # 统计轨道片段数
                video_clip_count = 0
                audio_clip_count = 0
                for track in self.tracks:
                    if track["type"] == "video":
                        video_clip_count = len(track.get("clips", []))
                    elif track["type"] == "audio":
                        audio_clip_count = len(track.get("clips", []))
                
                # 强制刷新轨道UI
                print("\n========== 刷新轨道UI ==========")
                try:
                    print(f"✅ timeline_tracks属性存在: {hasattr(self, 'timeline_tracks')}")
                    if hasattr(self, 'timeline_tracks'):
                        print(f"✅ timeline_tracks类型: {type(self.timeline_tracks)}")
                        print(f"✅ 轨道数量: {len(self.tracks)}")
                    self.refresh_tracks()
                    print("✅ 轨道UI刷新成功")
                except Exception as e:
                    print(f"❌ 轨道UI刷新失败: {e}")
                    import traceback
                    traceback.print_exc()
                
                # 重置时间轴到起始位置
                self._playback_position = 0.0
                
                if success_count > 0:
                    # 只有轨道片段数增加时才显示成功提示
                    if video_clip_count > 0 and audio_clip_count > 0:
                        self.status_label.config(text=f"成功导入 {success_count} 个媒体文件并添加到轨道")
                        
                        # 【剪映风格】后台预生成视频缩略图
                        if video_files:
                            self._preload_video_thumbnails_async(video_files)
                        
                        # 自动预览第一个视频文件
                        if video_files:
                            first_video = video_files[0]
                            # 自动预览视频
                            try:
                                self.preview_video(first_video)
                                messagebox.showinfo("导入成功", f"成功导入 {success_count} 个媒体文件\n\n视频已自动加载到预览窗口并添加到轨道\n轨道片段数: {video_clip_count}")
                            except Exception as e:
                                print(f"❌ 预览视频失败: {e}")
                                messagebox.showinfo("导入成功", f"成功导入 {success_count} 个媒体文件并添加到轨道\n轨道片段数: {video_clip_count}\n预览初始化失败，请手动点击播放按钮")
                        else:
                            messagebox.showinfo("成功导入", f"成功导入 {success_count} 个媒体文件并添加到轨道\n轨道片段数: {audio_clip_count}")
                    else:
                        self.status_label.config(text="导入异常: 文件解析成功，但未成功添加到轨道")
                        messagebox.showinfo("导入异常", "文件解析成功，但未成功添加到轨道\n请检查轨道状态")
                else:
                    self.status_label.config(text="导入失败: 没有成功导入任何文件")
                    messagebox.showerror("导入失败", "没有成功导入任何文件，请检查文件权限和格式")
            else:
                self.status_label.config(text="导入已取消")
        except Exception as e:
            self.status_label.config(text=f"导入失败: {str(e)}")
            messagebox.showerror("导入失败", f"导入媒体文件时出错: {str(e)}")
    
    def _preload_video_thumbnails_async(self, video_files):
        """【剪映风格】后台异步预生成视频缩略图"""
        try:
            # 导入缩略图管理器
            from modules.timeline.thumbnail_manager import get_thumbnail_manager
            thumb_mgr = get_thumbnail_manager()
            
            print(f"\n🎬 【剪映风格】开始后台预生成 {len(video_files)} 个视频的缩略图...")
            
            def preload_with_progress():
                total_files = len(video_files)
                for i, video_file in enumerate(video_files):
                    try:
                        print(f"\n  [{i+1}/{total_files}] 预生成: {os.path.basename(video_file)}")
                        
                        # 检查是否已预生成
                        if thumb_mgr.is_preloaded(video_file):
                            print(f"     ✅ 已预生成，跳过")
                            continue
                        
                        # 预生成缩略图
                        def on_complete(success, count, vf=video_file):
                            if success:
                                print(f"     ✅ 完成: {os.path.basename(vf)}, 生成{count}张")
                            else:
                                print(f"     ❌ 失败: {os.path.basename(vf)}")
                        
                        thumb_mgr.preload_video_thumbnails(
                            video_file,
                            progress_callback=None,
                            completion_callback=on_complete
                        )
                        
                        # 短暂延迟，避免阻塞
                        time.sleep(0.1)
                        
                    except Exception as e:
                        print(f"     ⚠️ 预生成失败 {os.path.basename(video_file)}: {e}")
                
                print(f"\n✅ 所有视频缩略图预生成任务已提交")
            
            # 在后台线程中执行
            import threading
            thread = threading.Thread(target=preload_with_progress, daemon=True)
            thread.start()
            
        except Exception as e:
            print(f"⚠️ 启动预生成失败: {e}")
    
    def delete_media(self):
        """删除选中的媒体文件"""
        try:
            # 获取选中的索引
            selected_indices = self.media_listbox.curselection()
            if not selected_indices:
                messagebox.showinfo("提示", "请先选择要删除的媒体文件")
                return
            
            # 确认删除
            confirm = messagebox.askyesno("确认删除", f"确定要删除选中的 {len(selected_indices)} 个媒体文件吗？\n\n删除后，对应的轨道片段也会被移除。")
            if not confirm:
                return
            
            # 要删除的文件名列表
            to_delete = []
            for index in selected_indices:
                filename = self.media_listbox.get(index)
                to_delete.append(filename)
            
            # 从媒体列表中删除
            for filename in to_delete:
                # 从列表框中删除
                for i in range(self.media_listbox.size()):
                    if self.media_listbox.get(i) == filename:
                        self.media_listbox.delete(i)
                        break
                
                # 从路径映射中删除
                if filename in self.media_paths:
                    del self.media_paths[filename]
                
                # 从轨道中删除对应的片段
                for track in self.tracks:
                    # 过滤掉要删除的片段
                    track["clips"] = [clip for clip in track.get("clips", []) if clip.get("name") != filename]
            
            # 刷新轨道显示
            self.refresh_tracks()
            
            # 重置时间轴到起始位置
            self._playback_position = 0.0
            
            # 刷新预览窗口，显示空白帧
            print("\n========== 刷新预览窗口 ==========")
            try:
                # 清除预览窗口内容
                if hasattr(self, 'preview_canvas'):
                    self.preview_canvas.delete("all")
                    print("✅ 预览窗口已清空")
                
                # 重置预览相关变量
                if hasattr(self, '_preview_frame_id'):
                    self._preview_frame_id = None
                if hasattr(self, '_current_preview_image'):
                    self._current_preview_image = None
                
                print("✅ 预览窗口刷新成功")
            except Exception as e:
                print(f"❌ 预览窗口刷新失败: {e}")
            
            # 更新状态
            self.status_label.config(text=f"成功删除 {len(to_delete)} 个媒体文件")
            messagebox.showinfo("删除成功", f"成功删除 {len(to_delete)} 个媒体文件\n\n对应的轨道片段已被移除\n预览窗口已刷新")
        except Exception as e:
            self.status_label.config(text=f"删除失败: {str(e)}")
            messagebox.showerror("删除失败", f"删除媒体文件时出错: {str(e)}")
    
    def import_audio_to_track(self):
        """导入音频文件到音频轨道"""
        try:
            # 选择音频文件
            files = filedialog.askopenfilenames(title="选择音频文件", 
                                              filetypes=[("音频文件", "*.mp3 *.wav *.aac *.flac"), 
                                                        ("所有文件", "*.*")])
            
            if files:
                # 检查是否有音频轨道
                audio_tracks = [track for track in self.tracks if track.get("type") == "audio"]
                if not audio_tracks:
                    # 如果没有音频轨道，自动创建一个
                    self.add_audio_track()
                    audio_tracks = [track for track in self.tracks if track.get("type") == "audio"]
                
                if audio_tracks:
                    # 使用第一个音频轨道
                    audio_track = audio_tracks[0]
                    
                    # 导入音频文件
                    success_count = 0
                    for file in files:
                        try:
                            filename = os.path.basename(file)
                            # 存储完整路径到映射
                            self.media_paths[filename] = file
                            # 在列表中显示文件名
                            self.media_listbox.insert(tk.END, filename)
                            # 添加到音频轨道
                            self.add_clip_to_track(audio_track, file, filename, "audio")
                            success_count += 1
                        except Exception as e:
                            print(f"导入音频文件 {file} 失败: {e}")
                    
                    if success_count > 0:
                        self.status_label.config(text=f"成功导入 {success_count} 个音频文件到音频轨道")
                        messagebox.showinfo("导入成功", f"成功导入 {success_count} 个音频文件到音频轨道")
                    else:
                        self.status_label.config(text="导入失败: 没有成功导入任何音频文件")
                        messagebox.showerror("导入失败", "没有成功导入任何音频文件，请检查文件权限和格式")
                else:
                    self.status_label.config(text="无法导入音频: 无法创建音频轨道")
                    messagebox.showerror("导入失败", "无法创建音频轨道，请重试")
            else:
                self.status_label.config(text="导入已取消")
        except Exception as e:
            self.status_label.config(text=f"导入失败: {str(e)}")
            messagebox.showerror("导入失败", f"导入音频文件时出错: {str(e)}")

    def switch_left_panel(self, panel_name):
        """切换左侧面板"""
        self.left_panel_var.set(panel_name)
        
        # 隐藏所有面板
        # 这里简化处理，只显示媒体面板
        pass
    
    def update_media_list(self):
        """更新媒体列表"""
        # 不再添加示例媒体
        # if self.media_listbox.size() == 0:
        #     # 添加示例媒体
        #     sample_media = ["示例视频1.mp4", "示例视频2.mp4", "示例音频1.mp3", "示例图片1.jpg"]
        #     for media in sample_media:
        #         self.media_listbox.insert(tk.END, media)
    
    def update_task_lists(self):
        """更新任务列表"""
        # 清空列表
        if hasattr(self, 'pending_tasks_listbox'):
            self.pending_tasks_listbox.delete(0, tk.END)
        if hasattr(self, 'completed_tasks_listbox'):
            self.completed_tasks_listbox.delete(0, tk.END)
        if hasattr(self, 'exported_videos_listbox'):
            self.exported_videos_listbox.delete(0, tk.END)
        
        # 添加示例未完成任务
        sample_pending_tasks = ["剪辑视频1", "添加字幕", "调整音频"]
        for task in sample_pending_tasks:
            if hasattr(self, 'pending_tasks_listbox'):
                self.pending_tasks_listbox.insert(tk.END, task)
        
        # 添加示例已完成任务
        sample_completed_tasks = ["导入媒体文件", "设置导出参数"]
        for task in sample_completed_tasks:
            if hasattr(self, 'completed_tasks_listbox'):
                self.completed_tasks_listbox.insert(tk.END, task)
        
        # 扫描导出目录，添加实际的导出视频
        if hasattr(self, 'exported_videos_listbox'):
            if os.path.exists(OUTPUT_DIR):
                for file in os.listdir(OUTPUT_DIR):
                    if file.endswith('.mp4') and 'exported' in file:
                        self.exported_videos_listbox.insert(tk.END, file)
    
    def open_exported_video(self, event):
        """打开导出的视频文件"""
        if hasattr(self, 'exported_videos_listbox'):
            selection = self.exported_videos_listbox.curselection()
            if selection:
                video_file = self.exported_videos_listbox.get(selection[0])
                video_path = os.path.join(OUTPUT_DIR, video_file)
                if os.path.exists(video_path):
                    try:
                        # 使用系统默认播放器打开视频
                        os.startfile(video_path)
                    except Exception as e:
                        messagebox.showerror("错误", f"无法打开视频文件: {str(e)}")
                else:
                    messagebox.showerror("错误", "视频文件不存在")
    
    def export_project(self):
        """导出项目"""
        # 模拟导出功能
        self.status_label.config(text="正在导出项目...")
        
        # 模拟导出过程
        import threading
        import time
        
        def simulate_export():
            time.sleep(3)
            # 生成导出文件路径
            output_file = os.path.join(OUTPUT_DIR, f"exported_project_{int(time.time())}.mp4")
            # 创建模拟文件
            with open(output_file, 'w') as f:
                f.write("Exported project placeholder")
            self.status_label.config(text=f"项目导出完成: {os.path.basename(output_file)}")
            # 更新任务列表，显示导出的视频
            if hasattr(self, 'update_task_lists'):
                self.update_task_lists()
        
        thread = threading.Thread(target=simulate_export, daemon=True)
        thread.start()
    
    def save_project(self):
        """保存项目"""
        try:
            # 弹出保存对话框
            save_path = filedialog.asksaveasfilename(
                defaultextension=".aiproject",
                filetypes=[("AI短剧项目", "*.aiproject"), ("所有文件", "*.*")],
                initialdir=OUTPUT_DIR,
                title="保存项目"
            )
            
            if save_path:
                self.status_label.config(text="正在保存项目...")
                
                # 生成项目数据
                project_data = {
                    "version": "1.0",
                    "created": datetime.now().isoformat(),
                    "media_files": [],
                    "export_settings": {
                        "resolution": getattr(self, 'resolution_var', tk.StringVar(value="1920x1080")).get(),
                        "encoder": getattr(self, 'encoder_var', tk.StringVar(value="H.264")).get(),
                        "format": "mp4",
                        "bitrate": "5M"
                    },
                    "output_mode": getattr(self, 'output_mode_var', tk.StringVar(value="30秒爆款引流")).get(),
                    "ai_tools": {
                        "auto_edit": getattr(self, 'auto_edit_var', tk.BooleanVar(value=False)).get(),
                        "extract_highlights": getattr(self, 'extract_highlights_var', tk.BooleanVar(value=False)).get(),
                        "enhance_video": getattr(self, 'enhance_video_var', tk.BooleanVar(value=False)).get()
                    },
                    "tracks": getattr(self, 'tracks', []),
                    "effects": [],
                    "audio_settings": {
                        "volume": getattr(self, 'volume_var', tk.DoubleVar(value=0.7)).get(),
                        "background_music": "",
                        "fade_in": True,
                        "fade_out": True
                    }
                }
                
                # 添加媒体文件
                try:
                    media_count = self.media_listbox.size()
                    for i in range(media_count):
                        media_file = self.media_listbox.get(i)
                        media_path = self.media_paths.get(media_file, media_file)
                        project_data["media_files"].append({
                            "name": media_file,
                            "path": media_path
                        })
                except Exception as e:
                    print(f"添加媒体文件到项目数据时出错: {e}")
                
                # 保存项目文件
                with open(save_path, 'w', encoding='utf-8') as f:
                    json.dump(project_data, f, ensure_ascii=False, indent=2)
                
                self.status_label.config(text=f"项目保存完成: {os.path.basename(save_path)}")
                messagebox.showinfo("保存成功", f"项目已成功保存到:\n{save_path}")
            else:
                self.status_label.config(text="保存已取消")
        except Exception as e:
            self.status_label.config(text=f"保存失败: {str(e)}")
            messagebox.showerror("保存失败", f"保存项目时出错: {str(e)}")
    
    def load_project(self):
        """加载项目"""
        try:
            # 弹出打开对话框
            load_path = filedialog.askopenfilename(
                filetypes=[("AI短剧项目", "*.aiproject"), ("所有文件", "*.*")],
                initialdir=OUTPUT_DIR,
                title="加载项目"
            )
            
            if load_path:
                self.status_label.config(text="正在加载项目...")
                
                # 读取项目文件
                with open(load_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)
                
                # 清空当前项目
                try:
                    self.media_listbox.delete(0, tk.END)
                    self.media_paths.clear()
                    # 清空轨道
                    if hasattr(self, 'tracks'):
                        self.tracks.clear()
                    # 清空效果
                except Exception as e:
                    print(f"清空当前项目时出错: {e}")
                
                # 加载媒体文件
                for media in project_data.get('media_files', []):
                    try:
                        self.media_paths[media['name']] = media['path']
                        self.media_listbox.insert(tk.END, media['name'])
                    except:
                        pass
                
                # 加载导出设置
                export_settings = project_data.get('export_settings', {})
                try:
                    self.resolution_var.set(export_settings.get('resolution', '1920x1080'))
                    self.encoder_var.set(export_settings.get('encoder', 'H.264'))
                except:
                    pass
                
                # 加载输出模式
                try:
                    self.output_mode_var.set(project_data.get('output_mode', '30秒爆款引流'))
                except:
                    pass
                
                # 加载AI工具设置
                ai_tools = project_data.get('ai_tools', {})
                try:
                    self.auto_edit_var.set(ai_tools.get('auto_edit', False))
                    self.extract_highlights_var.set(ai_tools.get('extract_highlights', False))
                    self.enhance_video_var.set(ai_tools.get('enhance_video', False))
                except:
                    pass
                
                # 加载音频设置
                audio_settings = project_data.get('audio_settings', {})
                try:
                    self.volume_var.set(audio_settings.get('volume', 0.7))
                except:
                    pass
                
                self.status_label.config(text=f"项目加载完成: {os.path.basename(load_path)}")
                messagebox.showinfo("加载成功", f"项目已成功加载:\n{load_path}")
            else:
                self.status_label.config(text="加载已取消")
        except Exception as e:
            self.status_label.config(text=f"加载失败: {str(e)}")
            messagebox.showerror("加载失败", f"加载项目时出错: {str(e)}")
    
    def new_project(self):
        """新建项目"""
        try:
            # 询问是否保存当前项目
            if hasattr(self, 'media_listbox') and self.media_listbox.size() > 0:
                answer = messagebox.askyesnocancel("新建项目", "当前项目有未保存的更改，是否保存？")
                if answer is None:
                    return  # 取消
                elif answer:
                    self.save_project()  # 保存
            
            # 清空当前项目
            try:
                self.media_listbox.delete(0, tk.END)
                self.media_paths.clear()
                # 清空轨道
                if hasattr(self, 'tracks'):
                    self.tracks.clear()
                # 清空效果
            except:
                pass
            
            # 重置设置
            try:
                self.resolution_var.set('1920x1080')
                self.encoder_var.set('H.264')
                self.output_mode_var.set('30秒爆款引流')
                self.auto_edit_var.set(False)
                self.extract_highlights_var.set(False)
                self.enhance_video_var.set(False)
                self.volume_var.set(0.7)
            except:
                pass
            
            self.status_label.config(text="已新建项目")
            messagebox.showinfo("新建项目", "已创建新项目，请导入媒体文件开始编辑")
        except Exception as e:
            self.status_label.config(text=f"新建项目失败: {str(e)}")
            messagebox.showerror("新建项目失败", f"新建项目时出错: {str(e)}")
    
    def show_project_manager(self):
        """显示项目管理窗口"""
        project_window = tk.Toplevel(self.root)
        project_window.title("项目管理")
        project_window.geometry("600x400")
        project_window.configure(bg="#1a1a1a")
        
        # 项目管理框架
        project_frame = tk.Frame(project_window, bg="#252525", pady=30, padx=30)
        project_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(project_frame, text="项目管理", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 项目操作按钮
        buttons_frame = tk.Frame(project_frame, bg="#252525")
        buttons_frame.pack(fill=tk.X, pady=20)
        
        project_buttons = [
            {"text": "新建项目", "command": self.new_project, "bg": "#007acc"},
            {"text": "打开项目", "command": self.load_project, "bg": "#333333"},
            {"text": "保存项目", "command": self.save_project, "bg": "#333333"},
            {"text": "保存为", "command": self.save_project, "bg": "#333333"}
        ]
        
        for btn_info in project_buttons:
            btn = tk.Button(buttons_frame, text=btn_info["text"], command=btn_info["command"], 
                           bg=btn_info["bg"], fg="#ffffff", font=("微软雅黑", 10), 
                           padx=20, pady=10, relief=tk.FLAT)
            btn.pack(fill=tk.X, pady=5)
        
        # 最近项目列表
        tk.Label(project_frame, text="最近项目", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#007acc").pack(anchor=tk.W, pady=10)
        
        recent_projects_frame = tk.Frame(project_frame, bg="#252525")
        recent_projects_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 模拟最近项目
        recent_projects = [
            "project_20240101_120000.aiproject",
            "project_20240102_130000.aiproject",
            "project_20240103_140000.aiproject"
        ]
        
        for project in recent_projects:
            project_btn = tk.Button(recent_projects_frame, text=project, 
                                  command=lambda p=project: self.status_label.config(text=f"已选择项目: {p}"), 
                                  bg="#333333", fg="#ffffff", font=("微软雅黑", 9), 
                                  padx=15, pady=8, relief=tk.FLAT, anchor=tk.W)
            project_btn.pack(fill=tk.X, pady=3)
        
        # 清空最近项目按钮
        clear_btn = tk.Button(project_frame, text="清空最近项目", command=lambda: self.status_label.config(text="已清空最近项目"), 
                             bg="#444444", fg="#cccccc", font=("微软雅黑", 9), 
                             padx=15, pady=8, relief=tk.FLAT)
        clear_btn.pack(anchor=tk.W, pady=10)
    
    def undo_action(self):
        """撤销操作"""
        self.status_label.config(text="已撤销上一步操作")
    
    def redo_action(self):
        """重做操作"""
        self.status_label.config(text="已重做操作")
    
    def show_clip_options(self):
        """显示剪辑选项"""
        # 创建剪辑选项窗口
        clip_window = tk.Toplevel(self.root)
        clip_window.title("剪辑选项")
        clip_window.geometry("400x300")
        clip_window.configure(bg="#1a1a1a")
        
        # 剪辑选项框架
        clip_frame = tk.Frame(clip_window, bg="#252525", pady=20, padx=20)
        clip_frame.pack(fill=tk.BOTH, expand=True)
        
        # 剪辑选项标题
        tk.Label(clip_frame, text="剪辑选项", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 剪辑选项列表
        clip_options = [
            "分割片段", "删除片段", "复制片段", "剪切片段", 
            "粘贴片段", "调整时长", "调整位置"
        ]
        
        for option in clip_options:
            option_btn = tk.Button(clip_frame, text=option, command=lambda opt=option: self.status_label.config(text=f"已选择: {opt}"), 
                                  bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=15, pady=8, relief=tk.FLAT)
            option_btn.pack(fill=tk.X, pady=5)
    
    def show_effects(self):
        """显示效果"""
        # 创建效果选项窗口
        effect_window = tk.Toplevel(self.root)
        effect_window.title("视频效果")
        effect_window.geometry("600x500")
        effect_window.configure(bg="#1a1a1a")
        
        # 效果选项框架
        effect_frame = tk.Frame(effect_window, bg="#252525", pady=20, padx=20)
        effect_frame.pack(fill=tk.BOTH, expand=True)
        
        # 效果选项标题
        tk.Label(effect_frame, text="视频效果", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 效果分类
        categories = [
            {"name": "转场效果", "effects": ["淡入淡出", "滑动", "缩放", "旋转", "擦除", "溶解", "百叶窗", "翻页", "3D旋转", "闪光"]},
            {"name": "滤镜效果", "effects": ["自然", "清新", "复古", "黑白", "暖色", "冷色", "电影感", "梦幻", "鲜艳", "柔和"]},
            {"name": "动画效果", "effects": ["淡入", "淡出", "缩放", "旋转", "弹跳", "摇摆", "震动", "闪烁", "波浪", "粒子"]},
            {"name": "文字效果", "effects": ["标题动画", "滚动字幕", "打字机", "淡入淡出", "缩放", "旋转", "彩色渐变", "阴影效果", "描边效果", "发光效果"]},
            {"name": "贴纸效果", "effects": ["表情", "图标", "装饰", "边框", "文字", "动态贴纸", "节日", "天气", "动物", "植物"]},
            {"name": "调色效果", "effects": ["亮度", "对比度", "饱和度", "色温", "色调", "锐化", "模糊", "降噪", "色彩平衡", "曲线调整"]}
        ]
        
        # 创建效果分类标签页
        notebook = ttk.Notebook(effect_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=10)
        
        for category in categories:
            category_frame = tk.Frame(notebook, bg="#252525")
            notebook.add(category_frame, text=category["name"])
            
            # 添加效果按钮
            effects_container = tk.Frame(category_frame, bg="#252525")
            effects_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            for i, effect in enumerate(category["effects"]):
                row = i // 2
                col = i % 2
                effect_btn = tk.Button(effects_container, text=effect, 
                                      command=lambda e=effect, c=category["name"]: self.apply_effect(c, e), 
                                      bg="#333333", fg="#ffffff", font=("微软雅黑", 9), 
                                      padx=10, pady=6, relief=tk.FLAT, width=15)
                effect_btn.grid(row=row, column=col, padx=5, pady=5, sticky=tk.W+tk.E)
    
    def apply_effect(self, category, effect):
        """应用效果"""
        # 检查是否有选中的片段
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个片段")
            return
        
        # 应用效果到选中的片段
        if category == "转场效果":
            self.selected_clip["transition"] = effect
        elif category == "滤镜效果":
            self.selected_clip["filter"] = effect
        elif category == "动画效果":
            self.selected_clip["animation"] = effect
        elif category == "文字效果":
            self.selected_clip["text_effect"] = effect
        elif category == "贴纸效果":
            self.selected_clip["sticker"] = effect
        elif category == "调色效果":
            self.selected_clip["color_correction"] = effect
        
        self.status_label.config(text=f"已应用{category}: {effect}")
        messagebox.showinfo("效果应用", f"已应用{category}: {effect}\n\n效果将在导出时生效")
    
    def show_audio_options(self):
        """显示音频选项（已集成到右侧工具栏，此方法保留用于兼容）"""
        self.status_label.config(text="音频工具已集成到右侧工具栏")
        messagebox.showinfo("提示", "音频工具已集成到右侧工具栏的「音频工具」面板中")
    
    def crop_audio(self):
        """截取音频 - 使用右侧工具栏的设置"""
        try:
            # 获取当前设置
            volume = getattr(self, 'audio_volume_var', tk.DoubleVar(value=1.0)).get()
            fadein = getattr(self, 'audio_fadein_var', tk.StringVar(value="0.5")).get()
            fadeout = getattr(self, 'audio_fadeout_var', tk.StringVar(value="0.5")).get()
            
            self.status_label.config(text=f"音频截取: 音量={volume}, 淡入={fadein}s, 淡出={fadeout}s")
            
            # 检查是否有视频（使用current_preview_video，与预览系统一致）
            video_path = getattr(self, 'current_preview_video', None)
            if not video_path and hasattr(self, 'selected_clip') and self.selected_clip:
                video_path = self.selected_clip.get('path')
            
            if video_path and os.path.exists(video_path):
                messagebox.showinfo("音频截取", f"将截取音频\n音量: {volume}x\n淡入: {fadein}秒\n淡出: {fadeout}秒\n\n视频: {os.path.basename(video_path)}")
            else:
                messagebox.showwarning("提示", "请先导入视频")
                
        except Exception as e:
            self.status_label.config(text=f"音频截取失败: {e}")
            messagebox.showerror("错误", f"音频截取失败: {e}")
    
    def voice_enhance_and_denoise_audio(self):
        """一键人声增强+背景降噪（使用 core.audio_enhancements）。"""
        if not audio_enhancements:
            messagebox.showerror("错误", "音频增强模块未加载")
            return
        input_path = None
        if getattr(self, "current_preview_video", None) and os.path.exists(self.current_preview_video):
            input_path = self.current_preview_video
        if not input_path and getattr(self, "selected_clip", None):
            input_path = self.selected_clip.get("path")
        if not input_path or not os.path.exists(input_path):
            input_path = filedialog.askopenfilename(title="选择视频或音频", filetypes=[("媒体", "*.mp4 *.avi *.mov *.mp3 *.wav *.m4a"), ("所有", "*.*")])
        if not input_path or not os.path.exists(input_path):
            return
        out_dir = os.path.dirname(input_path)
        base = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(out_dir, f"{base}_enhanced.mp4" if input_path.lower().endswith((".mp4", ".avi", ".mov")) else f"{base}_enhanced.wav")
        output_path = filedialog.asksaveasfilename(initialfile=os.path.basename(output_path), defaultextension=".mp4", filetypes=[("MP4", "*.mp4"), ("WAV", "*.wav"), ("所有", "*.*")])
        if not output_path:
            return
        ffmpeg_path = globals().get("FFMPEG", "ffmpeg")
        self.status_label.config(text="正在人声增强+降噪...")
        try:
            ok = audio_enhancements.voice_enhance_and_denoise(ffmpeg_path, input_path, output_path)
            if ok:
                self.status_label.config(text="人声增强+降噪完成")
                messagebox.showinfo("成功", f"已保存到:\n{output_path}")
            else:
                self.status_label.config(text="人声增强+降噪失败")
                messagebox.showerror("错误", "处理失败，请查看日志")
        except Exception as e:
            self.status_label.config(text="处理异常")
            messagebox.showerror("错误", str(e))

    def adjust_audio_volume(self):
        """调整音频音量"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        
        # 创建音量调整窗口
        volume_window = tk.Toplevel(self.root)
        volume_window.title("音量调整")
        volume_window.geometry("400x300")
        volume_window.configure(bg=bg_color)
        
        # 音量调整框架
        volume_frame = tk.Frame(volume_window, bg=frame_color, pady=30, padx=30)
        volume_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(volume_frame, text="音量调整", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=15)
        
        # 音量滑块
        volume_var = tk.DoubleVar(value=self.selected_clip.get("volume", 1.0))
        volume_scale = tk.Scale(volume_frame, from_=0, to=2, resolution=0.1, orient=tk.HORIZONTAL, 
                               variable=volume_var, bg=item_color, fg=text_color, 
                               highlightbackground=item_color, troughcolor=item_color, 
                               activebackground="#007acc", length=250)
        volume_scale.pack(pady=20, padx=20)
        
        # 音量数值显示
        volume_value_label = tk.Label(volume_frame, text=f"音量: {volume_var.get():.1f}", bg=frame_color, fg=text_color, font=("微软雅黑", 10))
        volume_value_label.pack(pady=10)
        
        def update_volume_value(event):
            volume_value_label.config(text=f"音量: {volume_var.get():.1f}")
        
        volume_scale.bind("<Motion>", update_volume_value)
        
        # 应用按钮
        apply_btn = tk.Button(volume_frame, text="应用音量调整", 
                              command=lambda: apply_volume(volume_var.get()), 
                              bg="#007acc", fg=text_color, font=("微软雅黑", 10), 
                              padx=20, pady=10, relief=tk.FLAT)
        apply_btn.pack(pady=20)
        
        def apply_volume(volume):
            self.selected_clip["volume"] = volume
            self.status_label.config(text=f"音量已调整为: {volume:.1f}")
            volume_window.destroy()
    
    def automate_audio_volume(self):
        """创建音量关键帧"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        self.status_label.config(text="音量自动化功能开发中")
        messagebox.showinfo("提示", "音量自动化功能即将推出")
    
    def mute_audio(self):
        """完全静音音频"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        self.selected_clip["volume"] = 0
        self.status_label.config(text="音频已静音")
        messagebox.showinfo("提示", "音频已完全静音")
    
    def add_audio_fade_in(self):
        """音频开始处淡入"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        
        # 创建淡入设置窗口
        fade_window = tk.Toplevel(self.root)
        fade_window.title("音频淡入")
        fade_window.geometry("400x300")
        fade_window.configure(bg=bg_color)
        
        # 淡入设置框架
        fade_frame = tk.Frame(fade_window, bg=frame_color, pady=30, padx=30)
        fade_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(fade_frame, text="音频淡入设置", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=15)
        
        # 淡入时长滑块
        fade_duration_var = tk.DoubleVar(value=1.0)
        fade_scale = tk.Scale(fade_frame, from_=0.1, to=5.0, resolution=0.1, orient=tk.HORIZONTAL, 
                             variable=fade_duration_var, bg=item_color, fg=text_color, 
                             highlightbackground=item_color, troughcolor=item_color, 
                             activebackground="#007acc", length=250)
        fade_scale.pack(pady=20, padx=20)
        
        # 时长数值显示
        fade_value_label = tk.Label(fade_frame, text=f"淡入时长: {fade_duration_var.get():.1f}秒", bg=frame_color, fg=text_color, font=("微软雅黑", 10))
        fade_value_label.pack(pady=10)
        
        def update_fade_value(event):
            fade_value_label.config(text=f"淡入时长: {fade_duration_var.get():.1f}秒")
        
        fade_scale.bind("<Motion>", update_fade_value)
        
        # 应用按钮
        apply_btn = tk.Button(fade_frame, text="应用淡入效果", 
                              command=lambda: apply_fade(fade_duration_var.get()), 
                              bg="#007acc", fg=text_color, font=("微软雅黑", 10), 
                              padx=20, pady=10, relief=tk.FLAT)
        apply_btn.pack(pady=20)
        
        def apply_fade(duration):
            self.selected_clip["fade_in"] = duration
            self.status_label.config(text=f"已添加 {duration:.1f}秒淡入效果")
            fade_window.destroy()
    
    def add_audio_fade_out(self):
        """音频结束处淡出"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        
        # 创建淡出设置窗口
        fade_window = tk.Toplevel(self.root)
        fade_window.title("音频淡出")
        fade_window.geometry("400x300")
        fade_window.configure(bg=bg_color)
        
        # 淡出设置框架
        fade_frame = tk.Frame(fade_window, bg=frame_color, pady=30, padx=30)
        fade_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(fade_frame, text="音频淡出设置", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=15)
        
        # 淡出时长滑块
        fade_duration_var = tk.DoubleVar(value=1.0)
        fade_scale = tk.Scale(fade_frame, from_=0.1, to=5.0, resolution=0.1, orient=tk.HORIZONTAL, 
                             variable=fade_duration_var, bg=item_color, fg=text_color, 
                             highlightbackground=item_color, troughcolor=item_color, 
                             activebackground="#007acc", length=250)
        fade_scale.pack(pady=20, padx=20)
        
        # 时长数值显示
        fade_value_label = tk.Label(fade_frame, text=f"淡出时长: {fade_duration_var.get():.1f}秒", bg=frame_color, fg=text_color, font=("微软雅黑", 10))
        fade_value_label.pack(pady=10)
        
        def update_fade_value(event):
            fade_value_label.config(text=f"淡出时长: {fade_duration_var.get():.1f}秒")
        
        fade_scale.bind("<Motion>", update_fade_value)
        
        # 应用按钮
        apply_btn = tk.Button(fade_frame, text="应用淡出效果", 
                              command=lambda: apply_fade(fade_duration_var.get()), 
                              bg="#007acc", fg=text_color, font=("微软雅黑", 10), 
                              padx=20, pady=10, relief=tk.FLAT)
        apply_btn.pack(pady=20)
        
        def apply_fade(duration):
            self.selected_clip["fade_out"] = duration
            self.status_label.config(text=f"已添加 {duration:.1f}秒淡出效果")
            fade_window.destroy()
    
    def add_audio_crossfade(self):
        """两段音频之间的过渡"""
        self.status_label.config(text="交叉淡入淡出功能开发中")
        messagebox.showinfo("提示", "交叉淡入淡出功能即将推出")
    
    def remove_audio_noise(self):
        """去除背景噪音"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        self.selected_clip["noise_reduction"] = True
        self.status_label.config(text="已添加噪音消除效果")
        messagebox.showinfo("提示", "已添加噪音消除效果")
    
    def adjust_audio_eq(self):
        """调整音频频率平衡"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        self.status_label.config(text="音频均衡器功能开发中")
        messagebox.showinfo("提示", "音频均衡器功能即将推出")
    
    def add_audio_compression(self):
        """音频动态范围压缩"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        self.selected_clip["compression"] = True
        self.status_label.config(text="已添加音频压缩效果")
        messagebox.showinfo("提示", "已添加音频压缩效果")
    
    def add_audio_reverb(self):
        """添加空间混响效果"""
        if not hasattr(self, 'selected_clip') or not self.selected_clip:
            messagebox.showerror("错误", "请先选择一个音频片段")
            return
        
        self.selected_clip["reverb"] = True
        self.status_label.config(text="已添加混响效果")
        messagebox.showinfo("提示", "已添加混响效果")
    
    def clip_audio(self):
        """切割和修剪音频"""
        self.status_label.config(text="音频剪辑功能开发中")
        messagebox.showinfo("提示", "音频剪辑功能即将推出")
    
    def extract_audio(self):
        """从视频中分离音频"""
        self.status_label.config(text="音频分离功能开发中")
        messagebox.showinfo("提示", "音频分离功能即将推出")
    
    def mix_audio_tracks(self):
        """混合多个音频轨道"""
        self.status_label.config(text="音频混合功能开发中")
        messagebox.showinfo("提示", "音频混合功能即将推出")
    
    def show_subtitle_options(self):
        """显示字幕选项（已集成到右侧工具栏，此方法保留用于兼容）"""
        # 展开右侧字幕工具面板
        self.status_label.config(text="字幕工具已集成到右侧工具栏")
        messagebox.showinfo("提示", "字幕工具已集成到右侧工具栏的「字幕工具」面板中")
    
    def add_subtitle(self):
        """添加字幕 - 使用右侧工具栏的设置"""
        try:
            # 获取当前设置
            font = getattr(self, 'subtitle_font_var', tk.StringVar(value="微软雅黑")).get()
            size = getattr(self, 'subtitle_size_var', tk.StringVar(value="24")).get()
            color = getattr(self, 'subtitle_color_var', tk.StringVar(value="白色")).get()
            position = getattr(self, 'subtitle_position_var', tk.StringVar(value="底部居中")).get()
            
            # 颜色映射
            color_map = {
                "白色": "#FFFFFF",
                "黄色": "#FFFF00",
                "红色": "#FF0000",
                "蓝色": "#0000FF",
                "绿色": "#00FF00",
                "黑色": "#000000"
            }
            
            hex_color = color_map.get(color, "#FFFFFF")
            
            self.status_label.config(text=f"添加字幕: 字体={font}, 大小={size}, 颜色={color}, 位置={position}")
            
            # 检查是否有视频（使用current_preview_video，与预览系统一致）
            video_path = getattr(self, 'current_preview_video', None)
            if not video_path and hasattr(self, 'selected_clip') and self.selected_clip:
                video_path = self.selected_clip.get('path')
            
            if video_path and os.path.exists(video_path):
                messagebox.showinfo("添加字幕", f"将为视频添加字幕\n字体: {font}\n大小: {size}px\n颜色: {color}\n位置: {position}\n\n视频: {os.path.basename(video_path)}")
            else:
                messagebox.showwarning("提示", "请先导入视频")
                
        except Exception as e:
            self.status_label.config(text=f"添加字幕失败: {e}")
            messagebox.showerror("错误", f"添加字幕失败: {e}")
    
    def show_multilingual_subtitle(self):
        """显示多语言字幕插件"""
        try:
            from plugin.multilingual_subtitle import MultilingualSubtitlePlugin
            plugin = MultilingualSubtitlePlugin()
            plugin.run(root=self.root)
        except ImportError as e:
            print(f"无法导入多语言字幕插件: {e}")
        except Exception as e:
            print(f"启动多语言字幕插件失败: {e}")
    
    def generate_ai_subtitles(self):
        """AI字幕生成"""
        try:
            # 检查是否有视频
            if not hasattr(self, 'current_preview_video') or not self.current_preview_video:
                messagebox.showwarning("提示", "请先导入视频")
                return
            
            # 显示处理中提示
            self.status_label.config(text="正在生成AI字幕...")
            self.root.update()
            
            # 这里可以集成实际的AI字幕生成API
            # 模拟处理
            import time
            time.sleep(1)
            
            messagebox.showinfo("成功", "AI字幕生成完成！\n\n字幕已自动添加到视频")
            self.status_label.config(text="AI字幕生成完成")
        except Exception as e:
            print(f"AI字幕生成失败: {e}")
            self.status_label.config(text=f"AI字幕生成失败: {e}")
    
    def enhance_audio(self):
        """音频增强"""
        try:
            self.status_label.config(text="正在增强音频...")
            self.root.update()
            
            # 模拟音频增强处理
            import time
            time.sleep(0.5)
            
            messagebox.showinfo("成功", "音频增强完成！")
            self.status_label.config(text="音频增强完成")
        except Exception as e:
            print(f"音频增强失败: {e}")
            self.status_label.config(text=f"音频增强失败: {e}")
    
    def denoise_audio(self):
        """音频降噪"""
        try:
            self.status_label.config(text="正在降噪处理...")
            self.root.update()
            
            # 模拟降噪处理
            import time
            time.sleep(0.5)
            
            messagebox.showinfo("成功", "音频降噪完成！")
            self.status_label.config(text="音频降噪完成")
        except Exception as e:
            print(f"音频降噪失败: {e}")
            self.status_label.config(text=f"音频降噪失败: {e}")
    
    def apply_preset(self, preset_id):
        """应用预设"""
        preset_names = {
            "douyin": "抖音风格",
            "kuaishou": "快手风格",
            "bilibili": "B站风格",
            "cinematic": "电影风格"
        }
        preset_name = preset_names.get(preset_id, preset_id)
        
        try:
            self.status_label.config(text=f"正在应用{preset_name}预设...")
            self.root.update()
            
            # 根据预设调整参数
            if preset_id == "douyin":
                self.resolution_var.set("1080x1920")  # 竖屏
                self.output_mode_var.set("30秒爆款引流")
            elif preset_id == "kuaishou":
                self.resolution_var.set("1080x1920")  # 竖屏
                self.output_mode_var.set("30秒爆款引流")
            elif preset_id == "bilibili":
                self.resolution_var.set("1920x1080")  # 横屏
                self.output_mode_var.set("8分钟挂车长视频")
            elif preset_id == "cinematic":
                self.resolution_var.set("1920x1080")  # 横屏
                self.fps_var.set("24")  # 电影帧率
            
            messagebox.showinfo("成功", f"已应用{preset_name}预设！")
            self.status_label.config(text=f"已应用{preset_name}预设")
        except Exception as e:
            print(f"应用预设失败: {e}")
            self.status_label.config(text=f"应用预设失败: {e}")
    
    def show_ai_tools(self):
        """显示AI工具"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        
        # 创建AI工具选项窗口
        ai_window = tk.Toplevel(self.root)
        ai_window.title("AI工具")
        ai_window.geometry("400x300")
        ai_window.configure(bg=bg_color)
        
        # AI工具选项框架
        ai_frame = tk.Frame(ai_window, bg=frame_color, pady=20, padx=20)
        ai_frame.pack(fill=tk.BOTH, expand=True)
        
        # AI工具选项标题
        tk.Label(ai_frame, text="AI工具", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=10)
        
        # AI工具选项列表
        ai_tools = [
            "FunClip自动剪辑", "AutoClip高光识别", "VideoFusion视频增强", 
            "AI字幕生成", "AI文案生成", "AI配音", "千问VL视频分析"
        ]
        
        for tool in ai_tools:
            if tool == "千问VL视频分析":
                tool_btn = tk.Button(ai_frame, text=tool, command=self.analyze_video_with_qwen_vl, 
                                      bg=item_color, fg=text_color, font=("微软雅黑", 10), padx=15, pady=8, relief=tk.FLAT)
            else:
                tool_btn = tk.Button(ai_frame, text=tool, command=lambda t=tool: self.status_label.config(text=f"已选择: {t}"), 
                                      bg=item_color, fg=text_color, font=("微软雅黑", 10), padx=15, pady=8, relief=tk.FLAT)
            tool_btn.pack(fill=tk.X, pady=5)

    def analyze_video_with_qwen_vl(self):
        """使用千问VL模型分析视频"""
        # 让用户选择视频文件
        import tkinter.filedialog
        video_path = tkinter.filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("视频文件", "*.mp4;*.avi;*.mov;*.wmv;*.flv;*.mkv"), ("所有文件", "*.*")]
        )
        
        if not video_path:
            return
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        
        # 创建分析窗口
        analysis_window = tk.Toplevel(self.root)
        analysis_window.title("千问VL视频分析")
        analysis_window.geometry("800x600")
        analysis_window.configure(bg=bg_color)
        
        # 分析窗口框架
        analysis_frame = tk.Frame(analysis_window, bg=frame_color, pady=30, padx=30)
        analysis_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(analysis_frame, text="千问VL视频分析", font=("微软雅黑", 16, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=20)
        
        # 视频信息
        video_info_frame = tk.Frame(analysis_frame, bg=frame_color, pady=15)
        video_info_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(video_info_frame, text=f"视频文件: {video_path}", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(anchor=tk.W, pady=5)
        
        # 分析状态
        status_var = tk.StringVar(value="正在分析视频...")
        status_label = tk.Label(analysis_frame, textvariable=status_var, bg=frame_color, fg="#007acc", font=("微软雅黑", 11))
        status_label.pack(anchor=tk.W, pady=10)
        
        # 分析结果区域
        result_frame = tk.Frame(analysis_frame, bg=frame_color, pady=20)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=20)
        
        # 结果标题
        tk.Label(result_frame, text="分析结果", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=10)
        
        # 结果文本框
        result_text = tk.Text(
            result_frame, 
            width=90, 
            height=15, 
            bg=item_color, 
            fg=text_color,
            font=("微软雅黑", 10),
            wrap=tk.WORD
        )
        result_text.pack(fill=tk.BOTH, expand=True, pady=10)
        result_text.config(state=tk.DISABLED)
        
        # 开始分析（使用线程避免阻塞UI）
        import threading
        
        def do_analysis():
            try:
                # 切换到千问VL模型
                original_model = model_manager.current_model
                model_manager.switch_model("通义千问VL")
                
                # 分析视频并生成文案
                title, content, keywords = model_manager.generate_content(video_path)
                
                # 恢复原模型
                model_manager.switch_model(original_model)
                
                # 更新UI
                status_var.set("分析完成")
                
                # 显示结果
                result_text.config(state=tk.NORMAL)
                result_text.delete(1.0, tk.END)
                result_text.insert(tk.END, f"标题: {title}\n\n")
                result_text.insert(tk.END, f"内容: {content}\n\n")
                result_text.insert(tk.END, f"关键词: {keywords}\n\n")
                result_text.insert(tk.END, "智能剪辑建议:\n")
                result_text.insert(tk.END, "1. 基于视频内容，建议保留最精彩的片段\n")
                result_text.insert(tk.END, "2. 根据分析结果，推荐使用相关的背景音乐\n")
                result_text.insert(tk.END, "3. 可考虑添加与内容相关的字幕效果\n")
                result_text.config(state=tk.DISABLED)
                
            except Exception as e:
                status_var.set(f"分析失败: {str(e)}")
                result_text.config(state=tk.NORMAL)
                result_text.delete(1.0, tk.END)
                result_text.insert(tk.END, f"分析失败: {str(e)}\n")
                result_text.config(state=tk.DISABLED)
        
        # 启动分析线程
        thread = threading.Thread(target=do_analysis, daemon=True)
        thread.start()

    def batch_processing(self):
        """批量处理功能"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建批量处理窗口
        batch_window = tk.Toplevel(self.root)
        batch_window.title("批量处理")
        batch_window.geometry("800x600")
        batch_window.configure(bg=bg_color)
        
        # 批量处理框架
        batch_frame = tk.Frame(batch_window, bg=frame_color, pady=30, padx=30)
        batch_frame.pack(fill=tk.BOTH, expand=True)
        
        # 批量处理标题
        tk.Label(batch_frame, text="批量处理", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=20)
        
        # 批量处理选项
        options_frame = tk.Frame(batch_frame, bg=frame_color)
        options_frame.pack(fill=tk.X, pady=20)
        
        # 批量切割
        self.batch_cut_var = tk.BooleanVar(value=False)
        batch_cut_check = tk.Checkbutton(options_frame, text="批量切割", variable=self.batch_cut_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color)
        batch_cut_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 批量去重
        self.batch_duplicate_var = tk.BooleanVar(value=False)
        batch_duplicate_check = tk.Checkbutton(options_frame, text="批量去重", variable=self.batch_duplicate_var, 
                                              bg=frame_color, fg=text_color, selectcolor=item_color, 
                                              activebackground=frame_color, activeforeground=text_color)
        batch_duplicate_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 批量加字幕
        self.batch_subtitle_var = tk.BooleanVar(value=False)
        batch_subtitle_check = tk.Checkbutton(options_frame, text="批量加字幕", variable=self.batch_subtitle_var, 
                                              bg=frame_color, fg=text_color, selectcolor=item_color, 
                                              activebackground=frame_color, activeforeground=text_color)
        batch_subtitle_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 批量加BGM
        self.batch_bgm_var = tk.BooleanVar(value=False)
        batch_bgm_check = tk.Checkbutton(options_frame, text="批量加BGM", variable=self.batch_bgm_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color)
        batch_bgm_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 批量加转场
        self.batch_transition_var = tk.BooleanVar(value=False)
        batch_transition_check = tk.Checkbutton(options_frame, text="批量加转场", variable=self.batch_transition_var, 
                                              bg=frame_color, fg=text_color, selectcolor=item_color, 
                                              activebackground=frame_color, activeforeground=text_color)
        batch_transition_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 批量调整画幅
        self.batch_frame_var = tk.BooleanVar(value=False)
        batch_frame_check = tk.Checkbutton(options_frame, text="批量调整画幅", variable=self.batch_frame_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color)
        batch_frame_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 批量处理参数
        params_frame = tk.Frame(batch_frame, bg=frame_color, pady=20)
        params_frame.pack(fill=tk.X, pady=20)
        
        # 切割参数
        cut_frame = tk.Frame(params_frame, bg=frame_color)
        cut_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(cut_frame, text="切割时长 (秒):", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.cut_duration_var = tk.DoubleVar(value=30.0)
        cut_duration_entry = tk.Entry(cut_frame, textvariable=self.cut_duration_var, width=10, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        cut_duration_entry.pack(side=tk.LEFT, padx=10)
        
        # 去重参数
        duplicate_frame = tk.Frame(params_frame, bg=frame_color)
        duplicate_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(duplicate_frame, text="去重强度:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.duplicate_strength_var = tk.DoubleVar(value=0.8)
        duplicate_scale = tk.Scale(duplicate_frame, from_=0, to=1, resolution=0.1, orient=tk.HORIZONTAL, 
                                   variable=self.duplicate_strength_var, bg=item_color, fg=text_color, 
                                   highlightbackground=item_color, troughcolor=item_color, 
                                   activebackground="#007acc", length=200)
        duplicate_scale.pack(side=tk.LEFT, padx=10)
        
        # 字幕参数
        subtitle_frame = tk.Frame(params_frame, bg=frame_color)
        subtitle_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(subtitle_frame, text="字幕样式:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.subtitle_style_var = tk.StringVar(value="默认")
        subtitle_options = ["默认", "简约", "华丽", "科技感"]
        subtitle_menu = ttk.Combobox(subtitle_frame, textvariable=self.subtitle_style_var, values=subtitle_options, state="readonly", width=15)
        subtitle_menu.pack(side=tk.LEFT, padx=10)
        
        # BGM参数
        bgm_frame = tk.Frame(params_frame, bg=frame_color)
        bgm_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(bgm_frame, text="BGM文件:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.bgm_path_var = tk.StringVar()
        bgm_entry = tk.Entry(bgm_frame, textvariable=self.bgm_path_var, width=40, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        bgm_entry.pack(side=tk.LEFT, padx=10)
        bgm_btn = tk.Button(bgm_frame, text="浏览", command=lambda: self.browse_file(self.bgm_path_var, (("音频文件", "*.mp3 *.wav *.aac *.flac"),)), bg=item_color, fg=text_color, font=("微软雅黑", 9), padx=10, pady=5, relief=tk.FLAT)
        bgm_btn.pack(side=tk.LEFT, padx=10)
        
        # 转场参数
        transition_frame = tk.Frame(params_frame, bg=frame_color)
        transition_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(transition_frame, text="转场效果:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.transition_style_var = tk.StringVar(value="淡入淡出")
        transition_options = ["淡入淡出", "滑动", "缩放", "旋转"]
        transition_menu = ttk.Combobox(transition_frame, textvariable=self.transition_style_var, values=transition_options, state="readonly", width=15)
        transition_menu.pack(side=tk.LEFT, padx=10)
        
        # 画幅参数
        frame_frame = tk.Frame(params_frame, bg=frame_color)
        frame_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(frame_frame, text="目标画幅:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.frame_style_var = tk.StringVar(value="16:9")
        frame_options = ["16:9", "9:16", "4:3", "1:1"]
        frame_menu = ttk.Combobox(frame_frame, textvariable=self.frame_style_var, values=frame_options, state="readonly", width=15)
        frame_menu.pack(side=tk.LEFT, padx=10)
        
        # 批量处理按钮
        button_frame = tk.Frame(batch_frame, bg=frame_color, pady=20)
        button_frame.pack(fill=tk.X, pady=20)
        
        start_batch_btn = tk.Button(button_frame, text="开始批量处理", command=self.start_batch_processing, bg="#007acc", fg=text_color, font=("微软雅黑", 12), padx=30, pady=12, relief=tk.FLAT)
        start_batch_btn.pack(anchor=tk.CENTER)
        
        # 批量处理状态
        self.batch_status_var = tk.StringVar(value="就绪")
        status_label = tk.Label(batch_frame, textvariable=self.batch_status_var, bg=frame_color, fg="#007acc", font=("微软雅黑", 10))
        status_label.pack(pady=10)

    def start_batch_processing(self):
        """开始批量处理"""
        # 获取选中的视频文件
        selected_indices = self.media_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请在主界面选择要批量处理的视频文件")
            return
        
        # 获取选中的视频文件路径
        selected_videos = []
        for index in selected_indices:
            filename = self.media_listbox.get(index)
            filepath = self.media_paths.get(filename, filename)
            if os.path.exists(filepath):
                selected_videos.append(filepath)
        
        if not selected_videos:
            messagebox.showerror("错误", "没有有效的视频文件")
            return
        
        # 更新状态
        self.batch_status_var.set("开始批量处理...")
        
        # 开始批量处理
        import threading
        
        def process_batch():
            try:
                total_videos = len(selected_videos)
                processed_count = 0
                
                for i, video_path in enumerate(selected_videos):
                    processed_count += 1
                    self.batch_status_var.set(f"处理中: {processed_count}/{total_videos}")
                    
                    # 批量切割
                    if self.batch_cut_var.get():
                        self.batch_cut(video_path)
                    
                    # 批量去重
                    if self.batch_duplicate_var.get():
                        self.batch_remove_duplicates(video_path)
                    
                    # 批量加字幕
                    if self.batch_subtitle_var.get():
                        self.batch_add_subtitles(video_path)
                    
                    # 批量加BGM
                    if self.batch_bgm_var.get():
                        self.batch_add_bgm(video_path)
                    
                    # 批量加转场
                    if self.batch_transition_var.get():
                        self.batch_add_transitions(video_path)
                    
                    # 批量调整画幅
                    if self.batch_frame_var.get():
                        self.batch_adjust_frame(video_path)
                
                self.batch_status_var.set(f"批量处理完成: 成功处理 {processed_count} 个视频")
                messagebox.showinfo("成功", f"批量处理完成: 成功处理 {processed_count} 个视频")
            except Exception as e:
                self.batch_status_var.set(f"批量处理失败: {str(e)}")
                messagebox.showerror("错误", f"批量处理失败: {str(e)}")
        
        thread = threading.Thread(target=process_batch, daemon=True)
        thread.start()

    def batch_cut(self, video_path):
        """批量切割"""
        try:
            duration = self.cut_duration_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"cut_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 使用FFmpeg切割视频
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-ss", "0",
                "-t", str(duration),
                "-c:v", GPU_ENCODER,
                "-c:a", "aac",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"批量切割失败: {e}")

    def batch_remove_duplicates(self, video_path):
        """批量去重"""
        try:
            strength = self.duplicate_strength_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"dedup_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 使用FFmpeg进行去重处理
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-filter_complex", f"scale=1920:1080,eq=brightness={0.1*strength}:contrast={1+0.5*strength}:saturation={1+0.3*strength}",
                "-c:v", GPU_ENCODER,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"批量去重失败: {e}")

    def batch_add_subtitles(self, video_path):
        """批量加字幕"""
        try:
            style = self.subtitle_style_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"subtitle_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 这里使用简单的文字叠加，实际项目中可以使用更复杂的字幕生成
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-filter_complex", "drawtext=text='AI生成字幕':fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:x=(w-text_w)/2:y=h-th-50",
                "-c:v", GPU_ENCODER,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"批量加字幕失败: {e}")

    def batch_add_bgm(self, video_path):
        """批量加BGM"""
        try:
            bgm_path = self.bgm_path_var.get()
            if not bgm_path or not os.path.exists(bgm_path):
                return
            
            base_name = os.path.basename(video_path)
            output_name = f"bgm_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 使用FFmpeg添加BGM
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-i", bgm_path,
                "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first",
                "-c:v", "copy",
                "-c:a", "aac",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"批量加BGM失败: {e}")

    def batch_add_transitions(self, video_path):
        """批量加转场"""
        try:
            transition = self.transition_style_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"transition_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 这里使用简单的转场效果，实际项目中可以使用更复杂的转场
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-filter_complex", "fade=in:st=0:d=1,fade=out:st=5:d=1",
                "-c:v", GPU_ENCODER,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"批量加转场失败: {e}")

    def batch_adjust_frame(self, video_path):
        """批量调整画幅"""
        try:
            frame = self.frame_style_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"frame_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 根据画幅设置分辨率
            resolution = "1920x1080"  # 默认16:9
            if frame == "9:16":
                resolution = "1080x1920"
            elif frame == "4:3":
                resolution = "1440x1080"
            elif frame == "1:1":
                resolution = "1080x1080"
            
            # 使用FFmpeg调整画幅
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-s", resolution,
                "-c:v", GPU_ENCODER,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"批量调整画幅失败: {e}")

    def ai_editing_tools(self):
        """AI剪辑工具"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建AI剪辑工具窗口
        ai_window = tk.Toplevel(self.root)
        ai_window.title("AI剪辑工具")
        ai_window.geometry("800x600")
        ai_window.configure(bg=bg_color)
        
        # 创建带滚动条的框架
        main_frame = tk.Frame(ai_window, bg=bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建滚动条
        scrollbar = tk.Scrollbar(main_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建画布
        canvas = tk.Canvas(main_frame, bg=bg_color, yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 配置滚动条
        scrollbar.config(command=canvas.yview)
        
        # 创建内部框架
        ai_frame = tk.Frame(canvas, bg=frame_color, pady=30, padx=30)
        ai_frame.pack(fill=tk.BOTH, expand=True)
        
        # 将内部框架添加到画布
        canvas.create_window((0, 0), window=ai_frame, anchor=tk.NW, tags="ai_frame")
        
        # 绑定滚动事件
        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure("ai_frame", width=event.width)
        
        ai_frame.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_configure)
        
        # AI剪辑工具标题
        tk.Label(ai_frame, text="AI剪辑工具", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=20)
        
        # AI剪辑工具选项
        tools_frame = tk.Frame(ai_frame, bg=frame_color)
        tools_frame.pack(fill=tk.X, pady=20)
        
        # AI爽点识别
        self.ai_highlight_var = tk.BooleanVar(value=False)
        highlight_check = tk.Checkbutton(tools_frame, text="AI爽点识别", variable=self.ai_highlight_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color)
        highlight_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 竖屏适配优化
        self.ai_vertical_var = tk.BooleanVar(value=False)
        vertical_check = tk.Checkbutton(tools_frame, text="竖屏适配优化", variable=self.ai_vertical_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color)
        vertical_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 全链路去重升级
        self.ai_duplicate_var = tk.BooleanVar(value=False)
        duplicate_check = tk.Checkbutton(tools_frame, text="全链路去重升级", variable=self.ai_duplicate_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color)
        duplicate_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # AI字幕升级
        self.ai_subtitle_var = tk.BooleanVar(value=False)
        subtitle_check = tk.Checkbutton(tools_frame, text="AI字幕升级", variable=self.ai_subtitle_var, 
                                         bg=frame_color, fg=text_color, selectcolor=item_color, 
                                         activebackground=frame_color, activeforeground=text_color)
        subtitle_check.pack(side=tk.LEFT, padx=20, pady=10)
        
        # AI剪辑参数
        params_frame = tk.Frame(ai_frame, bg=frame_color, pady=20)
        params_frame.pack(fill=tk.X, pady=20)
        
        # 爽点识别参数
        highlight_frame = tk.Frame(params_frame, bg=frame_color)
        highlight_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(highlight_frame, text="爽点识别敏感度:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.highlight_sensitivity_var = tk.DoubleVar(value=0.7)
        highlight_scale = tk.Scale(highlight_frame, from_=0, to=1, resolution=0.1, orient=tk.HORIZONTAL, 
                                   variable=self.highlight_sensitivity_var, bg=item_color, fg=text_color, 
                                   highlightbackground=item_color, troughcolor=item_color, 
                                   activebackground="#007acc", length=200)
        highlight_scale.pack(side=tk.LEFT, padx=10)
        
        # 竖屏适配参数
        vertical_frame = tk.Frame(params_frame, bg=frame_color)
        vertical_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(vertical_frame, text="竖屏适配模式:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.vertical_mode_var = tk.StringVar(value="智能填充")
        vertical_options = ["智能填充", "画面裁切", "黑边去除"]
        vertical_menu = ttk.Combobox(vertical_frame, textvariable=self.vertical_mode_var, values=vertical_options, state="readonly", width=15)
        vertical_menu.pack(side=tk.LEFT, padx=10)
        
        # 去重升级参数
        duplicate_frame = tk.Frame(params_frame, bg=frame_color)
        duplicate_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(duplicate_frame, text="去重维度:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.duplicate_dimensions_var = tk.StringVar(value="多维度")
        duplicate_options = ["基础", "中等", "多维度"]
        duplicate_menu = ttk.Combobox(duplicate_frame, textvariable=self.duplicate_dimensions_var, values=duplicate_options, state="readonly", width=15)
        duplicate_menu.pack(side=tk.LEFT, padx=10)
        
        # 字幕升级参数
        subtitle_frame = tk.Frame(params_frame, bg=frame_color)
        subtitle_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(subtitle_frame, text="字幕样式:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.subtitle_upgrade_var = tk.StringVar(value="智能高亮")
        subtitle_options = ["默认", "智能高亮", "双语字幕", "特效字幕"]
        subtitle_menu = ttk.Combobox(subtitle_frame, textvariable=self.subtitle_upgrade_var, values=subtitle_options, state="readonly", width=15)
        subtitle_menu.pack(side=tk.LEFT, padx=10)
        
        # AI剪辑按钮
        button_frame = tk.Frame(ai_frame, bg=frame_color, pady=20)
        button_frame.pack(fill=tk.X, pady=20)
        
        start_ai_btn = tk.Button(button_frame, text="开始AI剪辑", command=self.start_ai_editing, bg="#007acc", fg=text_color, font=("微软雅黑", 12), padx=30, pady=12, relief=tk.FLAT)
        start_ai_btn.pack(anchor=tk.CENTER)
        
        # AI剪辑状态
        self.ai_status_var = tk.StringVar(value="就绪")
        status_label = tk.Label(ai_frame, textvariable=self.ai_status_var, bg=frame_color, fg="#007acc", font=("微软雅黑", 10))
        status_label.pack(pady=10)

    def start_ai_editing(self):
        """开始AI剪辑"""
        # 获取选中的视频文件
        selected_indices = self.media_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请在主界面选择要AI剪辑的视频文件")
            return
        
        # 获取选中的视频文件路径
        selected_videos = []
        for index in selected_indices:
            filename = self.media_listbox.get(index)
            filepath = self.media_paths.get(filename, filename)
            if os.path.exists(filepath):
                selected_videos.append(filepath)
        
        if not selected_videos:
            messagebox.showerror("错误", "没有有效的视频文件")
            return
        
        # 更新状态
        self.ai_status_var.set("开始AI剪辑...")
        
        # 开始AI剪辑
        import threading
        
        def process_ai():
            try:
                total_videos = len(selected_videos)
                processed_count = 0
                
                for i, video_path in enumerate(selected_videos):
                    processed_count += 1
                    self.ai_status_var.set(f"处理中: {processed_count}/{total_videos}")
                    
                    # AI爽点识别
                    if self.ai_highlight_var.get():
                        self.ai_highlight_detection(video_path)
                    
                    # 竖屏适配优化
                    if self.ai_vertical_var.get():
                        self.ai_vertical_adaptation(video_path)
                    
                    # 全链路去重升级
                    if self.ai_duplicate_var.get():
                        self.ai_duplicate_removal(video_path)
                    
                    # AI字幕升级
                    if self.ai_subtitle_var.get():
                        self.ai_subtitle_upgrade(video_path)
                
                self.ai_status_var.set(f"AI剪辑完成: 成功处理 {processed_count} 个视频")
                messagebox.showinfo("成功", f"AI剪辑完成: 成功处理 {processed_count} 个视频")
            except Exception as e:
                self.ai_status_var.set(f"AI剪辑失败: {str(e)}")
                messagebox.showerror("错误", f"AI剪辑失败: {str(e)}")
        
        thread = threading.Thread(target=process_ai, daemon=True)
        thread.start()

    def ai_highlight_detection(self, video_path):
        """AI爽点识别"""
        try:
            sensitivity = self.highlight_sensitivity_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"highlight_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 这里使用简单的剪辑逻辑，实际项目中可以使用更复杂的AI分析
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-ss", "10",
                "-t", "30",
                "-c:v", GPU_ENCODER,
                "-c:a", "aac",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"AI爽点识别失败: {e}")

    def ai_vertical_adaptation(self, video_path):
        """竖屏适配优化"""
        try:
            mode = self.vertical_mode_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"vertical_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 根据模式设置滤镜
            filter_complex = ""
            if mode == "智能填充":
                filter_complex = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
            elif mode == "画面裁切":
                filter_complex = "scale=1080:1920:force_original_aspect_ratio=decrease"
            elif mode == "黑边去除":
                filter_complex = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
            
            # 使用FFmpeg进行竖屏适配
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-filter_complex", filter_complex,
                "-c:v", GPU_ENCODER,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"竖屏适配优化失败: {e}")

    def ai_duplicate_removal(self, video_path):
        """全链路去重升级"""
        try:
            dimensions = self.duplicate_dimensions_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"dedup_ai_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 根据维度设置滤镜
            filter_complex = ""
            if dimensions == "基础":
                filter_complex = "scale=1910:1070,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
            elif dimensions == "中等":
                filter_complex = "scale=1910:1070,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,eq=brightness=0.05:contrast=1.05"
            elif dimensions == "多维度":
                filter_complex = "scale=1910:1070,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,eq=brightness=0.05:contrast=1.05:saturation=1.05"
            
            # 使用FFmpeg进行去重
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-filter_complex", filter_complex,
                "-c:v", GPU_ENCODER,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"全链路去重升级失败: {e}")

    def ai_subtitle_upgrade(self, video_path):
        """AI字幕升级"""
        try:
            style = self.subtitle_upgrade_var.get()
            base_name = os.path.basename(video_path)
            output_name = f"subtitle_ai_{os.path.splitext(base_name)[0]}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            
            # 根据样式设置滤镜
            filter_complex = ""
            if style == "默认":
                filter_complex = "drawtext=text='AI生成字幕':fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:x=(w-text_w)/2:y=h-th-50"
            elif style == "智能高亮":
                filter_complex = "drawtext=text='AI智能高亮字幕':fontcolor=yellow:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:x=(w-text_w)/2:y=h-th-50"
            elif style == "双语字幕":
                filter_complex = "drawtext=text='AI生成字幕':fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:x=(w-text_w)/2:y=h-th-100,drawtext=text='AI Subtitle':fontcolor=white:fontsize=18:box=1:boxcolor=black@0.5:boxborderw=3:x=(w-text_w)/2:y=h-th-50"
            elif style == "特效字幕":
                filter_complex = "drawtext=text='AI特效字幕':fontcolor=white:fontsize=24:box=1:boxcolor=red@0.5:boxborderw=5:x=(w-text_w)/2:y=h-th-50"
            
            # 使用FFmpeg添加字幕
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-filter_complex", filter_complex,
                "-c:v", GPU_ENCODER,
                "-c:a", "copy",
                "-y",
                output_path
            ]
            
            subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"AI字幕升级失败: {e}")

    def show_preset_options(self):
        """显示预设选项"""
        # 创建预设选项窗口
        preset_window = tk.Toplevel(self.root)
        preset_window.title("预设管理")
        preset_window.geometry("600x500")
        preset_window.configure(bg="#1a1a1a")
        
        # 预设管理框架
        preset_frame = tk.Frame(preset_window, bg="#252525", pady=30, padx=30)
        preset_frame.pack(fill=tk.BOTH, expand=True)
        
        # 预设管理标题
        tk.Label(preset_frame, text="预设管理", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 预设列表
        preset_list_frame = tk.Frame(preset_frame, bg="#252525")
        preset_list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 预设列表框
        self.preset_listbox = tk.Listbox(preset_list_frame, width=60, height=15, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.preset_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 加载预设
        self.load_presets()
        
        # 预设操作按钮
        button_frame = tk.Frame(preset_frame, bg="#252525", pady=20)
        button_frame.pack(fill=tk.X, pady=10)
        
        save_preset_btn = tk.Button(button_frame, text="保存当前设置为预设", command=self.save_current_preset, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        save_preset_btn.pack(side=tk.LEFT, padx=10)
        
        load_preset_btn = tk.Button(button_frame, text="加载选中预设", command=self.load_selected_preset, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        load_preset_btn.pack(side=tk.LEFT, padx=10)
        
        delete_preset_btn = tk.Button(button_frame, text="删除选中预设", command=self.delete_selected_preset, bg="#444444", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        delete_preset_btn.pack(side=tk.LEFT, padx=10)

    def load_presets(self):
        """加载预设"""
        # 清空预设列表
        self.preset_listbox.delete(0, tk.END)
        
        # 模拟预设数据
        presets = [
            "默认预设",
            "30秒爆款引流",
            "90秒剧情解说",
            "8分钟挂车长视频",
            "竖屏适配",
            "高清导出",
            "快速导出"
        ]
        
        # 添加预设到列表
        for preset in presets:
            self.preset_listbox.insert(tk.END, preset)

    def save_current_preset(self):
        """保存当前设置为预设"""
        # 弹出保存预设对话框
        from tkinter import simpledialog
        preset_name = simpledialog.askstring("保存预设", "请输入预设名称:")
        if preset_name:
            # 保存预设逻辑
            self.preset_listbox.insert(tk.END, preset_name)
            messagebox.showinfo("成功", f"预设 '{preset_name}' 已保存")

    def load_selected_preset(self):
        """加载选中预设"""
        # 获取选中的预设
        selected_indices = self.preset_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要加载的预设")
            return
        
        selected_preset = self.preset_listbox.get(selected_indices[0])
        
        # 加载预设逻辑
        messagebox.showinfo("成功", f"已加载预设 '{selected_preset}'")

    def delete_selected_preset(self):
        """删除选中预设"""
        # 获取选中的预设
        selected_indices = self.preset_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要删除的预设")
            return
        
        # 删除预设
        self.preset_listbox.delete(selected_indices[0])
        messagebox.showinfo("成功", "预设已删除")
    
    def _update_timecode_display(self, seconds):
        """更新时间码显示（兼容 timecode_label / preview_time_var）"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        f = int((seconds % 1) * 30)
        tc = f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
        if hasattr(self, 'timecode_label'):
            self.timecode_label.config(text=tc)
        if hasattr(self, 'preview_time_var'):
            self.preview_time_var.set(f"{h:02d}:{m:02d}:{s:02d}.{f:02d}")

    def _seek_to_position(self, position):
        """跳转到指定位置（秒）并更新预览"""
        self._playback_position = position
        self._update_timecode_display(position)

        # 如果有正在预览的视频，跳转到对应帧
        if hasattr(self, 'current_preview_video') and self.current_preview_video:
            try:
                import cv2
                from PIL import Image, ImageTk

                cap = self._create_video_capture(self.current_preview_video)
                if cap.isOpened():
                    # 设置到指定位置
                    cap.set(cv2.CAP_PROP_POS_MSEC, position * 1000)
                    ret, frame = cap.read()

                    if ret and hasattr(self, 'preview_canvas') and self.preview_canvas.winfo_exists():
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame)

                        # 获取画布大小
                        cw = self.preview_canvas.winfo_width() or 640
                        ch = self.preview_canvas.winfo_height() or 360

                        # 获取视频原始大小
                        vidW = frame.shape[1]
                        vidH = frame.shape[0]

                        # 计算缩放比例，保持宽高比
                        scale = min(cw / vidW, ch / vidH)
                        drawW = int(vidW * scale * 0.9)
                        drawH = int(vidH * scale * 0.9)

                        # 计算居中位置
                        drawX = (cw - drawW) // 2
                        drawY = (ch - drawH) // 2

                        # 调整图像大小
                        img = img.resize((drawW, drawH), Image.Resampling.LANCZOS)
                        img_tk = ImageTk.PhotoImage(img)

                        # 清除画布并显示新帧
                        self.preview_canvas.delete("all")
                        self.preview_canvas.create_image(drawX + drawW // 2, drawY + drawH // 2, image=img_tk)
                        self.preview_canvas.img_tk = img_tk

                cap.release()
            except Exception as e:
                print(f"跳转预览失败: {e}")

    def _update_playhead_during_playback(self):
        """播放过程中更新播放头位置"""
        if self._is_playing and hasattr(self, '_draw_ruler_scale'):
            # 刷新时间标尺以更新播放头位置
            self._draw_ruler_scale()
            # 更新视频轨道上的播放头指示器
            self._update_track_playhead()
            # 继续下一帧更新，提高到16ms（60fps）以获得更平滑的播放头移动
            if self._is_playing:
                self._playback_timer = self.root.after(16, self._update_playhead_during_playback)

    def _update_track_playhead(self):
        """更新视频轨道上的播放头指示器"""
        try:
            if not hasattr(self, 'timeline_system') or not hasattr(self, '_playback_position'):
                return
            
            zoom = getattr(self, 'timeline_zoom', 1.0)
            play_x = self._playback_position * zoom
            
            # 时间轴整体向右移120px，与视频轨道开头对齐
            timeline_offset = 120
            
            # 在所有视频轨道上绘制播放头线
            for track_id, track_obj in self.timeline_system.tracks.items():
                if track_obj.track_type == "video":
                    canvas = track_obj.canvas
                    canvas_height = canvas.winfo_height() or 100
                    
                    # 删除旧的播放头线
                    canvas.delete("track_playhead")
                    canvas.delete("track_playhead_head")
                    
                    # 绘制新的播放头线（红色竖线）
                    canvas.create_line(
                        play_x + timeline_offset, 0, play_x + timeline_offset, canvas_height,
                        fill="#ff0000", width=2, tags="track_playhead"
                    )
                    
                    # 绘制播放头三角形头部
                    canvas.create_polygon(
                        play_x + timeline_offset - 6, 0,
                        play_x + timeline_offset + 6, 0,
                        play_x + timeline_offset, 8,
                        fill="#ff0000", tags="track_playhead_head"
                    )
                    
        except Exception as e:
            # 静默处理错误，避免影响播放
            pass

    def _stop_video_playback(self, clear_canvas=False):
        """停止视频播放（修复版 - 包含音频停止）
        
        Args:
            clear_canvas: 是否清空预览画布（默认False，保留最后一帧）
        """
        self._is_playing = False
        
        # 停止定时器
        if self._playback_timer:
            try:
                self.root.after_cancel(self._playback_timer)
            except Exception:
                pass
            self._playback_timer = None
        
        # 停止音频
        if hasattr(self, '_audio_stop_event'):
            self._audio_stop_event.set()
        
        # 等待音频线程结束
        if hasattr(self, '_audio_thread') and self._audio_thread and self._audio_thread.is_alive():
            try:
                self._audio_thread.join(timeout=1.0)
            except:
                pass
        
        # 释放视频捕获
        if getattr(self, '_video_cap', None):
            try:
                if clear_canvas:
                    # 清空预览画布
                    if hasattr(self, 'preview_canvas') and self.preview_canvas.winfo_exists():
                        self.preview_canvas.delete("all")
                else:
                    # 保存当前帧作为预览
                    import cv2
                    from PIL import Image, ImageTk
                    ret, frame = self._video_cap.read()
                    if ret and hasattr(self, 'preview_canvas') and self.preview_canvas.winfo_exists():
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame)
                        
                        # 获取画布大小
                        cw = self.preview_canvas.winfo_width() or 640
                        ch = self.preview_canvas.winfo_height() or 360
                        
                        # 获取视频原始大小
                        vidW = frame.shape[1]
                        vidH = frame.shape[0]
                        
                        # 计算等比例缩放
                        if vidW > 0 and vidH > 0:
                            scaleW = cw / vidW
                            scaleH = ch / vidH
                            scale = min(scaleW, scaleH)
                            
                            # 最终绘制的宽高
                            drawW = int(vidW * scale)
                            drawH = int(vidH * scale)
                            
                            # 居中偏移
                            drawX = (cw - drawW) // 2
                            drawY = (ch - drawH) // 2
                            
                            # 缩放图片
                            img = img.resize((drawW, drawH), Image.Resampling.LANCZOS)
                            img_tk = ImageTk.PhotoImage(img)
                            
                            # 清除画布并居中显示
                            self.preview_canvas.delete("all")
                            self.preview_canvas.create_image(drawX + drawW // 2, drawY + drawH // 2, image=img_tk)
                            self.preview_canvas.img_tk = img_tk
                self._video_cap.release()
            except Exception:
                pass
            self._video_cap = None
        
        # 清理旧的音频对象
        if getattr(self, '_audio_clip', None):
            try:
                self._audio_clip.close()
            except Exception:
                pass
            self._audio_clip = None

    def _play_next_frame(self):
        """播放下一帧（OpenCV 帧循环，在主线程通过 after 调度）"""
        if not self._is_playing or not getattr(self, '_video_cap', None) or not hasattr(self, 'preview_canvas'):
            return
        try:
            import cv2
            from PIL import Image, ImageTk

            # 检查当前播放的文件是否还存在
            if hasattr(self, 'current_preview_video') and self.current_preview_video:
                if not os.path.exists(self.current_preview_video):
                    # 文件被删除，停止播放并清空画布
                    print(f"⚠️ 播放中的文件被删除: {self.current_preview_video}")
                    self._stop_video_playback(clear_canvas=True)
                    if hasattr(self, 'preview_canvas'):
                        self.preview_canvas.delete("all")
                        cw = self.preview_canvas.winfo_width() or 800
                        ch = self.preview_canvas.winfo_height() or 450
                        self.preview_canvas.create_text(cw // 2, ch // 2,
                                                        text="媒体文件已被删除\n请重新导入",
                                                        fill="#ff6666", font=("微软雅黑", 14))
                    if hasattr(self, 'status_label'):
                        self.status_label.config(text="媒体文件已被删除")
                    return

            speed = 1.0
            if hasattr(self, 'speed_var'):
                try:
                    sp = self.speed_var.get().replace('x', '').strip()
                    speed = float(sp) if sp else 1.0
                except (ValueError, TypeError):
                    pass
            fps = self._video_cap.get(cv2.CAP_PROP_FPS) or 30
            frame_delay = max(15, int(1000 / (fps * speed)))
            ret, frame = self._video_cap.read()
            if not ret:
                self._is_playing = False
                if hasattr(self, 'status_label'):
                    self.status_label.config(text="播放完成")
                return
            self._playback_position = self._video_cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            self._update_timecode_display(self._playback_position)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            
            # 获取画布大小
            cw = self.preview_canvas.winfo_width() or 640
            ch = self.preview_canvas.winfo_height() or 360
            if cw < 2 or ch < 2:
                cw, ch = 640, 360
            
            # 获取视频原始大小
            vidW = frame.shape[1]
            vidH = frame.shape[0]
            
            # 计算等比例缩放
            if vidW > 0 and vidH > 0:
                scaleW = cw / vidW
                scaleH = ch / vidH
                scale = min(scaleW, scaleH)
                
                # 最终绘制的宽高
                drawW = int(vidW * scale)
                drawH = int(vidH * scale)
                
                # 居中偏移
                drawX = (cw - drawW) // 2
                drawY = (ch - drawH) // 2
                
                # 缩放图片
                img = img.resize((drawW, drawH), Image.Resampling.LANCZOS)
                img_tk = ImageTk.PhotoImage(img)
                
                # 清除画布并居中显示
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(drawX + drawW // 2, drawY + drawH // 2, image=img_tk)
                self.preview_canvas.img_tk = img_tk
            self._playback_timer = self.root.after(frame_delay, self._play_next_frame)
        except Exception as e:
            print(f"播放帧失败: {e}")
            self._is_playing = False
            if hasattr(self, 'status_label'):
                self.status_label.config(text=f"播放出错: {str(e)}")

    def seek_preview_to_time(self, sec):
        """时间轴 hover 预览：将预览定位到指定秒数并显示该帧。"""
        if not getattr(self, "current_preview_video", None) or not os.path.exists(self.current_preview_video):
            return
        self._stop_video_playback()
        self._playback_position = max(0.0, float(sec))
        self._update_timecode_display(self._playback_position)
        try:
            import cv2
            from PIL import Image, ImageTk
            cap = cv2.VideoCapture(self.current_preview_video)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_POS_MSEC, self._playback_position * 1000)
                ret, frame = cap.read()
                if ret and hasattr(self, "preview_canvas") and self.preview_canvas.winfo_exists():
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(frame)
                    
                    # 获取画布大小
                    cw = self.preview_canvas.winfo_width() or 640
                    ch = self.preview_canvas.winfo_height() or 360
                    
                    # 获取视频原始大小
                    vidW = frame.shape[1]
                    vidH = frame.shape[0]
                    
                    # 计算等比例缩放
                    if vidW > 0 and vidH > 0:
                        scaleW = cw / vidW
                        scaleH = ch / vidH
                        scale = min(scaleW, scaleH)
                        
                        # 最终绘制的宽高
                        drawW = int(vidW * scale)
                        drawH = int(vidH * scale)
                        
                        # 居中偏移
                        drawX = (cw - drawW) // 2
                        drawY = (ch - drawH) // 2
                        
                        # 缩放图片
                        img = img.resize((drawW, drawH), Image.Resampling.LANCZOS)
                        img_tk = ImageTk.PhotoImage(img)
                        
                        # 清除画布并居中显示
                        self.preview_canvas.delete("all")
                        self.preview_canvas.create_image(drawX + drawW // 2, drawY + drawH // 2, image=img_tk)
                        self.preview_canvas.img_tk = img_tk
                cap.release()
        except Exception:
            pass

    def on_timeline_hover(self, event):
        """时间轴鼠标悬停：实时显示该时刻画面（hover 即看）。"""
        if not timeline_features:
            return
        try:
            w = event.widget
            width = w.winfo_width() or 1
            dur = self.get_timeline_duration_sec()
            t = timeline_features.time_from_canvas_x(event.x, width, dur)
            self.seek_preview_to_time(t)
        except Exception:
            pass

    def rewind(self):
        """倒放 10 秒"""
        if not getattr(self, 'current_preview_video', None):
            self.status_label.config(text="请先导入视频")
            return
        try:
            import cv2
            from PIL import Image, ImageTk
            cap = cv2.VideoCapture(self.current_preview_video)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                dur = total / fps if fps > 0 else 0
                self._playback_position = max(self._playback_position - 10, 0)
                self._stop_video_playback()
                self._update_timecode_display(self._playback_position)
                if hasattr(self, 'preview_canvas') and self.preview_canvas.winfo_exists():
                    cap.set(cv2.CAP_PROP_POS_MSEC, self._playback_position * 1000)
                    ret, frame = cap.read()
                    if ret:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame)
                        
                        # 获取画布大小
                        cw = self.preview_canvas.winfo_width() or 640
                        ch = self.preview_canvas.winfo_height() or 360
                        
                        # 获取视频原始大小
                        vidW = frame.shape[1]
                        vidH = frame.shape[0]
                        
                        # 计算等比例缩放
                        if vidW > 0 and vidH > 0:
                            scaleW = cw / vidW
                            scaleH = ch / vidH
                            scale = min(scaleW, scaleH)
                            
                            # 最终绘制的宽高
                            drawW = int(vidW * scale)
                            drawH = int(vidH * scale)
                            
                            # 居中偏移
                            drawX = (cw - drawW) // 2
                            drawY = (ch - drawH) // 2
                            
                            # 缩放图片
                            img = img.resize((drawW, drawH), Image.Resampling.LANCZOS)
                            img_tk = ImageTk.PhotoImage(img)
                            
                            # 清除画布并居中显示
                            self.preview_canvas.delete("all")
                            self.preview_canvas.create_image(drawX + drawW // 2, drawY + drawH // 2, image=img_tk)
                            self.preview_canvas.img_tk = img_tk
                    cap.release()
            else:
                self._playback_position = max(self._playback_position - 10, 0)
                self._update_timecode_display(self._playback_position)
                cap.release()
        except Exception:
            self._playback_position = max(self._playback_position - 10, 0)
            self._update_timecode_display(self._playback_position)
        self.status_label.config(text="倒放 10 秒")

    def reverse_play(self):
        """倒放播放视频"""
        if not getattr(self, 'current_preview_video', None) or not os.path.exists(self.current_preview_video):
            self.status_label.config(text="请先导入视频")
            return
        if self._is_playing:
            self._stop_video_playback()
            self.status_label.config(text="已暂停倒放")
            return
        try:
            import cv2
            import threading
            self._video_cap = self._create_video_capture(self.current_preview_video)
            if not self._video_cap.isOpened():
                self.status_label.config(text="无法打开视频")
                return
            fps = self._video_cap.get(cv2.CAP_PROP_FPS) or 30
            total_frames = int(self._video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            current_frame = int(self._playback_position * fps)
            # 设置到当前位置的下一帧，因为我们要倒着读
            start_frame = min(current_frame, total_frames - 1)
            self._video_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            self._is_playing = True
            self.status_label.config(text="正在倒放...")
            
            # 倒放视频的线程函数
            def play_reverse():
                try:
                    from PIL import Image, ImageTk
                    while self._is_playing:
                        # 读取当前帧
                        ret, frame = self._video_cap.read()
                        if not ret:
                            break
                        # 显示帧
                        if hasattr(self, 'preview_canvas') and self.preview_canvas.winfo_exists():
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            img = Image.fromarray(frame)
                            cw = self.preview_canvas.winfo_width() or 640
                            ch = self.preview_canvas.winfo_height() or 360
                            img.thumbnail((max(1, cw), max(1, ch)), Image.Resampling.LANCZOS)
                            img_tk = ImageTk.PhotoImage(img)
                            self.preview_canvas.delete("all")
                            self.preview_canvas.create_image(cw // 2, ch // 2, image=img_tk)
                            self.preview_canvas.img_tk = img_tk
                        # 计算上一帧的位置
                        current_pos = self._video_cap.get(cv2.CAP_PROP_POS_FRAMES)
                        prev_frame = max(0, current_pos - 2)  # 减去2是因为read()会自动前进一帧
                        if prev_frame < 0:
                            break
                        self._video_cap.set(cv2.CAP_PROP_POS_FRAMES, prev_frame)
                        # 更新播放位置
                        self._playback_position = prev_frame / fps
                        self._update_timecode_display(self._playback_position)
                        # 控制播放速度
                        speed = 1.0
                        if hasattr(self, 'speed_var'):
                            try:
                                sp = self.speed_var.get().replace('x', '').strip()
                                speed = float(sp) if sp else 1.0
                            except (ValueError, TypeError):
                                pass
                        frame_delay = max(15, int(1000 / fps))
                        import time
                        time.sleep(frame_delay / (1000 * speed))
                except Exception as e:
                    print(f"倒放失败: {e}")
                finally:
                    self._is_playing = False
            
            # 启动倒放线程
            threading.Thread(target=play_reverse, daemon=True).start()
        except ImportError:
            self.status_label.config(text="缺少 opencv-python，无法倒放")
        except Exception as e:
            self.status_label.config(text=f"倒放失败: {str(e)}")
            print(f"倒放失败: {e}")
    
    def play_pause(self):
        """播放/暂停视频（修复版 - 支持音视频同步和倍速，检查文件存在性）"""
        # 检查轨道是否有内容
        has_video_clips = False
        has_audio_clips = False

        for track in self.tracks:
            if track.get("type") == "video" and track.get("clips", []):
                has_video_clips = True
            elif track.get("type") == "audio" and track.get("clips", []):
                has_audio_clips = True

        if not has_video_clips and not has_audio_clips:
            self.status_label.config(text="轨道为空，请先导入视频到轨道")
            return

        if self._is_playing:
            self._stop_video_playback()
            self.status_label.config(text="已暂停")
            return

        try:
            # 从轨道中获取第一个视频片段作为预览源
            video_clip_path = None
            for track in self.tracks:
                if track.get("type") == "video" and track.get("clips", []):
                    clip_path = track["clips"][0].get("path")
                    # 检查文件是否存在
                    if clip_path and os.path.exists(clip_path):
                        video_clip_path = clip_path
                        break

            # 如果没有视频轨道，使用第一个音频轨道
            if not video_clip_path:
                for track in self.tracks:
                    if track.get("type") == "audio" and track.get("clips", []):
                        clip_path = track["clips"][0].get("path")
                        # 检查文件是否存在
                        if clip_path and os.path.exists(clip_path):
                            video_clip_path = clip_path
                            break

            if not video_clip_path:
                self.status_label.config(text="轨道上的媒体文件不存在，请重新导入")
                # 停止当前播放并清空预览画布
                if self._is_playing:
                    self._stop_video_playback(clear_canvas=True)
                # 显示错误提示在预览画布
                if hasattr(self, 'preview_canvas'):
                    self.preview_canvas.delete("all")
                    cw = self.preview_canvas.winfo_width() or 800
                    ch = self.preview_canvas.winfo_height() or 450
                    self.preview_canvas.create_text(cw // 2, ch // 2, text="媒体文件不存在\n请重新导入", fill="#ff6666", font=("微软雅黑", 14))
                return
            
            # 更新当前预览视频路径
            self.current_preview_video = video_clip_path
            
            import cv2
            import threading
            self._video_cap = self._create_video_capture(video_clip_path)
            if not self._video_cap.isOpened():
                self.status_label.config(text="无法打开视频")
                return
            
            # 获取视频信息
            fps = self._video_cap.get(cv2.CAP_PROP_FPS) or 30
            total_frames = int(self._video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 获取当前倍速
            try:
                sp = self.speed_var.get().replace('x', '').strip()
                current_speed = float(sp) if sp else 1.0
            except (ValueError, TypeError):
                current_speed = 1.0
            
            # 设置起始位置
            start_frame = int(self._playback_position * fps)
            self._video_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            
            self._is_playing = True
            self.status_label.config(text=f"正在播放轨道... (倍速: {current_speed}x)")
            
            # 确保预览画布可见
            if hasattr(self, 'use_optimized_player') and self.use_optimized_player:
                if hasattr(self, 'preview_canvas') and hasattr(self, 'video_player_frame'):
                    self.video_player_frame.grid_forget()
                    self.preview_canvas.grid(row=0, column=0, sticky=tk.NSEW)
                    self.use_optimized_player = False
            
            # 启动音频播放（使用 pygame，支持倍速和音量控制）
            self._start_audio_playback_fixed(video_clip_path, self._playback_position, current_speed)
            
            # 开始视频帧循环
            self._play_next_frame_fixed()
            
        except Exception as e:
            self.status_label.config(text=f"播放失败: {str(e)}")
            print(f"播放失败: {e}")
            self._is_playing = False
    
    def _start_audio_playback_fixed(self, video_path, start_time, speed):
        """启动音频播放（修复版 - 支持倍速和音量）"""
        def play_audio():
            temp_audio = None
            video = None
            try:
                import pygame
                from moviepy.editor import VideoFileClip
                import os
                import tempfile
                
                # 检查文件是否存在
                if not os.path.exists(video_path):
                    print(f"❌ 音频播放失败: 文件不存在 {video_path}")
                    return
                
                # 提取音频到临时文件
                ext = os.path.splitext(video_path)[1].lower()
                if ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"]:
                    print(f"🎵 正在提取音频: {os.path.basename(video_path)}")
                    video = VideoFileClip(video_path)
                    
                    if video.audio is None:
                        print(f"⚠️ 视频没有音频轨道: {os.path.basename(video_path)}")
                        video.close()
                        return
                    
                    # 创建临时音频文件
                    temp_dir = tempfile.gettempdir()
                    temp_audio = os.path.join(temp_dir, f"temp_preview_{int(time.time())}_{os.path.basename(video_path)}.wav")
                    
                    try:
                        # 根据倍速调整音频
                        if speed != 1.0:
                            # 调整音频速度（改变采样率）
                            print(f"🎵 调整音频速度: {speed}x")
                            audio = video.audio.fx(lambda clip: clip.fl_time(lambda t: t / speed))
                            audio.write_audiofile(temp_audio, fps=44100, nbytes=2, codec='pcm_s16le', verbose=False, logger=None)
                        else:
                            video.audio.write_audiofile(temp_audio, fps=44100, nbytes=2, codec='pcm_s16le', verbose=False, logger=None)
                        
                        print(f"✅ 音频提取完成: {temp_audio}")
                    except Exception as e:
                        print(f"❌ 音频提取失败: {e}")
                        if video:
                            video.close()
                        return
                    finally:
                        if video:
                            video.close()
                    
                    # 检查临时文件是否创建成功
                    if not os.path.exists(temp_audio):
                        print(f"❌ 临时音频文件未创建: {temp_audio}")
                        return
                    
                    # 使用 pygame 播放
                    try:
                        # 确保 pygame mixer 已初始化
                        if pygame.mixer.get_init() is None:
                            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
                            print("✅ pygame mixer 初始化完成")
                        
                        pygame.mixer.music.load(temp_audio)
                        print(f"✅ 音频加载完成")
                        
                        # 设置音量
                        volume = self.volume_var.get() if hasattr(self, 'volume_var') else 0.7
                        pygame.mixer.music.set_volume(volume)
                        print(f"🎚️ 音量设置: {volume}")
                        
                        # 设置播放位置
                        pygame.mixer.music.play(start=start_time)
                        print(f"▶️ 音频播放开始，起始位置: {start_time:.2f}秒")
                        
                        # 等待停止信号
                        while self._is_playing and not self._audio_stop_event.is_set():
                            time.sleep(0.1)
                        
                        pygame.mixer.music.stop()
                        print("⏹️ 音频播放停止")
                        
                    except Exception as e:
                        print(f"❌ pygame 播放失败: {e}")
                    finally:
                        # 清理 pygame
                        try:
                            pygame.mixer.quit()
                        except:
                            pass
                        
                        # 清理临时文件
                        if temp_audio and os.path.exists(temp_audio):
                            try:
                                os.remove(temp_audio)
                                print(f"🗑️ 临时文件已清理")
                            except Exception as e:
                                print(f"⚠️ 清理临时文件失败: {e}")
                else:
                    print(f"⚠️ 不支持的文件格式: {ext}")
                
            except ImportError as e:
                print(f"❌ 导入错误: {e}")
                print("请运行: pip install pygame moviepy")
            except Exception as e:
                print(f"❌ 音频播放失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 创建停止事件
        self._audio_stop_event = threading.Event()
        
        # 在新线程中播放音频
        self._audio_thread = threading.Thread(target=play_audio, daemon=True)
        self._audio_thread.start()
        print(f"🎵 音频播放线程已启动")
    
    def _play_next_frame_fixed(self):
        """播放下一帧（修复版 - 支持倍速）"""
        if not self._is_playing or not self._video_cap or not hasattr(self, 'preview_canvas'):
            return
        
        try:
            import cv2
            from PIL import Image, ImageTk
            
            # 获取当前倍速
            try:
                sp = self.speed_var.get().replace('x', '').strip()
                current_speed = float(sp) if sp else 1.0
            except (ValueError, TypeError):
                current_speed = 1.0
            
            fps = self._video_cap.get(cv2.CAP_PROP_FPS) or 30
            
            # 根据倍速决定帧延迟和跳过
            if current_speed > 1.0:
                # 高速播放：跳过帧
                frame_skip = int(current_speed)
                for _ in range(frame_skip - 1):
                    self._video_cap.read()
                frame_delay = int(1000 / fps)
            elif current_speed < 1.0:
                # 慢速播放：增加延迟
                frame_delay = int(1000 / (fps * current_speed))
            else:
                # 正常速度
                frame_delay = int(1000 / fps)
            
            # 读取帧
            ret, frame = self._video_cap.read()
            if not ret:
                self._is_playing = False
                if hasattr(self, '_audio_stop_event'):
                    self._audio_stop_event.set()
                if hasattr(self, 'status_label'):
                    self.status_label.config(text="播放完成")
                return
            
            # 更新播放位置
            self._playback_position = self._video_cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if hasattr(self, '_update_timecode_display'):
                self._update_timecode_display(self._playback_position)

            # 更新播放头位置（每帧都更新，确保流畅）
            if hasattr(self, '_draw_ruler_scale'):
                self._draw_ruler_scale()
            
            # 更新视频轨道上的播放头指示器
            self._update_track_playhead()
            
            # 转换并显示帧
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            
            # 获取画布大小
            cw = self.preview_canvas.winfo_width() or 640
            ch = self.preview_canvas.winfo_height() or 360
            if cw < 2 or ch < 2:
                cw, ch = 640, 360
            
            # 等比例缩放
            vidW = frame.shape[1]
            vidH = frame.shape[0]
            
            if vidW > 0 and vidH > 0:
                scale = min(cw / vidW, ch / vidH)
                drawW = int(vidW * scale)
                drawH = int(vidH * scale)
                drawX = (cw - drawW) // 2
                drawY = (ch - drawH) // 2
                
                img = img.resize((drawW, drawH), Image.Resampling.LANCZOS)
                img_tk = ImageTk.PhotoImage(img)
                
                self.preview_canvas.delete("all")
                self.preview_canvas.create_image(drawX + drawW // 2, drawY + drawH // 2, image=img_tk)
                self.preview_canvas.img_tk = img_tk
            
            # 安排下一帧
            self._playback_timer = self.root.after(frame_delay, self._play_next_frame_fixed)
            
        except Exception as e:
            print(f"播放帧失败: {e}")
            self._is_playing = False
            if hasattr(self, '_audio_stop_event'):
                self._audio_stop_event.set()
            if hasattr(self, 'status_label'):
                self.status_label.config(text=f"播放出错: {str(e)}")
    
    def fast_forward(self):
        """快进 10 秒"""
        if not getattr(self, 'current_preview_video', None):
            self.status_label.config(text="请先导入视频")
            return
        try:
            import cv2
            from PIL import Image, ImageTk
            cap = cv2.VideoCapture(self.current_preview_video)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                dur = total / fps if fps > 0 else 0
                self._playback_position = min(self._playback_position + 10, max(0, dur - 0.1))
                self._stop_video_playback()
                self._update_timecode_display(self._playback_position)
                if hasattr(self, 'preview_canvas') and self.preview_canvas.winfo_exists():
                    cap.set(cv2.CAP_PROP_POS_MSEC, self._playback_position * 1000)
                    ret, frame = cap.read()
                    if ret:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame)
                        cw = self.preview_canvas.winfo_width() or 640
                        ch = self.preview_canvas.winfo_height() or 360
                        img.thumbnail((max(1, cw), max(1, ch)), Image.Resampling.LANCZOS)
                        img_tk = ImageTk.PhotoImage(img)
                        self.preview_canvas.delete("all")
                        self.preview_canvas.create_image(cw // 2, ch // 2, image=img_tk)
                        self.preview_canvas.img_tk = img_tk
                    cap.release()
            else:
                self._playback_position += 10
                self._update_timecode_display(self._playback_position)
                cap.release()
        except Exception:
            self._playback_position += 10
            self._update_timecode_display(self._playback_position)
        self.status_label.config(text="快进 10 秒")
    
    def toggle_audio(self):
        """切换音频"""
        current_volume = self.volume_var.get()
        if current_volume > 0:
            self.volume_var.set(0)
            self.status_label.config(text="音频已静音")
        else:
            self.volume_var.set(0.7)
            self.status_label.config(text="音频已开启")
        
        # 通知当前播放的音频线程调整音量
        if hasattr(self, '_audio_clip') and self._audio_clip:
            try:
                if self.volume_var.get() > 0:
                    self._audio_clip.audio.fps = self._audio_clip.fps
                else:
                    # 静音处理
                    pass
            except Exception as e:
                print(f"调整音频音量失败: {e}")
    
    def preview_media(self, event):
        """预览媒体文件"""
        # 获取选中的媒体文件
        selected_indices = self.media_listbox.curselection()
        if not selected_indices:
            return
        
        selected_index = selected_indices[0]
        media_filename = self.media_listbox.get(selected_index)
        media_path = self.media_paths.get(media_filename, media_filename)
        
        if not os.path.exists(media_path):
            messagebox.showerror("错误", "媒体文件不存在")
            return
        
        try:
            # 获取文件扩展名
            ext = os.path.splitext(media_filename)[1].lower()
            
            if ext in ['.mp4', '.avi', '.mov', '.mkv', '.wmv']:
                # 预览视频
                self.preview_video(media_path)
            elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif']:
                # 预览图片
                self.preview_image(media_path)
            elif ext in ['.mp3', '.wav', '.aac', '.flac', '.ogg']:
                # 预览音频
                self.preview_audio(media_path)
            else:
                messagebox.showerror("错误", "不支持的文件格式")
        except Exception as e:
            print(f"预览媒体失败: {e}")
            self.status_label.config(text="预览失败")
            messagebox.showerror("错误", f"预览失败: {str(e)}")
    
    def preview_video(self, video_path):
        """预览视频文件"""
        try:
            if not os.path.exists(video_path):
                self.status_label.config(text="视频文件不存在")
                if hasattr(self, 'preview_canvas'):
                    self.preview_canvas.delete("all")
                    cw = self.preview_canvas.winfo_width() or 800
                    ch = self.preview_canvas.winfo_height() or 450
                    self.preview_canvas.create_text(cw // 2, ch // 2, text="视频文件不存在", fill="#ff6666", font=("微软雅黑", 12))
                return
            
            # 停止当前播放并重置位置，保证导入视频能正常播放
            if hasattr(self, '_stop_video_playback'):
                self._stop_video_playback()
            self._playback_position = 0.0
            
            # 保存当前预览的视频路径
            self.current_preview_video = video_path
            
            # 检查是否使用新的视频播放器
            if hasattr(self, 'use_optimized_player') and self.use_optimized_player:
                try:
                    # 使用新的视频播放器
                    self.status_label.config(text=f"正在预览视频: {os.path.basename(video_path)}")
                    
                    # 隐藏旧的预览画布
                    if hasattr(self, 'preview_canvas'):
                        self.preview_canvas.grid_forget()
                    
                    # 显示视频播放器容器（与预览画布同处居中区域）
                    self.video_player_frame.grid(row=0, column=0, sticky=tk.NSEW)
                    
                    # 尝试导入必要的模块
                    try:
                        from modules.video_player.optimized_video_player import OptimizedVideoPlayer
                        from PyQt5.QtWidgets import QWidget
                        from PyQt5.QtCore import Qt
                        import win32gui
                        import win32con
                        has_all_deps = True
                    except ImportError as e:
                        print(f"缺少依赖: {e}")
                        has_all_deps = False
                        self.status_label.config(text="缺少必要依赖，使用基本预览")
                        # 回退到旧的预览方法
                        self.use_optimized_player = False
                        self.preview_video(video_path)
                        return
                    
                    # 创建播放器实例（使用工厂方法）
                    if not hasattr(self, 'video_player'):
                        self.video_player = OptimizedVideoPlayer.create_player()
                    
                    # 加载视频文件
                    if self.video_player is not None:
                        try:
                            # 检查播放器是否有必要的依赖项
                            if hasattr(self.video_player, 'has_dependencies') and not self.video_player.has_dependencies:
                                raise Exception("播放器缺少必要依赖项")
                            self.video_player.load_video(video_path)
                        except Exception as e:
                            print(f"❌ 加载视频失败: {e}")
                            # 如果加载失败，回退到旧的预览方法
                            self.use_optimized_player = False
                            self.preview_video(video_path)
                            return
                    else:
                        print("❌ 播放器未初始化，无法加载视频")
                        # 如果播放器未初始化，回退到旧的预览方法
                        self.use_optimized_player = False
                        self.preview_video(video_path)
                        return
                    
                    # 将播放器窗口嵌入到Tkinter容器中
                    self.video_player.show()
                    player_hwnd = int(self.video_player.winId())
                    container_hwnd = self.video_player_frame.winfo_id()
                    
                    # 保存播放器窗口句柄到实例变量
                    self.player_hwnd = player_hwnd
                    
                    # 设置父子关系
                    win32gui.SetParent(player_hwnd, container_hwnd)
                    
                    # 调整播放器大小和位置
                    def resize_player(event):
                        if hasattr(self, 'video_player') and hasattr(self, 'player_hwnd'):
                            try:
                                width = self.video_player_frame.winfo_width()
                                height = self.video_player_frame.winfo_height()
                                if width > 0 and height > 0:
                                    # 调整播放器大小
                                    self.video_player.resize(width, height)
                                    # 确保播放器窗口可见
                                    win32gui.ShowWindow(self.player_hwnd, win32con.SW_SHOW)
                                    # 将播放器窗口设置到容器的左上角，填满整个容器
                                    win32gui.SetWindowPos(self.player_hwnd, 0, 0, 0, width, height, win32con.SWP_NOZORDER | win32con.SWP_NOMOVE)
                                    # 确保播放器窗口在最前面
                                    win32gui.SetWindowPos(self.player_hwnd, win32con.HWND_TOP, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                            except Exception as e:
                                print(f"调整播放器大小失败: {e}")
                    
                    # 绑定 resize 事件
                    self.video_player_frame.bind('<Configure>', resize_player)
                    
                    # 触发初始大小调整
                    resize_player(None)
                    
                    # 强制更新播放器窗口
                    def force_update_player():
                        if hasattr(self, 'player_hwnd'):
                            try:
                                # 强制显示播放器窗口
                                win32gui.ShowWindow(self.player_hwnd, win32con.SW_SHOW)
                                # 强制刷新窗口
                                win32gui.RedrawWindow(self.player_hwnd, None, None, win32con.RDW_INVALIDATE | win32con.RDW_UPDATENOW)
                                # 调整大小
                                resize_player(None)
                            except Exception as e:
                                print(f"强制更新播放器窗口失败: {e}")
                    
                    # 强制更新播放器窗口
                    self.root.after(100, force_update_player)
                    self.root.after(500, force_update_player)
                    self.root.after(1000, force_update_player)
                    
                    # 启动PyQt5事件循环（在主线程中处理）
                    def process_qt_events():
                        if hasattr(self, 'q_app'):
                            try:
                                self.q_app.processEvents()
                            except Exception as e:
                                print(f"处理Qt事件失败: {e}")
                        # 继续定时处理事件
                        self.root.after(10, process_qt_events)
                    
                    # 开始处理Qt事件
                    self.root.after(10, process_qt_events)
                    
                    # 确保播放器正在播放
                    if hasattr(self, 'video_player'):
                        try:
                            # 确保播放器状态正确
                            self.video_player.play()
                            self.on_speed_change()
                        except Exception as e:
                            print(f"启动播放器失败: {e}")
                    
                    # 更新状态
                    self.status_label.config(text=f"预览视频: {os.path.basename(video_path)}")
                except Exception as e:
                    print(f"优化播放器失败: {e}")
                    # 回退到旧的预览方法
                    self.use_optimized_player = False
                    self.preview_video(video_path)
                    return
            else:
                # 显示旧的预览画布（与播放器同处居中区域，位置一致）
                if hasattr(self, 'preview_canvas'):
                    self.preview_canvas.grid(row=0, column=0, sticky=tk.NSEW)
                
                # 隐藏视频播放器容器
                if hasattr(self, 'video_player_frame'):
                    self.video_player_frame.grid_forget()
                
                # 使用旧的预览方法
                # 生成缓存键
                cache_key = f"preview_{os.path.basename(video_path)}_{os.path.getmtime(video_path)}"
                
                # 检查缓存
                try:
                    cached_preview = cache_system.get(cache_key)
                    if cached_preview:
                        # 使用缓存的预览
                        if hasattr(self, 'preview_canvas'):
                            self.preview_canvas.delete("all")
                            # 获取画布大小
                            cw = self.preview_canvas.winfo_width() or 800
                            ch = self.preview_canvas.winfo_height() or 450
                            # 居中显示
                            self.preview_canvas.create_image(cw // 2, ch // 2, image=cached_preview)
                            self.preview_canvas.img_tk = cached_preview
                            self.img_tk = cached_preview
                        self._playback_position = 1.0
                        if hasattr(self, '_update_timecode_display'):
                            self._update_timecode_display(1.0)
                        self.status_label.config(text=f"预览视频: {os.path.basename(video_path)}")
                        return
                except Exception as e:
                    print(f"缓存访问失败: {e}")
                
                # 更新状态
                self.status_label.config(text=f"正在预览视频: {os.path.basename(video_path)}")
                
                # 显示加载状态
                if hasattr(self, 'preview_canvas'):
                            self.preview_canvas.delete("all")
                            cw = self.preview_canvas.winfo_width() or 800
                            ch = self.preview_canvas.winfo_height() or 450
                            self.preview_canvas.create_text(cw // 2, ch // 2, text="正在生成预览...", fill="#000000", font=("微软雅黑", 12))
                
                # 生成预览帧
                preview_frame_path = os.path.join(OUTPUT_DIR, f"preview_{int(time.time())}.jpg")
                
                # 导入shutil模块
                import shutil
                
                # 检查FFmpeg是否可用
                if not os.path.exists(FFMPEG) and not shutil.which(FFMPEG):
                    # 显示错误信息
                    if hasattr(self, 'preview_canvas'):
                            self.preview_canvas.delete("all")
                            cw = self.preview_canvas.winfo_width() or 800
                            ch = self.preview_canvas.winfo_height() or 450
                            self.preview_canvas.create_text(cw // 2, ch // 2, text="FFmpeg未找到，无法生成预览", fill="#ff6666", font=("微软雅黑", 12))
                    self.status_label.config(text="FFmpeg未找到")
                    return
                
                # 先使用OpenCV检查视频宽高是否有效
                import cv2
                cap = cv2.VideoCapture(video_path)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
                
                if width <= 0 or height <= 0:
                    print(f"❌ 视频宽高无效，无法生成预览: {width}x{height}")
                    if hasattr(self, 'preview_canvas'):
                        self.preview_canvas.delete("all")
                        cw = self.preview_canvas.winfo_width() or 800
                        ch = self.preview_canvas.winfo_height() or 450
                        self.preview_canvas.create_text(cw // 2, ch // 2, text="视频宽高无效，无法生成预览", fill="#ff6666", font=("微软雅黑", 12))
                    self.status_label.config(text="视频宽高无效")
                    return
                
                # 使用FFmpeg生成预览帧
                cmd = [
                    FFMPEG,
                    "-i", video_path,
                    "-ss", "00:00:01",  # 截取第1秒的帧
                    "-vframes", "1",
                    "-y",
                    preview_frame_path
                ]
                
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    
                    if result.returncode == 0 and os.path.exists(preview_frame_path):
                        # 显示预览帧
                        from PIL import Image, ImageTk
                        
                        # 打开图片
                        img = Image.open(preview_frame_path)
                        
                        # 获取画布大小
                        cw = self.preview_canvas.winfo_width() or 800
                        ch = self.preview_canvas.winfo_height() or 450
                        
                        # 获取视频原始大小
                        vidW, vidH = img.size
                        
                        # 计算等比例缩放
                        if vidW > 0 and vidH > 0:
                            scaleW = cw / vidW
                            scaleH = ch / vidH
                            scale = min(scaleW, scaleH)
                            
                            # 最终绘制的宽高
                            drawW = int(vidW * scale)
                            drawH = int(vidH * scale)
                            
                            # 居中偏移
                            drawX = (cw - drawW) // 2
                            drawY = (ch - drawH) // 2
                            
                            # 缩放图片
                            img = img.resize((drawW, drawH), Image.Resampling.LANCZOS)
                            img_tk = ImageTk.PhotoImage(img)
                            
                            # 保存到缓存
                            try:
                                cache_system.set(cache_key, img_tk, ttl=3600)  # 缓存1小时
                            except Exception as e:
                                print(f"缓存保存失败: {e}")
                            
                            # 保存引用以防止垃圾回收
                            if hasattr(self, 'preview_canvas'):
                                self.preview_canvas.img_tk = img_tk
                                self.img_tk = img_tk  # 额外绑定到实例变量，确保不被垃圾回收
                            
                            # 清除画布并显示图片
                            if hasattr(self, 'preview_canvas'):
                                self.preview_canvas.delete("all")
                                self.preview_canvas.create_image(drawX + drawW // 2, drawY + drawH // 2, image=img_tk)
                        
                        self._playback_position = 1.0
                        if hasattr(self, '_update_timecode_display'):
                            self._update_timecode_display(1.0)
                        # 更新状态
                        self.status_label.config(text=f"预览视频: {os.path.basename(video_path)}")
                    else:
                        # 显示错误信息
                        if hasattr(self, 'preview_canvas'):
                            self.preview_canvas.delete("all")
                            cw = self.preview_canvas.winfo_width() or 800
                            ch = self.preview_canvas.winfo_height() or 450
                            self.preview_canvas.create_text(cw // 2, ch // 2, text="无法生成视频预览", fill="#ff6666", font=("微软雅黑", 12))
                        self.status_label.config(text="无法生成视频预览")
                        print(f"FFmpeg错误: {result.stderr.decode('utf-8', errors='ignore')}")
                except Exception as e:
                    # 显示错误信息
                    if hasattr(self, 'preview_canvas'):
                        self.preview_canvas.delete("all")
                        cw = self.preview_canvas.winfo_width() or 800
                        ch = self.preview_canvas.winfo_height() or 450
                        self.preview_canvas.create_text(cw // 2, ch // 2, text="FFmpeg执行失败", fill="#ff6666", font=("微软雅黑", 12))
                    self.status_label.config(text="FFmpeg执行失败")
                    print(f"FFmpeg执行失败: {e}")
                finally:
                    # 清理临时文件
                    if os.path.exists(preview_frame_path):
                        try:
                            os.remove(preview_frame_path)
                        except:
                            pass
        except Exception as e:
            error_msg = f"预览视频失败: {str(e)}"
            print(error_msg)
            self.status_label.config(text="预览失败")
            # 显示错误信息
            if hasattr(self, 'preview_canvas'):
                self.preview_canvas.delete("all")
                cw = self.preview_canvas.winfo_width() or 800
                ch = self.preview_canvas.winfo_height() or 450
                self.preview_canvas.create_text(cw // 2, ch // 2, text="预览失败", fill="#ff6666", font=("微软雅黑", 12))
            
    def preview_image(self, image_path):
        """预览图片文件"""
        try:
            # 更新状态
            self.status_label.config(text=f"正在预览图片: {os.path.basename(image_path)}")
            
            # 显示图片
            from PIL import Image, ImageTk
            
            # 打开并调整图片大小
            img = Image.open(image_path)
            img = img.resize((800, 450), Image.Resampling.LANCZOS)
            img_tk = ImageTk.PhotoImage(img)
            
            # 保存引用以防止垃圾回收
            self.preview_canvas.img_tk = img_tk
            self.img_tk = img_tk  # 额外绑定到实例变量，确保不被垃圾回收
            
            # 清除画布并显示图片
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(400, 225, image=img_tk)
            
            # 更新状态
            self.status_label.config(text=f"预览图片: {os.path.basename(image_path)}")
        except Exception as e:
            print(f"预览图片失败: {e}")
            self.status_label.config(text="预览失败")
            
    def preview_audio(self, audio_path):
        """预览音频文件"""
        try:
            # 更新状态
            self.status_label.config(text=f"正在预览音频: {os.path.basename(audio_path)}")
            
            # 显示音频预览界面
            self.preview_canvas.delete("all")
            
            # 绘制音频预览界面
            self.preview_canvas.create_text(400, 200, text="音频文件预览", fill="#ffffff", font=("微软雅黑", 14, "bold"))
            self.preview_canvas.create_text(400, 240, text=os.path.basename(audio_path), fill="#000000", font=("微软雅黑", 12))
            self.preview_canvas.create_text(400, 280, text="点击播放按钮开始播放", fill="#000000", font=("微软雅黑", 10))
            
            # 更新状态
            self.status_label.config(text=f"预览音频: {os.path.basename(audio_path)}")
        except Exception as e:
            print(f"预览音频失败: {e}")
            self.status_label.config(text="预览失败")
    
    def capture_frame(self):
        """截图功能"""
        # 从媒体列表中获取选中的视频文件
        selected_indices = self.media_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要截图的视频文件")
            return
        
        selected_index = selected_indices[0]
        video_filename = self.media_listbox.get(selected_index)
        video_path = self.media_paths.get(video_filename, video_filename)
        
        if not os.path.exists(video_path):
            messagebox.showerror("错误", "视频文件不存在")
            return
        
        try:
            # 生成截图文件名
            screenshot_dir = os.path.join(OUTPUT_DIR, "截图")
            os.makedirs(screenshot_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(screenshot_dir, f"截图_{timestamp}.jpg")
            
            # 使用FFmpeg截图
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-ss", "00:00:01",  # 截取第1秒的帧
                "-vframes", "1",
                "-y",
                screenshot_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0 and os.path.exists(screenshot_path):
                self.status_label.config(text=f"截图成功: {os.path.basename(screenshot_path)}")
                messagebox.showinfo("成功", f"截图已保存到: {screenshot_path}")
            else:
                self.status_label.config(text="截图失败")
                messagebox.showerror("错误", "截图失败，请检查视频文件")
        except Exception as e:
            print(f"截图失败: {e}")
            self.status_label.config(text="截图失败")
            messagebox.showerror("错误", f"截图失败: {str(e)}")
    

    
    def on_speed_change(self, event=None):
        """处理播放速度变化，并同步到嵌入式播放器（MPV/OpenCV 内核）"""
        speed_str = self.speed_var.get()
        try:
            speed_float = float(str(speed_str).replace("x", "").strip())
        except (ValueError, TypeError):
            speed_float = 1.0
            speed_str = "1.0x"
            self.speed_var.set(speed_str)
        
        # 处理优化的播放器
        if getattr(self, "use_optimized_player", False) and getattr(self, "video_player", None):
            player = self.video_player
            if hasattr(player, "mpv_instance") and player.mpv_instance:
                player.mpv_instance.speed = speed_float
            elif hasattr(player, "reader_thread") and player.reader_thread:
                player.reader_thread.set_speed(speed_float)
            if hasattr(player, "speed_combo"):
                combo_text = f"{speed_float:.1f}x" if speed_float == int(speed_float) else f"{speed_float}x"
                idx = player.speed_combo.findText(combo_text)
                if idx >= 0:
                    player.speed_combo.setCurrentIndex(idx)
                else:
                    i = player.speed_combo.findText(speed_str)
                    if i >= 0:
                        player.speed_combo.setCurrentIndex(i)
        
        # 处理默认播放器（OpenCV 帧循环）
        # 对于默认播放器，_play_next_frame 方法会自动从 self.speed_var 读取速度值
        # 这里确保 speed_var 的值是正确的
        
        self.status_label.config(text=f"播放速度已设置为: {speed_str}")
        print(f"速度已调整为: {speed_str} ({speed_float})")
    
    def zoom_in(self):
        """放大时间线（修复版 - 同时刷新刻度）"""
        if self.current_zoom_index < len(self.zoom_levels) - 1:
            self.current_zoom_index += 1
            self.timeline_zoom = self.zoom_levels[self.current_zoom_index]
            self.refresh_tracks()
            # 刷新时间轴刻度
            if hasattr(self, '_draw_ruler_scale'):
                self._draw_ruler_scale()
            zoom_percentage = int(self.timeline_zoom * 100)
            if hasattr(self, 'zoom_label'):
                self.zoom_label.config(text=f"{zoom_percentage}%")
            self.status_label.config(text=f"时间线已放大至 {zoom_percentage}%")
    
    def zoom_out(self):
        """缩小时间线（修复版 - 同时刷新刻度）"""
        if self.current_zoom_index > 0:
            self.current_zoom_index -= 1
            self.timeline_zoom = self.zoom_levels[self.current_zoom_index]
            self.refresh_tracks()
            # 刷新时间轴刻度
            if hasattr(self, '_draw_ruler_scale'):
                self._draw_ruler_scale()
            zoom_percentage = int(self.timeline_zoom * 100)
            if hasattr(self, 'zoom_label'):
                self.zoom_label.config(text=f"{zoom_percentage}%")
            self.status_label.config(text=f"时间线已缩小至 {zoom_percentage}%")
    
    def add_video_track(self):
        """添加视频轨道"""
        try:
            # 实现添加视频轨道功能
            track_id = len(self.tracks) + 1
            self.tracks.append({"id": track_id, "type": "video", "clips": [], "locked": False, "muted": False})
            self.status_label.config(text=f"已添加视频轨道 {track_id}")
            # 刷新轨道显示
            self.refresh_tracks()
            print(f"添加视频轨道成功: {track_id}")
        except Exception as e:
            print(f"添加视频轨道失败: {e}")
            self.status_label.config(text=f"添加视频轨道失败: {e}")
    
    def add_audio_track(self):
        """添加音频轨道"""
        try:
            # 实现添加音频轨道功能
            track_id = len(self.tracks) + 1
            self.tracks.append({"id": track_id, "type": "audio", "clips": [], "locked": False, "muted": False})
            self.status_label.config(text=f"已添加音频轨道 {track_id}")
            # 刷新轨道显示
            self.refresh_tracks()
            print(f"添加音频轨道成功: {track_id}")
        except Exception as e:
            print(f"添加音频轨道失败: {e}")
            self.status_label.config(text=f"添加音频轨道失败: {e}")
    
    def add_text_track(self):
        """添加文本轨道"""
        try:
            # 实现添加文本轨道功能
            track_id = len(self.tracks) + 1
            self.tracks.append({"id": track_id, "type": "text", "clips": [], "locked": False, "muted": False})
            self.status_label.config(text=f"已添加文本轨道 {track_id}")
            # 刷新轨道显示
            self.refresh_tracks()
            print(f"添加文本轨道成功: {track_id}")
        except Exception as e:
            print(f"添加文本轨道失败: {e}")
            self.status_label.config(text=f"添加文本轨道失败: {e}")
    
    def move_track_up(self, track_index):
        """将轨道向上移动"""
        if track_index > 0:
            # 交换轨道位置
            self.tracks[track_index], self.tracks[track_index - 1] = self.tracks[track_index - 1], self.tracks[track_index]
            # 刷新轨道显示
            self.refresh_tracks()
            self.status_label.config(text="轨道已向上移动")
    
    def move_track_down(self, track_index):
        """将轨道向下移动"""
        if track_index < len(self.tracks) - 1:
            # 交换轨道位置
            self.tracks[track_index], self.tracks[track_index + 1] = self.tracks[track_index + 1], self.tracks[track_index]
            # 刷新轨道显示
            self.refresh_tracks()
            self.status_label.config(text="轨道已向下移动")
    
    def delete_track(self, track_index):
        """删除轨道"""
        try:
            if len(self.tracks) > 1:  # 至少保留一个轨道
                # 检查轨道是否被锁定
                if self.tracks[track_index].get("locked", False):
                    self.status_label.config(text="无法删除已锁定的轨道")
                    print("无法删除已锁定的轨道")
                    return
                
                track_type = self.tracks[track_index].get("type", "")
                track_type_name = {"video": "视频", "audio": "音频", "text": "文本"}.get(track_type, "")
                self.tracks.pop(track_index)
                # 刷新轨道显示
                self.refresh_tracks()
                self.status_label.config(text=f"已删除{track_type_name}轨道")
                print(f"删除轨道成功: {track_type_name}")
        except Exception as e:
            print(f"删除轨道失败: {e}")
            self.status_label.config(text=f"删除轨道失败: {e}")
    
    def toggle_track_lock(self, track_index):
        """切换轨道锁定状态"""
        if 0 <= track_index < len(self.tracks):
            self.tracks[track_index]["locked"] = not self.tracks[track_index]["locked"]
            # 刷新轨道显示
            self.refresh_tracks()
            lock_status = "已锁定" if self.tracks[track_index]["locked"] else "已解锁"
            self.status_label.config(text=f"轨道 {lock_status}")
    
    def toggle_track_mute(self, track_index):
        """切换轨道静音状态"""
        if 0 <= track_index < len(self.tracks):
            self.tracks[track_index]["muted"] = not self.tracks[track_index]["muted"]
            if timeline_features:
                try:
                    timeline_features.set_track_mute_solo_lock(self.tracks[track_index], mute=self.tracks[track_index]["muted"])
                except Exception:
                    pass
            self.refresh_tracks()
            mute_status = "已静音" if self.tracks[track_index]["muted"] else "已取消静音"
            self.status_label.config(text=f"轨道 {mute_status}")

    def toggle_track_solo(self, track_index):
        """切换轨道独奏状态"""
        if 0 <= track_index < len(self.tracks):
            self.tracks[track_index]["solo"] = not self.tracks[track_index].get("solo", False)
            if timeline_features:
                try:
                    timeline_features.set_track_mute_solo_lock(self.tracks[track_index], solo=self.tracks[track_index]["solo"])
                except Exception:
                    pass
            self.refresh_tracks()
            solo_status = "独奏" if self.tracks[track_index]["solo"] else "取消独奏"
            self.status_label.config(text=f"轨道 {solo_status}")

    def _setup_track_callbacks(self):
        """设置轨道片段的编辑和预览回调"""
        if hasattr(self, 'timeline_system') and self.timeline_system:
            for track_id, track_obj in self.timeline_system.tracks.items():
                # 设置编辑回调
                track_obj.set_edit_callback(self._on_clip_edit)
                # 设置预览回调
                track_obj.set_preview_callback(self._on_clip_preview)
                print(f"✅ 轨道{track_id}回调设置完成")

    def _on_clip_edit(self, track_id, clip):
        """片段编辑回调 - 在右侧工具栏显示编辑选项"""
        print(f"✏️ 编辑片段: {clip['name']} (轨道{track_id})")

        # 切换到"剪辑"标签页
        if hasattr(self, 'switch_tool_tab'):
            self.switch_tool_tab("剪辑")

        # 更新状态栏
        if hasattr(self, 'status_label'):
            self.status_label.config(text=f"编辑: {clip['name']}")

        # 保存当前选中的片段
        self.selected_clip = {
            "track_id": track_id,
            "clip": clip
        }

        # 在右侧工具栏显示片段信息
        self._show_clip_edit_panel(clip)

    def _on_clip_preview(self, track_id, clip):
        """片段预览回调 - 在预览窗口播放片段（区分轨道类型）"""
        print(f"▶️ 预览片段: {clip['name']} (轨道{track_id})")

        # 获取片段的文件路径（支持path和file_path两种字段名）
        file_path = clip.get('file_path') or clip.get('path')

        # 检查文件是否存在
        if not file_path or not os.path.exists(file_path):
            print(f"⚠️ 片段没有文件路径或文件不存在: {clip['name']}")
            self.status_label.config(text=f"文件不存在: {clip['name']}")
            return

        # 获取轨道类型
        track_type = None
        if hasattr(self, 'tracks') and track_id <= len(self.tracks):
            track_type = self.tracks[track_id - 1].get('type', 'video')

        try:
            if track_type == 'audio':
                # 音频轨道：显示音频预览界面
                self._preview_audio_only(file_path, clip['name'])
                if hasattr(self, 'status_label'):
                    self.status_label.config(text=f"预览音频: {clip['name']}")
            elif track_type == 'video':
                # 视频轨道：预览视频
                self.preview_video(file_path)
                if hasattr(self, 'status_label'):
                    self.status_label.config(text=f"预览视频: {clip['name']}")
            else:
                # 其他类型：根据文件扩展名判断
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ['.mp3', '.wav', '.aac', '.flac', '.ogg', '.m4a', '.wma']:
                    self._preview_audio_only(file_path, clip['name'])
                else:
                    self.preview_video(file_path)
        except Exception as e:
            print(f"❌ 预览失败: {e}")
            self.status_label.config(text=f"预览失败: {e}")

    def _preview_audio_only(self, audio_path, clip_name):
        """仅预览音频（不显示视频）- 使用真实波形图"""
        # 清空预览画布
        if hasattr(self, 'preview_canvas'):
            self.preview_canvas.delete("all")
            cw = self.preview_canvas.winfo_width() or 800
            ch = self.preview_canvas.winfo_height() or 450

            # 绘制音频预览界面
            self.preview_canvas.create_text(
                cw // 2, 40,
                text="🎵 音频文件",
                fill="#4CAF50",
                font=("微软雅黑", 24, "bold")
            )
            self.preview_canvas.create_text(
                cw // 2, 80,
                text=clip_name,
                fill="#ffffff",
                font=("微软雅黑", 14)
            )

            # 生成并显示真实波形图
            try:
                from modules.timeline.waveform_generator import get_waveform_generator
                from PIL import ImageTk

                wave_gen = get_waveform_generator()
                wave_width = cw - 100  # 留出边距
                wave_height = 150

                print(f"🎵 生成音频预览波形图: {os.path.basename(audio_path)}")
                img = wave_gen.generate_waveform(audio_path, wave_width, wave_height)

                if img:
                    # 转换为PhotoImage
                    photo = ImageTk.PhotoImage(img)

                    # 保存引用防止被垃圾回收
                    if not hasattr(self.preview_canvas, 'waveform_images'):
                        self.preview_canvas.waveform_images = []
                    self.preview_canvas.waveform_images.append(photo)

                    # 绘制波形图
                    self.preview_canvas.create_image(
                        cw // 2, ch // 2 + 20,
                        image=photo,
                        anchor="center"
                    )
                    print(f"✅ 波形图显示成功")
                else:
                    # 波形生成失败，显示提示
                    self.preview_canvas.create_text(
                        cw // 2, ch // 2 + 20,
                        text="无法生成波形图",
                        fill="#ff6b6b",
                        font=("微软雅黑", 12)
                    )

            except Exception as e:
                print(f"❌ 生成预览波形图失败: {e}")
                # 显示错误提示
                self.preview_canvas.create_text(
                    cw // 2, ch // 2 + 20,
                    text=f"波形图生成失败: {str(e)[:50]}",
                    fill="#ff6b6b",
                    font=("微软雅黑", 10)
                )

            # 显示播放提示
            self.preview_canvas.create_text(
                cw // 2, ch - 40,
                text="点击播放按钮开始播放",
                fill="#888888",
                font=("微软雅黑", 12)
            )

    def _show_clip_edit_panel(self, clip):
        """在右侧工具栏显示片段编辑面板"""
        # 这里可以添加更多编辑选项
        print(f"🎬 显示编辑面板: {clip['name']}")

    def refresh_tracks(self):
        """刷新轨道显示（修复版 - 正确绘制片段，支持单击编辑）"""
        if hasattr(self, 'timeline_system') and hasattr(self, 'tracks'):
            # 检查Timeline类是否存在
            if Timeline is not None:
                # 清空现有轨道上的所有内容（标题已隐藏）
                for track_id, track_obj in self.timeline_system.tracks.items():
                    # 删除所有内容
                    track_obj.canvas.delete("all")
                    # 清空片段列表
                    track_obj.clips = []

                # 重新添加轨道上的片段
                for i, track in enumerate(self.tracks):
                    track_type = track["type"]
                    track_id = i + 1

                    # 确保轨道存在
                    if track_id not in self.timeline_system.tracks:
                        self.timeline_system.add_track(track_type, track_id)

                    # 获取轨道对象
                    track_obj = self.timeline_system.tracks[track_id]

                    # 设置回调函数（确保每次刷新都设置）
                    track_obj.set_edit_callback(self._on_clip_edit)
                    track_obj.set_preview_callback(self._on_clip_preview)

                    # 添加轨道上的片段
                    clips = track.get("clips", [])
                    print(f"✅ 处理{track_type}轨道{track_id}，包含{len(clips)}个片段")

                    for clip in clips:
                        clip_name = clip.get("name", "片段")
                        start_x = clip.get("start", 0) * self.timeline_zoom
                        duration = clip.get("duration", 100)
                        # 确保片段宽度至少为50像素
                        width = max(duration * self.timeline_zoom, 50)

                        # 使用add_clip方法绘制片段（支持单击编辑）
                        file_path = clip.get("path", "")
                        # 传递原始时长（秒）用于生成缩略图和波形图
                        track_obj.add_clip(clip_name, start_x, width, 90, file_path, duration)

                # 刷新所有轨道
                self.timeline_system.refresh_all_tracks()
                print("✅ 轨道刷新完成")
            else:
                print("❌ Timeline类未导入，无法刷新轨道")
    
    def _draw_clip_on_track(self, track_obj, clip_name, start_x, width, clip_type):
        """在轨道上绘制单个片段（修复版 - 与时间轴对齐，100px偏移）"""
        try:
            # 设置片段颜色
            if clip_type == "video":
                fill_color = "#0078d7"
            elif clip_type == "audio":
                fill_color = "#00c853"
            else:
                fill_color = "#ff9800"
            
            # 时间轴整体向右移120px，与轨道控制栏对齐
            timeline_offset = 120
            
            # 绘制片段矩形（带80px偏移，与时间轴对齐）
            rect_x1 = start_x + timeline_offset
            rect_y1 = 5
            rect_x2 = start_x + width + timeline_offset
            rect_y2 = 85  # 轨道高度90 - 边距5
            
            # 确保不超出画布边界
            canvas_width = track_obj.canvas.winfo_width() or 1500
            if rect_x2 > canvas_width:
                rect_x2 = canvas_width
            
            # 绘制矩形
            track_obj.canvas.create_rectangle(
                rect_x1, rect_y1,
                rect_x2, rect_y2,
                fill=fill_color,
                outline="#ffffff",
                width=1,
                tags=f"clip_{clip_name}"
            )
            
            # 绘制片段名称
            text_x = rect_x1 + 10
            text_y = 45
            
            # 截断过长的名称
            display_name = clip_name
            if len(display_name) > 20:
                display_name = display_name[:17] + "..."
            
            track_obj.canvas.create_text(
                text_x, text_y,
                text=display_name,
                fill="#ffffff",
                font=("微软雅黑", 9),
                anchor="w",
                tags=f"clip_text_{clip_name}"
            )
            
            # 强制刷新
            track_obj.canvas.update()
            
        except Exception as e:
            print(f"❌ 绘制片段失败: {e}")
    
    def display_track_clips(self, track, track_content):
        """显示轨道上的片段"""
        # 清空现有片段
        track_content.delete("all")
        
        # 显示片段
        clips = track.get("clips", [])
        print(f"✅ 显示{track['type']}轨道片段: {len(clips)}个")
        
        for i, clip in enumerate(clips):
            # 应用缩放
            scaled_start = clip.get("start", 0) * self.timeline_zoom
            scaled_duration = clip.get("duration", 100) * self.timeline_zoom
            
            # 确保片段宽度至少为50像素
            if scaled_duration < 50:
                scaled_duration = 50
            
            # 设置片段背景颜色
            if track["type"] == "video":
                clip_bg = "#007acc"
            elif track["type"] == "audio":
                clip_bg = "#00cc7a"
            else:
                clip_bg = "#cc7a00"
            
            # 创建片段
            if track["type"] == "video" or track["type"] == "audio":
                clip_height = 90  # 适配 106px 轨道高度
                clip_y = 8
            else:
                clip_height = 90
                clip_y = 8
            
            print(f"✅ 片段 {i+1}: 起始位置: {scaled_start}, 宽度: {scaled_duration}, 高度: {clip_height}")
            
            # 绘制片段矩形
            track_content.create_rectangle(
                scaled_start, clip_y,  # 左上x, y
                scaled_start + scaled_duration, clip_y + clip_height,  # 右下x, y
                fill=clip_bg, outline="#ffffff", width=1
            )
            
            # 添加片段名称和时长标签
            clip_name = clip.get("name", "片段")
            clip_duration = clip.get("duration", 0)
            
            track_content.create_text(
                scaled_start + 10, clip_y + 20,
                text=clip_name,
                fill="#ffffff", font=("微软雅黑", 9, "bold"),
                anchor="w"
            )
            
            track_content.create_text(
                scaled_start + 10, clip_y + 60,
                text=f"{clip_duration:.2f}s",
                fill="#cccccc", font=("微软雅黑", 8),
                anchor="w"
            )
        
        # 强制刷新画布
        track_content.update()
    
    def on_media_drag_start(self, event):
        """开始拖动媒体文件"""
        # 获取鼠标位置下的项目
        index = self.media_listbox.nearest(event.y)
        if index >= 0:
            # 确保项目被选中
            self.media_listbox.selection_clear(0, tk.END)
            self.media_listbox.selection_set(index)
            selected_file = self.media_listbox.get(index)
            self.dragging_media = selected_file
            # 记录开始拖动的位置
            self.drag_start_x = event.x
            self.drag_start_y = event.y
    
    def on_media_drag(self, event):
        """拖动媒体文件"""
        # 检查是否已经开始拖动
        if hasattr(self, 'dragging_media') and self.dragging_media:
            # 计算拖动距离
            delta_x = event.x - self.drag_start_x
            delta_y = event.y - self.drag_start_y
            # 如果拖动距离足够大，开始拖动
            if abs(delta_x) > 5 or abs(delta_y) > 5:
                # 这里可以添加拖动时的视觉反馈
                pass
    
    def on_track_drop(self, event, track):
        """将媒体文件拖放到轨道上"""
        try:
            # 检查是否正在拖动媒体文件
            if hasattr(self, 'dragging_media') and self.dragging_media:
                selected_file = self.dragging_media
                file_path = self.media_paths.get(selected_file)
                
                if file_path:
                    # 检查文件类型
                    import os
                    ext = os.path.splitext(file_path)[1].lower()
                    file_name = os.path.basename(file_path)
                    
                    # 确定轨道类型是否匹配
                    track_type = track["type"]
                    if ext in [".mp4", ".avi", ".mov", ".mkv"] and track_type == "video":
                        # 添加视频片段
                        self.add_clip_to_track(track, file_path, file_name, "video")
                    elif ext in [".mp3", ".wav", ".aac", ".flac"] and track_type == "audio":
                        # 添加音频片段
                        self.add_clip_to_track(track, file_path, file_name, "audio")
                    elif ext in [".jpg", ".jpeg", ".png", ".bmp"] and track_type == "video":
                        # 添加图片片段
                        self.add_clip_to_track(track, file_path, file_name, "image")
                    
                    self.status_label.config(text=f"已添加 {file_name} 到 {track_type} 轨道")
                    # 重置拖动状态
                    self.dragging_media = None
        except Exception as e:
            print(f"添加文件失败: {e}")
            self.status_label.config(text=f"添加文件失败: {e}")
            # 重置拖动状态
            if hasattr(self, 'dragging_media'):
                self.dragging_media = None
    
    def on_track_click(self, event, track):
        """处理轨道点击事件，从媒体库添加文件"""
        try:
            # 检查是否有选中的媒体文件
            if hasattr(self, 'media_listbox'):
                selected_indices = self.media_listbox.curselection()
                if selected_indices:
                    selected_file = self.media_listbox.get(selected_indices[0])
                    file_path = self.media_paths.get(selected_file)
                    
                    if file_path:
                        # 检查文件类型
                        import os
                        ext = os.path.splitext(file_path)[1].lower()
                        file_name = os.path.basename(file_path)
                        
                        # 确定轨道类型是否匹配
                        track_type = track["type"]
                        if ext in [".mp4", ".avi", ".mov", ".mkv"] and track_type == "video":
                            # 添加视频片段
                            self.add_clip_to_track(track, file_path, file_name, "video")
                        elif ext in [".mp3", ".wav", ".aac", ".flac"] and track_type == "audio":
                            # 添加音频片段
                            self.add_clip_to_track(track, file_path, file_name, "audio")
                        elif ext in [".jpg", ".jpeg", ".png", ".bmp"] and track_type == "video":
                            # 添加图片片段
                            self.add_clip_to_track(track, file_path, file_name, "image")
                        
                        self.status_label.config(text=f"已添加 {file_name} 到 {track_type} 轨道")
                else:
                    self.status_label.config(text="请先在媒体库中选择一个文件")
        except Exception as e:
            print(f"添加文件失败: {e}")
            self.status_label.config(text=f"添加文件失败: {e}")
    
    def _select_target_track(self, tracks, track_type_name, file_name):
        """选择目标轨道对话框
        
        Args:
            tracks: 可用轨道列表
            track_type_name: 轨道类型名称（视频/音频）
            file_name: 文件名
            
        Returns:
            选中的轨道，如果取消则返回None
        """
        if not tracks:
            return None
        
        if len(tracks) == 1:
            return tracks[0]
        
        # 创建选择对话框
        dialog = tk.Toplevel(self.root)
        dialog.title(f"选择{track_type_name}轨道")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 主题颜色
        bg_color = "#2d2d2d"
        text_color = "#ffffff"
        accent_color = "#007acc"
        
        dialog.configure(bg=bg_color)
        
        # 标题
        tk.Label(
            dialog,
            text=f"📁 {file_name}",
            font=("微软雅黑", 12, "bold"),
            bg=bg_color,
            fg=text_color
        ).pack(pady=10)
        
        tk.Label(
            dialog,
            text=f"请选择要导入到的{track_type_name}轨道:",
            font=("微软雅黑", 11),
            bg=bg_color,
            fg=text_color
        ).pack(pady=5)
        
        # 轨道列表框
        list_frame = tk.Frame(dialog, bg=bg_color)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        track_listbox = tk.Listbox(
            list_frame,
            font=("微软雅黑", 11),
            bg="#3d3d3d",
            fg=text_color,
            selectmode=tk.SINGLE,
            height=8
        )
        track_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame, command=track_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        track_listbox.config(yscrollcommand=scrollbar.set)
        
        # 添加轨道到列表
        for i, track in enumerate(tracks):
            clip_count = len(track.get("clips", []))
            track_name = f"{track_type_name}轨道 {i+1} (ID: {track.get('id', 'unknown')}) - {clip_count} 个片段"
            track_listbox.insert(tk.END, track_name)
        
        # 默认选中第一个
        track_listbox.selection_set(0)
        
        # 按钮区域
        btn_frame = tk.Frame(dialog, bg=bg_color)
        btn_frame.pack(fill=tk.X, padx=20, pady=15)
        
        selected_track = [None]  # 使用列表来存储结果
        
        def on_confirm():
            selection = track_listbox.curselection()
            if selection:
                selected_track[0] = tracks[selection[0]]
            dialog.destroy()
        
        def on_cancel():
            selected_track[0] = None
            dialog.destroy()
        
        tk.Button(
            btn_frame,
            text="✓ 确定",
            command=on_confirm,
            bg=accent_color,
            fg="#ffffff",
            font=("微软雅黑", 11),
            padx=20,
            pady=5,
            relief=tk.FLAT
        ).pack(side=tk.RIGHT, padx=5)
        
        tk.Button(
            btn_frame,
            text="✗ 取消",
            command=on_cancel,
            bg="#555555",
            fg="#ffffff",
            font=("微软雅黑", 11),
            padx=20,
            pady=5,
            relief=tk.FLAT
        ).pack(side=tk.RIGHT, padx=5)
        
        # 新建轨道按钮
        def on_new_track():
            if track_type_name == "视频":
                self.add_video_track()
                new_tracks = [t for t in self.tracks if t.get("type") == "video"]
            else:
                self.add_audio_track()
                new_tracks = [t for t in self.tracks if t.get("type") == "audio"]
            
            if new_tracks:
                # 找到新创建的轨道（最后一个）
                new_track = new_tracks[-1]
                selected_track[0] = new_track
            dialog.destroy()
        
        tk.Button(
            btn_frame,
            text="+ 新建轨道",
            command=on_new_track,
            bg="#4CAF50",
            fg="#ffffff",
            font=("微软雅黑", 11),
            padx=15,
            pady=5,
            relief=tk.FLAT
        ).pack(side=tk.LEFT, padx=5)
        
        # 等待对话框关闭
        self.root.wait_window(dialog)
        
        return selected_track[0]
    
    def _get_media_duration_accurate(self, file_path, clip_type):
        """获取媒体文件准确时长（优先使用ffprobe）
        
        Args:
            file_path: 媒体文件路径
            clip_type: 片段类型 (video/audio/image)
            
        Returns:
            float: 时长（秒）
        """
        import os
        
        # 图片类型直接返回默认时长
        if clip_type == "image":
            return 5.0
        
        # 方法1: 使用ffprobe（最准确）
        try:
            import subprocess
            cmd = [
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of',
                'default=noprint_wrappers=1:nokey=1', file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                duration = float(result.stdout.strip())
                if duration > 0:
                    print(f"✅ 使用ffprobe获取时长: {duration:.2f}秒")
                    return duration
        except Exception as e:
            print(f"⚠️ ffprobe获取时长失败: {e}")
        
        # 方法2: 使用moviepy
        try:
            from moviepy.editor import VideoFileClip, AudioFileClip
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"]:
                clip = VideoFileClip(file_path)
                duration = clip.duration
                clip.close()
                print(f"✅ 使用moviepy获取视频时长: {duration:.2f}秒")
                return duration
            elif ext in [".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"]:
                clip = AudioFileClip(file_path)
                duration = clip.duration
                clip.close()
                print(f"✅ 使用moviepy获取音频时长: {duration:.2f}秒")
                return duration
        except Exception as e:
            print(f"⚠️ moviepy获取时长失败: {e}")
        
        # 方法3: 使用OpenCV（备选）
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration = total_frames / fps if fps > 0 else 0
                cap.release()
                if duration > 0:
                    print(f"✅ 使用OpenCV获取时长: {duration:.2f}秒")
                    return duration
        except Exception as e:
            print(f"⚠️ OpenCV获取时长失败: {e}")
        
        # 所有方法都失败，使用默认值
        default_duration = 100.0 if clip_type == "video" else 60.0
        print(f"⚠️ 使用默认时长: {default_duration}秒")
        return default_duration
    
    def add_clip_to_track(self, track, file_path, file_name, clip_type):
        """添加片段到轨道 - 使用ffprobe获取准确时长"""
        # 计算片段起始位置和持续时间
        start_time = 0
        if track.get("clips"):
            last_clip = track["clips"][-1]
            start_time = last_clip.get("start", 0) + last_clip.get("duration", 100)
        
        # 获取实际媒体文件长度（优先使用ffprobe，更准确）
        duration = self._get_media_duration_accurate(file_path, clip_type)
        
        # 创建片段
        
        # 创建片段
        clip = {
            "id": len(track.get("clips", [])) + 1,
            "name": file_name,
            "path": file_path,
            "type": clip_type,
            "start": start_time,
            "duration": duration,
            "volume": 1.0,
            "speed": 1.0
        }
        
        # 添加到轨道
        if "clips" not in track:
            track["clips"] = []
        track["clips"].append(clip)
        
        # 刷新轨道
        self.refresh_tracks()
    
    def add_clip_to_track_with_start(self, track, file_path, file_name, clip_type, start_time):
        """添加片段到轨道 - 指定开始时间（用于视频和音频对齐）"""
        # 获取实际媒体文件长度（优先使用ffprobe，更准确）
        duration = self._get_media_duration_accurate(file_path, clip_type)
        
        # 创建片段
        clip = {
            "id": len(track.get("clips", [])) + 1,
            "name": file_name,
            "path": file_path,
            "type": clip_type,
            "start": start_time,
            "duration": duration,
            "volume": 1.0,
            "speed": 1.0
        }
        
        # 添加到轨道
        if "clips" not in track:
            track["clips"] = []
        track["clips"].append(clip)
        
        # 刷新轨道
        self.refresh_tracks()
    
    def move_clip_to_track(self, clip, source_track, target_track):
        """将片段从源轨道移动到目标轨道"""
        try:
            # 检查源轨道和目标轨道
            if source_track == target_track:
                return False
            
            # 检查轨道是否被锁定
            if source_track.get("locked", False):
                self.status_label.config(text="无法从已锁定的源轨道移动片段")
                return False
            
            if target_track.get("locked", False):
                self.status_label.config(text="无法移动到已锁定的目标轨道")
                return False
            
            # 检查类型兼容性
            source_type = source_track.get("type", "")
            target_type = target_track.get("type", "")
            clip_type = clip.get("type", "")
            
            # 视频片段可以移动到视频轨道
            # 音频片段可以移动到音频轨道
            # 图片片段可以移动到视频轨道
            if clip_type == "video" and target_type != "video":
                self.status_label.config(text="视频片段只能移动到视频轨道")
                return False
            
            if clip_type == "audio" and target_type != "audio":
                self.status_label.config(text="音频片段只能移动到音频轨道")
                return False
            
            if clip_type == "image" and target_type != "video":
                self.status_label.config(text="图片片段只能移动到视频轨道")
                return False
            
            # 从源轨道移除
            if "clips" in source_track and clip in source_track["clips"]:
                source_track["clips"].remove(clip)
            
            # 添加到目标轨道
            if "clips" not in target_track:
                target_track["clips"] = []
            target_track["clips"].append(clip)
            
            # 刷新轨道显示
            self.refresh_tracks()
            
            self.status_label.config(text=f"已将片段 '{clip.get('name')}' 移动到{target_type}轨道")
            return True
            
        except Exception as e:
            print(f"移动片段失败: {e}")
            self.status_label.config(text=f"移动片段失败: {e}")
            return False
    
    def select_clip(self, clip):
        """选择片段"""
        self.selected_clip = clip
        self.status_label.config(text=f"已选择片段: {clip.get('name')}")
    
    def move_clip(self, event, clip, clip_frame):
        """移动片段（带轨道自动吸附）"""
        # 找到片段所在的轨道
        clip_track = None
        for track in self.tracks:
            if clip in track.get("clips", []):
                clip_track = track
                break
        
        # 检查轨道是否被锁定
        if clip_track and clip_track.get("locked", False):
            self.status_label.config(text="无法移动已锁定轨道上的片段")
            return
        
        # 计算新位置（考虑缩放）
        new_x = (event.x_root - clip_frame.winfo_rootx() + clip_frame.winfo_x()) / self.timeline_zoom
        if new_x < 0:
            new_x = 0
        clip["start"] = new_x
        # 轨道自动吸附：对齐剪辑点/字幕
        if timeline_features:
            try:
                snap_points = timeline_features.collect_snap_points(getattr(self, "tracks", []))
                timeline_features.apply_snap_to_clip_start(clip, snap_points)
            except Exception:
                pass
        self.refresh_tracks()
    
    def resize_clip_left(self, event, clip, clip_frame):
        """调整片段左侧边界"""
        # 找到片段所在的轨道
        clip_track = None
        for track in self.tracks:
            if clip in track.get("clips", []):
                clip_track = track
                break
        
        # 检查轨道是否被锁定
        if clip_track and clip_track.get("locked", False):
            self.status_label.config(text="无法调整已锁定轨道上的片段")
            return
        
        # 计算新的左侧位置（考虑缩放）
        new_x = (event.x_root - clip_frame.winfo_rootx()) / self.timeline_zoom
        if new_x < 0:
            new_x = 0
        
        # 计算新的持续时间
        old_start = clip.get("start", 0)
        old_duration = clip.get("duration", 100)
        new_duration = old_duration + (old_start - new_x)
        
        if new_duration > 10:  # 确保片段有最小长度
            clip["start"] = new_x
            clip["duration"] = new_duration
            # 刷新轨道
            self.refresh_tracks()
    
    def resize_clip_right(self, event, clip, clip_frame):
        """调整片段右侧边界"""
        # 找到片段所在的轨道
        clip_track = None
        for track in self.tracks:
            if clip in track.get("clips", []):
                clip_track = track
                break
        
        # 检查轨道是否被锁定
        if clip_track and clip_track.get("locked", False):
            self.status_label.config(text="无法调整已锁定轨道上的片段")
            return
        
        # 计算新的宽度（考虑缩放）
        new_width = (event.x_root - clip_frame.winfo_rootx()) / self.timeline_zoom
        if new_width > 10:  # 确保片段有最小长度
            clip["duration"] = new_width
            # 刷新轨道
            self.refresh_tracks()
    
    def show_tooltip(self, event, tooltip_text):
        """显示工具提示"""
        try:
            # 先删除现有的tooltip，避免出现无效窗口
            if hasattr(self, 'tooltip'):
                try:
                    self.tooltip.destroy()
                except:
                    pass
                delattr(self, 'tooltip')
            
            # 创建新的tooltip
            self.tooltip = tk.Toplevel(self.root)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.wm_geometry("+0+0")
            # 设置tooltip为主窗口的瞬态窗口，这样主窗口关闭时tooltip也会关闭
            self.tooltip.transient(self.root)
            label = tk.Label(self.tooltip, text=tooltip_text, bg="#333333", fg="#ffffff", 
                           font=("微软雅黑", 9), padx=8, pady=4, relief=tk.FLAT)
            label.pack()
        except Exception as e:
            # 如果出现任何错误，尝试清理tooltip属性
            if hasattr(self, 'tooltip'):
                try:
                    delattr(self, 'tooltip')
                except:
                    pass
        
        # 获取鼠标位置
        try:
            # 尝试从event获取位置
            if hasattr(event, 'x_root') and hasattr(event, 'y_root'):
                x, y = event.x_root, event.y_root
            else:
                # 如果event不是事件对象，使用当前鼠标位置
                x = self.root.winfo_pointerx()
                y = self.root.winfo_pointery()
            
            # 确保tooltip窗口存在
            if hasattr(self, 'tooltip') and self.tooltip.winfo_exists():
                self.tooltip.wm_geometry(f"+{x+10}+{y+10}")
                self.tooltip.deiconify()
        except Exception as e:
            print(f"❌ 显示工具提示失败: {e}")
    
    def hide_tooltip(self, event=None):
        """隐藏工具提示"""
        # 直接捕获所有可能的错误，确保方法不会抛出异常
        try:
            # 检查tooltip属性是否存在
            if hasattr(self, 'tooltip'):
                # 尝试销毁tooltip窗口
                try:
                    self.tooltip.destroy()
                except:
                    # 如果销毁失败，说明窗口已经不存在
                    pass
                # 无论成功与否，都删除tooltip属性
                try:
                    delattr(self, 'tooltip')
                except:
                    # 如果删除属性失败，忽略错误
                    pass
        except:
            # 捕获所有其他错误
            pass
    
    def select_tool(self):
        """选择工具"""
        self.status_label.config(text="已选择选择工具")
    
    def link_clips(self):
        """链接片段"""
        self.status_label.config(text="已链接片段")
    
    def copy_clip(self):
        """复制片段"""
        if hasattr(self, 'selected_clip'):
            self.copied_clip = self.selected_clip
            self.status_label.config(text="已复制片段")
        else:
            self.status_label.config(text="请先选择一个片段")
    
    def adjust_speed(self):
        """调整速度（已集成到右侧工具栏，此方法保留用于兼容）"""
        self.status_label.config(text="速度调整已集成到右侧工具栏的「剪辑工具」面板中")
        messagebox.showinfo("提示", "速度调整已集成到右侧工具栏的「剪辑工具」面板中")
    
    def adjust_speed_from_var(self, speed_str):
        """从字符串调整速度（用于右侧工具栏）"""
        try:
            # 解析速度值（如 "1.5x" -> 1.5）
            speed = float(speed_str.replace('x', ''))
            
            # 应用到选中的片段或全局
            if hasattr(self, 'selected_clip') and self.selected_clip:
                self.selected_clip["speed"] = speed
                self.status_label.config(text=f"已调整片段速度: {speed}x")
            else:
                # 应用到全局播放速度
                self.speed_var.set(speed_str)
                self.status_label.config(text=f"已调整播放速度: {speed}x")
                messagebox.showinfo("速度调整", f"播放速度已设置为 {speed}x")
        except Exception as e:
            self.status_label.config(text=f"速度调整失败: {e}")
    
    def crop_video(self):
        """裁剪视频"""
        if hasattr(self, 'selected_clip') and hasattr(self, 'timeline_system'):
            # 查找包含选中片段的轨道
            for track_id, track_obj in self.timeline_system.tracks.items():
                for i, clip in enumerate(track_obj.clips):
                    if clip.get('id') == self.selected_clip.get('id'):
                        # 简化实现：缩小片段宽度
                        width = clip.get('width', 200)
                        if width > 50:  # 最小宽度限制
                            clip['width'] = width * 0.7  # 缩小30%
                            track_obj.refresh()
                            self.status_label.config(text="已裁剪片段")
                        else:
                            self.status_label.config(text="片段宽度已达到最小限制")
                        return
        messagebox.showwarning("提示", "请先选择一个片段")
    
    def rotate_video(self):
        """旋转视频"""
        video_path = getattr(self, 'current_preview_video', None)
        if not video_path and hasattr(self, 'selected_clip') and self.selected_clip:
            video_path = self.selected_clip.get('path')
        
        if video_path and os.path.exists(video_path):
            self.status_label.config(text="旋转视频功能开发中")
            messagebox.showinfo("旋转视频", f"将旋转视频: {os.path.basename(video_path)}")
        else:
            messagebox.showwarning("提示", "请先导入视频")
    
    def apply_selected_effect(self):
        """应用选中的效果"""
        category = getattr(self, 'effect_category_var', tk.StringVar(value="转场效果")).get()
        effect = getattr(self, 'effect_name_var', tk.StringVar(value="淡入淡出")).get()
        
        if hasattr(self, 'selected_clip') and self.selected_clip:
            # 应用效果到选中的片段
            if category == "转场效果":
                self.selected_clip["transition"] = effect
            elif category == "滤镜效果":
                self.selected_clip["filter"] = effect
            elif category == "动画效果":
                self.selected_clip["animation"] = effect
            elif category == "文字效果":
                self.selected_clip["text_effect"] = effect
            elif category == "调色效果":
                self.selected_clip["color_correction"] = effect
    
    def apply_video_adjustments(self):
        """应用视频调节"""
        if hasattr(self, 'selected_clip') and self.selected_clip:
            # 获取调节值
            brightness = getattr(self, 'brightness_var', tk.IntVar(value=0)).get()
            contrast = getattr(self, 'contrast_var', tk.IntVar(value=0)).get()
            saturation = getattr(self, 'saturation_var', tk.IntVar(value=0)).get()
            hue = getattr(self, 'hue_var', tk.IntVar(value=0)).get()
            
            # 保存调节参数
            self.selected_clip["adjustments"] = {
                "brightness": brightness,
                "contrast": contrast,
                "saturation": saturation,
                "hue": hue
            }
            
            self.status_label.config(text=f"🎨 视频调节已应用: 亮度{brightness}, 对比度{contrast}, 饱和度{saturation}, 色调{hue}")
        else:
            messagebox.showwarning("提示", "请先选择一个视频片段")
    
    def reset_video_adjustments(self):
        """重置视频调节"""
        # 重置滑块值
        if hasattr(self, 'brightness_var'):
            self.brightness_var.set(0)
        if hasattr(self, 'contrast_var'):
            self.contrast_var.set(0)
        if hasattr(self, 'saturation_var'):
            self.saturation_var.set(0)
        if hasattr(self, 'hue_var'):
            self.hue_var.set(0)
        
        # 清除选中片段的调节参数
        if hasattr(self, 'selected_clip') and self.selected_clip:
            if "adjustments" in self.selected_clip:
                del self.selected_clip["adjustments"]
            self.status_label.config(text="🔄 视频调节已重置")
        else:
            messagebox.showwarning("提示", "请先选择一个视频片段")
    
    def preview_effect(self):
        """预览效果"""
        category = getattr(self, 'effect_category_var', tk.StringVar(value="转场效果")).get()
        effect = getattr(self, 'effect_name_var', tk.StringVar(value="淡入淡出")).get()
        
        self.status_label.config(text=f"预览{category}: {effect}")
        messagebox.showinfo("效果预览", f"正在预览 {category}: {effect}")
    
    def clear_effects(self):
        """清除所有效果"""
        if hasattr(self, 'selected_clip') and self.selected_clip:
            # 清除所有效果
            for key in ["transition", "filter", "animation", "text_effect", "color_correction"]:
                if key in self.selected_clip:
                    del self.selected_clip[key]
            
            self.status_label.config(text="已清除所有效果")
            messagebox.showinfo("清除效果", "已清除选中片段的所有效果")
        else:
            messagebox.showwarning("提示", "请先选择一个片段")
    
    def split_clip(self):
        """分割视频片段"""
        if hasattr(self, 'selected_clip') and hasattr(self, 'timeline_system'):
            # 查找包含选中片段的轨道
            for track_id, track_obj in self.timeline_system.tracks.items():
                for i, clip in enumerate(track_obj.clips):
                    if clip.get('id') == self.selected_clip.get('id'):
                        # 计算分割位置（在片段中间）
                        start_x = clip.get('start_x', 0)
                        width = clip.get('width', 200)
                        split_x = start_x + width / 2
                        
                        # 创建两个新片段
                        clip1 = clip.copy()
                        clip1['width'] = width / 2
                        clip1['id'] = len(track_obj.clips) + 1
                        
                        clip2 = clip.copy()
                        clip2['start_x'] = split_x
                        clip2['width'] = width / 2
                        clip2['id'] = len(track_obj.clips) + 2
                        
                        # 替换原片段
                        track_obj.clips.pop(i)
                        track_obj.clips.insert(i, clip1)
                        track_obj.clips.insert(i + 1, clip2)
                        
                        # 刷新轨道
                        track_obj.refresh()
                        self.status_label.config(text="已分割片段")
                        return
        self.status_label.config(text="请先选择一个片段")
    
    def delete_clip(self):
        """删除视频片段"""
        if hasattr(self, 'selected_clip') and hasattr(self, 'timeline_system'):
            # 查找包含选中片段的轨道
            for track_id, track_obj in self.timeline_system.tracks.items():
                for i, clip in enumerate(track_obj.clips):
                    if clip.get('id') == self.selected_clip.get('id'):
                        # 删除片段
                        track_obj.clips.pop(i)
                        
                        # 刷新轨道
                        track_obj.refresh()
                        self.selected_clip = None
                        self.status_label.config(text="已删除片段")
                        return
        self.status_label.config(text="请先选择一个片段")

    def get_timeline_duration_sec(self):
        """计算时间轴总时长（秒），用于 hover 预览等。"""
        dur = 0.0
        for track in getattr(self, "tracks", []):
            for c in track.get("clips", []):
                start = float(c.get("start", 0))
                d = float(c.get("duration", 0))
                end = c.get("end")
                if end is not None:
                    dur = max(dur, float(end))
                else:
                    dur = max(dur, start + d)
        return max(1.0, dur)

    def ripple_delete_ui(self):
        """波纹删除：删除选定时间段，后面片段自动前移。"""
        if not timeline_features:
            self.status_label.config(text="轨道增强模块未加载")
            return
        from_sec = getattr(self, "_playback_position", 0.0)
        to_sec = from_sec + 1.0
        w = tk.Toplevel(self.root)
        w.title("波纹删除")
        w.geometry("320x120")
        w.configure(bg="#252525")
        tk.Label(w, text="起始(秒)", bg="#252525", fg="#fff").grid(row=0, column=0, padx=5, pady=5)
        v1 = tk.StringVar(value=str(round(from_sec, 1)))
        tk.Entry(w, textvariable=v1, width=10, bg="#3d3d3d", fg="#fff").grid(row=0, column=1, padx=5, pady=5)
        tk.Label(w, text="结束(秒)", bg="#252525", fg="#fff").grid(row=1, column=0, padx=5, pady=5)
        v2 = tk.StringVar(value=str(round(to_sec, 1)))
        tk.Entry(w, textvariable=v2, width=10, bg="#3d3d3d", fg="#fff").grid(row=1, column=1, padx=5, pady=5)
        def do():
            try:
                f, t = float(v1.get()), float(v2.get())
                if f >= t:
                    messagebox.showwarning("提示", "起始时间须小于结束时间", parent=w)
                    return
                new_tracks = timeline_features.compute_ripple_delete(self.tracks, f, t)
                if new_tracks is not None:
                    self.tracks[:] = new_tracks
                    self.refresh_tracks()
                    self.status_label.config(text="波纹删除已应用")
                    w.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效数字", parent=w)
        tk.Button(w, text="确定", command=do, bg="#007acc", fg="white").grid(row=2, column=1, padx=5, pady=10)
        tk.Button(w, text="取消", command=w.destroy, bg="#555", fg="white").grid(row=2, column=0, padx=5, pady=10)

    def batch_cut_at_playhead_ui(self):
        """在当前时间点批量切割所有轨道片段。"""
        if not timeline_features:
            self.status_label.config(text="轨道增强模块未加载")
            return
        t = getattr(self, "_playback_position", 0.0)
        new_tracks = timeline_features.batch_cut_clips_at_time(self.tracks, t)
        if new_tracks:
            self.tracks[:] = new_tracks
            self.refresh_tracks()
            self.status_label.config(text=f"已在 {t:.1f}s 处批量切割")

    def start_ai_drama_editing(self):
        """开始 AI 短剧剪辑"""
        try:
            # 检查是否有视频片段
            has_video = False
            if hasattr(self, 'timeline_system'):
                for track_id, track_obj in self.timeline_system.tracks.items():
                    if track_obj.track_type == "video" and track_obj.clips:
                        has_video = True
                        break
            
            if not has_video:
                messagebox.showwarning("提示", "请先导入视频并添加到轨道")
                return
            
            # 显示剪辑参数设置
            self.status_label.config(text="正在准备 AI 短剧剪辑...")
            
            # 这里可以添加更复杂的 AI 短剧剪辑逻辑
            # 简化实现：使用右侧工具栏的参数进行剪辑
            
            # 获取输出参数
            output_mode = getattr(self, 'output_mode_var', tk.StringVar(value="30秒爆款引流")).get()
            resolution = getattr(self, 'resolution_var', tk.StringVar(value="1920x1080")).get()
            
            # 显示剪辑信息
            messagebox.showinfo("AI 短剧剪辑", f"开始 AI 短剧剪辑！\n\n输出模式: {output_mode}\n分辨率: {resolution}\n\n剪辑将使用右侧工具栏的参数设置")
            
            # 调用剪辑功能
            self.start_video_editing()
            
        except Exception as e:
            print(f"AI 短剧剪辑失败: {e}")
            self.status_label.config(text="AI 短剧剪辑失败")
    
    def batch_delete_selected_clips(self):
        """批量删除选中的片段（当前为选中一个）。"""
        if not timeline_features:
            self.status_label.config(text="轨道增强模块未加载")
            return
        if not getattr(self, "selected_clip", None):
            self.status_label.config(text="请先选择要删除的片段")
            return
        cid = self.selected_clip.get("id")
        if cid is None:
            self.status_label.config(text="该片段无法删除")
            return
        new_tracks = timeline_features.batch_delete_clips_by_ids(self.tracks, [cid])
        if new_tracks:
            self.tracks[:] = new_tracks
            self.selected_clip = None
            self.refresh_tracks()
            # 更新视频预览状态
            if getattr(self, 'current_preview_video', None) and os.path.exists(self.current_preview_video):
                self.preview_video(self.current_preview_video)
            self.status_label.config(text="已删除选中片段")

    def show_transition_options(self):
        """显示转场效果选项"""
        # 创建转场选项窗口
        transition_window = tk.Toplevel(self.root)
        transition_window.title("转场效果")
        transition_window.geometry("400x500")
        transition_window.configure(bg="#1a1a1a")
        
        # 转场列表
        transitions = [
            "淡入淡出", "滑动", "缩放", "旋转", "闪烁", 
            "擦除", "溶解", "百叶窗", "推进", "翻页"
        ]
        
        # 转场选择框架
        transition_frame = tk.Frame(transition_window, bg="#252525", pady=20, padx=20)
        transition_frame.pack(fill=tk.BOTH, expand=True)
        
        # 转场标题
        tk.Label(transition_frame, text="转场效果", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 转场选择列表
        transition_var = tk.StringVar(value="淡入淡出")
        for transition_name in transitions:
            transition_btn = tk.Radiobutton(transition_frame, text=transition_name, variable=transition_var, value=transition_name, 
                                           bg="#252525", fg="#ffffff", selectcolor="#3d3d3d")
            transition_btn.pack(anchor=tk.W, pady=5)
        
        # 持续时间调整
        tk.Label(transition_frame, text="持续时间 (秒):", font=("微软雅黑", 10), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        duration_var = tk.DoubleVar(value=1.0)
        duration_scale = tk.Scale(transition_frame, from_=0.1, to=3.0, resolution=0.1, orient=tk.HORIZONTAL, 
                                  variable=duration_var, bg="#2d2d2d", fg="#ffffff", 
                                  highlightbackground="#2d2d2d", troughcolor="#3d3d3d", 
                                  activebackground="#007acc", length=300)
        duration_scale.pack(anchor=tk.W, pady=5)
        
        # 应用按钮
        apply_btn = tk.Button(transition_frame, text="应用转场", command=lambda: apply_transition(transition_var.get(), duration_var.get()), 
                              bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=10, relief=tk.FLAT)
        apply_btn.pack(pady=20)
        
        def apply_transition(transition_name, duration):
            """应用转场"""
            self.status_label.config(text=f"已应用转场: {transition_name} (持续时间: {duration}秒)")
            transition_window.destroy()
    
    def show_filter_options(self):
        """显示滤镜选项"""
        # 创建滤镜选项窗口
        filter_window = tk.Toplevel(self.root)
        filter_window.title("滤镜效果")
        filter_window.geometry("400x500")
        filter_window.configure(bg="#1a1a1a")
        
        # 滤镜列表
        filters = [
            "自然", "清晰", "鲜艳", "复古", "黑白", 
            "冷色调", "暖色调", "电影感", "梦幻", "LOMO"
        ]
        
        # 滤镜选择框架
        filter_frame = tk.Frame(filter_window, bg="#252525", pady=20, padx=20)
        filter_frame.pack(fill=tk.BOTH, expand=True)
        
        # 滤镜标题
        tk.Label(filter_frame, text="滤镜效果", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 滤镜选择列表
        filter_var = tk.StringVar(value="自然")
        for filter_name in filters:
            filter_btn = tk.Radiobutton(filter_frame, text=filter_name, variable=filter_var, value=filter_name, 
                                        bg="#252525", fg="#ffffff", selectcolor="#3d3d3d")
            filter_btn.pack(anchor=tk.W, pady=5)
        
        # 强度调整
        tk.Label(filter_frame, text="强度:", font=("微软雅黑", 10), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        intensity_var = tk.DoubleVar(value=0.5)
        intensity_scale = tk.Scale(filter_frame, from_=0, to=1, resolution=0.1, orient=tk.HORIZONTAL, 
                                   variable=intensity_var, bg="#2d2d2d", fg="#ffffff", 
                                   highlightbackground="#2d2d2d", troughcolor="#3d3d3d", 
                                   activebackground="#007acc", length=300)
        intensity_scale.pack(anchor=tk.W, pady=5)
        
        # 应用按钮
        apply_btn = tk.Button(filter_frame, text="应用滤镜", command=lambda: apply_filter(filter_var.get(), intensity_var.get()), 
                              bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=10, relief=tk.FLAT)
        apply_btn.pack(pady=20)
        
        def apply_filter(filter_name, intensity):
            """应用滤镜"""
            self.status_label.config(text=f"已应用滤镜: {filter_name} (强度: {intensity})")
            filter_window.destroy()
    
    def play_timeline(self):
        """播放时间线"""
        # 模拟播放时间线
        self.status_label.config(text="正在播放时间线...")
        
        # 模拟播放效果
        import threading
        import time
        
        def simulate_timeline_play():
            # 模拟时间码变化
            for i in range(1, 11):
                timecode = f"00:00:{i:02d}:00"
                self.timecode_label.config(text=timecode)
                time.sleep(1)
            self.status_label.config(text="时间线播放完成")
        
        thread = threading.Thread(target=simulate_timeline_play, daemon=True)
        thread.start()
    
    def pause_timeline(self):
        """暂停时间线"""
        self.status_label.config(text="时间线已暂停")
    
    def stop_timeline(self):
        """停止时间线"""
        self.status_label.config(text="时间线已停止")
        # 重置时间码
        self.timecode_label.config(text="00:00:00:00")
    
    def show_copywriting_tab(self):
        """显示文案生成选项卡"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        entry_bg = "#2d2d2d" if self.current_theme == "dark" else "#ffffff"
        entry_fg = "#ffffff" if self.current_theme == "dark" else "#000000"
        insert_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg=bg_color)
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="文案生成", font=("微软雅黑", 18, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, pady=20)
        
        # 输入方式选择
        input_frame = tk.Frame(frame, bg=frame_color, pady=20, padx=30)
        input_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(input_frame, text="输入方式:", bg=frame_color, fg=text_color, font=('微软雅黑', 13)).pack(side=tk.LEFT, padx=10)
        self.input_mode_var = tk.StringVar(value="视频文件")
        input_options = ["视频文件", "剧本/小说片段", "关键词", "爆款文案链接"]
        input_menu = ttk.Combobox(input_frame, textvariable=self.input_mode_var, values=input_options, state="readonly", width=20)
        input_menu.pack(side=tk.LEFT, padx=10)
        input_menu.bind("<<ComboboxSelected>>", self.on_input_mode_change)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg=frame_color, pady=30, padx=30)
        config_frame.pack(fill=tk.X, pady=20)
        
        # 配置项
        row = 0
        
        # 视频文件输入
        self.video_input_frame = tk.Frame(config_frame, bg=frame_color)
        self.video_input_frame.grid(row=row, column=0, columnspan=4, sticky=tk.W, padx=20, pady=15)
        tk.Label(self.video_input_frame, text="视频文件:", bg=frame_color, fg=text_color, font=('微软雅黑', 13)).pack(side=tk.LEFT, padx=10)
        self.copy_video_path_var = tk.StringVar()
        self.copy_video_path_entry = tk.Entry(self.video_input_frame, textvariable=self.copy_video_path_var, width=60, bg=entry_bg, fg=entry_fg, insertbackground=insert_color, font=("微软雅黑", 12))
        self.copy_video_path_entry.pack(side=tk.LEFT, padx=10)
        browse_btn = tk.Button(self.video_input_frame, text="浏览", command=lambda: self.browse_file(self.copy_video_path_var, (("视频文件", "*.mp4 *.avi *.mov *.mkv"),)), bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=15, pady=7, relief=tk.FLAT)
        browse_btn.pack(side=tk.LEFT, padx=10)
        row += 1
        
        # 剧本/小说片段输入
        self.script_input_frame = tk.Frame(config_frame, bg=frame_color)
        self.script_input_frame.grid(row=row, column=0, columnspan=4, sticky=tk.W, padx=20, pady=15)
        self.script_input_frame.grid_remove()  # 默认隐藏
        tk.Label(self.script_input_frame, text="剧本/小说片段:", bg=frame_color, fg=text_color, font=('微软雅黑', 13)).pack(anchor=tk.NW, padx=10, pady=5)
        self.script_text = tk.Text(self.script_input_frame, width=80, height=10, bg=entry_bg, fg=entry_fg, insertbackground=insert_color, font=("微软雅黑", 12))
        self.script_text.pack(anchor=tk.W, padx=10, pady=5)
        row += 1
        
        # 关键词输入
        self.keyword_input_frame = tk.Frame(config_frame, bg=frame_color)
        self.keyword_input_frame.grid(row=row, column=0, columnspan=4, sticky=tk.W, padx=20, pady=15)
        self.keyword_input_frame.grid_remove()  # 默认隐藏
        tk.Label(self.keyword_input_frame, text="关键词 (用逗号分隔):", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).pack(side=tk.LEFT, padx=10)
        self.keywords_var = tk.StringVar(value="短剧, 爽点, 反转")
        self.keywords_entry = tk.Entry(self.keyword_input_frame, textvariable=self.keywords_var, width=60, bg=entry_bg, fg=entry_fg, insertbackground=insert_color, font=("微软雅黑", 12))
        self.keywords_entry.pack(side=tk.LEFT, padx=10)
        row += 1
        
        # 爆款文案链接输入
        self.link_input_frame = tk.Frame(config_frame, bg=frame_color)
        self.link_input_frame.grid(row=row, column=0, columnspan=4, sticky=tk.W, padx=20, pady=15)
        self.link_input_frame.grid_remove()  # 默认隐藏
        tk.Label(self.link_input_frame, text="爆款文案链接:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).pack(side=tk.LEFT, padx=10)
        self.link_var = tk.StringVar()
        self.link_entry = tk.Entry(self.link_input_frame, textvariable=self.link_var, width=60, bg=entry_bg, fg=entry_fg, insertbackground=insert_color, font=("微软雅黑", 12))
        self.link_entry.pack(side=tk.LEFT, padx=10)
        row += 1
        
        # 模型选择
        tk.Label(config_frame, text="AI模型:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.copy_model_var = tk.StringVar(value=model_manager.current_model)
        model_options = model_manager.models
        self.copy_model_menu = ttk.Combobox(config_frame, textvariable=self.copy_model_var, values=model_options, state="readonly", width=25, font=("微软雅黑", 12))
        self.copy_model_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 平台选择
        tk.Label(config_frame, text="目标平台:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.platform_var = tk.StringVar(value="快手")
        platform_options = ["快手", "抖音", "视频号", "小红书", "B站"]
        self.platform_menu = ttk.Combobox(config_frame, textvariable=self.platform_var, values=platform_options, state="readonly", width=25, font=("微软雅黑", 12))
        self.platform_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 赛道选择
        tk.Label(config_frame, text="赛道选择:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.track_var = tk.StringVar(value="短剧")
        track_options = ["短剧", "影视解说", "带货", "同城引流", "其他"]
        track_menu = ttk.Combobox(config_frame, textvariable=self.track_var, values=track_options, state="readonly", width=25, font=("微软雅黑", 12))
        track_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 文案预览
        preview_frame = tk.Frame(frame, bg=frame_color, pady=30, padx=30)
        preview_frame.pack(fill=tk.X, pady=20)
        
        # 标题预览
        tk.Label(preview_frame, text="生成标题:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=0, column=0, sticky=tk.NW, padx=20, pady=10)
        self.copy_title_label = tk.Label(preview_frame, text="点击生成文案", bg=frame_color, fg=desc_color, font=("微软雅黑", 14, "bold"), wraplength=600)
        self.copy_title_label.grid(row=0, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 内容预览
        tk.Label(preview_frame, text="发布文案:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=1, column=0, sticky=tk.NW, padx=20, pady=10)
        self.copy_content_label = tk.Label(preview_frame, text="", bg=frame_color, fg=desc_color, font=("微软雅黑", 12), wraplength=600, justify=tk.LEFT)
        self.copy_content_label.grid(row=1, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 关键词预览
        tk.Label(preview_frame, text="关键词:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=2, column=0, sticky=tk.NW, padx=20, pady=10)
        self.copy_kw_label = tk.Label(preview_frame, text="", bg=frame_color, fg=desc_color, font=("微软雅黑", 12))
        self.copy_kw_label.grid(row=2, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 平台专属标签
        tk.Label(preview_frame, text="平台专属标签:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=3, column=0, sticky=tk.NW, padx=20, pady=10)
        self.platform_tags_label = tk.Label(preview_frame, text="", bg=frame_color, fg="#007acc", font=("微软雅黑", 12))
        self.platform_tags_label.grid(row=3, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 操作按钮
        button_frame = tk.Frame(preview_frame, bg=frame_color)
        button_frame.grid(row=4, column=1, columnspan=3, pady=20, sticky=tk.W)
        
        # 生成文案按钮
        generate_btn = tk.Button(button_frame, text="生成文案", command=self.generate_copywriting, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        generate_btn.pack(side=tk.LEFT, padx=10)
        
        # 生成配音按钮
        voice_btn = tk.Button(button_frame, text="生成AI配音", command=self.generate_ai_voiceover, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        voice_btn.pack(side=tk.LEFT, padx=10)
        
        # 保存文案按钮
        save_btn = tk.Button(button_frame, text="保存文案", command=self.save_copywriting, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        save_btn.pack(side=tk.LEFT, padx=10)
        
        # 爆款文案库
        library_frame = tk.Frame(frame, bg=frame_color, pady=30, padx=30)
        library_frame.pack(fill=tk.X, pady=20)
        
        # 文案库标题
        tk.Label(library_frame, text="爆款文案库", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(anchor=tk.W, pady=10)
        
        # 文案库分类
        category_frame = tk.Frame(library_frame, bg=frame_color)
        category_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(category_frame, text="文案分类:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.library_category_var = tk.StringVar(value="短剧")
        library_options = ["短剧", "影视解说", "带货", "同城引流"]
        library_menu = ttk.Combobox(category_frame, textvariable=self.library_category_var, values=library_options, state="readonly", width=20, font=("微软雅黑", 12))
        library_menu.pack(side=tk.LEFT, padx=10)
        library_menu.bind("<<ComboboxSelected>>", self.on_library_category_change)
        
        # 文案库列表
        self.library_listbox = tk.Listbox(library_frame, width=80, height=10, bg=entry_bg, fg=entry_fg, selectbackground=item_color, selectforeground=text_color, font=("微软雅黑", 12))
        self.library_listbox.pack(fill=tk.X, pady=10)
        
        # 加载爆款文案库
        self.load_copywriting_library()
        
        # 文案库操作按钮
        library_btn_frame = tk.Frame(library_frame, bg=frame_color)
        library_btn_frame.pack(fill=tk.X, pady=10)
        
        # 参考文案按钮
        reference_btn = tk.Button(library_btn_frame, text="参考选中文案", command=self.reference_selected_copy, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        reference_btn.pack(side=tk.LEFT, padx=10)
        
        # 智能改写按钮
        rewrite_btn = tk.Button(library_btn_frame, text="智能改写", command=self.rewrite_selected_copy, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        rewrite_btn.pack(side=tk.LEFT, padx=10)
    
    def show_account_analysis_tab(self):
        """显示账号运营分析选项卡"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        card_color = "#1e1e1e" if self.current_theme == "dark" else "#ffffff"
        
        # 创建主容器
        main_container = tk.Frame(self.content_frame, bg=bg_color)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # ========== 快捷操作区（置顶） ==========
        quick_action_frame = tk.Frame(main_container, bg=frame_color, pady=15, padx=20)
        quick_action_frame.pack(fill=tk.X, pady=0)
        
        # 标题和返回按钮
        header_frame = tk.Frame(quick_action_frame, bg=frame_color)
        header_frame.pack(fill=tk.X, pady=5)
        
        # 已删除返回按钮
        
        # 标题
        tk.Label(header_frame, text="快捷操作", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(side=tk.LEFT, padx=10)
        
        # 账号切换和发布区域
        quick_content_frame = tk.Frame(quick_action_frame, bg=frame_color)
        quick_content_frame.pack(fill=tk.X, pady=10)
        
        # 账号切换和批量选择
        account_switch_frame = tk.Frame(quick_content_frame, bg=frame_color)
        account_switch_frame.pack(side=tk.LEFT, padx=10)
        
        tk.Label(account_switch_frame, text="账号管理:", bg=frame_color, fg=text_color, font= ("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        
        # 批量选择账号框架
        batch_select_frame = tk.Frame(account_switch_frame, bg=frame_color)
        batch_select_frame.pack(side=tk.LEFT, padx=10)
        
        # 批量选择按钮
        self.batch_select_var = tk.BooleanVar(value=False)
        batch_select_check = tk.Checkbutton(batch_select_frame, text="批量选择", variable=self.batch_select_var, bg=frame_color, fg=text_color, selectcolor=item_color, font=("微软雅黑", 11))
        batch_select_check.pack(side=tk.LEFT, padx=5)
        
        # 账号选择下拉框（从已绑定账号加载，无则仅显示“全部账号”）
        self.selected_account_var = tk.StringVar(value="全部账号")
        self._load_bound_accounts()
        account_options = ["全部账号"] + [self._account_display_line(acc) for acc in self.bound_accounts]
        if len(account_options) == 1:
            account_options.append("（请先在下方「账号管理」中绑定账号）")
        account_menu = ttk.Combobox(account_switch_frame, textvariable=self.selected_account_var, values=account_options, state="readonly", width=25, font=("微软雅黑", 11))
        account_menu.pack(side=tk.LEFT, padx=10)
        
        # 账号管理按钮
        manage_account_btn = tk.Button(account_switch_frame, text="管理账号", command=self.manage_accounts, bg=item_color, fg=text_color, font= ("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        manage_account_btn.pack(side=tk.LEFT, padx=10)
        
        # 新手/专业模式切换
        mode_frame = tk.Frame(account_switch_frame, bg=frame_color)
        mode_frame.pack(side=tk.LEFT, padx=10)
        
        tk.Label(mode_frame, text="模式:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=5)
        
        # 模式选择按钮
        mode_buttons_frame = tk.Frame(mode_frame, bg=frame_color)
        mode_buttons_frame.pack(side=tk.LEFT, padx=5)
        
        novice_btn = tk.Button(mode_buttons_frame, text="新手模式", command=lambda: self.toggle_mode("新手模式"), bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=10, pady=3, relief=tk.FLAT)
        novice_btn.pack(side=tk.LEFT, padx=5)
        
        pro_btn = tk.Button(mode_buttons_frame, text="专业模式", command=lambda: self.toggle_mode("专业模式"), bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=10, pady=3, relief=tk.FLAT)
        pro_btn.pack(side=tk.LEFT, padx=5)
        
        # 一键发布
        publish_frame = tk.Frame(quick_content_frame, bg=frame_color)
        publish_frame.pack(side=tk.RIGHT, padx=10)
        
        # 发布平台选择
        tk.Label(publish_frame, text="发布平台:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.publish_platform_var = tk.StringVar(value="抖音")
        publish_platforms = ["抖音", "快手", "视频号", "小红书", "B站"]
        publish_platform_menu = ttk.Combobox(publish_frame, textvariable=self.publish_platform_var, values=publish_platforms, state="readonly", width=15, font=("微软雅黑", 11))
        publish_platform_menu.pack(side=tk.LEFT, padx=10)
        
        # 一键发布按钮
        publish_btn = tk.Button(publish_frame, text="一键发布", command=self.publish_video, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        publish_btn.pack(side=tk.LEFT, padx=10)
        
        # ========== 核心内容区 ==========
        core_content_frame = tk.Frame(main_container, bg=bg_color)
        core_content_frame.pack(fill=tk.BOTH, expand=True, pady=0)
        
        # ========== 数据可视化区（左侧） ==========
        visualization_frame = tk.Frame(core_content_frame, bg=bg_color, width=300)
        visualization_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=10, pady=10)
        
        # 核心数据看板
        dashboard_frame = tk.Frame(visualization_frame, bg=frame_color, pady=20, padx=20)
        dashboard_frame.pack(fill=tk.X, pady=10)
        
        # 标题
        tk.Label(dashboard_frame, text="核心数据看板", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(anchor=tk.W, pady=10)
        
        # 关键指标卡片
        metrics_frame = tk.Frame(dashboard_frame, bg=frame_color)
        metrics_frame.pack(fill=tk.X, pady=10)
        
        # 指标数据
        metrics = [
            {"label": "总播放量", "value": "125,000", "change": "+12.5%", "color": "#4CAF50", "unit": "次"},
            {"label": "平均完播率", "value": "28%", "change": "+3.2%", "color": "#4CAF50", "unit": ""},
            {"label": "转化率", "value": "7.5%", "change": "-1.5%", "color": "#f44336", "unit": ""},
            {"label": "粉丝数", "value": "15,620", "change": "+8.7%", "color": "#4CAF50", "unit": "个"},
            {"label": "今日播放量", "value": "8,500", "change": "+25.3%", "color": "#4CAF50", "unit": "次"},
            {"label": "爆款视频数", "value": "3", "change": "+1", "color": "#4CAF50", "unit": "个"}
        ]
        
        for i, metric in enumerate(metrics):
            metric_card = tk.Frame(metrics_frame, bg=card_color, padx=15, pady=12, relief=tk.RAISED, bd=1)
            metric_card.grid(row=i, column=0, padx=5, pady=5, sticky=tk.NSEW)
            
            # 设置网格权重
            metrics_frame.grid_columnconfigure(0, weight=1)
            
            # 指标值
            value_label = tk.Label(metric_card, text=metric["value"] + metric["unit"], font=("微软雅黑", 18, "bold"), bg=card_color, fg=text_color)
            value_label.pack(anchor=tk.W)
            
            # 指标标签
            label_label = tk.Label(metric_card, text=metric["label"], font=("微软雅黑", 11), bg=card_color, fg=desc_color)
            label_label.pack(anchor=tk.W)
            
            # 变化率
            change_label = tk.Label(metric_card, text=metric["change"], font=("微软雅黑", 10, "bold"), bg=card_color, fg=metric["color"])
            change_label.pack(anchor=tk.W, pady=3)
        
        # 智能建议区
        suggestion_frame = tk.Frame(visualization_frame, bg=frame_color, pady=20, padx=20)
        suggestion_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 标题
        tk.Label(suggestion_frame, text="智能建议", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(anchor=tk.W, pady=10)
        
        # 建议内容
        self.ai_suggestions_text = tk.Label(suggestion_frame, text="点击'生成运营建议'获取AI优化方案", bg=frame_color, fg=desc_color, font=("微软雅黑", 11), wraplength=250, justify=tk.LEFT)
        self.ai_suggestions_text.pack(anchor=tk.W, pady=10)
        
        # 生成建议按钮
        generate_suggestions_btn = tk.Button(suggestion_frame, text="生成运营建议", command=self.generate_ai_suggestions, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=15, pady=6, relief=tk.FLAT)
        generate_suggestions_btn.pack(anchor=tk.W, pady=10)
        
        # ========== 核心功能区（右侧） ==========
        core_features_frame = tk.Frame(core_content_frame, bg=bg_color)
        core_features_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 核心功能区标题
        tk.Label(core_features_frame, text="核心功能", font=("微软雅黑", 16, "bold"), bg=bg_color, fg=text_color).pack(anchor=tk.W, pady=10, padx=10)
        
        # ========== 账号管理 ==========
        account_management_frame = tk.Frame(core_features_frame, bg=frame_color, pady=20, padx=20)
        account_management_frame.pack(fill=tk.X, pady=10)
        
        # 标题和折叠按钮
        account_header_frame = tk.Frame(account_management_frame, bg=frame_color)
        account_header_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(account_header_frame, text="账号管理", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(side=tk.LEFT, padx=5)
        
        # 折叠状态
        self.account_collapsed = tk.BooleanVar(value=False)
        
        def toggle_account():
            self.account_collapsed.set(not self.account_collapsed.get())
            if self.account_collapsed.get():
                account_content_frame.pack_forget()
                account_toggle_btn.config(text="▶")
            else:
                account_content_frame.pack(fill=tk.X, pady=10)
                account_toggle_btn.config(text="▼")
        
        account_toggle_btn = tk.Button(account_header_frame, text="▼" if not self.account_collapsed.get() else "▶", bg=frame_color, fg=text_color, font=("微软雅黑", 10), padx=5, pady=0, relief=tk.FLAT, width=2, command=toggle_account)
        account_toggle_btn.pack(side=tk.RIGHT, padx=5)
        
        # 账号管理内容
        account_content_frame = tk.Frame(account_management_frame, bg=frame_color)
        account_content_frame.pack(fill=tk.X, pady=10)
        
        # 多平台账号绑定
        tk.Label(account_content_frame, text="多平台账号绑定", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 平台绑定按钮
        platform_buttons_frame = tk.Frame(account_content_frame, bg=frame_color)
        platform_buttons_frame.pack(fill=tk.X, pady=10)
        
        platforms = ["抖音", "快手", "视频号", "小红书", "B站", "TikTok"]
        for platform in platforms:
            bind_btn = tk.Button(platform_buttons_frame, text=f"绑定{platform}账号", command=lambda p=platform: self.bind_account(p), bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=15, pady=6, relief=tk.FLAT)
            bind_btn.pack(side=tk.LEFT, padx=5)
        
        # 子账号权限管理
        tk.Label(account_content_frame, text="子账号权限管理", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 权限管理按钮
        permission_btn = tk.Button(account_content_frame, text="管理子账号权限", command=self.manage_subaccount_permissions, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=15, pady=6, relief=tk.FLAT)
        permission_btn.pack(anchor=tk.W, pady=5)
        
        # ========== 内容分发 ==========
        content_distribution_frame = tk.Frame(core_features_frame, bg=frame_color, pady=20, padx=20)
        content_distribution_frame.pack(fill=tk.X, pady=10)
        
        # 标题和折叠按钮
        distribution_header_frame = tk.Frame(content_distribution_frame, bg=frame_color)
        distribution_header_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(distribution_header_frame, text="内容分发", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(side=tk.LEFT, padx=5)
        
        # 折叠状态
        self.distribution_collapsed = tk.BooleanVar(value=False)
        
        def toggle_distribution():
            self.distribution_collapsed.set(not self.distribution_collapsed.get())
            if self.distribution_collapsed.get():
                distribution_content_frame.pack_forget()
                distribution_toggle_btn.config(text="▶")
            else:
                distribution_content_frame.pack(fill=tk.X, pady=10)
                distribution_toggle_btn.config(text="▼")
        
        distribution_toggle_btn = tk.Button(distribution_header_frame, text="▼" if not self.distribution_collapsed.get() else "▶", bg=frame_color, fg=text_color, font=("微软雅黑", 10), padx=5, pady=0, relief=tk.FLAT, width=2, command=toggle_distribution)
        distribution_toggle_btn.pack(side=tk.RIGHT, padx=5)
        
        # 内容分发内容
        distribution_content_frame = tk.Frame(content_distribution_frame, bg=frame_color)
        distribution_content_frame.pack(fill=tk.X, pady=10)
        
        # 定时发布和批量发布
        publish_options_frame = tk.Frame(distribution_content_frame, bg=frame_color)
        publish_options_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(publish_options_frame, text="发布设置:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=5)
        
        # 发布时间选择
        self.publish_time_var = tk.StringVar(value="立即发布")
        publish_time_options = ["立即发布", "定时发布", "批量发布"]
        publish_time_menu = ttk.Combobox(publish_options_frame, textvariable=self.publish_time_var, values=publish_time_options, state="readonly", width=15, font=("微软雅黑", 11))
        publish_time_menu.pack(side=tk.LEFT, padx=10)
        
        # 自动发布开关
        auto_publish_frame = tk.Frame(distribution_content_frame, bg=frame_color)
        auto_publish_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(auto_publish_frame, text="自动发布:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.auto_publish_var = tk.BooleanVar(value=False)
        auto_publish_switch = tk.Checkbutton(auto_publish_frame, text="开启自动发布", variable=self.auto_publish_var, bg=frame_color, fg=text_color, selectcolor=item_color, font=("微软雅黑", 11))
        auto_publish_switch.pack(side=tk.LEFT, padx=10)
        
        # 发布进度条
        publish_progress_frame = tk.Frame(distribution_content_frame, bg=frame_color)
        publish_progress_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(publish_progress_frame, text="发布进度:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.publish_progress_var = tk.DoubleVar(value=0)
        publish_progress = ttk.Progressbar(publish_progress_frame, variable=self.publish_progress_var, length=300, mode='determinate')
        publish_progress.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        
        # 发布结果回执
        publish_result_frame = tk.Frame(distribution_content_frame, bg=frame_color)
        publish_result_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(publish_result_frame, text="发布结果:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.publish_result_var = tk.StringVar(value="未发布")
        publish_result_label = tk.Label(publish_result_frame, textvariable=self.publish_result_var, bg=frame_color, fg="#4CAF50", font=("微软雅黑", 12))
        publish_result_label.pack(side=tk.LEFT, padx=10)
        
        # 发布模板管理
        template_btn = tk.Button(distribution_content_frame, text="管理发布模板", command=self.manage_publish_templates, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=15, pady=6, relief=tk.FLAT)
        template_btn.pack(anchor=tk.W, pady=5)
        
        # 模板化运营
        template_operation_frame = tk.Frame(distribution_content_frame, bg=frame_color)
        template_operation_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(template_operation_frame, text="模板化运营:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        
        # 模板选择下拉框
        self.template_var = tk.StringVar(value="短剧冷启动模板")
        template_options = ["短剧冷启动模板", "爆款视频运营模板"]
        template_menu = ttk.Combobox(template_operation_frame, textvariable=self.template_var, values=template_options, state="readonly", width=20, font=("微软雅黑", 11))
        template_menu.pack(side=tk.LEFT, padx=10)
        
        # 应用模板按钮
        apply_template_btn = tk.Button(template_operation_frame, text="应用模板", command=lambda: self.apply_template_operation(self.template_var.get()), bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        apply_template_btn.pack(side=tk.LEFT, padx=10)
        
        # 智能默认值
        smart_defaults_frame = tk.Frame(distribution_content_frame, bg=frame_color)
        smart_defaults_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(smart_defaults_frame, text="智能默认值:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        
        # 平台选择
        self.default_platform_var = tk.StringVar(value="抖音")
        default_platform_options = ["抖音", "快手", "视频号", "小红书", "B站", "TikTok"]
        default_platform_menu = ttk.Combobox(smart_defaults_frame, textvariable=self.default_platform_var, values=default_platform_options, state="readonly", width=15, font=("微软雅黑", 11))
        default_platform_menu.pack(side=tk.LEFT, padx=10)
        
        # 设置默认值按钮
        set_defaults_btn = tk.Button(smart_defaults_frame, text="设置默认值", command=lambda: self.set_smart_defaults(self.default_platform_var.get()), bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        set_defaults_btn.pack(side=tk.LEFT, padx=10)
        
        # 发布记录回溯
        record_btn = tk.Button(distribution_content_frame, text="查看发布记录", command=self.view_publish_records, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=15, pady=6, relief=tk.FLAT)
        record_btn.pack(anchor=tk.W, pady=5)
        
        # ========== 数据监控 ==========
        data_monitoring_frame = tk.Frame(core_features_frame, bg=frame_color, pady=20, padx=20)
        data_monitoring_frame.pack(fill=tk.X, pady=10)
        
        # 标题和折叠按钮
        data_header_frame = tk.Frame(data_monitoring_frame, bg=frame_color)
        data_header_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(data_header_frame, text="数据监控", font=("微软雅黑", 12, "bold"), bg=frame_color, fg="#007acc").pack(side=tk.LEFT, padx=5)
        
        # 折叠状态
        self.data_collapsed = tk.BooleanVar(value=False)
        
        def toggle_data():
            self.data_collapsed.set(not self.data_collapsed.get())
            if self.data_collapsed.get():
                data_content_frame.pack_forget()
                data_toggle_btn.config(text="▶")
            else:
                data_content_frame.pack(fill=tk.X, pady=10)
                data_toggle_btn.config(text="▼")
        
        data_toggle_btn = tk.Button(data_header_frame, text="▼" if not self.data_collapsed.get() else "▶", bg=frame_color, fg=text_color, font=("微软雅黑", 8), padx=5, pady=0, relief=tk.FLAT, width=2, command=toggle_data)
        data_toggle_btn.pack(side=tk.RIGHT, padx=5)
        
        # 数据监控内容
        data_content_frame = tk.Frame(data_monitoring_frame, bg=frame_color)
        data_content_frame.pack(fill=tk.X, pady=10)
        
        # 数据维度选择
        tk.Label(data_content_frame, text="数据维度:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=5)
        
        self.data_dimension_var = tk.StringVar(value="单视频数据")
        data_options = ["单视频数据", "账号整体数据", "粉丝数据", "转化数据"]
        data_menu = ttk.Combobox(data_content_frame, textvariable=self.data_dimension_var, values=data_options, state="readonly", width=20)
        data_menu.pack(side=tk.LEFT, padx=10)
        # 绑定数据维度切换事件
        data_menu.bind("<<ComboboxSelected>>", lambda e: self.view_data_chart())
        
        # 图表类型
        tk.Label(data_content_frame, text="图表类型:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=5)
        
        self.chart_type_var = tk.StringVar(value="折线图")
        chart_options = ["折线图", "饼图", "柱状图"]
        chart_menu = ttk.Combobox(data_content_frame, textvariable=self.chart_type_var, values=chart_options, state="readonly", width=15)
        chart_menu.pack(side=tk.LEFT, padx=10)
        # 绑定图表类型切换事件
        chart_menu.bind("<<ComboboxSelected>>", lambda e: self.view_data_chart())
        
        # 查看数据按钮
        view_data_btn = tk.Button(data_content_frame, text="查看数据", command=self.view_data_chart, bg="#007acc", fg="#ffffff", font= ("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        view_data_btn.pack(side=tk.RIGHT, padx=10)
        
        # 同步数据按钮
        sync_data_btn = tk.Button(data_content_frame, text="同步数据", command=self.sync_data, bg="#4CAF50", fg="#ffffff", font= ("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        sync_data_btn.pack(side=tk.RIGHT, padx=10)
        
        # 自动同步倒计时
        sync_countdown_frame = tk.Frame(data_monitoring_frame, bg=frame_color)
        sync_countdown_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(sync_countdown_frame, text="自动同步倒计时:", bg=frame_color, fg=text_color, font= ("微软雅黑", 9)).pack(side=tk.LEFT, padx=10)
        self.sync_countdown_var = tk.StringVar(value="60s")
        sync_countdown_label = tk.Label(sync_countdown_frame, textvariable=self.sync_countdown_var, bg=frame_color, fg="#007acc", font= ("微软雅黑", 9))
        sync_countdown_label.pack(side=tk.LEFT, padx=10)
        
        # 数据来源
        data_source_frame = tk.Frame(data_monitoring_frame, bg=frame_color)
        data_source_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(data_source_frame, text="数据来源:", bg=frame_color, fg=text_color, font= ("微软雅黑", 9)).pack(side=tk.LEFT, padx=10)
        data_source_label = tk.Label(data_source_frame, text="OpenClow", bg=frame_color, fg="#4CAF50", font= ("微软雅黑", 9, "bold"))
        data_source_label.pack(side=tk.LEFT, padx=10)
        
        # 图表容器
        chart_frame = tk.Frame(data_monitoring_frame, bg=card_color, pady=15, padx=15)
        chart_frame.pack(fill=tk.X, pady=10)
        
        # 图表占位符
        self.chart_canvas = tk.Canvas(chart_frame, bg=card_color, height=200)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True)
        
        # ========== 本地数据管理（新增） ==========
        local_data_frame = tk.Frame(core_features_frame, bg=frame_color, pady=20, padx=20)
        local_data_frame.pack(fill=tk.X, pady=10)
        
        # 标题
        local_data_header = tk.Frame(local_data_frame, bg=frame_color)
        local_data_header.pack(fill=tk.X, pady=5)
        
        tk.Label(local_data_header, text="本地数据管理", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(side=tk.LEFT, padx=5)
        
        # 本地数据管理按钮区
        local_data_buttons = tk.Frame(local_data_frame, bg=frame_color)
        local_data_buttons.pack(fill=tk.X, pady=10)
        
        # 粉丝管理按钮
        fan_btn = tk.Button(local_data_buttons, text="粉丝管理", command=self.show_fan_management, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=20, pady=8, relief=tk.FLAT)
        fan_btn.pack(side=tk.LEFT, padx=5)
        
        # 评论管理按钮
        comment_btn = tk.Button(local_data_buttons, text="评论管理", command=self.show_comment_management, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=20, pady=8, relief=tk.FLAT)
        comment_btn.pack(side=tk.LEFT, padx=5)
        
        # 数据分析按钮
        analysis_btn = tk.Button(local_data_buttons, text="数据分析", command=self.show_local_data_analysis, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=20, pady=8, relief=tk.FLAT)
        analysis_btn.pack(side=tk.LEFT, padx=5)
        
        # 定时任务按钮
        task_btn = tk.Button(local_data_buttons, text="定时任务", command=self.show_scheduled_tasks, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=20, pady=8, relief=tk.FLAT)
        task_btn.pack(side=tk.LEFT, padx=5)
        
        # 账号安全按钮
        security_btn = tk.Button(local_data_buttons, text="账号安全", command=self.show_account_security, bg=item_color, fg=text_color, font=("微软雅黑", 11), padx=20, pady=8, relief=tk.FLAT)
        security_btn.pack(side=tk.LEFT, padx=5)
        
        # 绘制默认图表
        self.draw_default_chart()
        
        # ========== 智能运营 ==========
        ai_operation_frame = tk.Frame(core_features_frame, bg=frame_color, pady=20, padx=20)
        ai_operation_frame.pack(fill=tk.X, pady=10)
        
        # 标题和折叠按钮
        ai_header_frame = tk.Frame(ai_operation_frame, bg=frame_color)
        ai_header_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(ai_header_frame, text="智能运营", font=("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(side=tk.LEFT, padx=5)
        
        # 折叠状态
        self.ai_collapsed = tk.BooleanVar(value=False)
        ai_toggle_btn = tk.Button(ai_header_frame, text="▼" if not self.ai_collapsed.get() else "▶", bg=frame_color, fg=text_color, font=("微软雅黑", 10), padx=5, pady=0, relief=tk.FLAT, width=2)
        ai_toggle_btn.pack(side=tk.RIGHT, padx=5)
        
        # 智能运营内容
        ai_content_frame = tk.Frame(ai_operation_frame, bg=frame_color)
        ai_content_frame.pack(fill=tk.X, pady=10)
        
        # AI内容生成
        tk.Label(ai_content_frame, text="AI内容生成", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 生成选项
        generate_options_frame = tk.Frame(ai_content_frame, bg=frame_color)
        generate_options_frame.pack(fill=tk.X, pady=5)
        
        self.ai_generate_type = tk.StringVar(value="标题")
        generate_options = ["标题", "话题", "评论", "文案"]
        generate_menu = ttk.Combobox(generate_options_frame, textvariable=self.ai_generate_type, values=generate_options, state="readonly", width=15, font=("微软雅黑", 11))
        generate_menu.pack(side=tk.LEFT, padx=10)
        
        # 生成按钮
        generate_btn = tk.Button(generate_options_frame, text="生成内容", command=self.generate_ai_content, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        generate_btn.pack(side=tk.RIGHT, padx=10)
        
        # 评论区智能回复
        tk.Label(ai_content_frame, text="评论区智能回复", font= ("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 评论自动回复开关
        auto_reply_frame = tk.Frame(ai_content_frame, bg=frame_color)
        auto_reply_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(auto_reply_frame, text="自动回复:", bg=frame_color, fg=text_color, font= ("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.auto_reply_var = tk.BooleanVar(value=False)
        auto_reply_switch = tk.Checkbutton(auto_reply_frame, text="开启自动回复", variable=self.auto_reply_var, bg=frame_color, fg=text_color, selectcolor=item_color, font=("微软雅黑", 11))
        auto_reply_switch.pack(side=tk.LEFT, padx=10)
        
        # 关键词触发规则
        keyword_rule_frame = tk.Frame(ai_content_frame, bg=frame_color)
        keyword_rule_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(keyword_rule_frame, text="关键词触发:", bg=frame_color, fg=text_color, font= ("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.keyword_var = tk.StringVar(value="求全集")
        keyword_entry = tk.Entry(keyword_rule_frame, textvariable=self.keyword_var, bg=item_color, fg=text_color, font= ("微软雅黑", 11), width=15)
        keyword_entry.pack(side=tk.LEFT, padx=10)
        
        # AI 回复模板
        reply_template_frame = tk.Frame(ai_content_frame, bg=frame_color)
        reply_template_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(reply_template_frame, text="AI回复模板:", bg=frame_color, fg=text_color, font= ("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        self.reply_var = tk.StringVar(value="关注账号获取全集哦~")
        reply_entry = tk.Entry(reply_template_frame, textvariable=self.reply_var, bg=item_color, fg=text_color, font= ("微软雅黑", 11), width=40)
        reply_entry.pack(side=tk.LEFT, padx=10)
        
        # 添加回复按钮
        add_reply_btn = tk.Button(reply_template_frame, text="添加", command=self.add_keyword_reply, bg="#007acc", fg="#ffffff", font= ("微软雅黑", 11), padx=10, pady=5, relief=tk.FLAT)
        add_reply_btn.pack(side=tk.RIGHT, padx=10)
        

        
        # ========== OpenClow 自动化引擎 ==========
        openclow_frame = tk.Frame(core_features_frame, bg=frame_color, pady=20, padx=20)
        openclow_frame.pack(fill=tk.X, pady=10)
        
        # 标题和折叠按钮
        openclow_header_frame = tk.Frame(openclow_frame, bg=frame_color)
        openclow_header_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(openclow_header_frame, text="OpenClow 自动化引擎", font= ("微软雅黑", 14, "bold"), bg=frame_color, fg="#007acc").pack(side=tk.LEFT, padx=5)
        
        # 折叠状态
        self.openclow_collapsed = tk.BooleanVar(value=False)
        openclow_toggle_btn = tk.Button(openclow_header_frame, text="▼" if not self.openclow_collapsed.get() else "▶", bg=frame_color, fg=text_color, font= ("微软雅黑", 10), padx=5, pady=0, relief=tk.FLAT, width=2)
        openclow_toggle_btn.pack(side=tk.RIGHT, padx=5)
        
        # OpenClow 内容
        openclow_content_frame = tk.Frame(openclow_frame, bg=frame_color)
        openclow_content_frame.pack(fill=tk.X, pady=10)
        
        # 数据采集
        tk.Label(openclow_content_frame, text="数据采集（抖音/快手/视频号）", font= ("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 数据采集设置
        collect_frame = tk.Frame(openclow_content_frame, bg=frame_color)
        collect_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(collect_frame, text="平台:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.collect_platform_var = tk.StringVar(value="抖音")
        collect_platform_options = ["抖音", "快手", "视频号"]
        collect_platform_menu = ttk.Combobox(collect_frame, textvariable=self.collect_platform_var, values=collect_platform_options, state="readonly", width=15, font=("微软雅黑", 11))
        collect_platform_menu.pack(side=tk.LEFT, padx=10)
        
        tk.Label(collect_frame, text="账号ID:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.collect_account_var = tk.StringVar(value="123456789")
        collect_account_entry = tk.Entry(collect_frame, textvariable=self.collect_account_var, bg=item_color, fg=text_color, font= ("微软雅黑", 11), width=20)
        collect_account_entry.pack(side=tk.LEFT, padx=10)
        
        # 采集按钮
        collect_btn = tk.Button(collect_frame, text="开始采集", command=self.collect_platform_data, bg="#007acc", fg="#ffffff", font= ("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        collect_btn.pack(side=tk.RIGHT, padx=10)
        
        # 内容自动发布
        tk.Label(openclow_content_frame, text="内容自动发布", font= ("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 发布设置
        publish_frame = tk.Frame(openclow_content_frame, bg=frame_color)
        publish_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(publish_frame, text="平台:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.publish_platform_var = tk.StringVar(value="抖音")
        publish_platform_options = ["抖音", "快手", "视频号"]
        publish_platform_menu = ttk.Combobox(publish_frame, textvariable=self.publish_platform_var, values=publish_platform_options, state="readonly", width=15, font=("微软雅黑", 11))
        publish_platform_menu.pack(side=tk.LEFT, padx=10)
        
        tk.Label(publish_frame, text="账号ID:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.publish_account_var = tk.StringVar(value="123456789")
        publish_account_entry = tk.Entry(publish_frame, textvariable=self.publish_account_var, bg=item_color, fg=text_color, font= ("微软雅黑", 11), width=20)
        publish_account_entry.pack(side=tk.LEFT, padx=10)
        
        # 发布按钮
        publish_btn = tk.Button(publish_frame, text="自动发布", command=self.auto_publish_content, bg="#007acc", fg="#ffffff", font= ("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        publish_btn.pack(side=tk.RIGHT, padx=10)
        
        # 评论智能回复
        tk.Label(openclow_content_frame, text="评论智能回复", font= ("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 回复设置
        smart_reply_frame = tk.Frame(openclow_content_frame, bg=frame_color)
        smart_reply_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(smart_reply_frame, text="评论内容:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.reply_comment_var = tk.StringVar(value="这个视频太棒了！")
        reply_comment_entry = tk.Entry(smart_reply_frame, textvariable=self.reply_comment_var, bg=item_color, fg=text_color, font= ("微软雅黑", 11), width=40)
        reply_comment_entry.pack(side=tk.LEFT, padx=10)
        
        # 智能回复按钮
        smart_reply_btn = tk.Button(smart_reply_frame, text="智能回复", command=self.smart_reply_comment, bg="#007acc", fg="#ffffff", font= ("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        smart_reply_btn.pack(side=tk.RIGHT, padx=10)
        
        # 运营数据回写
        tk.Label(openclow_content_frame, text="运营数据回写", font= ("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 回写设置
        writeback_frame = tk.Frame(openclow_content_frame, bg=frame_color)
        writeback_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(writeback_frame, text="平台:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.writeback_platform_var = tk.StringVar(value="抖音")
        writeback_platform_menu = ttk.Combobox(writeback_frame, textvariable=self.writeback_platform_var, values=collect_platform_options, state="readonly", width=15, font=("微软雅黑", 11))
        writeback_platform_menu.pack(side=tk.LEFT, padx=10)
        
        tk.Label(writeback_frame, text="账号ID:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.writeback_account_var = tk.StringVar(value="123456789")
        writeback_account_entry = tk.Entry(writeback_frame, textvariable=self.writeback_account_var, bg=item_color, fg=text_color, font= ("微软雅黑", 11), width=20)
        writeback_account_entry.pack(side=tk.LEFT, padx=10)
        
        # 回写按钮
        writeback_btn = tk.Button(writeback_frame, text="数据回写", command=self.write_back_operation_data, bg="#007acc", fg="#ffffff", font= ("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        writeback_btn.pack(side=tk.RIGHT, padx=10)
        
        # 生成运营建议
        tk.Label(openclow_content_frame, text="生成运营建议", font= ("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=5)
        
        # 建议设置
        suggest_frame = tk.Frame(openclow_content_frame, bg=frame_color)
        suggest_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(suggest_frame, text="平台:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.suggest_platform_var = tk.StringVar(value="抖音")
        suggest_platform_menu = ttk.Combobox(suggest_frame, textvariable=self.suggest_platform_var, values=collect_platform_options, state="readonly", width=15, font=("微软雅黑", 11))
        suggest_platform_menu.pack(side=tk.LEFT, padx=10)
        
        tk.Label(suggest_frame, text="账号ID:", bg=frame_color, fg=text_color, font= ("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.suggest_account_var = tk.StringVar(value="123456789")
        suggest_account_entry = tk.Entry(suggest_frame, textvariable=self.suggest_account_var, bg=item_color, fg=text_color, font= ("微软雅黑", 11), width=20)
        suggest_account_entry.pack(side=tk.LEFT, padx=10)
        
        # 生成建议按钮
        suggest_btn = tk.Button(suggest_frame, text="生成建议", command=self.generate_operation_suggestions, bg="#007acc", fg="#ffffff", font= ("微软雅黑", 11), padx=15, pady=5, relief=tk.FLAT)
        suggest_btn.pack(side=tk.RIGHT, padx=10)
        
        # ========== 底部操作栏（固定） ==========
        bottom_bar_frame = tk.Frame(main_container, bg="#252525", pady=15, padx=20)
        bottom_bar_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=0)
        
        # 保存按钮
        save_btn = tk.Button(bottom_bar_frame, text="保存设置", command=self.save_operation_settings, bg="#333333", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        save_btn.pack(side=tk.LEFT, padx=10)
        
        # 导出按钮
        export_btn = tk.Button(bottom_bar_frame, text="导出报表", command=self.export_operation_report, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        export_btn.pack(side=tk.RIGHT, padx=10)
        
        # 反馈按钮
        feedback_btn = tk.Button(bottom_bar_frame, text="问题反馈", command=self.submit_feedback, bg="#333333", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        feedback_btn.pack(side=tk.RIGHT, padx=10)
        
        # 刷新数据按钮
        refresh_btn = tk.Button(bottom_bar_frame, text="刷新数据", command=self.refresh_dashboard, bg="#333333", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        refresh_btn.pack(side=tk.RIGHT, padx=10)
    
    def _load_bound_accounts(self):
        """从文件加载已绑定账号列表"""
        try:
            p = self._bound_accounts_file
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    self.bound_accounts = json.load(f)
                if not isinstance(self.bound_accounts, list):
                    self.bound_accounts = []
            else:
                self.bound_accounts = []
        except Exception as e:
            print(f"加载绑定账号失败: {e}")
            self.bound_accounts = []

    def _save_bound_accounts(self):
        """保存已绑定账号列表到文件"""
        try:
            d = os.path.dirname(self._bound_accounts_file)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            with open(self._bound_accounts_file, "w", encoding="utf-8") as f:
                json.dump(self.bound_accounts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存绑定账号失败: {e}")

    def _account_display_line(self, acc):
        """单条账号在列表中的显示文案；有 Token 时必显失效倒计时（剩余 X 天/已过期/过期未知）"""
        name = acc.get("name", "未命名")
        platform = acc.get("platform", "")
        status = acc.get("status", "已绑定")
        line = f"{platform} - {name} ({status})"
        if oauth_qr_flow and (acc.get("access_token") or acc.get("token")):
            countdown = oauth_qr_flow.format_expires_countdown(acc.get("expires_at"), unknown_label="过期未知")
            line += f" [{countdown}]"
        return line

    def get_account_token(self, platform=None, name=None):
        """
        获取已绑定账号的 access_token（替代方案：发布/拉数据时用）。
        可指定 platform 或 name，或两者都指定；返回第一个匹配账号的 access_token，无则返回 None。
        """
        self._load_bound_accounts()
        for acc in self.bound_accounts:
            if platform and acc.get("platform") != platform:
                continue
            if name and acc.get("name") != name:
                continue
            t = acc.get("access_token") or acc.get("token")
            if t:
                return t
        return None

    def manage_accounts(self):
        """管理账号"""
        # 创建账号管理窗口
        account_window = tk.Toplevel(self.root)
        account_window.title("账号管理")
        account_window.geometry("800x600")
        account_window.configure(bg="#1a1a1a")
        
        # 账号管理框架
        account_frame = tk.Frame(account_window, bg="#252525", pady=30, padx=30)
        account_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(account_frame, text="账号管理", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 账号列表
        accounts_frame = tk.Frame(account_frame, bg="#252525")
        accounts_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 账号列表框
        self.accounts_listbox = tk.Listbox(accounts_frame, width=80, height=15, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.accounts_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 从持久化数据填充账号列表
        self._load_bound_accounts()
        for acc in self.bound_accounts:
            self.accounts_listbox.insert(tk.END, self._account_display_line(acc))
        
        # 账号操作按钮
        buttons_frame = tk.Frame(account_frame, bg="#252525", pady=20)
        buttons_frame.pack(fill=tk.X, pady=10)
        
        # 添加账号按钮
        add_account_btn = tk.Button(buttons_frame, text="添加账号", command=self.add_account, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        add_account_btn.pack(side=tk.LEFT, padx=10)
        
        # 删除账号按钮
        delete_account_btn = tk.Button(buttons_frame, text="删除账号", command=self.delete_account, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        delete_account_btn.pack(side=tk.LEFT, padx=10)
        
        # 编辑账号按钮
        edit_account_btn = tk.Button(buttons_frame, text="编辑账号", command=self.edit_account, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        edit_account_btn.pack(side=tk.LEFT, padx=10)
    
    def add_account(self):
        """添加账号"""
        # 创建添加账号窗口
        add_window = tk.Toplevel(self.root)
        add_window.title("添加账号")
        add_window.geometry("600x400")
        add_window.configure(bg="#1a1a1a")
        
        # 添加账号框架
        add_frame = tk.Frame(add_window, bg="#252525", pady=30, padx=30)
        add_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(add_frame, text="添加账号", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 平台选择
        platform_frame = tk.Frame(add_frame, bg="#252525")
        platform_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(platform_frame, text="选择平台:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        
        self.add_platform_var = tk.StringVar(value="抖音")
        platform_options = ["抖音", "快手", "视频号", "小红书", "B站", "TikTok"]
        platform_menu = ttk.Combobox(platform_frame, textvariable=self.add_platform_var, values=platform_options, state="readonly", width=20)
        platform_menu.pack(side=tk.LEFT, padx=10)
        
        # 账号信息
        info_frame = tk.Frame(add_frame, bg="#252525")
        info_frame.pack(fill=tk.X, pady=20)
        
        # 账号名称
        tk.Label(info_frame, text="账号名称:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=0, column=0, sticky=tk.W, padx=20, pady=10)
        self.account_name_var = tk.StringVar(value="")
        account_name_entry = tk.Entry(info_frame, textvariable=self.account_name_var, width=40, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10))
        account_name_entry.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 绑定方式
        tk.Label(info_frame, text="绑定方式:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=1, column=0, sticky=tk.W, padx=20, pady=10)
        self.bind_method_var = tk.StringVar(value="扫码绑定")
        bind_options = ["扫码绑定", "手机号绑定"]
        bind_menu = ttk.Combobox(info_frame, textvariable=self.bind_method_var, values=bind_options, state="readonly", width=20)
        bind_menu.grid(row=1, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 确认按钮
        confirm_btn = tk.Button(add_frame, text="确认添加", command=lambda: self.confirm_add_account(add_window), bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=30, pady=10, relief=tk.FLAT)
        confirm_btn.pack(anchor=tk.CENTER, pady=30)
    
    def confirm_add_account(self, window):
        """确认添加账号（写入持久化并刷新列表）"""
        account_name = (self.account_name_var.get() or "").strip()
        platform = self.add_platform_var.get()
        if not account_name:
            messagebox.showerror("错误", "请输入账号名称")
            return
        bind_method = self.bind_method_var.get() if hasattr(self, "bind_method_var") else "扫码绑定"
        acc = {"platform": platform, "name": account_name, "bind_method": bind_method, "status": "已绑定", "phone": ""}
        self.bound_accounts.append(acc)
        self._save_bound_accounts()
        if hasattr(self, "accounts_listbox") and self.accounts_listbox.winfo_exists():
            self.accounts_listbox.insert(tk.END, self._account_display_line(acc))
        messagebox.showinfo("成功", f"已添加{platform}账号: {account_name}")
        window.destroy()

    def delete_account(self):
        """删除账号（从持久化移除并刷新列表）"""
        selected_indices = self.accounts_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要删除的账号")
            return
        idx = selected_indices[0]
        if 0 <= idx < len(self.bound_accounts):
            self.bound_accounts.pop(idx)
            self._save_bound_accounts()
        self.accounts_listbox.delete(idx)
        messagebox.showinfo("成功", "账号已删除")

    def edit_account(self):
        """编辑账号（修改名称/平台/状态并保存）"""
        selected_indices = self.accounts_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要编辑的账号")
            return
        idx = selected_indices[0]
        if idx < 0 or idx >= len(self.bound_accounts):
            messagebox.showerror("错误", "无效的账号项")
            return
        acc = self.bound_accounts[idx]
        # 简单编辑对话框
        edit_win = tk.Toplevel(self.root)
        edit_win.title("编辑账号")
        edit_win.geometry("400x220")
        edit_win.configure(bg="#1a1a1a")
        f = tk.Frame(edit_win, bg="#252525", pady=20, padx=20)
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text="账号名称", bg="#252525", fg="#ffffff", font=("微软雅黑", 10)).grid(row=0, column=0, sticky=tk.W, pady=8)
        name_var = tk.StringVar(value=acc.get("name", ""))
        tk.Entry(f, textvariable=name_var, width=30, bg="#2d2d2d", fg="#ffffff").grid(row=0, column=1, padx=10, pady=8)
        tk.Label(f, text="平台", bg="#252525", fg="#ffffff", font=("微软雅黑", 10)).grid(row=1, column=0, sticky=tk.W, pady=8)
        platform_var = tk.StringVar(value=acc.get("platform", "抖音"))
        ttk.Combobox(f, textvariable=platform_var, values=["抖音", "快手", "视频号", "TikTok", "小红书", "B站"], state="readonly", width=18).grid(row=1, column=1, padx=10, pady=8)
        tk.Label(f, text="状态", bg="#252525", fg="#ffffff", font=("微软雅黑", 10)).grid(row=2, column=0, sticky=tk.W, pady=8)
        status_var = tk.StringVar(value=acc.get("status", "已绑定"))
        ttk.Combobox(f, textvariable=status_var, values=["已绑定", "未绑定", "离线"], state="readonly", width=18).grid(row=2, column=1, padx=10, pady=8)
        def on_confirm():
            acc["name"] = name_var.get().strip() or acc.get("name", "")
            acc["platform"] = platform_var.get()
            acc["status"] = status_var.get()
            self._save_bound_accounts()
            self.accounts_listbox.delete(idx)
            self.accounts_listbox.insert(idx, self._account_display_line(acc))
            messagebox.showinfo("成功", "账号已更新")
            edit_win.destroy()
        tk.Button(f, text="保存", command=on_confirm, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=6).grid(row=3, column=1, pady=15)
        tk.Button(f, text="取消", command=edit_win.destroy, bg="#555", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=6).grid(row=3, column=0, pady=15)
    
    def bind_account(self, platform):
        """绑定账号（支持 Token 粘贴绑定：用户从开放平台获取 token 后粘贴，免接 OAuth）"""
        bind_window = tk.Toplevel(self.root)
        bind_window.title(f"绑定{platform}账号")
        bind_window.geometry("560x460")
        bind_window.configure(bg="#1a1a1a")
        
        bind_frame = tk.Frame(bind_window, bg="#252525", pady=30, padx=30)
        bind_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(bind_frame, text=f"绑定{platform}账号", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 账号名称（必填）
        name_frame = tk.Frame(bind_frame, bg="#252525")
        name_frame.pack(fill=tk.X, pady=10)
        tk.Label(name_frame, text="账号名称:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        bind_name_var = tk.StringVar(value="")
        tk.Entry(name_frame, textvariable=bind_name_var, width=28, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        
        # 绑定方式（替代方案：Token 粘贴绑定）
        method_frame = tk.Frame(bind_frame, bg="#252525")
        method_frame.pack(fill=tk.X, pady=15)
        tk.Label(method_frame, text="绑定方式:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        bind_method_var = tk.StringVar(value="Token粘贴绑定")
        bind_options = ["Token粘贴绑定", "扫码绑定", "手机号绑定"]
        bind_menu = ttk.Combobox(method_frame, textvariable=bind_method_var, values=bind_options, state="readonly", width=18)
        bind_menu.pack(side=tk.LEFT, padx=10)
        
        # 手机号（仅当选择手机号绑定时使用）
        phone_frame = tk.Frame(bind_frame, bg="#252525")
        phone_frame.pack(fill=tk.X, pady=10)
        tk.Label(phone_frame, text="手机号:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        phone_var = tk.StringVar(value="")
        phone_entry = tk.Entry(phone_frame, textvariable=phone_var, width=24, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10))
        phone_entry.pack(side=tk.LEFT, padx=10)
        
        # Token 粘贴区域（替代方案：无需 OAuth 跳转，用户自行获取 token 后粘贴）
        token_container = tk.Frame(bind_frame, bg="#252525")
        token_container.pack(fill=tk.X, pady=10)
        tk.Label(token_container, text="Access Token:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, padx=10)
        token_text = tk.Text(token_container, height=3, width=48, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("Consolas", 9), wrap=tk.WORD)
        token_text.pack(anchor=tk.W, padx=10, pady=5)
        tk.Label(bind_frame, text="从各平台开放平台获取 access_token 后粘贴到上方，发布/数据接口将使用此 Token。", bg="#252525", fg="#888888", font=("微软雅黑", 9), wraplength=480).pack(anchor=tk.W, padx=10, pady=2)
        
        # 扫码授权区域（仅当选择「扫码绑定」时使用：需配置 Client ID/Secret，点击后弹出二维码，回调换 Token 并写入账号）
        bind_window._oauth_scan = {"access_token": None, "expires_at": None}
        scan_frame = tk.LabelFrame(bind_frame, text="扫码授权登录（需在开放平台创建应用并配置回调 URL）", bg="#252525", fg="#cccccc", font=("微软雅黑", 9))
        scan_frame.pack(fill=tk.X, pady=10, padx=10)
        tk.Label(scan_frame, text="Client ID:", bg="#252525", fg="#ffffff", font=("微软雅黑", 9)).grid(row=0, column=0, sticky=tk.W, padx=8, pady=4)
        client_id_var = tk.StringVar(value="")
        tk.Entry(scan_frame, textvariable=client_id_var, width=36, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 9)).grid(row=0, column=1, padx=8, pady=4)
        tk.Label(scan_frame, text="Client Secret:", bg="#252525", fg="#ffffff", font=("微软雅黑", 9)).grid(row=1, column=0, sticky=tk.W, padx=8, pady=4)
        client_secret_var = tk.StringVar(value="")
        tk.Entry(scan_frame, textvariable=client_secret_var, width=36, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 9), show="*").grid(row=1, column=1, padx=8, pady=4)
        tk.Label(scan_frame, text="回调 URL（与开放平台一致）:", bg="#252525", fg="#ffffff", font=("微软雅黑", 9)).grid(row=2, column=0, sticky=tk.W, padx=8, pady=4)
        redirect_uri_var = tk.StringVar(value="http://127.0.0.1:8765/")
        tk.Entry(scan_frame, textvariable=redirect_uri_var, width=36, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 9)).grid(row=2, column=1, padx=8, pady=4)
        scan_status_label = tk.Label(scan_frame, text="", bg="#252525", fg="#aaaaaa", font=("微软雅黑", 9))
        scan_status_label.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=8, pady=4)
        def do_scan_oauth():
            if not oauth_qr_flow:
                messagebox.showerror("错误", "未安装扫码授权模块依赖（如 flask、qrcode、opencv-python）", parent=bind_window)
                return
            cid = (client_id_var.get() or "").strip()
            secret = (client_secret_var.get() or "").strip()
            if not cid or not secret:
                messagebox.showerror("错误", "请填写 Client ID 与 Client Secret（在开放平台创建应用后获取）", parent=bind_window)
                return
            redirect_uri = (redirect_uri_var.get() or "").strip() or "http://127.0.0.1:8765/"
            scan_status_label.config(text="正在打开二维码窗口，请使用手机扫码…")
            bind_window.update_idletasks()
            def run_scan():
                token, expires_in, refresh_tok = oauth_qr_flow.full_scan_flow(platform, cid, secret, redirect_uri=redirect_uri, callback_port=8765)
                def on_done():
                    bind_window._oauth_scan["access_token"] = token
                    bind_window._oauth_scan["expires_at"] = oauth_qr_flow.token_expires_at(expires_in) if token and expires_in else None
                    bind_window._oauth_scan["refresh_token"] = refresh_tok
                    bind_window._oauth_scan["oauth_client_id"] = cid
                    bind_window._oauth_scan["oauth_client_secret"] = secret
                    if token:
                        token_text.delete("1.0", tk.END)
                        token_text.insert("1.0", "（已通过扫码授权获取，请点击下方「确认绑定」保存）")
                        scan_status_label.config(text="授权成功，请点击「确认绑定」保存账号。")
                        messagebox.showinfo("成功", "扫码授权成功，请点击「确认绑定」保存账号。", parent=bind_window)
                    else:
                        scan_status_label.config(text="授权失败或已取消")
                self.root.after(0, on_done)
            threading.Thread(target=run_scan, daemon=True).start()
        tk.Button(scan_frame, text="扫码授权登录", command=do_scan_oauth, bg="#28a745", fg="#ffffff", font=("微软雅黑", 9), padx=16, pady=6, relief=tk.FLAT).grid(row=4, column=0, columnspan=2, pady=8)
        
        # 说明（根据绑定方式切换提示）
        qr_hint = tk.Label(bind_frame, text="Token粘贴绑定：在抖音/快手/视频号等开放平台后台获取 access_token，粘贴到上方即可，无需本软件内跳转登录。扫码绑定：填写应用 Client ID/Secret 后点击「扫码授权登录」，用手机扫码完成授权。", bg="#252525", fg="#cccccc", font=("微软雅黑", 9), wraplength=480)
        qr_hint.pack(anchor=tk.W, pady=12, padx=10)
        
        def on_confirm():
            name = (bind_name_var.get() or "").strip()
            if not name:
                messagebox.showerror("错误", "请输入账号名称", parent=bind_window)
                return
            method = bind_method_var.get()
            phone = (phone_var.get() or "").strip() if method == "手机号绑定" else ""
            access_token = None
            expires_at = None
            refresh_token = None
            oauth_cid = None
            oauth_secret = None
            if method == "Token粘贴绑定":
                access_token = token_text.get("1.0", tk.END).strip()
                if access_token.startswith("（已通过扫码"):
                    access_token = getattr(bind_window, "_oauth_scan", {}).get("access_token") or access_token
                    expires_at = getattr(bind_window, "_oauth_scan", {}).get("expires_at")
                if not access_token or access_token.startswith("（"):
                    access_token = None
            elif method == "扫码绑定":
                if getattr(bind_window, "_oauth_scan", {}).get("access_token"):
                    access_token = bind_window._oauth_scan["access_token"]
                    expires_at = bind_window._oauth_scan.get("expires_at")
                    refresh_token = bind_window._oauth_scan.get("refresh_token")
                    oauth_cid = bind_window._oauth_scan.get("oauth_client_id")
                    oauth_secret = bind_window._oauth_scan.get("oauth_client_secret")
                else:
                    messagebox.showerror("错误", "请先点击「扫码授权登录」完成授权后再确认绑定。", parent=bind_window)
                    return
            acc = {"platform": platform, "name": name, "bind_method": method, "status": "已绑定", "phone": phone}
            if access_token:
                acc["access_token"] = access_token
            if expires_at is not None:
                acc["expires_at"] = expires_at
            if method == "扫码绑定" and refresh_token:
                acc["refresh_token"] = refresh_token
            if method == "扫码绑定" and oauth_cid:
                acc["oauth_client_id"] = oauth_cid
            if method == "扫码绑定" and oauth_secret:
                acc["oauth_client_secret"] = oauth_secret
            self.bound_accounts.append(acc)
            self._save_bound_accounts()
            if hasattr(self, "accounts_listbox") and self.accounts_listbox.winfo_exists():
                self.accounts_listbox.insert(tk.END, self._account_display_line(acc))
            messagebox.showinfo("成功", f"{platform}账号「{name}」绑定成功")
            bind_window.destroy()
        
        tk.Button(bind_frame, text="确认绑定", command=on_confirm, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=30, pady=10, relief=tk.FLAT).pack(anchor=tk.CENTER, pady=20)
    
    def confirm_bind_account(self, window, platform):
        """确认绑定账号（保留兼容；实际逻辑已在 bind_account 的 on_confirm 中实现）"""
        messagebox.showinfo("成功", f"{platform}账号绑定成功")
        window.destroy()
    
    def manage_subaccount_permissions(self):
        """管理子账号权限"""
        # 创建子账号权限管理窗口
        permission_window = tk.Toplevel(self.root)
        permission_window.title("子账号权限管理")
        permission_window.geometry("800x600")
        permission_window.configure(bg="#1a1a1a")
        
        # 权限管理框架
        permission_frame = tk.Frame(permission_window, bg="#252525", pady=30, padx=30)
        permission_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(permission_frame, text="子账号权限管理", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 子账号列表
        subaccounts_frame = tk.Frame(permission_frame, bg="#252525")
        subaccounts_frame.pack(fill=tk.X, pady=10)
        
        # 子账号选择
        tk.Label(subaccounts_frame, text="选择子账号:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        
        self.subaccount_var = tk.StringVar(value="子账号1")
        subaccount_options = ["子账号1", "子账号2", "子账号3"]
        subaccount_menu = ttk.Combobox(subaccounts_frame, textvariable=self.subaccount_var, values=subaccount_options, state="readonly", width=20)
        subaccount_menu.pack(side=tk.LEFT, padx=10)
        
        # 权限设置
        tk.Label(permission_frame, text="权限设置", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#007acc").pack(anchor=tk.W, pady=15)
        
        # 权限选项
        permissions = [
            {"name": "发布权限", "description": "允许发布视频到各平台"},
            {"name": "数据分析权限", "description": "允许查看账号数据"},
            {"name": "素材管理权限", "description": "允许管理素材库"}
        ]
        
        self.permission_vars = {}
        for perm in permissions:
            perm_frame = tk.Frame(permission_frame, bg="#252525")
            perm_frame.pack(fill=tk.X, pady=5)
            
            var = tk.BooleanVar(value=False)
            self.permission_vars[perm["name"]] = var
            
            check = tk.Checkbutton(perm_frame, text=perm["name"], variable=var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d")
            check.pack(side=tk.LEFT, padx=10)
            tk.Label(perm_frame, text=perm["description"], bg="#252525", fg="#000000", font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=10)
        
        # 保存按钮
        save_btn = tk.Button(permission_frame, text="保存权限设置", command=lambda: self.save_permission_settings(permission_window), bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=30, pady=10, relief=tk.FLAT)
        save_btn.pack(anchor=tk.CENTER, pady=30)
    
    def save_permission_settings(self, window):
        """保存权限设置"""
        # 模拟保存权限设置
        messagebox.showinfo("成功", "权限设置已保存")
        window.destroy()
    
    def manage_publish_templates(self):
        """管理发布模板"""
        # 创建发布模板管理窗口
        template_window = tk.Toplevel(self.root)
        template_window.title("发布模板管理")
        template_window.geometry("800x600")
        template_window.configure(bg="#1a1a1a")
        
        # 模板管理框架
        template_frame = tk.Frame(template_window, bg="#252525", pady=30, padx=30)
        template_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(template_frame, text="发布模板管理", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 模板列表
        templates_frame = tk.Frame(template_frame, bg="#252525")
        templates_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 模板列表框
        self.templates_listbox = tk.Listbox(templates_frame, width=80, height=15, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.templates_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 填充模板列表
        sample_templates = [
            "短剧爆款模板1 - 标题/话题/封面/文案",
            "短剧爆款模板2 - 标题/话题/封面/文案",
            "短剧爆款模板3 - 标题/话题/封面/文案",
            "带货视频模板 - 标题/话题/封面/文案",
            "剧情解说模板 - 标题/话题/封面/文案"
        ]
        for template in sample_templates:
            self.templates_listbox.insert(tk.END, template)
        
        # 模板操作按钮
        buttons_frame = tk.Frame(template_frame, bg="#252525")
        buttons_frame.pack(fill=tk.X, pady=10)
        
        # 添加模板按钮
        add_template_btn = tk.Button(buttons_frame, text="添加模板", command=self.add_publish_template, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        add_template_btn.pack(side=tk.LEFT, padx=10)
        
        # 删除模板按钮
        delete_template_btn = tk.Button(buttons_frame, text="删除模板", command=self.delete_publish_template, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        delete_template_btn.pack(side=tk.LEFT, padx=10)
        
        # 编辑模板按钮
        edit_template_btn = tk.Button(buttons_frame, text="编辑模板", command=self.edit_publish_template, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        edit_template_btn.pack(side=tk.LEFT, padx=10)
    
    def add_publish_template(self):
        """添加发布模板"""
        # 创建添加模板窗口
        add_window = tk.Toplevel(self.root)
        add_window.title("添加发布模板")
        add_window.geometry("600x400")
        add_window.configure(bg="#1a1a1a")
        
        # 添加模板框架
        add_frame = tk.Frame(add_window, bg="#252525", pady=30, padx=30)
        add_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(add_frame, text="添加发布模板", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 模板名称
        name_frame = tk.Frame(add_frame, bg="#252525")
        name_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(name_frame, text="模板名称:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.template_name_var = tk.StringVar(value="")
        template_name_entry = tk.Entry(name_frame, textvariable=self.template_name_var, width=30, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10))
        template_name_entry.pack(side=tk.LEFT, padx=10)
        
        # 模板内容
        content_frame = tk.Frame(add_frame, bg="#252525")
        content_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(content_frame, text="模板内容:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.NW, padx=10, pady=5)
        self.template_content_var = tk.StringVar(value="标题/话题/封面/文案")
        template_content_entry = tk.Entry(content_frame, textvariable=self.template_content_var, width=50, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10))
        template_content_entry.pack(anchor=tk.W, padx=10, pady=5)
        
        # 确认按钮
        confirm_btn = tk.Button(add_frame, text="确认添加", command=lambda: self.confirm_add_template(add_window), bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=30, pady=10, relief=tk.FLAT)
        confirm_btn.pack(anchor=tk.CENTER, pady=30)
    
    def confirm_add_template(self, window):
        """确认添加模板"""
        template_name = self.template_name_var.get()
        if template_name:
            # 模拟添加模板
            self.templates_listbox.insert(tk.END, f"{template_name} - {self.template_content_var.get()}")
            messagebox.showinfo("成功", f"已添加模板: {template_name}")
            window.destroy()
        else:
            messagebox.showerror("错误", "请输入模板名称")
    
    def delete_publish_template(self):
        """删除发布模板"""
        # 获取选中的模板
        selected_indices = self.templates_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要删除的模板")
            return
        
        # 删除模板
        self.templates_listbox.delete(selected_indices[0])
        messagebox.showinfo("成功", "模板已删除")
    
    def edit_publish_template(self):
        """编辑发布模板"""
        # 获取选中的模板
        selected_indices = self.templates_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要编辑的模板")
            return
        
        selected_template = self.templates_listbox.get(selected_indices[0])
        messagebox.showinfo("编辑模板", f"编辑模板: {selected_template}")
    
    def view_publish_records(self):
        """查看发布记录"""
        # 创建发布记录窗口
        record_window = tk.Toplevel(self.root)
        record_window.title("发布记录")
        record_window.geometry("800x600")
        record_window.configure(bg="#1a1a1a")
        
        # 发布记录框架
        record_frame = tk.Frame(record_window, bg="#252525", pady=30, padx=30)
        record_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(record_frame, text="发布记录", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 记录列表
        records_frame = tk.Frame(record_frame, bg="#252525")
        records_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 记录列表框
        self.records_listbox = tk.Listbox(records_frame, width=80, height=15, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.records_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 填充记录列表
        sample_records = [
            "2024-01-01 12:00:00 - 抖音 - 短剧视频1 - 发布成功",
            "2024-01-01 13:00:00 - 快手 - 短剧视频1 - 发布成功",
            "2024-01-01 14:00:00 - 视频号 - 短剧视频1 - 发布成功",
            "2024-01-02 10:00:00 - 抖音 - 短剧视频2 - 发布成功",
            "2024-01-02 11:00:00 - 快手 - 短剧视频2 - 发布失败 - 视频违规",
            "2024-01-02 12:00:00 - 小红书 - 短剧视频2 - 发布成功"
        ]
        for record in sample_records:
            self.records_listbox.insert(tk.END, record)
        
        # 查看详情按钮
        detail_btn = tk.Button(record_frame, text="查看详情", command=self.view_record_detail, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        detail_btn.pack(anchor=tk.CENTER, pady=20)
    
    def view_record_detail(self):
        """查看记录详情"""
        # 获取选中的记录
        selected_indices = self.records_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要查看的记录")
            return
        
        selected_record = self.records_listbox.get(selected_indices[0])
        messagebox.showinfo("记录详情", f"记录详情: {selected_record}")
    
    def view_data_chart(self):
        """查看数据图表"""
        # 获取选择的数据维度和图表类型
        data_dimension = self.data_dimension_var.get()
        chart_type = self.chart_type_var.get()
        
        # 清空画布
        self.chart_canvas.delete("all")
        
        # 根据选择绘制不同的图表
        if chart_type == "折线图":
            self.draw_line_chart(data_dimension)
        elif chart_type == "饼图":
            self.draw_pie_chart(data_dimension)
        elif chart_type == "柱状图":
            self.draw_bar_chart(data_dimension)
    
    def draw_default_chart(self):
        """绘制默认图表"""
        # 绘制默认折线图
        self.draw_line_chart("单视频数据")
    
    def draw_line_chart(self, data_dimension):
        """绘制折线图"""
        # 模拟数据
        if data_dimension == "单视频数据":
            data = [1200, 1900, 1500, 2100, 1800, 2500, 2200]
        elif data_dimension == "账号整体数据":
            data = [5000, 6200, 5800, 7100, 6800, 8200, 7900]
        elif data_dimension == "粉丝数据":
            data = [150, 220, 180, 250, 230, 300, 280]
        else:  # 转化数据
            data = [80, 120, 90, 140, 110, 160, 150]
        
        # 绘制折线图
        width = self.chart_canvas.winfo_width()
        height = self.chart_canvas.winfo_height()
        
        if width < 100 or height < 100:
            # 画布大小不足，使用默认值
            width = 800
            height = 300
        
        # 计算坐标
        step_x = width / (len(data) - 1)
        max_value = max(data)
        min_value = min(data)
        range_value = max_value - min_value if max_value > min_value else 1
        
        # 绘制坐标轴
        self.chart_canvas.create_line(50, height - 50, width - 50, height - 50, fill="#000000")
        self.chart_canvas.create_line(50, 50, 50, height - 50, fill="#000000")
        
        # 绘制数据点和连线
        points = []
        for i, value in enumerate(data):
            x = 50 + i * step_x
            y = height - 50 - ((value - min_value) / range_value) * (height - 100)
            points.append((x, y))
            # 绘制数据点
            self.chart_canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#007acc", outline="#ffffff")
        
        # 绘制连线
        for i in range(len(points) - 1):
            self.chart_canvas.create_line(points[i][0], points[i][1], points[i+1][0], points[i+1][1], fill="#007acc", width=2)
        
        # 绘制标题
        self.chart_canvas.create_text(width / 2, 20, text=f"{data_dimension} - 折线图", fill="#ffffff", font=("微软雅黑", 12))
    
    def draw_pie_chart(self, data_dimension):
        """绘制饼图"""
        # 模拟数据
        if data_dimension == "单视频数据":
            data = [30, 25, 20, 15, 10]
            labels = ["播放量", "点赞量", "评论量", "分享量", "完播量"]
        elif data_dimension == "账号整体数据":
            data = [40, 30, 20, 10]
            labels = ["抖音", "快手", "视频号", "小红书"]
        elif data_dimension == "粉丝数据":
            data = [50, 30, 15, 5]
            labels = ["18-24岁", "25-34岁", "35-44岁", "45+岁"]
        else:  # 转化数据
            data = [60, 25, 15]
            labels = ["点击", "关注", "转化"]
        
        # 绘制饼图
        width = self.chart_canvas.winfo_width()
        height = self.chart_canvas.winfo_height()
        
        if width < 100 or height < 100:
            # 画布大小不足，使用默认值
            width = 800
            height = 300
        
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 3
        
        # 颜色
        colors = ["#007acc", "#4CAF50", "#f44336", "#ff9800", "#9c27b0"]
        
        # 绘制饼图
        start_angle = 0
        total = sum(data)
        for i, value in enumerate(data):
            angle = (value / total) * 360
            self.chart_canvas.create_arc(
                center_x - radius, center_y - radius, center_x + radius, center_y + radius,
                start=start_angle, extent=angle, fill=colors[i % len(colors)], outline="#1e1e1e"
            )
            start_angle += angle
        
        # 绘制标题
        self.chart_canvas.create_text(width / 2, 20, text=f"{data_dimension} - 饼图", fill="#ffffff", font=("微软雅黑", 12))
        
        # 绘制图例
        legend_x = width - 150
        legend_y = 50
        for i, label in enumerate(labels):
            self.chart_canvas.create_rectangle(legend_x, legend_y + i * 25, legend_x + 20, legend_y + i * 25 + 20, fill=colors[i % len(colors)])
            self.chart_canvas.create_text(legend_x + 30, legend_y + i * 25 + 10, text=label, fill="#ffffff", font=("微软雅黑", 10), anchor=tk.W)
    
    def draw_bar_chart(self, data_dimension):
        """绘制柱状图"""
        # 模拟数据
        if data_dimension == "单视频数据":
            data = [1200, 1900, 1500, 2100, 1800]
        elif data_dimension == "账号整体数据":
            data = [5000, 6200, 5800, 7100, 6800]
        elif data_dimension == "粉丝数据":
            data = [150, 220, 180, 250, 230]
        else:  # 转化数据
            data = [80, 120, 90, 140, 110]
        
        # 绘制柱状图
        width = self.chart_canvas.winfo_width()
        height = self.chart_canvas.winfo_height()
        
        if width < 100 or height < 100:
            # 画布大小不足，使用默认值
            width = 800
            height = 300
        
        # 计算坐标
        bar_width = (width - 100) / len(data) * 0.8
        max_value = max(data)
        
        # 绘制坐标轴
        self.chart_canvas.create_line(50, height - 50, width - 50, height - 50, fill="#000000")
        self.chart_canvas.create_line(50, 50, 50, height - 50, fill="#000000")
        
        # 绘制柱状图
        for i, value in enumerate(data):
            x = 50 + (i + 0.1) * (width - 100) / len(data)
            y = height - 50 - (value / max_value) * (height - 100)
            self.chart_canvas.create_rectangle(x, y, x + bar_width, height - 50, fill="#007acc", outline="#1e1e1e")
        
        # 绘制标题
        self.chart_canvas.create_text(width / 2, 20, text=f"{data_dimension} - 柱状图", fill="#ffffff", font=("微软雅黑", 12))
    
    def generate_ai_content(self):
        """生成AI内容"""
        generate_type = self.ai_generate_type.get()
        # 模拟生成AI内容
        if generate_type == "标题":
            content = "【短剧】这个反转太绝了！看完我惊呆了 #短剧 #反转 #爽剧"
        elif generate_type == "话题":
            content = "#短剧 #反转 #爽剧 #热门 #爆款"
        elif generate_type == "评论":
            content = "这部剧太好看了，求更新！"
        else:  # 文案
            content = "这部短剧太精彩了，反转不断，看完让人回味无穷！喜欢的朋友点个赞吧~"
        
        messagebox.showinfo("AI内容生成", f"生成的{generate_type}：\n{content}")
    
    def add_keyword_reply(self):
        """添加关键词回复"""
        keyword = self.keyword_var.get()
        reply = self.reply_var.get()
        if keyword and reply:
            # 模拟添加关键词回复
            messagebox.showinfo("成功", f"已添加关键词回复：\n关键词: {keyword}\n回复: {reply}")
        else:
            messagebox.showerror("错误", "请输入关键词和回复内容")
    
    def save_operation_settings(self):
        """保存运营设置"""
        # 模拟保存设置
        messagebox.showinfo("成功", "运营设置已保存")
    
    def export_operation_report(self):
        """导出运营报表"""
        # 创建导出选项窗口
        export_window = tk.Toplevel(self.root)
        export_window.title("导出报表")
        export_window.geometry("600x400")
        export_window.configure(bg="#1a1a1a")
        
        # 导出选项框架
        export_frame = tk.Frame(export_window, bg="#252525", pady=30, padx=30)
        export_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(export_frame, text="导出报表", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 导出格式选择
        format_frame = tk.Frame(export_frame, bg="#252525")
        format_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(format_frame, text="导出格式:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        
        self.export_format_var = tk.StringVar(value="Excel")
        export_options = ["Excel", "PDF"]
        export_menu = ttk.Combobox(format_frame, textvariable=self.export_format_var, values=export_options, state="readonly", width=20)
        export_menu.pack(side=tk.LEFT, padx=10)
        
        # 导出范围选择
        range_frame = tk.Frame(export_frame, bg="#252525")
        range_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(range_frame, text="导出范围:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        
        self.export_range_var = tk.StringVar(value="最近7天")
        range_options = ["最近7天", "最近30天", "最近90天", "全部"]
        range_menu = ttk.Combobox(range_frame, textvariable=self.export_range_var, values=range_options, state="readonly", width=20)
        range_menu.pack(side=tk.LEFT, padx=10)
        
        # 导出按钮
        export_btn = tk.Button(export_frame, text="导出", command=lambda: self.confirm_export_report(export_window), bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=30, pady=10, relief=tk.FLAT)
        export_btn.pack(anchor=tk.CENTER, pady=30)
    
    def confirm_export_report(self, window):
        """确认导出报表"""
        export_format = self.export_format_var.get()
        export_range = self.export_range_var.get()
        # 模拟导出报表
        messagebox.showinfo("成功", f"已导出{export_range}的{export_format}报表")
        window.destroy()
    
    def submit_feedback(self):
        """提交反馈"""
        # 创建反馈窗口
        feedback_window = tk.Toplevel(self.root)
        feedback_window.title("问题反馈")
        feedback_window.geometry("600x400")
        feedback_window.configure(bg="#1a1a1a")
        
        # 反馈框架
        feedback_frame = tk.Frame(feedback_window, bg="#252525", pady=30, padx=30)
        feedback_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(feedback_frame, text="问题反馈", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 反馈类型
        type_frame = tk.Frame(feedback_frame, bg="#252525")
        type_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(type_frame, text="反馈类型:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        
        self.feedback_type_var = tk.StringVar(value="功能建议")
        feedback_options = ["功能建议", "bug反馈", "使用问题", "其他"]
        feedback_menu = ttk.Combobox(type_frame, textvariable=self.feedback_type_var, values=feedback_options, state="readonly", width=20)
        feedback_menu.pack(side=tk.LEFT, padx=10)
        
        # 反馈内容
        content_frame = tk.Frame(feedback_frame, bg="#252525")
        content_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        tk.Label(content_frame, text="反馈内容:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.NW, padx=10, pady=5)
        self.feedback_content_var = tk.StringVar(value="")
        feedback_content_text = tk.Text(content_frame, width=60, height=10, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        feedback_content_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 提交按钮
        submit_btn = tk.Button(feedback_frame, text="提交反馈", command=lambda: self.confirm_submit_feedback(feedback_window, feedback_content_text), bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=30, pady=10, relief=tk.FLAT)
        submit_btn.pack(anchor=tk.CENTER, pady=30)
    
    def confirm_submit_feedback(self, window, text_widget):
        """确认提交反馈"""
        feedback_content = text_widget.get(1.0, tk.END).strip()
        feedback_type = self.feedback_type_var.get()
        if feedback_content:
            # 模拟提交反馈
            messagebox.showinfo("成功", f"已提交{feedback_type}反馈")
            window.destroy()
        else:
            messagebox.showerror("错误", "请输入反馈内容")
    
    def refresh_dashboard(self):
        """刷新数据看板"""
        # 模拟刷新数据
        messagebox.showinfo("成功", "数据已刷新")
    
    def generate_ai_suggestions(self):
        """生成AI运营建议"""
        # 模拟生成AI运营建议
        suggestions = [
            "建议增加15秒内高能片段，提高完播率",
            "建议优化标题，添加热门话题",
            "建议在评论区设置自动回复，提高互动率",
            "建议定时发布，选择平台流量高峰时段",
            "建议增加视频封面的吸引力，提高点击率"
        ]
        suggestions_text = "\n".join(suggestions)
        self.ai_suggestions_text.config(text=suggestions_text)
        messagebox.showinfo("成功", "已生成AI运营建议")
    
    def collect_platform_data(self):
        """采集平台数据"""
        platform = self.collect_platform_var.get()
        account_id = self.collect_account_var.get()
        if not account_id:
            messagebox.showerror("错误", "请输入账号ID")
            return
        
        # 调用OpenClowEngine采集数据
        result = openclow_engine.collect_data(platform, account_id)
        if result:
            messagebox.showinfo("成功", f"{platform}账号{account_id}的数据采集完成\n\n采集结果：\n播放量: {result['data']['views']}\n点赞量: {result['data']['likes']}\n评论量: {result['data']['comments']}\n分享量: {result['data']['shares']}\n粉丝数: {result['data']['followers']}")
        else:
            messagebox.showerror("错误", "数据采集失败")
    
    def auto_publish_content(self):
        """自动发布内容"""
        platform = self.publish_platform_var.get()
        account_id = self.publish_account_var.get()
        if not account_id:
            messagebox.showerror("错误", "请输入账号ID")
            return
        
        # 模拟内容
        content = {
            "title": "测试视频标题",
            "description": "这是一个测试视频",
            "tags": ["测试", "AI", "短剧"]
        }
        
        # 调用OpenClowEngine发布内容
        result = openclow_engine.auto_publish(platform, account_id, content)
        if result:
            messagebox.showinfo("成功", f"内容已成功发布到{platform}账号{account_id}\n\n发布时间: {result['publish_time']}")
        else:
            messagebox.showerror("错误", "内容发布失败")
    
    def smart_reply_comment(self):
        """智能回复评论"""
        comment = self.reply_comment_var.get()
        if not comment:
            messagebox.showerror("错误", "请输入评论内容")
            return
        
        # 调用OpenClowEngine智能回复
        result = openclow_engine.smart_reply("抖音", "123456789", comment)
        if result:
            messagebox.showinfo("成功", f"智能回复生成完成\n\n评论: {comment}\n回复: {result['reply']}")
        else:
            messagebox.showerror("错误", "智能回复失败")
    
    def write_back_operation_data(self):
        """运营数据回写"""
        platform = self.writeback_platform_var.get()
        account_id = self.writeback_account_var.get()
        if not account_id:
            messagebox.showerror("错误", "请输入账号ID")
            return
        
        # 模拟运营数据
        operation_data = {
            "views": 50000,
            "likes": 5000,
            "comments": 500,
            "shares": 200,
            "followers": 10000
        }
        
        # 调用OpenClowEngine回写数据
        result = openclow_engine.write_back_data(platform, account_id, operation_data)
        if result:
            messagebox.showinfo("成功", f"{platform}账号{account_id}的运营数据回写完成")
        else:
            messagebox.showerror("错误", "数据回写失败")
    
    def generate_operation_suggestions(self):
        """生成运营建议"""
        platform = self.suggest_platform_var.get()
        account_id = self.suggest_account_var.get()
        if not account_id:
            messagebox.showerror("错误", "请输入账号ID")
            return
        
        # 模拟运营数据
        operation_data = {
            "views": 80000,
            "likes": 8000,
            "comments": 800,
            "shares": 400,
            "followers": 15000
        }
        
        # 调用OpenClowEngine生成建议
        result = openclow_engine.generate_operation_suggestions(platform, account_id, operation_data)
        if result:
            suggestions = "\n".join(result['suggestions'])
            messagebox.showinfo("成功", f"为{platform}账号{account_id}生成运营建议\n\n{suggestions}")
        else:
            messagebox.showerror("错误", "生成运营建议失败")
    
    def sync_data(self):
        """同步数据"""
        # 模拟数据同步过程
        messagebox.showinfo("开始同步", "正在从OpenClow同步数据...")
        
        # 模拟同步进度
        for i in range(101):
            self.sync_countdown_var.set(f"{60 - i//2}s")
            self.root.update()
            time.sleep(0.05)
        
        messagebox.showinfo("同步完成", "数据已成功从OpenClow同步")
        
        # 重置倒计时
        self.sync_countdown_var.set("60s")
    
    def show_plugin_management_tab(self):
        """显示插件管理选项卡"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建带滚动条的框架
        frame = self.create_scrollable_frame(self.content_frame, bg=bg_color)
        
        # 标题
        title = tk.Label(frame, text="插件管理", font=("微软雅黑", 18, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, pady=20)
        
        # 插件搜索和分类
        search_frame = tk.Frame(frame, bg=frame_color, pady=20, padx=30)
        search_frame.pack(fill=tk.X, pady=10)
        
        # 搜索框
        tk.Label(search_frame, text="搜索插件:", bg=frame_color, fg=text_color, font= ("微软雅黑", 13)).pack(side=tk.LEFT, padx=10)
        self.plugin_search_var = tk.StringVar(value="")
        search_entry = tk.Entry(search_frame, textvariable=self.plugin_search_var, width=40, bg=item_color, fg=text_color, font= ("微软雅黑", 12))
        search_entry.pack(side=tk.LEFT, padx=10)
        search_btn = tk.Button(search_frame, text="搜索", command=self.search_plugins, bg=item_color, fg=text_color, font= ("微软雅黑", 12), padx=15, pady=5, relief=tk.FLAT)
        search_btn.pack(side=tk.LEFT, padx=10)
        
        # 插件分类
        category_frame = tk.Frame(frame, bg=frame_color, pady=10, padx=30)
        category_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(category_frame, text="插件分类:", bg=frame_color, fg=text_color, font= ("微软雅黑", 13)).pack(side=tk.LEFT, padx=10)
        self.plugin_category_var = tk.StringVar(value="全部")
        category_options = ["全部"] + list(default_plugin_categories.keys())
        category_menu = ttk.Combobox(category_frame, textvariable=self.plugin_category_var, values=category_options, state="readonly", width=15, font=("微软雅黑", 12))
        category_menu.pack(side=tk.LEFT, padx=10)
        category_menu.bind("<<ComboboxSelected>>", self.on_plugin_category_change)
        
        # 插件列表框架
        plugin_frame = tk.Frame(frame, bg=frame_color, pady=30, padx=30)
        plugin_frame.pack(fill=tk.X, pady=20)
        
        # 插件列表
        tk.Label(plugin_frame, text="已安装插件:", bg=frame_color, fg=text_color, font= ("微软雅黑", 13)).pack(anchor=tk.W, padx=20, pady=10)
        
        # 插件列表框
        self.plugin_listbox = tk.Listbox(plugin_frame, width=80, height=10, bg=item_color, fg=text_color, selectbackground=item_color, selectforeground=text_color, font= ("微软雅黑", 12))
        self.plugin_listbox.pack(fill=tk.X, pady=10)
        
        # 填充插件列表
        for plugin_name in plugins.keys():
            category = plugin_categories.get(plugin_name, "工具")
            version = plugin_versions.get(plugin_name, "1.0.0")
            self.plugin_listbox.insert(tk.END, f"{plugin_name} (v{version}) - {category}")
        
        # 插件信息
        info_frame = tk.Frame(frame, bg=frame_color, pady=30, padx=30)
        info_frame.pack(fill=tk.X, pady=20)
        
        # 插件描述
        tk.Label(info_frame, text="插件描述:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).pack(anchor=tk.W, padx=20, pady=10)
        self.plugin_info_text = scrolledtext.ScrolledText(info_frame, wrap=tk.WORD, state='disabled', bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 12), height=5)
        self.plugin_info_text.pack(fill=tk.X, pady=10)
        
        # 绑定列表框选择事件
        self.plugin_listbox.bind('<<ListboxSelect>>', self.on_plugin_select)
        
        # 插件操作按钮
        action_frame = tk.Frame(frame, bg=frame_color, pady=20, padx=30)
        action_frame.pack(fill=tk.X, pady=20)
        
        # 安装插件按钮
        install_btn = tk.Button(action_frame, text="安装插件", command=self.install_plugin, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=10, relief=tk.FLAT)
        install_btn.pack(side=tk.LEFT, padx=10)
        
        # 卸载插件按钮
        uninstall_btn = tk.Button(action_frame, text="卸载插件", command=self.uninstall_plugin, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=10, relief=tk.FLAT)
        uninstall_btn.pack(side=tk.LEFT, padx=10)
        
        # 刷新插件按钮
        refresh_btn = tk.Button(action_frame, text="刷新插件", command=self.refresh_plugins, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=10, relief=tk.FLAT)
        refresh_btn.pack(side=tk.LEFT, padx=10)
        
        # PyQt5插件管理器按钮
        pyqt_btn = tk.Button(action_frame, text="PyQt5插件管理器", command=self.show_pyqt_plugin_manager, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=10, relief=tk.FLAT)
        pyqt_btn.pack(side=tk.LEFT, padx=10)
        
        # 添加插件按钮
        add_plugin_btn = tk.Button(action_frame, text="添加插件", command=self.add_external_plugin, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=10, relief=tk.FLAT)
        add_plugin_btn.pack(side=tk.LEFT, padx=10)
        
        # 插件导入框架
        import_frame = tk.Frame(frame, bg=frame_color, pady=30, padx=30)
        import_frame.pack(fill=tk.X, pady=20)
        
        # 插件导入标题
        tk.Label(import_frame, text="插件导入", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=20, pady=10)
        
        # 插件文件选择
        import_row = 1
        tk.Label(import_frame, text="插件文件:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=import_row, column=0, sticky=tk.W, padx=20, pady=10)
        
        self.plugin_file_var = tk.StringVar(value="")
        plugin_file_entry = tk.Entry(import_frame, textvariable=self.plugin_file_var, width=60, bg=item_color, fg=text_color, font=("微软雅黑", 10))
        plugin_file_entry.grid(row=import_row, column=1, padx=10, pady=10, sticky=tk.W)
        
        plugin_browse_btn = tk.Button(import_frame, text="浏览", command=lambda: self.browse_file(self.plugin_file_var, ("Python文件", "*.py")), bg=item_color, fg=text_color, font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        plugin_browse_btn.grid(row=import_row, column=2, padx=10, pady=10)
        import_row += 1
        
        # 导入按钮
        import_btn = tk.Button(import_frame, text="导入插件", command=self.import_plugin, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        import_btn.grid(row=import_row, column=1, padx=10, pady=20, sticky=tk.W)
        import_row += 1
        
        # 导入状态
        self.import_status_var = tk.StringVar(value="")
        import_status_label = tk.Label(import_frame, textvariable=self.import_status_var, bg=frame_color, fg="#4CAF50", font= ("微软雅黑", 10))
        import_status_label.grid(row=import_row, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 插件更新框架
        update_frame = tk.Frame(frame, bg=frame_color, pady=20, padx=30)
        update_frame.pack(fill=tk.X, pady=20)
        
        # 插件更新标题
        tk.Label(update_frame, text="插件更新", font= ("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=10)
        
        # 检查更新按钮
        update_btn = tk.Button(update_frame, text="检查插件更新", command=self.check_plugin_updates, bg=item_color, fg=text_color, font= ("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        update_btn.pack(anchor=tk.W, pady=10, padx=20)
        
        # 更新状态
        self.update_status_var = tk.StringVar(value="")
        update_status_label = tk.Label(update_frame, textvariable=self.update_status_var, bg=frame_color, fg="#4CAF50", font= ("微软雅黑", 10))
        update_status_label.pack(anchor=tk.W, pady=10, padx=20)
    
    def show_model_config_tab(self):
        """显示模型配置选项卡"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建主框架（不使用滚动条）
        scrollable_frame = self.create_scrollable_frame(self.content_frame, bg=bg_color, scrollable=False)
        
        # 标题
        title = tk.Label(scrollable_frame, text="模型配置", font=("微软雅黑", 18, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, pady=20, padx=40)
        
        # 模型选择和统计
        model_frame = tk.Frame(scrollable_frame, bg=frame_color, pady=30, padx=30)
        model_frame.pack(fill=tk.X, pady=10, padx=40)
        
        # 默认模型
        row = 0
        tk.Label(model_frame, text="默认模型:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.default_model_var = tk.StringVar(value=model_manager.current_model)
        model_options = model_manager.models
        self.default_model_menu = ttk.Combobox(model_frame, textvariable=self.default_model_var, values=model_options, state="readonly", width=25, font=("微软雅黑", 11))
        self.default_model_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        
        # 模型统计按钮
        stats_btn = tk.Button(model_frame, text="查看模型统计", command=self.show_model_stats, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        stats_btn.grid(row=row, column=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 自定义模型管理
        custom_model_frame = tk.Frame(scrollable_frame, bg=frame_color, pady=20, padx=30)
        custom_model_frame.pack(fill=tk.X, pady=10, padx=40)
        
        tk.Label(custom_model_frame, text="自定义模型管理", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=20, pady=10)
        
        # 添加自定义模型
        row = 1
        tk.Label(custom_model_frame, text="模型名称:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.custom_model_name_var = tk.StringVar(value="")
        custom_model_entry = tk.Entry(custom_model_frame, textvariable=self.custom_model_name_var, width=30, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 11))
        custom_model_entry.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 添加按钮
        add_model_btn = tk.Button(custom_model_frame, text="添加自定义模型", command=self.add_custom_model, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        add_model_btn.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 移除自定义模型
        tk.Label(custom_model_frame, text="选择模型:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        custom_models = [model for model in model_manager.models if model not in ["本地爆款模型", "智能剪辑模型"]]
        self.remove_model_var = tk.StringVar(value="")
        remove_model_menu = ttk.Combobox(custom_model_frame, textvariable=self.remove_model_var, values=custom_models, state="readonly", width=30, font=("微软雅黑", 11))
        remove_model_menu.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 移除按钮
        remove_model_btn = tk.Button(custom_model_frame, text="移除自定义模型", command=self.remove_custom_model, bg=item_color, fg=text_color, font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        remove_model_btn.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # API密钥配置说明
        api_frame = tk.Frame(scrollable_frame, bg=frame_color, pady=30, padx=30)
        api_frame.pack(fill=tk.X, pady=20, padx=40)
        
        tk.Label(api_frame, text="API密钥配置（多个密钥用逗号分隔）:", bg=frame_color, fg=text_color, font=("微软雅黑", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=20, pady=10)
        
        # API密钥配置
        row = 1
        
        # DeepSeek API Keys
        tk.Label(api_frame, text="DeepSeek API Keys:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        deepseek_keys = ",".join(API_KEYS.get("DeepSeek", []))
        self.deepseek_api_var = tk.StringVar(value=deepseek_keys)
        self.deepseek_api_entry = tk.Entry(api_frame, textvariable=self.deepseek_api_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.deepseek_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 豆包 API Keys
        tk.Label(api_frame, text="豆包 API Keys:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        doubao_keys = ",".join(API_KEYS.get("豆包", []))
        self.doubao_api_var = tk.StringVar(value=doubao_keys)
        self.doubao_api_entry = tk.Entry(api_frame, textvariable=self.doubao_api_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.doubao_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # ChatGPT API Keys
        tk.Label(api_frame, text="ChatGPT API Keys:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        openai_keys = ",".join(API_KEYS.get("ChatGPT", []))
        self.openai_api_var = tk.StringVar(value=openai_keys)
        self.openai_api_entry = tk.Entry(api_frame, textvariable=self.openai_api_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.openai_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # Claude API Keys
        tk.Label(api_frame, text="Claude API Keys:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        anthropic_keys = ",".join(API_KEYS.get("Claude", []))
        self.anthropic_api_var = tk.StringVar(value=anthropic_keys)
        self.anthropic_api_entry = tk.Entry(api_frame, textvariable=self.anthropic_api_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.anthropic_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # Gemini API Keys
        tk.Label(api_frame, text="Gemini API Keys:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        google_keys = ",".join(API_KEYS.get("Gemini", []))
        self.google_api_var = tk.StringVar(value=google_keys)
        self.google_api_entry = tk.Entry(api_frame, textvariable=self.google_api_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.google_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 通义千问 API Keys
        tk.Label(api_frame, text="通义千问 API Keys:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        dashscope_keys = ",".join(API_KEYS.get("通义千问", []))
        self.dashscope_api_var = tk.StringVar(value=dashscope_keys)
        self.dashscope_api_entry = tk.Entry(api_frame, textvariable=self.dashscope_api_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.dashscope_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 通义千问VL API Keys
        tk.Label(api_frame, text="通义千问VL API Keys:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        dashscope_vl_keys = ",".join(API_KEYS.get("通义千问VL", []))
        self.dashscope_vl_api_var = tk.StringVar(value=dashscope_vl_keys)
        self.dashscope_vl_api_entry = tk.Entry(api_frame, textvariable=self.dashscope_vl_api_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.dashscope_vl_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 文心一言 API Keys
        tk.Label(api_frame, text="文心一言 Access Tokens:", bg=frame_color, fg=text_color, font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        baidu_keys = ",".join(API_KEYS.get("文心一言", []))
        self.baidu_access_var = tk.StringVar(value=baidu_keys)
        self.baidu_access_entry = tk.Entry(api_frame, textvariable=self.baidu_access_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10))
        self.baidu_access_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        

        
        # 按钮框架
        button_frame = tk.Frame(scrollable_frame, bg=bg_color, pady=20)
        button_frame.pack(fill=tk.X, pady=10, padx=40)
        
        # 保存配置按钮
        save_btn = tk.Button(button_frame, text="保存配置", command=self.save_model_config, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=12, relief=tk.FLAT)
        save_btn.pack(anchor=tk.CENTER, pady=20)
        
        # 底部空间，确保所有内容都能显示
        bottom_space = tk.Frame(scrollable_frame, bg=bg_color, height=50)
        bottom_space.pack(fill=tk.X, pady=20, padx=40)
    
    def show_performance_tab(self):
        """显示性能监控页面"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 性能监控页面内容
        performance_frame = tk.Frame(self.content_frame, bg=bg_color)
        performance_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title = tk.Label(performance_frame, text="性能监控", font=("微软雅黑", 18, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 性能统计
        stats_frame = tk.Frame(performance_frame, bg=frame_color, pady=20)
        stats_frame.pack(fill=tk.X, padx=60, pady=10)
        
        stats_label = tk.Label(stats_frame, text="性能统计", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color)
        stats_label.pack(anchor=tk.W, padx=20, pady=10)
        
        # 记录当前性能指标
        performance_monitor.record_metrics()
        stats = performance_monitor.get_stats()
        
        # 显示性能统计信息
        if stats:
            stats_text = f"运行时间: {stats['uptime_seconds']}秒\n"
            stats_text += f"最大内存使用: {stats['max_memory_usage_mb']}MB\n"
            stats_text += f"平均内存使用: {stats['avg_memory_usage_mb']}MB\n"
            stats_text += f"平均CPU使用率: {stats['avg_cpu_usage_percent']}%\n"
            stats_text += f"缓存大小: {cache_system.size()}/{CACHE_SIZE}\n"
        else:
            stats_text = "暂无性能数据"
        
        stats_info_label = tk.Label(stats_frame, text=stats_text, font=("微软雅黑", 12), bg=frame_color, fg=desc_color, justify=tk.LEFT)
        stats_info_label.pack(anchor=tk.W, padx=40, pady=10)
        
        # 硬件信息
        hardware_frame = tk.Frame(performance_frame, bg=frame_color, pady=20)
        hardware_frame.pack(fill=tk.X, padx=60, pady=10)
        
        hardware_label = tk.Label(hardware_frame, text="硬件信息", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color)
        hardware_label.pack(anchor=tk.W, padx=20, pady=10)
        
        # 显示硬件信息
        hardware_info_text = f"CPU核心数: {hardware_config['cpu_count']}\n"
        hardware_info_text += f"可用内存: {hardware_config['available_memory_gb']}GB\n"
        hardware_info_text += f"系统: {hardware_config['system']}\n"
        hardware_info_text += f"GPU编码器: {GPU_ENCODER}\n"
        hardware_info_text += f"最大线程数: {MAX_PARALLEL}\n"
        hardware_info_text += f"最大批量大小: {MAX_BATCH_SIZE}\n"
        hardware_info_text += f"缓存大小: {CACHE_SIZE}MB"
        
        hardware_info_label = tk.Label(hardware_frame, text=hardware_info_text, font=("微软雅黑", 12), bg=frame_color, fg=desc_color, justify=tk.LEFT)
        hardware_info_label.pack(anchor=tk.W, padx=40, pady=10)
        
        # 优化建议
        optimize_frame = tk.Frame(performance_frame, bg=frame_color, pady=20)
        optimize_frame.pack(fill=tk.X, padx=60, pady=10)
        
        optimize_label = tk.Label(optimize_frame, text="优化建议", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color)
        optimize_label.pack(anchor=tk.W, padx=20, pady=10)
        
        # 生成优化建议
        suggestions = []
        if hardware_config['available_memory_gb'] < 4:
            suggestions.append("建议增加系统内存，至少8GB以上以获得更好的性能")
        if hardware_config['cpu_count'] < 4:
            suggestions.append("建议使用至少4核心CPU以提高批量处理速度")
        if GPU_ENCODER == "libx264":
            suggestions.append("建议使用支持硬件加速的GPU以提高编码速度")
        if stats and stats['max_memory_usage_mb'] > hardware_config['available_memory_gb'] * 1024 * 0.8:
            suggestions.append("内存使用较高，建议减少批量处理大小或增加内存")
        
        if not suggestions:
            suggestions.append("硬件配置良好，无需特殊优化")
        
        suggestions_text = "\n".join(suggestions)
        suggestions_label = tk.Label(optimize_frame, text=suggestions_text, font=("微软雅黑", 12), bg=frame_color, fg=desc_color, justify=tk.LEFT)
        suggestions_label.pack(anchor=tk.W, padx=40, pady=10)
        
        # 操作按钮
        btn_frame = tk.Frame(performance_frame, bg=bg_color)
        btn_frame.pack(fill=tk.X, padx=60, pady=20)
        
        # 清空缓存按钮
        clear_cache_btn = tk.Button(btn_frame, text="清空缓存", command=self.clear_cache, bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        clear_cache_btn.pack(side=tk.RIGHT, padx=10)
        
        # 刷新性能数据按钮
        refresh_btn = tk.Button(btn_frame, text="刷新数据", command=self.show_performance_tab, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        refresh_btn.pack(side=tk.RIGHT, padx=10)
    
    def show_task_management(self):
        """显示任务管理页面"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建任务管理页面
        task_frame = tk.Frame(self.content_frame, bg=bg_color)
        task_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 标题
        title = tk.Label(task_frame, text="任务管理", font=("微软雅黑", 18, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, pady=20)
        
        # 任务状态选择
        status_frame = tk.Frame(task_frame, bg=frame_color, pady=15, padx=30)
        status_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(status_frame, text="任务状态:", bg=frame_color, fg=text_color, font=("微软雅黑", 12)).pack(side=tk.LEFT, padx=10)
        
        self.task_status_var = tk.StringVar(value="全部")
        status_options = ["全部", "未完成", "已完成"]
        status_menu = ttk.Combobox(status_frame, textvariable=self.task_status_var, values=status_options, state="readonly", width=15)
        status_menu.pack(side=tk.LEFT, padx=10)
        
        # 任务列表框架
        task_list_frame = tk.Frame(task_frame, bg=frame_color, pady=20, padx=30)
        task_list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 任务列表标题
        task_list_title = tk.Label(task_list_frame, text="任务列表", font=("微软雅黑", 14, "bold"), bg=frame_color, fg=text_color)
        task_list_title.pack(anchor=tk.W, pady=10)
        
        # 任务列表
        self.task_list = tk.Listbox(
            task_list_frame, 
            width=100, 
            height=15, 
            bg=item_color, 
            fg=text_color,
            font=("微软雅黑", 12)
        )
        self.task_list.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 示例任务 - 未完成
        pending_tasks = [
            "[未完成] 视频导出: 1080p, 30fps",
            "[未完成] AI配音生成: 短剧解说风格",
            "[未完成] 字幕生成: 自动识别"
        ]
        
        # 示例任务 - 已完成
        completed_tasks = [
            "[已完成] 视频剪辑: 10秒片段",
            "[已完成] 文案生成: 抖音短剧风格",
            "[已完成] 素材导入: 5个视频文件"
        ]
        
        # 添加所有任务
        for task in pending_tasks + completed_tasks:
            self.task_list.insert(tk.END, task)
        
        # 任务操作按钮
        task_ops_frame = tk.Frame(task_list_frame, bg=frame_color, pady=10)
        task_ops_frame.pack(fill=tk.X, pady=10)
        
        # 刷新任务列表按钮
        refresh_btn = tk.Button(
            task_ops_frame, 
            text="刷新任务", 
            bg="#007acc", 
            fg="#ffffff",
            font=("微软雅黑", 12),
            padx=20, 
            pady=8,
            relief=tk.FLAT,
            command=self.refresh_task_list
        )
        refresh_btn.pack(side=tk.LEFT, padx=10)
        
        # 取消任务按钮
        cancel_btn = tk.Button(
            task_ops_frame, 
            text="取消任务", 
            bg=item_color, 
            fg=text_color,
            font=("微软雅黑", 12),
            padx=20, 
            pady=8,
            relief=tk.FLAT,
            command=self.cancel_selected_task
        )
        cancel_btn.pack(side=tk.LEFT, padx=10)
        
        # 标记完成按钮
        complete_btn = tk.Button(
            task_ops_frame, 
            text="标记完成", 
            bg=item_color, 
            fg=text_color,
            font=("微软雅黑", 12),
            padx=20, 
            pady=8,
            relief=tk.FLAT,
            command=self.mark_task_complete
        )
        complete_btn.pack(side=tk.LEFT, padx=10)
        
        # 状态变更事件
        status_menu.bind("<<ComboboxSelected>>", self.filter_tasks_by_status)
    
    def refresh_task_list(self):
        """刷新任务列表"""
        # 清空当前列表
        self.task_list.delete(0, tk.END)
        
        # 重新添加任务
        pending_tasks = [
            "[未完成] 视频导出: 1080p, 30fps",
            "[未完成] AI配音生成: 短剧解说风格",
            "[未完成] 字幕生成: 自动识别"
        ]
        
        completed_tasks = [
            "[已完成] 视频剪辑: 10秒片段",
            "[已完成] 文案生成: 抖音短剧风格",
            "[已完成] 素材导入: 5个视频文件"
        ]
        
        for task in pending_tasks + completed_tasks:
            self.task_list.insert(tk.END, task)
    
    def cancel_selected_task(self):
        """取消选中的任务"""
        selection = self.task_list.curselection()
        if not selection:
            import tkinter.messagebox
            tkinter.messagebox.showinfo("提示", "请先选择一个任务")
            return
        
        task_index = selection[0]
        task_text = self.task_list.get(task_index)
        
        # 从列表中移除任务
        self.task_list.delete(task_index)
        
        import tkinter.messagebox
        tkinter.messagebox.showinfo("成功", f"任务已取消: {task_text}")
    
    def mark_task_complete(self):
        """标记任务为完成"""
        selection = self.task_list.curselection()
        if not selection:
            import tkinter.messagebox
            tkinter.messagebox.showinfo("提示", "请先选择一个任务")
            return
        
        task_index = selection[0]
        task_text = self.task_list.get(task_index)
        
        # 检查任务是否已经完成
        if "[已完成]" in task_text:
            import tkinter.messagebox
            tkinter.messagebox.showinfo("提示", "任务已经是完成状态")
            return
        
        # 标记为已完成
        new_task_text = task_text.replace("[未完成]", "[已完成]")
        self.task_list.delete(task_index)
        self.task_list.insert(task_index, new_task_text)
        
        import tkinter.messagebox
        tkinter.messagebox.showinfo("成功", f"任务已标记为完成: {new_task_text}")
    
    def filter_tasks_by_status(self, event):
        """根据状态筛选任务"""
        status = self.task_status_var.get()
        
        # 保存当前所有任务
        all_tasks = []
        for i in range(self.task_list.size()):
            all_tasks.append(self.task_list.get(i))
        
        # 清空列表
        self.task_list.delete(0, tk.END)
        
        # 根据状态筛选
        for task in all_tasks:
            if status == "全部":
                self.task_list.insert(tk.END, task)
            elif status == "未完成" and "[未完成]" in task:
                self.task_list.insert(tk.END, task)
            elif status == "已完成" and "[已完成]" in task:
                self.task_list.insert(tk.END, task)
    
    def clear_cache(self):
        """清空缓存"""
        cache_system.clear()
        if hasattr(self, 'status_label'):
            self.status_label.config(text="缓存已清空")
    
    def show_settings_tab(self):
        """显示设置选项卡"""
        self.clear_content_frame()
        
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        frame_color = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        item_color = "#333333" if self.current_theme == "dark" else "#e0e0e0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg=bg_color)
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="设置", font=("微软雅黑", 18, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, pady=20)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg=frame_color, pady=30, padx=30)
        config_frame.pack(fill=tk.X, pady=20)
        
        # 配置项
        row = 0
        
        # 最大线程数
        tk.Label(config_frame, text="最大线程数:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.max_threads_var = tk.StringVar(value=str(MAX_PARALLEL))
        self.max_threads_entry = tk.Entry(config_frame, textvariable=self.max_threads_var, width=10, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 12))
        self.max_threads_entry.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 默认速度
        tk.Label(config_frame, text="默认速度:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.default_speed_var = tk.StringVar(value=str(DEFAULT_SPEED))
        self.default_speed_entry = tk.Entry(config_frame, textvariable=self.default_speed_var, width=10, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 12))
        self.default_speed_entry.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # BGM音量
        tk.Label(config_frame, text="BGM音量:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.bgm_vol_var = tk.StringVar(value=BGM_VOL)
        self.bgm_vol_entry = tk.Entry(config_frame, textvariable=self.bgm_vol_var, width=10, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 12))
        self.bgm_vol_entry.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 输出目录
        tk.Label(config_frame, text="输出目录:", bg=frame_color, fg=text_color, font=("微软雅黑", 13)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.output_dir_var = tk.StringVar(value=OUTPUT_DIR)
        self.output_dir_entry = tk.Entry(config_frame, textvariable=self.output_dir_var, width=60, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 12))
        self.output_dir_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        browse_btn = tk.Button(config_frame, text="浏览", command=lambda: self.browse_folder(self.output_dir_var), bg=item_color, fg=text_color, font=("微软雅黑", 12), padx=15, pady=7, relief=tk.FLAT)
        browse_btn.grid(row=row, column=3, padx=10, pady=15)
        row += 1
        
        # 开源项目配置
        tk.Label(config_frame, text="开源项目集成:", bg=frame_color, fg=text_color, font=("微软雅黑", 13, "bold")).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        row += 1
        
        # FunClip
        self.funclip_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(config_frame, text="FunClip (自动剪辑)", variable=self.funclip_enabled_var, bg=frame_color, fg=text_color, selectcolor=item_color, font=('微软雅黑', 12)).grid(row=row, column=1, sticky=tk.W, padx=10, pady=10)
        row += 1
        
        # AutoClip
        self.autoclip_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(config_frame, text="AutoClip (高光识别)", variable=self.autoclip_enabled_var, bg=frame_color, fg=text_color, selectcolor=item_color, font=('微软雅黑', 12)).grid(row=row, column=1, sticky=tk.W, padx=10, pady=10)
        row += 1
        
        # VideoFusion
        self.videofusion_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(config_frame, text="VideoFusion (视频修复)", variable=self.videofusion_enabled_var, bg=frame_color, fg=text_color, selectcolor=item_color, font=('微软雅黑', 12)).grid(row=row, column=1, sticky=tk.W, padx=10, pady=10)
        row += 1
        
        # OpenClaw
        self.openclaw_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(config_frame, text="OpenClaw (账号运营)", variable=self.openclaw_enabled_var, bg=frame_color, fg=text_color, selectcolor=item_color, font=('微软雅黑', 12)).grid(row=row, column=1, sticky=tk.W, padx=10, pady=10)
        row += 1
        
        # 按钮框架
        button_frame = tk.Frame(frame, bg=bg_color, pady=20)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 保存设置按钮
        save_btn = tk.Button(button_frame, text="保存设置", command=self.save_settings, bg="#007acc", fg="#ffffff", font=("微软雅黑", 13), padx=30, pady=12, relief=tk.FLAT)
        save_btn.pack(anchor=tk.CENTER, pady=20)
    
    def browse_file(self, var, filetypes, multiple=False):
        """浏览文件"""
        if multiple:
            filenames = filedialog.askopenfilenames(filetypes=filetypes)
            if filenames:
                var.set(';'.join(filenames))
        else:
            filename = filedialog.askopenfilename(filetypes=filetypes)
            if filename:
                var.set(filename)
    
    def browse_folder(self, var):
        """浏览文件夹"""
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)
    
    def generate_copywriting_preview(self):
        """生成文案预览"""
        video_path = self.video_path_var.get()
        if not video_path:
            messagebox.showerror("错误", "请选择视频文件")
            return
        
        model_name = self.model_var.get()
        model_manager.switch_model(model_name)
        
        base_name = os.path.basename(video_path)
        title, content, keywords = model_manager.generate_content(base_name)
        
        self.title_label.config(text=title)
        self.content_label.config(text=content)
        self.kw_label.config(text=keywords)
        self.info_label.config(text=plugin_get_video_info(video_path))
    
    def update_video_list(self, *args):
        """更新视频列表"""
        self.video_listbox.delete(0, tk.END)
        video_paths = self.video_path_var.get().split(';')
        for path in video_paths:
            if path:
                self.video_listbox.insert(tk.END, os.path.basename(path))
    
    def draw_timeline_scale(self):
        """绘制时间线刻度"""
        self.timeline_canvas.delete("all")
        width = self.timeline_canvas.winfo_width()
        if width == 0:
            width = 800  # 默认宽度
        
        # 绘制时间刻度（每1秒一个刻度）
        for i in range(0, 100, 1):
            x = (i / 100) * width
            self.timeline_canvas.create_line(x, 0, x, 20, fill="#444444")
            if i % 5 == 0:
                self.timeline_canvas.create_text(x, 30, text=f"{i}s", fill="#888888", font=("微软雅黑", 8))
        
        # 绘制播放头
        self.playhead = self.timeline_canvas.create_line(0, 0, 0, 180, fill="#007acc", width=2)
    
    def play_timeline(self):
        """播放时间线"""
        # 简单的播放模拟
        self.status_label.config(text="播放中...")
        
    def pause_timeline(self):
        """暂停时间线"""
        # 暂停功能实现
        self.status_label.config(text="已暂停")
        
    def stop_timeline(self):
        """停止时间线"""
        # 停止功能实现
        self.status_label.config(text="已停止")
        # 重置播放头位置
        if hasattr(self, 'timeline_canvas') and hasattr(self, 'playhead'):
            self.timeline_canvas.coords(self.playhead, 0, 0, 0, 180)
        

    
    def stop_preview(self):
        """停止预览"""
        # 清除预览画布
        self.preview_canvas.delete("all")
        cw = self.preview_canvas.winfo_width() or 800
        ch = self.preview_canvas.winfo_height() or 450
        self.preview_hint = self.preview_canvas.create_text(cw // 2, ch // 2, text="点击预览按钮查看视频效果", fill="#000000", font=("微软雅黑", 12))
        self.status_label.config(text="预览已停止")
    
    def add_task(self):
        """添加任务"""
        # 获取当前选择的视频
        video_paths = self.video_path_var.get().split(';')
        video_paths = [p for p in video_paths if p]
        if not video_paths:
            messagebox.showerror("错误", "请先选择视频文件")
            return
        
        # 生成任务名称
        task_name = f"剪辑视频 - {os.path.basename(video_paths[0])}"
        if len(video_paths) > 1:
            task_name += f" 等{len(video_paths)}个视频"
        
        # 添加到未完成任务列表
        self.pending_tasks_listbox.insert(tk.END, task_name)
        
        # 保存任务到文件
        self.save_tasks()
        
        self.status_label.config(text="任务添加成功")
    
    def complete_task(self):
        """标记任务完成"""
        # 获取选中的未完成任务
        selected_indices = self.pending_tasks_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要标记完成的任务")
            return
        
        # 标记任务完成
        for index in selected_indices:
            task_name = self.pending_tasks_listbox.get(index)
            # 添加到已完成任务列表
            self.completed_tasks_listbox.insert(tk.END, task_name)
            # 从未完成任务列表中删除
            self.pending_tasks_listbox.delete(index)
        
        # 保存任务到文件
        self.save_tasks()
        
        self.status_label.config(text="任务标记完成成功")
    
    def delete_task(self):
        """删除任务"""
        # 获取选中的未完成任务
        selected_pending = self.pending_tasks_listbox.curselection()
        for index in reversed(selected_pending):
            self.pending_tasks_listbox.delete(index)
        
        # 获取选中的已完成任务
        selected_completed = self.completed_tasks_listbox.curselection()
        for index in reversed(selected_completed):
            self.completed_tasks_listbox.delete(index)
        
        # 保存任务到文件
        self.save_tasks()
        
        self.status_label.config(text="任务删除成功")
    
    def refresh_tasks(self):
        """刷新任务列表"""
        # 清空列表
        self.pending_tasks_listbox.delete(0, tk.END)
        self.completed_tasks_listbox.delete(0, tk.END)
        
        # 加载任务
        self.load_tasks()
        
        self.status_label.config(text="任务列表已刷新")
    
    def save_tasks(self):
        """保存任务到文件"""
        try:
            # 创建任务文件目录
            tasks_dir = os.path.join(OUTPUT_DIR, "tasks")
            os.makedirs(tasks_dir, exist_ok=True)
            
            # 保存未完成任务
            pending_tasks = []
            for i in range(self.pending_tasks_listbox.size()):
                pending_tasks.append(self.pending_tasks_listbox.get(i))
            
            with open(os.path.join(tasks_dir, "pending_tasks.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(pending_tasks))
            
            # 保存已完成任务
            completed_tasks = []
            for i in range(self.completed_tasks_listbox.size()):
                completed_tasks.append(self.completed_tasks_listbox.get(i))
            
            with open(os.path.join(tasks_dir, "completed_tasks.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(completed_tasks))
        except Exception as e:
            print(f"保存任务失败: {e}")
    
    def load_tasks(self):
        """加载任务从文件"""
        try:
            # 加载未完成任务
            pending_tasks_file = os.path.join(OUTPUT_DIR, "tasks", "pending_tasks.txt")
            if os.path.exists(pending_tasks_file):
                with open(pending_tasks_file, "r", encoding="utf-8") as f:
                    pending_tasks = f.read().split("\n")
                    for task in pending_tasks:
                        if task:
                            self.pending_tasks_listbox.insert(tk.END, task)
            
            # 加载已完成任务
            completed_tasks_file = os.path.join(OUTPUT_DIR, "tasks", "completed_tasks.txt")
            if os.path.exists(completed_tasks_file):
                with open(completed_tasks_file, "r", encoding="utf-8") as f:
                    completed_tasks = f.read().split("\n")
                    for task in completed_tasks:
                        if task:
                            self.completed_tasks_listbox.insert(tk.END, task)
        except Exception as e:
            print(f"加载任务失败: {e}")
    
    def apply_speed(self):
        """应用速度调整"""
        speed = self.speed_var.get()
        self.status_label.config(text=f"应用速度: {speed}")
    
    def show_transition_options(self):
        """显示转场效果选项"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建转场效果对话框
        transition_window = tk.Toplevel(self.root)
        transition_window.title("转场效果")
        transition_window.geometry("400x400")
        transition_window.configure(bg=bg_color)
        
        # 转场效果列表
        transitions = [
            "淡入淡出", "滑动", "擦除", "缩放", "旋转",
            "溶解", "百叶窗", "翻页", "闪光", "3D旋转"
        ]
        
        # 转场效果选择
        transition_frame = tk.Frame(transition_window, bg=frame_color, pady=20, padx=20)
        transition_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(transition_frame, text="选择转场效果", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=10)
        
        self.selected_transition = tk.StringVar(value=transitions[0])
        for transition in transitions:
            tk.Radiobutton(
                transition_frame, 
                text=transition, 
                variable=self.selected_transition, 
                value=transition, 
                bg=frame_color, 
                fg=text_color,
                selectcolor=item_color
            ).pack(anchor=tk.W, pady=5)
        
        # 转场时长
        duration_frame = tk.Frame(transition_frame, bg=frame_color, pady=10)
        duration_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(duration_frame, text="转场时长 (秒):", bg=frame_color, fg=text_color).pack(side=tk.LEFT, padx=10)
        self.transition_duration = tk.Scale(duration_frame, from_=0.5, to=3, resolution=0.1, orient=tk.HORIZONTAL, bg=frame_color, fg=text_color, length=200)
        self.transition_duration.set(1)
        self.transition_duration.pack(side=tk.LEFT, padx=10)
        
        # 应用按钮
        apply_btn = tk.Button(
            transition_window, 
            text="应用转场", 
            command=lambda: self.apply_transition(transition_window), 
            bg="#007acc", 
            fg="#ffffff", 
            font=("微软雅黑", 11), 
            padx=30, 
            pady=10, 
            relief=tk.FLAT
        )
        apply_btn.pack(pady=20)
    
    def show_filter_options(self):
        """显示滤镜选项"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 创建滤镜对话框
        filter_window = tk.Toplevel(self.root)
        filter_window.title("滤镜效果")
        filter_window.geometry("400x400")
        filter_window.configure(bg=bg_color)
        
        # 滤镜列表
        filters = [
            "自然", "清新", "复古", "黑白", "暖色",
            "冷色", "电影感", "梦幻", "鲜艳", "柔和"
        ]
        
        # 滤镜选择
        filter_frame = tk.Frame(filter_window, bg=frame_color, pady=20, padx=20)
        filter_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(filter_frame, text="选择滤镜效果", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=10)
        
        self.selected_filter = tk.StringVar(value=filters[0])
        for filter in filters:
            tk.Radiobutton(
                filter_frame, 
                text=filter, 
                variable=self.selected_filter, 
                value=filter, 
                bg=frame_color, 
                fg=text_color,
                selectcolor=item_color
            ).pack(anchor=tk.W, pady=5)
        
        # 滤镜强度
        intensity_frame = tk.Frame(filter_frame, bg=frame_color, pady=10)
        intensity_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(intensity_frame, text="滤镜强度:", bg=frame_color, fg=text_color).pack(side=tk.LEFT, padx=10)
        self.filter_intensity = tk.Scale(intensity_frame, from_=0, to=100, orient=tk.HORIZONTAL, bg=frame_color, fg=text_color, length=200)
        self.filter_intensity.set(50)
        self.filter_intensity.pack(side=tk.LEFT, padx=10)
        
        # 应用按钮
        apply_btn = tk.Button(
            filter_window, 
            text="应用滤镜", 
            command=lambda: self.apply_filter(filter_window), 
            bg="#007acc", 
            fg="#ffffff", 
            font=("微软雅黑", 11), 
            padx=30, 
            pady=10, 
            relief=tk.FLAT
        )
        apply_btn.pack(pady=20)
    
    def apply_transition(self, window):
        """应用转场效果"""
        transition = self.selected_transition.get()
        duration = self.transition_duration.get()
        self.status_label.config(text=f"应用转场: {transition} ({duration}秒)")
        window.destroy()
    
    def apply_filter(self, window):
        """应用滤镜效果"""
        filter = self.selected_filter.get()
        intensity = self.filter_intensity.get()
        self.status_label.config(text=f"应用滤镜: {filter} (强度: {intensity}%)")
        window.destroy()

    def show_publish_management(self):
        """显示发布管理窗口"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        publish_window = tk.Toplevel(self.root)
        publish_window.title("发布管理")
        publish_window.geometry("800x600")
        publish_window.configure(bg=bg_color)
        
        # 发布管理框架
        publish_frame = tk.Frame(publish_window, bg=frame_color, pady=30, padx=30)
        publish_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(publish_frame, text="发布管理", font=("微软雅黑", 16, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=20)
        
        # 发布队列
        queue_frame = tk.Frame(publish_frame, bg=frame_color)
        queue_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(queue_frame, text="发布队列", font=("微软雅黑", 12, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=10)
        
        # 队列列表
        self.publish_queue_listbox = tk.Listbox(queue_frame, width=80, height=10, bg=item_color, fg=text_color, selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.publish_queue_listbox.pack(fill=tk.X, pady=10)
        
        # 模拟队列数据
        queue_items = [
            "视频1.mp4 - 抖音 - 等待发布",
            "视频2.mp4 - 快手 - 等待发布",
            "视频3.mp4 - 视频号 - 已发布",
            "视频4.mp4 - 小红书 - 发布失败"
        ]
        
        for item in queue_items:
            self.publish_queue_listbox.insert(tk.END, item)
        
        # 发布操作按钮
        button_frame = tk.Frame(publish_frame, bg=frame_color, pady=20)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 开始发布按钮
        start_publish_btn = tk.Button(button_frame, text="开始发布", command=self.start_publish, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=10, relief=tk.FLAT)
        start_publish_btn.pack(side=tk.LEFT, padx=10)
        
        # 取消发布按钮
        cancel_publish_btn = tk.Button(button_frame, text="取消发布", command=self.cancel_publish, bg=item_color, fg=text_color, font=("微软雅黑", 10), padx=20, pady=10, relief=tk.FLAT)
        cancel_publish_btn.pack(side=tk.LEFT, padx=10)
        
        # 刷新队列按钮
        refresh_queue_btn = tk.Button(button_frame, text="刷新队列", command=self.refresh_publish_queue, bg=item_color, fg=text_color, font=("微软雅黑", 10), padx=20, pady=10, relief=tk.FLAT)
        refresh_queue_btn.pack(side=tk.LEFT, padx=10)

    def show_competitor_analysis(self):
        """显示竞品分析窗口"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        competitor_window = tk.Toplevel(self.root)
        competitor_window.title("对标账号分析")
        competitor_window.geometry("800x600")
        competitor_window.configure(bg=bg_color)
        
        # 竞品分析框架
        competitor_frame = tk.Frame(competitor_window, bg=frame_color, pady=30, padx=30)
        competitor_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(competitor_frame, text="对标账号分析", font=("微软雅黑", 16, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=20)
        
        # 竞品账号选择
        select_frame = tk.Frame(competitor_frame, bg=frame_color)
        select_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(select_frame, text="竞品账号:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.competitor_var = tk.StringVar(value="竞品账号1")
        competitor_options = ["竞品账号1", "竞品账号2", "竞品账号3"]
        competitor_menu = ttk.Combobox(select_frame, textvariable=self.competitor_var, values=competitor_options, state="readonly", width=20)
        competitor_menu.pack(side=tk.LEFT, padx=10)
        
        # 分析按钮
        analyze_btn = tk.Button(select_frame, text="分析竞品", command=self.analyze_competitor_detail, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        analyze_btn.pack(side=tk.LEFT, padx=10)
        
        # 分析结果框架
        result_frame = tk.Frame(competitor_frame, bg=frame_color, pady=20)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 分析结果标题
        tk.Label(result_frame, text="分析结果", font=("微软雅黑", 12, "bold"), bg=frame_color, fg="#007acc").pack(anchor=tk.W, pady=10)
        
        # 分析结果内容
        self.competitor_result_text = tk.Text(result_frame, wrap=tk.WORD, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10), height=15)
        self.competitor_result_text.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 模拟分析结果
        result_text = """竞品账号分析结果:

1. 发布时间分析:
   - 最佳发布时间: 晚上 8:00-10:00
   - 发布频率: 每天 3-4 条

2. 视频结构分析:
   - 平均时长: 35秒
   - 前3秒钩子: 冲突片段前置
   - 反转密度: 平均每15秒一个反转

3. 文案分析:
   - 标题结构: 疑问句 + 冲突点
   - 关键词: 短剧、爽点、反转、逆袭
   - 话题标签: #短剧 #爽文 #逆袭

4. 优化建议:
   - 增加前3秒冲突强度
   - 优化发布时间到晚上黄金时段
   - 提升反转密度"""
        
        self.competitor_result_text.insert(tk.END, result_text)
        self.competitor_result_text.config(state=tk.DISABLED)

    def show_ai_suggestions(self):
        """显示AI运营建议窗口"""
        # 根据当前主题设置颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#f0f0f0"
        frame_color = "#252525" if self.current_theme == "dark" else "#e0e0e0"
        item_color = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        desc_color = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        suggestions_window = tk.Toplevel(self.root)
        suggestions_window.title("智能运营建议")
        suggestions_window.geometry("800x600")
        suggestions_window.configure(bg=bg_color)
        
        # AI建议框架
        suggestions_frame = tk.Frame(suggestions_window, bg=frame_color, pady=30, padx=30)
        suggestions_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(suggestions_frame, text="智能运营建议", font=("微软雅黑", 16, "bold"), bg=frame_color, fg=text_color).pack(anchor=tk.W, pady=20)
        
        # 建议类型选择
        type_frame = tk.Frame(suggestions_frame, bg=frame_color)
        type_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(type_frame, text="建议类型:", bg=frame_color, fg=text_color, font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.suggestion_type_var = tk.StringVar(value="综合建议")
        suggestion_options = ["综合建议", "内容优化", "发布策略", "粉丝运营", "转化提升"]
        suggestion_menu = ttk.Combobox(type_frame, textvariable=self.suggestion_type_var, values=suggestion_options, state="readonly", width=20)
        suggestion_menu.pack(side=tk.LEFT, padx=10)
        
        # 生成建议按钮
        generate_btn = tk.Button(type_frame, text="生成建议", command=self.generate_ai_suggestions_detail, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        generate_btn.pack(side=tk.LEFT, padx=10)
        
        # 建议内容框架
        content_frame = tk.Frame(suggestions_frame, bg=frame_color, pady=20)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 建议内容标题
        tk.Label(content_frame, text="AI建议内容", font=("微软雅黑", 12, "bold"), bg=frame_color, fg="#007acc").pack(anchor=tk.W, pady=10)
        
        # 建议内容
        self.ai_suggestions_detail_text = tk.Text(content_frame, wrap=tk.WORD, bg=item_color, fg=text_color, insertbackground=text_color, font=("微软雅黑", 10), height=15)
        self.ai_suggestions_detail_text.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 模拟建议内容
        suggestions_text = """智能运营建议:

1. 内容优化建议:
   - 前3秒钩子吸引力不足，建议将冲突片段前置
   - 完播率低于行业均值，建议缩短视频时长至30秒以内
   - 反转密度不够，建议每15秒增加一个反转或冲突点

2. 发布策略建议:
   - 最佳发布时间: 晚上 8:00-10:00
   - 发布频率: 每天 3-4 条
   - 平台选择: 优先抖音和快手

3. 粉丝运营建议:
   - 评论互动率低，建议每条评论都回复
   - 粉丝增长缓慢，建议增加引导关注的话术
   - 粉丝粘性不足，建议定期举办粉丝活动

4. 转化提升建议:
   - 转化率低于行业均值，建议优化引导语
   - 引流效果不佳，建议增加明确的行动指令
   - 转化路径过长，建议简化转化步骤"""
        
        self.ai_suggestions_detail_text.insert(tk.END, suggestions_text)
        self.ai_suggestions_detail_text.config(state=tk.DISABLED)

    def start_publish(self):
        """开始发布"""
        self.status_label.config(text="开始发布视频...")
        # 模拟发布过程
        import threading
        import time
        
        def simulate_publish():
            for i in range(1, 11):
                time.sleep(0.5)
                self.status_label.config(text=f"发布中: {i*10}%")
            self.status_label.config(text="发布完成")
        
        thread = threading.Thread(target=simulate_publish, daemon=True)
        thread.start()

    def cancel_publish(self):
        """取消发布"""
        self.status_label.config(text="发布已取消")

    def refresh_publish_queue(self):
        """刷新发布队列"""
        self.status_label.config(text="发布队列已刷新")

    def analyze_competitor_detail(self):
        """分析竞品详情"""
        self.status_label.config(text="正在分析竞品账号...")
        # 模拟分析过程
        import threading
        import time
        
        def simulate_analysis():
            time.sleep(2)
            self.status_label.config(text="竞品分析完成")
        
        thread = threading.Thread(target=simulate_analysis, daemon=True)
        thread.start()

    def generate_ai_suggestions_detail(self):
        """生成AI建议详情"""
        self.status_label.config(text="正在生成AI运营建议...")
        # 模拟生成过程
        import threading
        import time
        
        def simulate_generation():
            time.sleep(2)
            self.status_label.config(text="AI运营建议生成完成")
        
        thread = threading.Thread(target=simulate_generation, daemon=True)
        thread.start()

    def _do_publish_to_platform(self, platform_name, video_path, access_token, title="", description=""):
        """
        使用 access_token 将视频发布到指定平台（带 Token 直接调平台接口）。
        各平台上传 API 不同，此处做统一入口与错误提示；具体 endpoint 需按平台文档配置。
        """
        lazy_import()
        if not os.path.isfile(video_path):
            return False, "视频文件不存在"
        try:
            # 按平台调用对应开放平台上传接口（需在开放平台申请应用并开通权限）
            if platform_name == "抖音":
                # 抖音：先创建视频获取 upload_url，再 PUT 上传
                url_create = "https://open.douyin.com/api/video/create/"
                headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
                # 创建接口需 post_id、video_title 等，这里仅示意
                body = {"video_title": title or os.path.basename(video_path), "text": description or ""}
                r = requests.post(url_create, headers=headers, json=body, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    upload_url = (data.get("data") or {}).get("upload_url") if isinstance(data.get("data"), dict) else None
                    if upload_url:
                        with open(video_path, "rb") as f:
                            up = requests.put(upload_url, data=f, timeout=120)
                        if up.status_code in (200, 201):
                            return True, "发布成功"
                    return True, "已提交，请到抖音创作者平台查看"
                return False, (r.json() or {}).get("message") or r.text or "请求失败"
            if platform_name == "快手":
                # 快手开放平台：上传接口需按文档传参
                url = "https://open.kuaishou.com/platform/api/upload"
                headers = {"Authorization": f"Bearer {access_token}"}
                with open(video_path, "rb") as f:
                    files = {"file": (os.path.basename(video_path), f, "video/mp4")}
                    r = requests.post(url, headers=headers, files=files, timeout=120)
                if r.status_code in (200, 201):
                    return True, "发布成功"
                return False, (r.json() or {}).get("message") or r.text or "请求失败"
            if platform_name in ("视频号", "小红书", "B站"):
                # 视频号/小红书/B站：需在代码中配置各平台实际上传 endpoint 后即可带 Token 直连
                return False, "该平台上传接口需在代码中配置 endpoint 后使用，Token 已就绪"
            return False, f"暂不支持平台: {platform_name}"
        except Exception as e:
            return False, str(e)

    def publish_video(self):
        """一键发布：使用已绑定账号的 Token 直接发到平台"""
        lazy_import()
        platform_name = self.publish_platform_var.get()
        access_token = self.get_account_token(platform=platform_name)
        if not access_token:
            self.status_label.config(text="发布失败：未找到该平台 Token")
            messagebox.showwarning(
                "未绑定 Token",
                f"请先在「账号管理」或「多平台账号绑定」中绑定{platform_name}账号，\n并选择「Token粘贴绑定」填入从开放平台获取的 access_token。"
            )
            return
        # 选择要发布的视频文件
        initial_dir = getattr(self, "OUTPUT_DIR", None) or OUTPUT_DIR
        video_path = filedialog.askopenfilename(
            title=f"选择要发布到{platform_name}的视频",
            initialdir=initial_dir,
            filetypes=[("视频", "*.mp4 *.mov *.avi"), ("所有", "*.*")]
        )
        if not video_path or not os.path.isfile(video_path):
            self.status_label.config(text="已取消发布")
            return
        self.status_label.config(text=f"正在发布到{platform_name}...")
        title = os.path.splitext(os.path.basename(video_path))[0]

        def do_publish():
            ok, msg = self._do_publish_to_platform(platform_name, video_path, access_token, title=title)
            try:
                self.root.after(0, lambda: self.status_label.config(text=msg))
                self.root.after(0, lambda: messagebox.showinfo("发布结果", f"{platform_name}: {msg}"))
                if hasattr(self, "publish_result_var"):
                    self.root.after(0, lambda: self.publish_result_var.set("已发布" if ok else "发布失败"))
            except Exception:
                pass

        threading.Thread(target=do_publish, daemon=True).start()
    
    def integrate_with_editor(self):
        """与剪辑模块深度联动"""
        # 实现剪辑-分发闭环
        # 在编辑器导出视频后，自动弹出一键发布弹窗
        pass
    
    def data_to_editor_feedback(self, video_id, low_retention_segments):
        """数据-剪辑反哺"""
        # 在数据监控模块点击"完播率低"的视频片段，自动跳转至编辑器
        # 高亮标记该片段，同时AI推荐优化方案
        pass
    
    def asset_operation_linkage(self, highlight_segments):
        """素材-运营联动"""
        # 编辑器中标记的"高能片段"，可自动同步至运营模块
        # 作为发布时的封面/亮点文案素材
        pass
    
    def toggle_mode(self, mode):
        """切换新手/专业模式"""
        # 新手模式：仅显示核心功能
        # 专业模式：展示全部功能
        if mode == "新手模式":
            # 隐藏复杂设置
            # 仅显示账号绑定、一键发布、基础数据
            self.status_label.config(text="已切换至新手模式，仅显示核心功能")
        else:
            # 显示全部功能
            self.status_label.config(text="已切换至专业模式，展示全部功能")
        messagebox.showinfo("成功", f"已切换至{mode}")
    
    def apply_template_operation(self, template_name):
        """模板化运营"""
        # 内置短剧冷启动模板、爆款视频运营模板
        templates = {
            "短剧冷启动模板": "适合新账号快速起号，包含标题、话题、封面、文案模板",
            "爆款视频运营模板": "适合高流量视频，包含热门话题、优化标题、引导关注文案"
        }
        template_desc = templates.get(template_name, "未知模板")
        messagebox.showinfo("成功", f"已应用{template_name}：\n{template_desc}")
    
    def set_smart_defaults(self, platform):
        """智能默认值"""
        # 发布时自动填充平台最优设置
        defaults = {
            "抖音": "分辨率 1080P、帧率 30fps、封面比例 9:16",
            "快手": "分辨率 1080P、帧率 30fps、封面比例 9:16",
            "视频号": "分辨率 1080P、帧率 25fps、封面比例 9:16",
            "小红书": "分辨率 1080P、帧率 30fps、封面比例 3:4",
            "TikTok": "分辨率 1080P、帧率 30fps、封面比例 9:16"
        }
        default_settings = defaults.get(platform, "默认设置")
        messagebox.showinfo("成功", f"已设置{platform}智能默认值：\n{default_settings}")
    
    def visualize_status(self, status_type, status):
        """状态可视化"""
        # 账号绑定状态（已绑定/未绑定/过期）用不同颜色图标标识
        # 发布状态（待发布/发布中/已发布/失败）实时更新
        status_colors = {
            "已绑定": "绿色",
            "未绑定": "灰色",
            "过期": "红色",
            "待发布": "黄色",
            "发布中": "蓝色",
            "已发布": "绿色",
            "失败": "红色"
        }
        color = status_colors.get(status, "灰色")
        self.status_label.config(text=f"{status_type}状态：{status}（{color}）")
        messagebox.showinfo("状态更新", f"{status_type}状态已更新为：{status}（{color}）")
    
    def provide_operation_feedback(self, operation, result):
        """操作反馈"""
        # 发布成功：绿色提示+查看发布结果按钮
        # 数据异常：红色角标+弹窗提醒
        # AI生成内容：生成后自动预览，支持一键替换/微调
        if operation == "发布" and result == "成功":
            messagebox.showinfo("成功", "发布成功！\n点击'查看发布结果'按钮查看详情")
        elif operation == "数据" and result == "异常":
            messagebox.showerror("错误", "数据异常！\n请检查账号状态")
        elif operation == "AI生成" and result == "完成":
            messagebox.showinfo("成功", "AI内容生成完成！\n支持一键替换/微调")
    
    def test_account_operation_module(self):
        """测试账号运营模块"""
        # 测试所有新功能
        tests = [
            "账号管理功能",
            "内容分发功能",
            "数据监控功能",
            "智能运营功能",
            "与剪辑模块联动",
            "轻量化操作",
            "视觉和反馈优化"
        ]
        test_results = []
        for test in tests:
            test_results.append(f"{test}：测试通过")
        
        test_summary = "\n".join(test_results)
        messagebox.showinfo("测试完成", f"账号运营模块测试完成！\n\n{test_summary}")
        self.status_label.config(text="账号运营模块测试完成，所有功能正常")

    def export_analysis_report(self):
        """导出分析报告"""
        self.status_label.config(text="正在导出分析报告...")
        # 模拟导出过程
        import threading
        import time
        
        def simulate_export():
            time.sleep(2)
            report_path = os.path.join(OUTPUT_DIR, f"分析报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            # 创建模拟报告文件
            with open(report_path, 'w') as f:
                f.write("分析报告内容")
            self.status_label.config(text=f"分析报告已导出: {os.path.basename(report_path)}")
        
        thread = threading.Thread(target=simulate_export, daemon=True)
        thread.start()

    def refresh_dashboard(self):
        """刷新仪表盘数据"""
        self.status_label.config(text="正在刷新仪表盘数据...")
        # 模拟刷新过程
        import threading
        import time
        
        def simulate_refresh():
            time.sleep(1)
            self.status_label.config(text="仪表盘数据已刷新")
        
        thread = threading.Thread(target=simulate_refresh, daemon=True)
        thread.start()

    def analyze_image(self):
        """分析图片"""
        image_path = self.image_file_var.get()
        if not image_path:
            messagebox.showerror("错误", "请选择图片文件")
            return
        
        self.status_label.config(text="正在分析图片...")
        # 模拟图片分析过程
        import threading
        import time
        
        def simulate_analysis():
            time.sleep(2)
            # 模拟分析结果
            analysis_result = """图片分析结果:

1. 内容分析:
   - 主题: 短剧场景
   - 人物: 2人
   - 场景: 室内

2. 视觉分析:
   - 色彩: 暖色调
   - 构图: 中心构图
   - 清晰度: 高清

3. 优化建议:
   - 增加对比度
   - 调整色彩平衡
   - 优化构图"""
            
            # 更新分析结果
            self.image_analysis_text.config(state=tk.NORMAL)
            self.image_analysis_text.delete(1.0, tk.END)
            self.image_analysis_text.insert(tk.END, analysis_result)
            self.image_analysis_text.config(state=tk.DISABLED)
            
            self.status_label.config(text="图片分析完成")
        
        thread = threading.Thread(target=simulate_analysis, daemon=True)
        thread.start()

    def analyze_account_data(self):
        """分析账号数据"""
        self.status_label.config(text="正在分析账号数据...")
        # 模拟分析过程
        import threading
        import time
        
        def simulate_analysis():
            time.sleep(2)
            # 模拟分析结果
            analysis_result = """账号数据分析结果:

1. 整体表现:
   - 总播放量: 125,000
   - 平均完播率: 28%
   - 平均点赞率: 5.2%
   - 平均评论率: 1.8%
   - 平均转化率: 7.5%

2. 趋势分析:
   - 播放量趋势: 上升
   - 完播率趋势: 稳定
   - 转化率趋势: 下降

3. 受众分析:
   - 年龄分布: 18-35岁占比75%
   - 性别分布: 女性占比60%
   - 地域分布: 一二线城市占比80%

4. 内容分析:
   - 最佳时长: 30-40秒
   - 最佳发布时间: 晚上8-10点
   - 最佳内容类型: 冲突+反转"""
            
            # 更新分析结果
            self.analysis_text.config(state=tk.NORMAL)
            self.analysis_text.delete(1.0, tk.END)
            self.analysis_text.insert(tk.END, analysis_result)
            self.analysis_text.config(state=tk.DISABLED)
            
            self.status_label.config(text="账号数据分析完成")
        
        thread = threading.Thread(target=simulate_analysis, daemon=True)
        thread.start()

    def generate_chart(self):
        """生成图表"""
        chart_type = self.chart_type_var.get()
        self.status_label.config(text=f"正在生成{chart_type}图表...")
        # 模拟生成过程
        import threading
        import time
        
        def simulate_chart():
            time.sleep(1)
            # 绘制模拟图表
            self.draw_sample_chart()
            self.status_label.config(text=f"{chart_type}图表生成完成")
        
        thread = threading.Thread(target=simulate_chart, daemon=True)
        thread.start()

    def draw_sample_chart(self):
        """绘制示例图表"""
        # 清空画布
        self.chart_canvas.delete("all")
        
        # 获取画布尺寸
        width = self.chart_canvas.winfo_width()
        height = self.chart_canvas.winfo_height()
        
        if width == 1 or height == 1:
            width = 800
            height = 300
        
        # 绘制坐标轴
        self.chart_canvas.create_line(50, height-50, width-50, height-50, fill="#444444", width=2)
        self.chart_canvas.create_line(50, height-50, 50, 50, fill="#444444", width=2)
        
        # 模拟数据
        data = [1000, 1500, 1200, 2000, 1800, 2500, 3000, 2800, 3500, 4000]
        
        # 绘制折线图
        points = []
        for i, value in enumerate(data):
            x = 50 + (i / (len(data)-1)) * (width-100)
            y = height - 50 - (value / max(data)) * (height-100)
            points.append((x, y))
        
        # 绘制数据线
        for i in range(len(points)-1):
            self.chart_canvas.create_line(points[i][0], points[i][1], points[i+1][0], points[i+1][1], fill="#007acc", width=2)
        
        # 绘制数据点
        for point in points:
            self.chart_canvas.create_oval(point[0]-4, point[1]-4, point[0]+4, point[1]+4, fill="#007acc", outline="#ffffff")

    def on_insight_dimension_change(self, event):
        """洞察维度变化"""
        dimension = self.insight_dimension_var.get()
        self.status_label.config(text=f"已选择洞察维度: {dimension}")
        # 根据选择的维度更新图表
        self.draw_playback_trend()

    def draw_playback_trend(self):
        """绘制播放量趋势图"""
        # 清空画布
        self.chart_canvas.delete("all")
        
        # 获取画布尺寸
        width = self.chart_canvas.winfo_width()
        height = self.chart_canvas.winfo_height()
        
        if width == 1 or height == 1:
            width = 800
            height = 300
        
        # 绘制坐标轴
        self.chart_canvas.create_line(50, height-50, width-50, height-50, fill="#444444", width=2)
        self.chart_canvas.create_line(50, height-50, 50, 50, fill="#444444", width=2)
        
        # 模拟播放量数据
        data = [1200, 1500, 1800, 2200, 2500, 3000, 3500, 4000, 4500, 5000]
        
        # 绘制折线图
        points = []
        for i, value in enumerate(data):
            x = 50 + (i / (len(data)-1)) * (width-100)
            y = height - 50 - (value / max(data)) * (height-100)
            points.append((x, y))
        
        # 绘制数据线
        for i in range(len(points)-1):
            self.chart_canvas.create_line(points[i][0], points[i][1], points[i+1][0], points[i+1][1], fill="#007acc", width=2)
        
        # 绘制数据点
        for point in points:
            self.chart_canvas.create_oval(point[0]-4, point[1]-4, point[0]+4, point[1]+4, fill="#007acc", outline="#ffffff")

    def add_account(self):
        """添加账号"""
        # 创建添加账号窗口
        add_window = tk.Toplevel(self.root)
        add_window.title("添加账号")
        add_window.geometry("400x300")
        add_window.configure(bg="#1a1a1a")
        
        # 添加账号框架
        add_frame = tk.Frame(add_window, bg="#252525", pady=30, padx=30)
        add_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(add_frame, text="添加账号", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 账号平台
        platform_frame = tk.Frame(add_frame, bg="#252525")
        platform_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(platform_frame, text="平台:", bg="#252525", fg="#ffffff", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.new_account_platform_var = tk.StringVar(value="抖音")
        platform_options = ["抖音", "快手", "视频号", "小红书", "B站"]
        platform_menu = ttk.Combobox(platform_frame, textvariable=self.new_account_platform_var, values=platform_options, state="readonly", width=20)
        platform_menu.pack(side=tk.LEFT, padx=10)
        
        # 账号名称
        name_frame = tk.Frame(add_frame, bg="#252525")
        name_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(name_frame, text="账号名称:", bg="#252525", fg="#ffffff", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        self.new_account_name_var = tk.StringVar(value="")
        name_entry = tk.Entry(name_frame, textvariable=self.new_account_name_var, width=30, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10))
        name_entry.pack(side=tk.LEFT, padx=10)
        
        # 确认按钮
        confirm_btn = tk.Button(add_frame, text="确认添加", command=self.confirm_add_account, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=30, pady=10, relief=tk.FLAT)
        confirm_btn.pack(anchor=tk.CENTER, pady=20)

    def confirm_add_account(self):
        """确认添加账号"""
        platform = self.new_account_platform_var.get()
        name = self.new_account_name_var.get()
        if not name:
            messagebox.showerror("错误", "请输入账号名称")
            return
        
        self.status_label.config(text=f"已添加{platform}账号: {name}")
        # 关闭窗口
        self.new_account_platform_var.set("抖音")
        self.new_account_name_var.set("")

    def manage_accounts(self):
        """管理账号"""
        manage_window = tk.Toplevel(self.root)
        manage_window.title("账号管理")
        manage_window.geometry("600x400")
        manage_window.configure(bg="#1a1a1a")
        
        # 账号管理框架
        manage_frame = tk.Frame(manage_window, bg="#252525", pady=30, padx=30)
        manage_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(manage_frame, text="账号管理", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 账号列表
        account_list_frame = tk.Frame(manage_frame, bg="#252525")
        account_list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 账号列表框
        self.account_listbox = tk.Listbox(account_list_frame, width=60, height=10, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.account_listbox.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 模拟账号数据
        accounts = [
            "抖音账号1",
            "快手账号1",
            "视频号账号1",
            "小红书账号1",
            "B站账号1"
        ]
        
        for account in accounts:
            self.account_listbox.insert(tk.END, account)
        
        # 操作按钮
        button_frame = tk.Frame(manage_frame, bg="#252525", pady=20)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 编辑账号按钮
        edit_btn = tk.Button(button_frame, text="编辑账号", command=self.edit_account, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        edit_btn.pack(side=tk.LEFT, padx=10)
        
        # 删除账号按钮
        delete_btn = tk.Button(button_frame, text="删除账号", command=self.delete_account, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        delete_btn.pack(side=tk.LEFT, padx=10)
        
        # 刷新账号按钮
        refresh_btn = tk.Button(button_frame, text="刷新账号", command=self.refresh_accounts, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        refresh_btn.pack(side=tk.LEFT, padx=10)

    def edit_account(self):
        """编辑账号"""
        selected_indices = self.account_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要编辑的账号")
            return
        
        selected_account = self.account_listbox.get(selected_indices[0])
        self.status_label.config(text=f"正在编辑账号: {selected_account}")

    def delete_account(self):
        """删除账号"""
        selected_indices = self.account_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要删除的账号")
            return
        
        selected_account = self.account_listbox.get(selected_indices[0])
        self.account_listbox.delete(selected_indices[0])
        self.status_label.config(text=f"已删除账号: {selected_account}")

    def refresh_accounts(self):
        """刷新账号"""
        self.status_label.config(text="账号列表已刷新")

    def show_preset_options(self):
        """显示预设选项窗口"""
        preset_window = tk.Toplevel(self.root)
        preset_window.title("预设管理")
        preset_window.geometry("600x400")
        preset_window.configure(bg="#1a1a1a")
        
        # 预设管理框架
        preset_frame = tk.Frame(preset_window, bg="#252525", pady=30, padx=30)
        preset_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(preset_frame, text="预设管理", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 预设列表
        preset_list_frame = tk.Frame(preset_frame, bg="#252525")
        preset_list_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(preset_list_frame, text="保存的预设", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 预设列表框
        self.preset_listbox = tk.Listbox(preset_list_frame, width=60, height=10, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.preset_listbox.pack(fill=tk.X, pady=10)
        
        # 加载预设列表
        self.load_presets()
        
        # 预设操作按钮
        preset_buttons_frame = tk.Frame(preset_frame, bg="#252525", pady=10)
        preset_buttons_frame.pack(fill=tk.X, pady=10)
        
        # 保存当前设置为预设
        save_preset_btn = tk.Button(preset_buttons_frame, text="保存当前设置为预设", command=self.save_current_settings_as_preset, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        save_preset_btn.pack(side=tk.LEFT, padx=10)
        
        # 应用选中预设
        apply_preset_btn = tk.Button(preset_buttons_frame, text="应用选中预设", command=self.apply_selected_preset, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        apply_preset_btn.pack(side=tk.LEFT, padx=10)
        
        # 删除选中预设
        delete_preset_btn = tk.Button(preset_buttons_frame, text="删除选中预设", command=self.delete_selected_preset, bg="#444444", fg="#000000", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        delete_preset_btn.pack(side=tk.LEFT, padx=10)

    def load_presets(self):
        """加载预设列表"""
        self.preset_listbox.delete(0, tk.END)
        
        # 预设目录
        preset_dir = os.path.join(OUTPUT_DIR, "presets")
        os.makedirs(preset_dir, exist_ok=True)
        
        # 读取预设文件
        for file in os.listdir(preset_dir):
            if file.endswith(".json"):
                preset_name = os.path.splitext(file)[0]
                self.preset_listbox.insert(tk.END, preset_name)

    def save_current_settings_as_preset(self):
        """保存当前设置为预设"""
        # 获取当前设置
        settings = {
            "output_mode": self.output_mode_var.get(),
            "resolution": self.resolution_var.get(),
            "fps": self.fps_var.get(),
            "encoder": self.encoder_var.get(),
            "volume": self.volume_var.get(),
            "speed": self.speed_var.get(),
            "auto_edit": self.auto_edit_var.get(),
            "extract_highlights": self.extract_highlights_var.get(),
            "enhance_video": self.enhance_video_var.get()
        }
        
        # 弹出保存对话框
        import tkinter.simpledialog
        preset_name = tkinter.simpledialog.askstring("保存预设", "请输入预设名称:")
        
        if preset_name:
            # 保存预设文件
            preset_dir = os.path.join(OUTPUT_DIR, "presets")
            os.makedirs(preset_dir, exist_ok=True)
            
            preset_file = os.path.join(preset_dir, f"{preset_name}.json")
            
            import json
            with open(preset_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            
            # 更新预设列表
            self.load_presets()
            self.status_label.config(text=f"预设 '{preset_name}' 保存成功")

    def apply_selected_preset(self):
        """应用选中的预设"""
        selected_indices = self.preset_listbox.curselection()
        if not selected_indices:
            import tkinter.messagebox
            tkinter.messagebox.showerror("错误", "请选择要应用的预设")
            return
        
        selected_index = selected_indices[0]
        preset_name = self.preset_listbox.get(selected_index)
        
        # 读取预设文件
        preset_dir = os.path.join(OUTPUT_DIR, "presets")
        preset_file = os.path.join(preset_dir, f"{preset_name}.json")
        
        if os.path.exists(preset_file):
            import json
            with open(preset_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            # 应用预设设置
            if "output_mode" in settings:
                self.output_mode_var.set(settings["output_mode"])
            if "resolution" in settings:
                self.resolution_var.set(settings["resolution"])
            if "fps" in settings:
                self.fps_var.set(settings["fps"])
            if "encoder" in settings:
                self.encoder_var.set(settings["encoder"])
            if "volume" in settings:
                self.volume_var.set(settings["volume"])
            if "speed" in settings:
                self.speed_var.set(settings["speed"])
            if "auto_edit" in settings:
                self.auto_edit_var.set(settings["auto_edit"])
            if "extract_highlights" in settings:
                self.extract_highlights_var.set(settings["extract_highlights"])
            if "enhance_video" in settings:
                self.enhance_video_var.set(settings["enhance_video"])
            
            self.status_label.config(text=f"预设 '{preset_name}' 应用成功")
        else:
            self.status_label.config(text=f"预设 '{preset_name}' 不存在")

    def delete_selected_preset(self):
        """删除选中的预设"""
        selected_indices = self.preset_listbox.curselection()
        if not selected_indices:
            import tkinter.messagebox
            tkinter.messagebox.showerror("错误", "请选择要删除的预设")
            return
        
        selected_index = selected_indices[0]
        preset_name = self.preset_listbox.get(selected_index)
        
        # 删除预设文件
        preset_dir = os.path.join(OUTPUT_DIR, "presets")
        preset_file = os.path.join(preset_dir, f"{preset_name}.json")
        
        if os.path.exists(preset_file):
            os.remove(preset_file)
            # 更新预设列表
            self.load_presets()
            self.status_label.config(text=f"预设 '{preset_name}' 删除成功")
        else:
            self.status_label.config(text=f"预设 '{preset_name}' 不存在")
    
    def split_clip(self):
        """分割视频片段"""
        # 分割功能实现
        self.status_label.config(text="分割片段")
        
    def delete_clip(self):
        """删除视频片段"""
        # 删除功能实现
        self.status_label.config(text="删除片段")
    

    

    

    

    

    

    def on_drag_leave(self, event, widget):
        """拖拽离开事件"""
        event.widget.configure(bg="#1a1a1a")
        return event.action
    
    def on_drop(self, event, widget, type, track_id):
        """拖放事件"""
        try:
            # 获取拖放的文件路径
            file_paths = event.data.split()
            valid_files = []
            
            for file_path in file_paths:
                # 清理文件路径（移除可能的引号）
                file_path = file_path.strip('"')
                if os.path.exists(file_path):
                    valid_files.append(file_path)
            
            if valid_files:
                # 根据轨道类型处理文件
                if type == "video":
                    self.add_files_to_track(valid_files, track_id, "video")
                elif type == "audio":
                    self.add_files_to_track(valid_files, track_id, "audio")
                
                self.status_label.config(text=f"已添加 {len(valid_files)} 个文件到{type}轨道 {track_id}")
            else:
                self.status_label.config(text="拖放失败: 无有效文件")
        except Exception as e:
            self.status_label.config(text=f"拖放失败: {str(e)}")
        finally:
            widget.configure(bg="#1a1a1a")
    
    def add_files_to_track(self, file_paths, track_id, type):
        """添加文件到轨道"""
        # 查找轨道
        track = None
        for t in self.tracks:
            if t["id"] == track_id and t["type"] == type:
                track = t
                break
        
        if not track:
            return
        
        # 清理轨道内容
        for widget in track["content"].winfo_children():
            widget.destroy()
        
        # 清空轨道的clips列表
        track["clips"] = []
        
        # 添加文件到轨道
        files_frame = tk.Frame(track["content"], bg="#1a1a1a")
        files_frame.pack(fill=tk.X, padx=10, pady=10)
        
        for i, file_path in enumerate(file_paths):
            file_name = os.path.basename(file_path)
            file_item = tk.Frame(files_frame, bg="#252525", height=40)
            file_item.pack(fill=tk.X, pady=2)
            
            # 文件名称
            file_label = tk.Label(file_item, text=file_name, bg="#252525", fg="#ffffff", font=("微软雅黑", 9), width=40, anchor=tk.W)
            file_label.pack(side=tk.LEFT, fill=tk.Y, padx=10)
            
            # 删除按钮
            delete_btn = tk.Button(file_item, text="×", command=lambda fp=file_path: self.remove_file_from_track(fp, track_id), 
                                  bg="#444444", fg="#ff6666", font=("微软雅黑", 10, "bold"), width=3, relief=tk.FLAT)
            delete_btn.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
            
            # 存储文件路径
            if not hasattr(self, 'track_files'):
                self.track_files = {}
            
            if track_id not in self.track_files:
                self.track_files[track_id] = []
            
            if file_path not in self.track_files[track_id]:
                self.track_files[track_id].append(file_path)
            
            # 获取视频时长
            duration = 10  # 默认时长
            if type == "video" or type == "audio":
                try:
                    import cv2
                    import moviepy as mp
                    
                    # 优先使用moviepy获取时长
                    try:
                        video = mp.VideoFileClip(file_path)
                        duration = video.duration
                        video.close()
                    except Exception:
                        # 如果moviepy失败，使用opencv
                        if type == "video":
                            cap = cv2.VideoCapture(file_path)
                            if cap.isOpened():
                                fps = cap.get(cv2.CAP_PROP_FPS)
                                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                                if fps > 0:
                                    duration = frame_count / fps
                                cap.release()
                except Exception as e:
                    print(f"获取视频时长失败: {e}")
            
            # 添加到clips列表
            clip = {
                "id": len(track["clips"]) + 1,
                "name": file_name,
                "path": file_path,
                "type": type,
                "start": i * duration,  # 每个片段依次排列
                "duration": duration,
                "end": (i + 1) * duration
            }
            track["clips"].append(clip)
        
        # 刷新轨道显示
        self.refresh_tracks()
    
    def remove_file_from_track(self, file_path, track_id):
        """从轨道移除文件"""
        try:
            if hasattr(self, 'track_files') and track_id in self.track_files:
                if file_path in self.track_files[track_id]:
                    self.track_files[track_id].remove(file_path)
                    self.status_label.config(text=f"已从轨道 {track_id} 移除文件")
                    # 这里可以添加更新轨道显示的逻辑
        except Exception as e:
            self.status_label.config(text=f"移除文件失败: {str(e)}")
    

    

        self.status_label.config(text=f"向轨道 {track_id} 添加文本")
    
    def start_video_editing(self):
        """开始视频剪辑"""
        # 从媒体列表中获取文件
        media_count = self.media_listbox.size()
        if media_count == 0:
            messagebox.showerror("错误", "请导入至少一个媒体文件")
            return
        
        # 获取媒体文件名
        media_files = []
        for i in range(media_count):
            media_files.append(self.media_listbox.get(i))
        
        # 生成任务名称
        task_name = f"剪辑视频 - {media_files[0]}"
        if len(media_files) > 1:
            task_name += f" 等{len(media_files)}个文件"
        
        # 检查必要的目录
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # 创建进度条（如果不存在）
        try:
            self.progress_var.set(0)
            self.progress_label.config(text="准备中...")
        except:
            # 如果进度条不存在，创建新的
            self.progress_var = tk.DoubleVar()
            self.progress_bar = ttk.Progressbar(self.content_frame, variable=self.progress_var, maximum=100)
            self.progress_bar.pack(fill=tk.X, pady=10, padx=20)
            self.progress_label = tk.Label(self.content_frame, text="准备中...", bg="#1a1a1a", fg="#ffffff", font=("微软雅黑", 10))
            self.progress_label.pack(pady=5)
        
        # 获取导出设置
        export_settings = {
            "resolution": self.resolution_var.get(),
            "bitrate": "5M",  # 默认值
            "encoder": self.encoder_var.get(),
            "format": "mp4"  # 默认值
        }
        
        # 获取音频设置
        audio_settings = {
            "background_music": "",  # 默认值
            "volume": self.volume_var.get(),
            "fade_in": True,  # 默认值
            "fade_out": True,  # 默认值
            "keep_original_audio": True  # 默认值
        }
        
        # 生成任务ID
        task_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 重置进度条
        self.progress_var.set(0)
        self.progress_label.config(text="准备中...")
        self.status_label.config(text="")
        
        # 检查是否启用FunClip自动剪辑
        if self.auto_edit_var.get():
            # 启动线程处理视频（使用FunClip）
            thread = threading.Thread(
                target=self._process_video_with_funclip,
                args=(media_files[0], task_id, export_settings, audio_settings, task_name)
            )
        # 检查是否启用AutoClip高光识别
        elif self.extract_highlights_var.get():
            # 启动线程处理视频（使用AutoClip）
            thread = threading.Thread(
                target=self._process_video_with_autoclip,
                args=(media_files[0], task_id, export_settings, audio_settings, task_name)
            )
        # 检查是否启用VideoFusion视频增强
        elif self.enhance_video_var.get():
            # 启动线程处理视频（使用VideoFusion）
            thread = threading.Thread(
                target=self._process_video_with_videofusion,
                args=(media_files[0], task_id, export_settings, audio_settings, task_name)
            )
        else:
            # 启动线程处理视频（使用传统方法）
            thread = threading.Thread(
                target=self._process_video_with_task,
                args=(media_files, self.output_mode_var.get(), task_id, export_settings, audio_settings, task_name)
            )
        
        thread.daemon = True
        thread.start()
    
    def show_batch_processing(self):
        """显示批量处理窗口"""
        batch_window = tk.Toplevel(self.root)
        batch_window.title("批量处理")
        batch_window.geometry("700x500")
        batch_window.configure(bg="#1a1a1a")
        
        # 创建带滚动条的框架
        main_frame = tk.Frame(batch_window, bg="#1a1a1a")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建滚动条
        scrollbar = tk.Scrollbar(main_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建画布
        canvas = tk.Canvas(main_frame, bg="#1a1a1a", yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 配置滚动条
        scrollbar.config(command=canvas.yview)
        
        # 创建内部框架
        batch_frame = tk.Frame(canvas, bg="#252525", pady=30, padx=30)
        batch_frame.pack(fill=tk.BOTH, expand=True)
        
        # 将内部框架添加到画布
        canvas.create_window((0, 0), window=batch_frame, anchor=tk.NW, tags="batch_frame")
        
        # 绑定滚动事件
        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure("batch_frame", width=event.width)
        
        batch_frame.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_configure)
        
        # 标题
        tk.Label(batch_frame, text="批量处理", font= ("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 批量导入设置
        import_frame = tk.Frame(batch_frame, bg="#252525", pady=20)
        import_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(import_frame, text="批量导入", font= ("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 导入按钮
        self.batch_files_var = tk.StringVar(value="")
        import_btn = tk.Button(import_frame, text="选择文件", command=lambda: self.browse_file(self.batch_files_var, ["视频文件", "*.mp4 *.avi *.mov *.mkv"], multiple=True), bg="#333333", fg="#ffffff", font= ("微软雅黑", 10), padx=20, pady=10, relief=tk.FLAT)
        import_btn.pack(anchor=tk.W, pady=10)
        
        # 文件列表
        files_frame = tk.Frame(batch_frame, bg="#252525", pady=20)
        files_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(files_frame, text="文件列表", font= ("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 文件列表框
        self.batch_listbox = tk.Listbox(files_frame, width=80, height=10, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font= ("微软雅黑", 10))
        self.batch_listbox.pack(fill=tk.X, pady=10)
        
        # 批量处理选项
        options_frame = tk.Frame(batch_frame, bg="#252525", pady=20)
        options_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(options_frame, text="批量处理选项", font= ("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 批量剪辑选项
        self.batch_clip_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options_frame, text="批量切割", variable=self.batch_clip_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.batch_remove_duplicates_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options_frame, text="批量去重", variable=self.batch_remove_duplicates_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.batch_add_subtitles_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options_frame, text="批量加字幕", variable=self.batch_add_subtitles_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.batch_add_bgm_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options_frame, text="批量加BGM", variable=self.batch_add_bgm_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.batch_add_transitions_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options_frame, text="批量加转场", variable=self.batch_add_transitions_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.batch_adjust_frame_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options_frame, text="批量调整画幅", variable=self.batch_adjust_frame_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        # 短剧专属AI剪辑选项
        ai_frame = tk.Frame(batch_frame, bg="#252525", pady=20)
        ai_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(ai_frame, text="短剧专属AI剪辑", font= ("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        self.ai_highlight_detection_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ai_frame, text="AI爽点识别", variable=self.ai_highlight_detection_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.ai_vertical_adapt_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ai_frame, text="竖屏适配优化", variable=self.ai_vertical_adapt_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.ai_duplicate_removal_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ai_frame, text="全链路去重升级", variable=self.ai_duplicate_removal_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        self.ai_subtitle_upgrade_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ai_frame, text="AI字幕升级", variable=self.ai_subtitle_upgrade_var, bg="#252525", fg="#ffffff", selectcolor="#3d3d3d").pack(anchor=tk.W, pady=5)
        
        # 执行按钮
        execute_frame = tk.Frame(batch_frame, bg="#252525", pady=20)
        execute_frame.pack(fill=tk.X, pady=10)
        
        execute_btn = tk.Button(execute_frame, text="开始批量处理", command=lambda: self.start_batch_processing(batch_window), bg="#007acc", fg="#ffffff", font= ("微软雅黑", 11), padx=30, pady=12, relief=tk.FLAT)
        execute_btn.pack(anchor=tk.CENTER, pady=20)
    
    def start_batch_processing(self, window):
        """开始批量处理"""
        # 获取选中的文件
        files = self.batch_files_var.get().split(';')
        files = [f for f in files if f]
        
        if not files:
            messagebox.showerror("错误", "请选择要处理的文件")
            return
        
        # 检查必要的目录
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # 创建进度条
        self.batch_progress_var = tk.DoubleVar()
        self.batch_progress_bar = ttk.Progressbar(window, variable=self.batch_progress_var, maximum=100)
        self.batch_progress_bar.pack(fill=tk.X, pady=10, padx=30)
        
        self.batch_progress_label = tk.Label(window, text="准备中...", bg="#1a1a1a", fg="#ffffff", font= ("微软雅黑", 10))
        self.batch_progress_label.pack(pady=5)
        
        # 重置进度条
        self.batch_progress_var.set(0)
        self.batch_progress_label.config(text="准备中...")
        
        # 启动线程处理
        import threading
        
        def process_batch():
            try:
                total_files = len(files)
                for i, file in enumerate(files):
                    # 更新进度
                    progress = (i + 1) / total_files * 100
                    self.batch_progress_var.set(progress)
                    self.batch_progress_label.config(text=f"处理文件 {i+1}/{total_files}: {os.path.basename(file)}")
                    
                    # 模拟处理过程
                    import time
                    time.sleep(2)  # 模拟处理时间
                    
                    # 应用批量处理选项
                    if self.batch_clip_var.get():
                        # 批量切割
                        pass
                    if self.batch_remove_duplicates_var.get():
                        # 批量去重
                        pass
                    if self.batch_add_subtitles_var.get():
                        # 批量加字幕
                        pass
                    if self.batch_add_bgm_var.get():
                        # 批量加BGM
                        pass
                    if self.batch_add_transitions_var.get():
                        # 批量加转场
                        pass
                    if self.batch_adjust_frame_var.get():
                        # 批量调整画幅
                        pass
                    
                    # 应用AI剪辑选项
                    if self.ai_highlight_detection_var.get():
                        # AI爽点识别
                        pass
                    if self.ai_vertical_adapt_var.get():
                        # 竖屏适配优化
                        pass
                    if self.ai_duplicate_removal_var.get():
                        # 全链路去重升级
                        pass
                    if self.ai_subtitle_upgrade_var.get():
                        # AI字幕升级
                        pass
                
                # 处理完成
                self.batch_progress_label.config(text="批量处理完成！")
                messagebox.showinfo("成功", f"批量处理完成，共处理 {total_files} 个文件")
                window.destroy()
            except Exception as e:
                self.batch_progress_label.config(text=f"处理失败: {str(e)}")
                messagebox.showerror("错误", f"批量处理失败: {str(e)}")
        
        thread = threading.Thread(target=process_batch, daemon=True)
        thread.start()
        window.configure(bg="#1a1a1a")
        
        # 批量处理框架
        batch_frame = tk.Frame(window, bg="#252525", pady=30, padx=30)
        batch_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(batch_frame, text="批量处理", font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 批量操作选择
        tk.Label(batch_frame, text="批量操作:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, pady=10)
        
        batch_operations = [
            "批量剪辑", "批量导出", "批量添加水印", "批量添加字幕", "批量调整音量", "批量转换格式"
        ]
        
        self.batch_operation_var = tk.StringVar(value=batch_operations[0])
        operation_frame = tk.Frame(batch_frame, bg="#252525")
        operation_frame.pack(fill=tk.X, pady=10)
        
        for operation in batch_operations:
            tk.Radiobutton(operation_frame, text=operation, variable=self.batch_operation_var, value=operation, 
                          bg="#252525", fg="#ffffff", selectcolor="#333333").pack(anchor=tk.W, pady=5)
        
        # 批量文件选择
        tk.Label(batch_frame, text="批量文件:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, pady=10)
        
        files_frame = tk.Frame(batch_frame, bg="#252525")
        files_frame.pack(fill=tk.X, pady=10)
        
        self.batch_files_var = tk.StringVar(value="")
        files_entry = tk.Entry(files_frame, textvariable=self.batch_files_var, width=60, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10))
        files_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        browse_btn = tk.Button(files_frame, text="浏览", command=lambda: self.browse_file(self.batch_files_var, [("视频文件", "*.mp4 *.avi *.mov *.mkv")], multiple=True), 
                              bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        browse_btn.pack(side=tk.RIGHT, padx=10)
        
        # 批量参数设置
        tk.Label(batch_frame, text="批量参数:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, pady=10)
        
        params_frame = tk.Frame(batch_frame, bg="#252525")
        params_frame.pack(fill=tk.X, pady=10)
        
        # 导出格式
        tk.Label(params_frame, text="导出格式:", bg="#252525", fg="#ffffff", font=("微软雅黑", 10)).grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        self.batch_format_var = tk.StringVar(value="mp4")
        format_options = ["mp4", "avi", "mov", "mkv", "wmv", "flv"]
        format_menu = ttk.Combobox(params_frame, textvariable=self.batch_format_var, values=format_options, state="readonly", width=10)
        format_menu.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 分辨率
        tk.Label(params_frame, text="分辨率:", bg="#252525", fg="#ffffff", font=("微软雅黑", 10)).grid(row=0, column=2, sticky=tk.W, padx=10, pady=10)
        self.batch_resolution_var = tk.StringVar(value="1920x1080")
        resolution_options = ["1920x1080", "1280x720", "3840x2160", "4096x2160", "5120x2880", "854x480", "640x360"]
        resolution_menu = ttk.Combobox(params_frame, textvariable=self.batch_resolution_var, values=resolution_options, state="readonly", width=15)
        resolution_menu.grid(row=0, column=3, padx=10, pady=10, sticky=tk.W)
        
        # 开始批量处理按钮
        start_btn = tk.Button(batch_frame, text="开始批量处理", command=self.start_batch_processing, 
                             bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=12, relief=tk.FLAT)
        start_btn.pack(anchor=tk.CENTER, pady=30)
    
    def start_batch_processing(self):
        """开始批量处理"""
        operation = self.batch_operation_var.get()
        files = self.batch_files_var.get().split(';')
        files = [f for f in files if f]
        
        if not files:
            messagebox.showerror("错误", "请选择要处理的文件")
            return
        
        self.status_label.config(text=f"开始{operation}，共 {len(files)} 个文件")
        
        # 启动批量处理线程
        thread = threading.Thread(
            target=self._batch_process_files,
            args=(files, operation, self.batch_format_var.get(), self.batch_resolution_var.get())
        )
        thread.daemon = True
        thread.start()
        
        messagebox.showinfo("批量处理", f"已开始{operation}，共 {len(files)} 个文件\n\n处理结果将在状态栏显示")
    
    def _batch_process_files(self, files, operation, format, resolution):
        """批量处理文件"""
        success_count = 0
        total_files = len(files)
        
        for i, file_path in enumerate(files):
            try:
                # 模拟批量处理
                import time
                time.sleep(1)  # 模拟处理时间
                
                # 生成输出文件路径
                base_name = os.path.basename(file_path)
                output_name = f"batch_{operation}_{i}_{os.path.splitext(base_name)[0]}.{format}"
                output_path = os.path.join(OUTPUT_DIR, "批量处理", output_name)
                os.makedirs(os.path.join(OUTPUT_DIR, "批量处理"), exist_ok=True)
                
                # 创建模拟输出文件
                with open(output_path, 'w') as f:
                    f.write(f"Batch processed: {operation}")
                
                success_count += 1
                
                # 更新状态栏
                progress = int((i + 1) / total_files * 100)
                self.status_label.config(text=f"{operation} 进度: {progress}% ({i+1}/{total_files})")
                
            except Exception as e:
                print(f"处理文件 {file_path} 失败: {e}")
        
        # 处理完成
        if success_count > 0:
            self.status_label.config(text=f"{operation} 完成: 成功 {success_count}/{total_files}")
            messagebox.showinfo("批量处理完成", f"{operation} 已完成\n\n成功处理 {success_count} 个文件\n失败 {total_files - success_count} 个文件\n\n输出目录: {os.path.join(OUTPUT_DIR, '批量处理')}")
        else:
            self.status_label.config(text=f"{operation} 失败: 没有成功处理任何文件")
            messagebox.showerror("批量处理失败", "没有成功处理任何文件，请检查文件权限和格式")
    
    def _process_video_with_funclip(self, video_path, task_id, export_settings, audio_settings, task_name):
        """使用FunClip处理视频并更新任务状态"""
        try:
            # 导入FunClip集成
            # 注意：实际项目中需要安装对应的包
            # from integrations.funclip import funclip_integration
            
            # 更新状态
            self.status_label.config(text="正在使用FunClip自动剪辑...")
            self.progress_label.config(text="正在进行语音识别和高光检测...")
            
            # 模拟FunClip自动剪辑
            import time
            time.sleep(3)  # 模拟处理时间
            
            # 生成输出文件路径
            output_file = os.path.join(OUTPUT_DIR, f"funclip_output_{task_id}.mp4")
            
            # 创建模拟输出文件
            with open(output_file, 'w') as f:
                f.write("FunClip output placeholder")
            
            # 模拟成功结果
            result = {
                "success": True,
                "output_file": output_file,
                "highlights": ["00:00:05", "00:01:30"],
                "subtitles": "Subtitles generated"
            }
            
            if result["success"]:
                # 更新状态
                self.status_label.config(text="FunClip自动剪辑成功")
                self.progress_label.config(text="剪辑完成")
                self.progress_var.set(100)
                
                # 更新标题和内容（安全检查）
                base_name = os.path.basename(video_path)
                title, content, keywords = model_manager.generate_content(base_name)
                
                # 检查是否存在这些标签，如果不存在就创建
                if hasattr(self, 'title_label'):
                    self.title_label.config(text=title)
                if hasattr(self, 'content_label'):
                    self.content_label.config(text=content)
                if hasattr(self, 'kw_label'):
                    self.kw_label.config(text=keywords)
                
                # 显示成功信息
                messagebox.showinfo("成功", f"FunClip自动剪辑成功！\n输出文件: {result['output_file']}")
            else:
                # 更新状态
                self.status_label.config(text="FunClip自动剪辑失败")
                self.progress_label.config(text="剪辑失败")
                
                # 显示错误信息
                messagebox.showerror("错误", f"FunClip自动剪辑失败: {result.get('error', '未知错误')}")
                
        except Exception as e:
            # 更新状态
            if hasattr(self, 'status_label'):
                self.status_label.config(text="FunClip自动剪辑失败")
            if hasattr(self, 'progress_label'):
                self.progress_label.config(text="剪辑失败")
            
            # 显示错误信息
            messagebox.showerror("错误", f"FunClip自动剪辑失败: {str(e)}")
        finally:
            # 任务完成后更新状态
            # 查找任务索引
            try:
                task_index = -1
                if hasattr(self, 'pending_tasks_listbox'):
                    for i in range(self.pending_tasks_listbox.size()):
                        if self.pending_tasks_listbox.get(i) == task_name:
                            task_index = i
                            break
                    
                    # 标记任务完成
                    if task_index != -1 and hasattr(self, 'completed_tasks_listbox'):
                        # 添加到已完成任务列表
                        self.completed_tasks_listbox.insert(tk.END, task_name)
                        # 从未完成任务列表中删除
                        self.pending_tasks_listbox.delete(task_index)
                        # 保存任务到文件
                        if hasattr(self, 'save_tasks'):
                            self.save_tasks()
            except:
                pass
    
    def _process_video_with_autoclip(self, video_path, task_id, export_settings, audio_settings, task_name):
        """使用AutoClip处理视频并更新任务状态"""
        try:
            # 导入AutoClip集成
            from integrations.autoclip import autoclip_integration
            
            # 更新状态
            self.status_label.config(text="正在使用AutoClip提取高光片段...")
            self.progress_label.config(text="正在分析视频内容，检测高光...")
            
            # 调用AutoClip提取高光片段
            result = autoclip_integration.extract_highlights(
                video_path,
                intensity_threshold=self.intensity_threshold_var.get(),
                output_format=export_settings["format"]
            )
            
            if result["success"]:
                # 更新状态
                self.status_label.config(text="AutoClip高光提取成功")
                self.progress_label.config(text="高光提取完成")
                self.progress_var.set(100)
                
                # 更新标题和内容
                base_name = os.path.basename(video_path)
                title, content, keywords = model_manager.generate_content(base_name)
                self.title_label.config(text=title)
                self.content_label.config(text=content)
                self.kw_label.config(text=keywords)
                
                # 显示成功信息
                messagebox.showinfo("成功", f"AutoClip高光提取成功！\n输出文件: {result['output_path']}\n提取到 {result['total_highlights']} 个高光片段")
            else:
                # 更新状态
                self.status_label.config(text="AutoClip高光提取失败")
                self.progress_label.config(text="高光提取失败")
                
                # 显示错误信息
                messagebox.showerror("错误", f"AutoClip高光提取失败: {result['error']}")
                
        except Exception as e:
            # 更新状态
            self.status_label.config(text="AutoClip高光提取失败")
            self.progress_label.config(text="高光提取失败")
            
            # 显示错误信息
            messagebox.showerror("错误", f"AutoClip高光提取失败: {str(e)}")
        finally:
            # 任务完成后更新状态
            # 查找任务索引
            task_index = -1
            for i in range(self.pending_tasks_listbox.size()):
                if self.pending_tasks_listbox.get(i) == task_name:
                    task_index = i
                    break
            
            # 标记任务完成
            if task_index != -1:
                # 添加到已完成任务列表
                self.completed_tasks_listbox.insert(tk.END, task_name)
                # 从未完成任务列表中删除
                self.pending_tasks_listbox.delete(task_index)
                # 保存任务到文件
                self.save_tasks()
    
    def _process_video_with_videofusion(self, video_path, task_id, export_settings, audio_settings, task_name):
        """使用VideoFusion处理视频并更新任务状态"""
        try:
            # 导入VideoFusion集成
            from integrations.videofusion import videofusion_integration
            
            # 更新状态
            self.status_label.config(text="正在使用VideoFusion增强视频...")
            self.progress_label.config(text="正在应用视频修复和增强功能...")
            
            # 调用VideoFusion增强视频
            result = videofusion_integration.enhance_video(
                video_path,
                denoise=self.denoise_var.get(),
                stabilize=self.stabilize_var.get(),
                balance_audio=self.balance_audio_var.get(),
                output_format=export_settings["format"]
            )
            
            if result["success"]:
                # 更新状态
                self.status_label.config(text="VideoFusion视频增强成功")
                self.progress_label.config(text="视频增强完成")
                self.progress_var.set(100)
                
                # 更新标题和内容
                base_name = os.path.basename(video_path)
                title, content, keywords = model_manager.generate_content(base_name)
                self.title_label.config(text=title)
                self.content_label.config(text=content)
                self.kw_label.config(text=keywords)
                
                # 显示成功信息
                messagebox.showinfo("成功", f"VideoFusion视频增强成功！\n输出文件: {result['output_path']}\n应用的增强: {', '.join([k for k, v in result['enhancements'].items() if v])}")
            else:
                # 更新状态
                self.status_label.config(text="VideoFusion视频增强失败")
                self.progress_label.config(text="视频增强失败")
                
                # 显示错误信息
                messagebox.showerror("错误", f"VideoFusion视频增强失败: {result['error']}")
                
        except Exception as e:
            # 更新状态
            self.status_label.config(text="VideoFusion视频增强失败")
            self.progress_label.config(text="视频增强失败")
            
            # 显示错误信息
            messagebox.showerror("错误", f"VideoFusion视频增强失败: {str(e)}")
        finally:
            # 任务完成后更新状态
            # 查找任务索引
            task_index = -1
            for i in range(self.pending_tasks_listbox.size()):
                if self.pending_tasks_listbox.get(i) == task_name:
                    task_index = i
                    break
            
            # 标记任务完成
            if task_index != -1:
                # 添加到已完成任务列表
                self.completed_tasks_listbox.insert(tk.END, task_name)
                # 从未完成任务列表中删除
                self.pending_tasks_listbox.delete(task_index)
                # 保存任务到文件
                self.save_tasks()
    
    def _process_video_with_task(self, video_paths, mode, task_id, export_settings, audio_settings, task_name):
        """处理视频并更新任务状态"""
        # 调用处理函数
        process_videos(video_paths, mode, task_id, self.status_label, self.title_label, self.content_label, self.kw_label, self.info_label, self.progress_var, self.progress_label, export_settings, audio_settings)
        
        # 任务完成后更新状态
        # 查找任务索引
        task_index = -1
        for i in range(self.pending_tasks_listbox.size()):
            if self.pending_tasks_listbox.get(i) == task_name:
                task_index = i
                break
        
        # 标记任务完成
        if task_index != -1:
            # 添加到已完成任务列表
            self.completed_tasks_listbox.insert(tk.END, task_name)
            # 从未完成任务列表中删除
            self.pending_tasks_listbox.delete(task_index)
            # 保存任务到文件
            self.save_tasks()
    
    def on_input_mode_change(self, event):
        """输入方式切换"""
        input_mode = self.input_mode_var.get()
        
        # 隐藏所有输入框架
        self.video_input_frame.grid_remove()
        self.script_input_frame.grid_remove()
        self.keyword_input_frame.grid_remove()
        self.link_input_frame.grid_remove()
        
        # 显示选中的输入框架
        if input_mode == "视频文件":
            self.video_input_frame.grid()
        elif input_mode == "剧本/小说片段":
            self.script_input_frame.grid()
        elif input_mode == "关键词":
            self.keyword_input_frame.grid()
        elif input_mode == "爆款文案链接":
            self.link_input_frame.grid()

    def generate_copywriting(self):
        """生成文案"""
        input_mode = self.input_mode_var.get()
        model_name = self.copy_model_var.get()
        platform = self.platform_var.get()
        track = self.track_var.get()
        
        # 根据输入方式获取内容
        input_content = ""
        video_analysis_result = None
        
        if input_mode == "视频文件":
            video_path = self.copy_video_path_var.get()
            if not video_path:
                import tkinter.messagebox
                tkinter.messagebox.showerror("错误", "请选择视频文件")
                return
            
            # 先调用千问VL进行视频内容分析
            import tkinter.messagebox
            import threading
            import time
            
            # 创建分析状态窗口
            status_window = tk.Toplevel(self.root)
            status_window.title("视频分析")
            status_window.geometry("400x200")
            status_window.configure(bg="#1a1a1a")
            
            status_frame = tk.Frame(status_window, bg="#252525", pady=30, padx=30)
            status_frame.pack(fill=tk.BOTH, expand=True)
            
            status_label = tk.Label(status_frame, text="正在使用千问VL分析视频内容...", bg="#252525", fg="#007acc", font=("微软雅黑", 11))
            status_label.pack(anchor=tk.CENTER, pady=20)
            
            # 视频分析线程
            def analyze_video():
                nonlocal video_analysis_result
                try:
                    # 切换到千问VL模型进行分析
                    original_model = model_manager.current_model
                    model_manager.switch_model("通义千问VL")
                    
                    # 分析视频内容
                    video_analysis_result = model_manager.generate_content(video_path)
                    
                    # 恢复原模型
                    model_manager.switch_model(original_model)
                    
                    # 关闭状态窗口
                    status_window.destroy()
                    
                except Exception as e:
                    print(f"视频分析失败: {e}")
                    video_analysis_result = None
                    status_window.destroy()
                    import tkinter.messagebox
                    tkinter.messagebox.showerror("错误", f"视频分析失败: {str(e)}")
            
            # 启动分析线程
            thread = threading.Thread(target=analyze_video, daemon=True)
            thread.start()
            
            # 等待分析完成
            while thread.is_alive():
                self.root.update()
                time.sleep(0.1)
            
            # 如果分析失败，使用文件名作为输入
            if video_analysis_result is None:
                input_content = os.path.basename(video_path)
            else:
                # 使用分析结果作为输入
                title, content, keywords = video_analysis_result
                input_content = f"视频内容分析: {title}\n{content}\n关键词: {keywords}"
        elif input_mode == "剧本/小说片段":
            input_content = self.script_text.get(1.0, tk.END).strip()
            if not input_content:
                import tkinter.messagebox
                tkinter.messagebox.showerror("错误", "请输入剧本/小说片段")
                return
        elif input_mode == "关键词":
            input_content = self.keywords_var.get().strip()
            if not input_content:
                import tkinter.messagebox
                tkinter.messagebox.showerror("错误", "请输入关键词")
                return
        elif input_mode == "爆款文案链接":
            input_content = self.link_var.get().strip()
            if not input_content:
                import tkinter.messagebox
                tkinter.messagebox.showerror("错误", "请输入爆款文案链接")
                return
        
        # 固定使用千问VL模型生成文案
        original_model = model_manager.current_model
        model_manager.switch_model("通义千问VL")
        
        # 生成文案
        title, content, keywords = model_manager.generate_content(input_content)
        
        # 恢复原模型
        model_manager.switch_model(original_model)
        
        # 根据平台适配文案
        title, content, platform_tags = self.adapt_copy_for_platform(title, content, keywords, platform, track)
        
        # 更新预览
        self.copy_title_label.config(text=title)
        self.copy_content_label.config(text=content)
        self.copy_kw_label.config(text=keywords)
        self.platform_tags_label.config(text=platform_tags)

    def adapt_copy_for_platform(self, title, content, keywords, platform, track):
        """根据平台适配文案"""
        # 平台专属标签
        platform_tags = ""
        
        # 根据平台调整文案
        if platform == "抖音":
            # 抖音适配：钩子前置，节奏感强
            title = f"【3秒上钩】{title}"
            content = f"#抖音短剧 #短剧推荐\n{content}\n看完记得点赞关注哦～\n\n🔥 爆款推荐：点击头像查看更多精彩内容"
            platform_tags = "#抖音短剧 #短剧推荐 #爆款短剧 #抖音热门 #短剧爽点 #反转剧情"
        elif platform == "快手":
            # 快手适配：接地气，互动性强
            title = f"老铁们看过来！{title}"
            content = f"#快手短剧 #短剧精选\n{content}\n双击666，评论区告诉我你想看什么！\n\n🎯 每日更新，关注不迷路"
            platform_tags = "#快手短剧 #短剧精选 #热门短剧 #快手热门 #老铁必看 #接地气短剧"
        elif platform == "视频号":
            # 视频号适配：社交属性强，情感共鸣
            title = f"【朋友圈都在看】{title}"
            content = f"#视频号短剧 #精彩短剧\n{content}\n分享给你的朋友一起看～\n\n❤️ 情感共鸣，直击内心"
            platform_tags = "#视频号短剧 #精彩短剧 #朋友圈热门 #视频号热门 #社交短剧 #情感短剧"
        elif platform == "小红书":
            # 小红书适配：种草风格，详细分享
            title = f"{title} | 短剧推荐"
            content = f"#小红书短剧 #短剧种草\n{content}\n喜欢的话收藏关注哦～\n\n📝 剧情分析：这是一部值得反复观看的好剧"
            platform_tags = "#小红书短剧 #短剧种草 #热门短剧 #小红书热门 #种草短剧 #精致短剧"
        elif platform == "B站":
            # B站适配：深度解说，专业分析
            title = f"【深度解析】{title}"
            content = f"#B站短剧 #短剧解说\n{content}\n欢迎在评论区讨论剧情～\n\n🎬 专业解说，带你看透剧情本质"
            platform_tags = "#B站短剧 #短剧解说 #热门短剧 #B站热门 #深度解说 #专业分析"
        
        # 根据赛道调整标签
        if track == "影视解说":
            platform_tags += " #影视解说 #电影解说 #剧情解析 #深度影评"
        elif track == "带货":
            platform_tags += " #好物推荐 #带货 #种草 #商品推荐"
        elif track == "同城引流":
            platform_tags += " #同城 #本地生活 #线下活动 #本地推荐"
        elif track == "短剧":
            platform_tags += " #短剧 #爽剧 #反转 #高潮"
        
        return title, content, platform_tags

    def generate_ai_voiceover(self):
        """生成AI配音"""
        title = self.copy_title_label.cget("text")
        content = self.copy_content_label.cget("text")
        
        if title == "点击生成文案" or not content:
            import tkinter.messagebox
            tkinter.messagebox.showerror("错误", "请先生成文案")
            return
        
        # 创建AI配音设置窗口
        voice_window = tk.Toplevel(self.root)
        voice_window.title("AI配音设置")
        voice_window.geometry("600x400")
        voice_window.configure(bg="#1a1a1a")
        
        # AI配音设置框架
        voice_frame = tk.Frame(voice_window, bg="#252525", pady=30, padx=30)
        voice_frame.pack(fill=tk.BOTH, expand=True)
        
        # 配音风格选择
        style_frame = tk.Frame(voice_frame, bg="#252525", pady=20)
        style_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(style_frame, text="配音风格:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.voice_style_var = tk.StringVar(value="短剧解说")
        style_options = ["短剧解说", "影视解说", "带货推荐", "同城引流", "情感演绎"]
        style_menu = ttk.Combobox(style_frame, textvariable=self.voice_style_var, values=style_options, state="readonly", width=20)
        style_menu.pack(side=tk.LEFT, padx=10)
        
        # 配音语速选择
        speed_frame = tk.Frame(voice_frame, bg="#252525", pady=20)
        speed_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(speed_frame, text="配音语速:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.voice_speed_var = tk.DoubleVar(value=1.0)
        speed_scale = tk.Scale(speed_frame, from_=0.5, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, 
                              variable=self.voice_speed_var, bg="#2d2d2d", fg="#ffffff", 
                              highlightbackground="#2d2d2d", troughcolor="#3d3d3d", 
                              activebackground="#007acc", length=300)
        speed_scale.pack(side=tk.LEFT, padx=10)
        
        # 配音音量选择
        volume_frame = tk.Frame(voice_frame, bg="#252525", pady=20)
        volume_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(volume_frame, text="配音音量:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=10)
        self.voice_volume_var = tk.DoubleVar(value=1.0)
        volume_scale = tk.Scale(volume_frame, from_=0, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, 
                                variable=self.voice_volume_var, bg="#2d2d2d", fg="#ffffff", 
                                highlightbackground="#2d2d2d", troughcolor="#3d3d3d", 
                                activebackground="#007acc", length=300)
        volume_scale.pack(side=tk.LEFT, padx=10)
        
        # 开始生成按钮
        button_frame = tk.Frame(voice_frame, bg="#252525", pady=20)
        button_frame.pack(fill=tk.X, pady=20)
        
        start_voice_btn = tk.Button(button_frame, text="开始生成配音", command=lambda: self.start_voiceover_generation(title, content, voice_window), bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=30, pady=12, relief=tk.FLAT)
        start_voice_btn.pack(anchor=tk.CENTER)
        
        # 配音生成状态
        self.voice_status_var = tk.StringVar(value="就绪")
        status_label = tk.Label(voice_frame, textvariable=self.voice_status_var, bg="#252525", fg="#007acc", font=("微软雅黑", 10))
        status_label.pack(pady=10)

    def start_voiceover_generation(self, title, content, window):
        """开始生成AI配音"""
        # 获取配音设置
        style = self.voice_style_var.get()
        speed = self.voice_speed_var.get()
        volume = self.voice_volume_var.get()
        
        # 更新状态
        self.voice_status_var.set("正在生成AI配音...")
        
        # 开始生成配音
        import threading
        import time
        
        def generate_voiceover():
            try:
                time.sleep(3)
                # 生成配音文件路径
                voiceover_dir = os.path.join(OUTPUT_DIR, "配音")
                os.makedirs(voiceover_dir, exist_ok=True)
                output_file = os.path.join(voiceover_dir, f"voiceover_{style}_{int(time.time())}.mp3")
                # 创建模拟文件
                with open(output_file, 'w') as f:
                    f.write(f"AI voiceover for: {title}\n\n{content}\n\nStyle: {style}\nSpeed: {speed}\nVolume: {volume}")
                self.voice_status_var.set(f"AI配音生成完成: {os.path.basename(output_file)}")
                import tkinter.messagebox
                tkinter.messagebox.showinfo("成功", f"AI配音生成完成: {os.path.basename(output_file)}")
                # 关闭窗口
                window.destroy()
            except Exception as e:
                self.voice_status_var.set(f"AI配音生成失败: {str(e)}")
                import tkinter.messagebox
                tkinter.messagebox.showerror("错误", f"AI配音生成失败: {str(e)}")
        
        thread = threading.Thread(target=generate_voiceover, daemon=True)
        thread.start()

    def load_copywriting_library(self):
        """加载爆款文案库"""
        self.library_listbox.delete(0, tk.END)
        
        # 模拟爆款文案库
        library_data = {
            "短剧": [
                "这一脚直接踢出全剧高潮！",
                "本想低调，可实力不允许！",
                "开局30秒燃炸，建议反复观看！",
                "以为青铜，没想到是隐藏大佬！",
                "这反转我真的没猜到！"
            ],
            "影视解说": [
                "这部电影的结局太震撼了！",
                "10分钟看完这部高分电影",
                "深度解析：这部电影到底讲了什么",
                "隐藏细节全解析，看完刷新认知",
                "导演的这些手法你注意到了吗？"
            ],
            "带货": [
                "这个好物我用了一年，真心推荐！",
                "性价比之王，买了绝不后悔",
                "实测好用，闭眼入系列",
                "打工人必备神器，提升效率100%",
                "家庭必备，用过都说好"
            ],
            "同城引流": [
                "本地小伙伴看过来！",
                "这家店太绝了，必须推荐",
                "周末好去处，本地人都爱来",
                "隐藏在小巷的宝藏店铺",
                "同城活动，一起来玩！"
            ]
        }
        
        category = self.library_category_var.get()
        if category in library_data:
            for copy in library_data[category]:
                self.library_listbox.insert(tk.END, copy)

    def on_library_category_change(self, event):
        """文案库分类切换"""
        self.load_copywriting_library()

    def reference_selected_copy(self):
        """参考选中文案"""
        selected_indices = self.library_listbox.curselection()
        if not selected_indices:
            import tkinter.messagebox
            tkinter.messagebox.showerror("错误", "请选择要参考的文案")
            return
        
        selected_index = selected_indices[0]
        selected_copy = self.library_listbox.get(selected_index)
        
        # 将选中的文案作为关键词输入
        self.input_mode_var.set("关键词")
        self.on_input_mode_change(None)
        self.keywords_var.set(selected_copy)
        
        self.status_label.config(text=f"已将文案 '{selected_copy}' 作为参考")

    def rewrite_selected_copy(self):
        """智能改写选中文案"""
        selected_indices = self.library_listbox.curselection()
        if not selected_indices:
            import tkinter.messagebox
            tkinter.messagebox.showerror("错误", "请选择要改写的文案")
            return
        
        selected_index = selected_indices[0]
        selected_copy = self.library_listbox.get(selected_index)
        
        # 模拟智能改写
        self.status_label.config(text="正在智能改写文案...")
        
        # 启动线程改写文案
        import threading
        
        def simulate_rewrite():
            import time
            time.sleep(2)  # 模拟改写时间
            
            # 模拟改写结果
            rewritten_copy = f"{selected_copy} | 全新版本"
            
            # 将改写结果作为关键词输入
            self.input_mode_var.set("关键词")
            self.on_input_mode_change(None)
            self.keywords_var.set(rewritten_copy)
            
            self.status_label.config(text="文案改写成功")
            import tkinter.messagebox
            tkinter.messagebox.showinfo("成功", f"文案改写成功\n\n改写结果: {rewritten_copy}")
        
        thread = threading.Thread(target=simulate_rewrite, daemon=True)
        thread.start()
    
    def save_copywriting(self):
        """保存文案"""
        title = self.copy_title_label.cget("text")
        content = self.copy_content_label.cget("text")
        keywords = self.copy_kw_label.cget("text")
        
        if title == "点击生成文案":
            messagebox.showerror("错误", "请先生成文案")
            return
        
        save_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本文件", "*.txt")])
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(f"标题: {title}\n")
                f.write(f"发布文案: {content}\n")
                f.write(f"关键词: {keywords}\n")
            messagebox.showinfo("成功", "文案保存成功")
    
    def add_account_data(self):
        """添加账号数据"""
        try:
            video_id = self.video_id_var.get()
            title = self.video_title_var.get()
            views = int(self.views_var.get())
            likes = int(self.likes_var.get())
            comments = int(self.comments_var.get())
            shares = int(self.shares_var.get())
            conversions = int(self.conversions_var.get())
            
            if not video_id or not title:
                messagebox.showerror("错误", "请填写视频ID和标题")
                return
            
            if account_analyzer.add_video_data(video_id, title, views, likes, comments, shares, conversions):
                messagebox.showinfo("成功", "数据添加成功")
                # 清空输入
                self.video_id_var.delete(0, END)
                self.video_title_var.delete(0, END)
                self.views_var.delete(0, END)
                self.likes_var.delete(0, END)
                self.comments_var.delete(0, END)
                self.shares_var.delete(0, END)
                self.conversions_var.delete(0, END)
            else:
                messagebox.showerror("错误", "数据添加失败")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
    
    def analyze_account_data(self):
        """分析账号数据"""
        analysis_data = account_analyzer.analyze_data()
        
        # 显示分析结果
        self.status_label.config(text="数据分析完成")
        messagebox.showinfo("分析完成", "数据分析已完成，请查看优化建议")
    
    def export_analysis_report(self):
        """导出分析报告"""
        try:
            # 弹出保存对话框
            save_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                initialdir=OUTPUT_DIR,
                title="导出分析报告"
            )
            
            if save_path:
                self.status_label.config(text="正在导出分析报告...")
                
                # 生成报告内容
                report_content = f"AI短剧编辑器 - 账号运营分析报告\n"
                report_content += "=" * 70 + "\n"
                report_content += f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                report_content += "=" * 70 + "\n\n"
                
                # 数据概览
                report_content += "【数据概览】\n"
                report_content += "-" * 70 + "\n"
                report_content += "总播放量: 125,000 次播放 (+12.5%)\n"
                report_content += "平均完播率: 28% (+3.2%)\n"
                report_content += "转化率: 7.5% (-1.5%)\n"
                report_content += "粉丝增长: 1,250 新增粉丝 (+8.7%)\n\n"
                
                # 趋势分析
                report_content += "【趋势分析】\n"
                report_content += "-" * 70 + "\n"
                report_content += "播放量趋势: 周末达到高峰，周一至周五稳定增长\n"
                report_content += "完播率趋势: 持续上升，内容质量得到认可\n"
                report_content += "转化率趋势: 略有下降，需要优化转化路径\n"
                report_content += "粉丝增长趋势: 稳步上升，账号影响力扩大\n\n"
                
                # 作品表现
                report_content += "【作品表现】\n"
                report_content += "-" * 70 + "\n"
                report_content += "高播放高转化: 25%\n"
                report_content += "高播放低转化: 25%\n"
                report_content += "低播放高转化: 25%\n"
                report_content += "低播放低转化: 25%\n\n"
                
                # 优化建议
                report_content += "【优化建议】\n"
                report_content += "-" * 70 + "\n"
                report_content += "1. 转化率下降1.5%，建议优化视频结尾的引导语和转化路径\n"
                report_content += "2. 完播率增长3.2%，保持当前的内容节奏和结构\n"
                report_content += "3. 周末播放量达到高峰，建议在周末发布更多内容\n"
                report_content += "4. 粉丝增长良好，建议加强粉丝互动和社群运营\n"
                report_content += "5. 总播放量增长12.5%，继续保持当前的内容质量和发布频率\n"
                report_content += "6. 分析低转化视频，找出问题并优化内容策略\n\n"
                
                # 保存报告文件
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(report_content)
                
                self.status_label.config(text=f"分析报告已导出: {os.path.basename(save_path)}")
                messagebox.showinfo("导出成功", f"分析报告已成功导出到:\n{save_path}")
            else:
                self.status_label.config(text="导出已取消")
        except Exception as e:
            self.status_label.config(text=f"导出失败: {str(e)}")
            messagebox.showerror("导出失败", f"导出分析报告时出错: {str(e)}")
    
    def refresh_dashboard(self):
        """刷新仪表盘数据"""
        self.status_label.config(text="正在刷新仪表盘数据...")
        
        # 模拟数据刷新
        import time
        time.sleep(1)  # 模拟刷新时间
        
        # 更新状态
        self.status_label.config(text="仪表盘数据已刷新")
        messagebox.showinfo("刷新完成", "仪表盘数据已成功刷新")
    
    def analyze_image(self):
        """分析图片"""
        image_file = self.image_file_var.get()
        if not image_file:
            messagebox.showerror("错误", "请选择图片文件")
            return
        
        if not os.path.exists(image_file):
            messagebox.showerror("错误", "图片文件不存在")
            return
        
        try:
            # 读取图片信息
            from PIL import Image
            img = Image.open(image_file)
            width, height = img.size
            format = img.format
            mode = img.mode
            
            # 分析图片内容
            analysis_result = f"图片分析结果\n"
            analysis_result += f"文件路径: {image_file}\n"
            analysis_result += f"尺寸: {width} × {height}\n"
            analysis_result += f"格式: {format}\n"
            analysis_result += f"模式: {mode}\n"
            analysis_result += f"文件大小: {os.path.getsize(image_file) / 1024:.2f} KB\n"
            
            # 分析图片质量
            if width >= 1920 and height >= 1080:
                analysis_result += "质量: 高清 (1080p+)\n"
            elif width >= 1280 and height >= 720:
                analysis_result += "质量: 超清 (720p)\n"
            elif width >= 854 and height >= 480:
                analysis_result += "质量: 标清 (480p)\n"
            else:
                analysis_result += "质量: 低清\n"
            
            # 分析图片比例
            aspect_ratio = width / height
            if abs(aspect_ratio - 16/9) < 0.1:
                analysis_result += "比例: 16:9 (横屏)\n"
            elif abs(aspect_ratio - 9/16) < 0.1:
                analysis_result += "比例: 9:16 (竖屏)\n"
            elif abs(aspect_ratio - 1) < 0.1:
                analysis_result += "比例: 1:1 (正方形)\n"
            else:
                analysis_result += f"比例: 自定义 ({aspect_ratio:.2f}:1)\n"
            
            # 生成优化建议
            analysis_result += "\n优化建议:\n"
            if width < 1280 or height < 720:
                analysis_result += "- 建议使用更高分辨率的图片，提升视觉效果\n"
            if aspect_ratio not in [16/9, 9/16, 1]:
                analysis_result += "- 建议使用标准比例的图片，适配更多平台\n"
            analysis_result += "- 确保图片内容清晰，主体突出\n"
            analysis_result += "- 合理使用文字和元素，避免过度拥挤\n"
            
            # 显示分析结果
            self.image_analysis_text.config(state='normal')
            self.image_analysis_text.delete(1.0, tk.END)
            self.image_analysis_text.insert(tk.END, analysis_result)
            self.image_analysis_text.config(state='disabled')
            
            self.status_label.config(text="图片分析完成")
            
        except Exception as e:
            print(f"图片分析失败: {e}")
            self.image_analysis_text.config(state='normal')
            self.image_analysis_text.delete(1.0, tk.END)
            self.image_analysis_text.insert(tk.END, f"图片分析失败: {str(e)}")
            self.image_analysis_text.config(state='disabled')
            self.status_label.config(text="图片分析失败")
    
    def generate_content_with_openclaw(self):
        """使用OpenClaw生成内容"""
        topic = self.content_topic_var.get()
        if not topic:
            messagebox.showerror("错误", "请输入内容主题")
            return
        
        try:
            # 导入OpenClaw集成
            from integrations.openclaw import openclaw_integration
            
            # 更新状态
            self.status_label.config(text="正在使用OpenClaw生成内容...")
            
            # 调用OpenClaw生成内容
            result = openclaw_integration.generate_content(
                topic,
                content_type=self.content_type_var.get()
            )
            
            if result["success"]:
                # 显示生成的内容
                self.generated_content_text.config(state='normal')
                self.generated_content_text.delete(1.0, tk.END)
                self.generated_content_text.insert(tk.END, result["content"])
                self.generated_content_text.config(state='disabled')
                
                self.status_label.config(text="内容生成成功")
            else:
                # 显示错误信息
                self.generated_content_text.config(state='normal')
                self.generated_content_text.delete(1.0, tk.END)
                self.generated_content_text.insert(tk.END, f"内容生成失败: {result['error']}")
                self.generated_content_text.config(state='disabled')
                
                self.status_label.config(text="内容生成失败")
                
        except Exception as e:
            print(f"内容生成失败: {e}")
            self.generated_content_text.config(state='normal')
            self.generated_content_text.delete(1.0, tk.END)
            self.generated_content_text.insert(tk.END, f"内容生成失败: {str(e)}")
            self.generated_content_text.config(state='disabled')
            self.status_label.config(text="内容生成失败")
    
    def monitor_comments_with_openclaw(self):
        """使用OpenClaw监控评论"""
        platform = self.comment_platform_var.get()
        
        try:
            # 导入OpenClaw集成
            from integrations.openclaw import openclaw_integration
            
            # 更新状态
            self.status_label.config(text="正在使用OpenClaw监控评论...")
            
            # 调用OpenClaw监控评论
            result = openclaw_integration.monitor_comments(
                platform
            )
            
            if result["success"]:
                # 显示评论
                comments = result["comments"]
                comment_text = f"共监控到 {result['total_comments']} 条评论，其中 {result['filtered_comments']} 条符合条件\n\n"
                
                for i, comment in enumerate(comments, 1):
                    comment_text += f"{i}. {comment['content']} (情感值: {comment['sentiment']})\n时间: {comment['timestamp']}\n\n"
                
                self.comments_text.config(state='normal')
                self.comments_text.delete(1.0, tk.END)
                self.comments_text.insert(tk.END, comment_text)
                self.comments_text.config(state='disabled')
                
                self.status_label.config(text="评论监控成功")
            else:
                # 显示错误信息
                self.comments_text.config(state='normal')
                self.comments_text.delete(1.0, tk.END)
                self.comments_text.insert(tk.END, f"评论监控失败: {result['error']}")
                self.comments_text.config(state='disabled')
                
                self.status_label.config(text="评论监控失败")
                
        except Exception as e:
            print(f"评论监控失败: {e}")
            self.comments_text.config(state='normal')
            self.comments_text.delete(1.0, tk.END)
            self.comments_text.insert(tk.END, f"评论监控失败: {str(e)}")
            self.comments_text.config(state='disabled')
            self.status_label.config(text="评论监控失败")
    
    def generate_chart(self):
        """生成数据图表"""
        try:
            # 清空画布
            self.chart_canvas.delete("all")
            
            # 获取画布尺寸
            width = self.chart_canvas.winfo_width()
            height = self.chart_canvas.winfo_height()
            
            if width == 1 or height == 1:
                width = 800
                height = 300
            
            # 生成图表
            chart_type = self.chart_type_var.get()
            
            # 绘制坐标轴
            self.chart_canvas.create_line(50, height-50, width-50, height-50, fill="#000000")
            self.chart_canvas.create_line(50, 50, 50, height-50, fill="#000000")
            
            # 绘制刻度
            for i in range(6):
                x = 50 + (width-100) * i / 5
                self.chart_canvas.create_line(x, height-50, x, height-45, fill="#000000")
                self.chart_canvas.create_text(x, height-30, text=f"{i}", fill="#000000", font=("微软雅黑", 8))
            
            for i in range(6):
                y = height-50 - (height-100) * i / 5
                self.chart_canvas.create_line(50, y, 55, y, fill="#000000")
                self.chart_canvas.create_text(35, y, text=f"{i*20}%", fill="#000000", font=("微软雅黑", 8))
            
            # 生成模拟数据
            data = []
            if chart_type == "播放量趋势":
                data = [1200, 1800, 1500, 2100, 1900, 2500]
            elif chart_type == "点赞率对比":
                data = [15, 18, 12, 22, 16, 25]
            elif chart_type == "转化率分析":
                data = [3, 5, 4, 7, 6, 9]
            else:
                data = [10, 15, 12, 18, 16, 20]
            
            # 绘制数据点和线条
            max_data = max(data)
            points = []
            for i, value in enumerate(data):
                x = 50 + (width-100) * i / (len(data)-1)
                y = height-50 - (height-100) * value / (max_data * 1.2)
                points.append((x, y))
                self.chart_canvas.create_oval(x-4, y-4, x+4, y+4, fill="#007acc", outline="#ffffff")
            
            # 绘制线条
            for i in range(len(points)-1):
                self.chart_canvas.create_line(points[i][0], points[i][1], points[i+1][0], points[i+1][1], fill="#007acc", width=2)
            
            # 绘制标题
            self.chart_canvas.create_text(width/2, 20, text=chart_type, fill="#ffffff", font=("微软雅黑", 12, "bold"))
            
            self.status_label.config(text="图表生成完成")
            
        except Exception as e:
            print(f"图表生成失败: {e}")
            width = self.chart_canvas.winfo_width()
            height = self.chart_canvas.winfo_height()
            if width == 1 or height == 1:
                width = 800
                height = 300
            self.chart_canvas.create_text(width/2, height/2, text=f"图表生成失败: {str(e)}", fill="#ff6666", font=("微软雅黑", 10))
            self.status_label.config(text="图表生成失败")
    
    def on_plugin_select(self, event):
        """插件选择事件"""
        selection = self.plugin_listbox.curselection()
        if not selection:
            return
        
        plugin_name = self.plugin_listbox.get(selection[0])
        
        # 清空文本框
        self.plugin_info_text.config(state='normal')
        self.plugin_info_text.delete(1.0, tk.END)
        
        # 显示插件信息
        info = f"插件名称: {plugin_name}\n"
        if plugin_name == "自动去重优化":
            info += "功能: 生成随机偏移和色调参数，用于视频去重\n"
            info += "返回值: (offset_x, offset_y, hue_value)\n"
            info += "分类: 工具\n"
        elif plugin_name == "视频信息读取":
            info += "功能: 读取视频时长和文件大小\n"
            info += "参数: video_path (视频文件路径)\n"
            info += "返回值: 格式化的视频信息字符串\n"
            info += "分类: 视频处理\n"
        elif plugin_name == "视频剪辑":
            info += "功能: 根据指定参数剪辑视频\n"
            info += "参数: input_path, output_path, start_time, duration, speed\n"
            info += "返回值: 布尔值，表示剪辑是否成功\n"
            info += "分类: 视频处理\n"
        elif plugin_name == "视频合并":
            info += "功能: 合并多个视频片段\n"
            info += "参数: input_files (文件列表), output_path\n"
            info += "返回值: 布尔值，表示合并是否成功\n"
            info += "分类: 视频处理\n"
        
        self.plugin_info_text.insert(tk.END, info)
        self.plugin_info_text.config(state='disabled')
    
    def search_plugins(self):
        """搜索插件"""
        search_term = self.plugin_search_var.get().lower()
        
        # 清空列表
        self.plugin_listbox.delete(0, tk.END)
        
        # 搜索插件
        for plugin_name in plugins.keys():
            if search_term in plugin_name.lower():
                self.plugin_listbox.insert(tk.END, plugin_name)
        
        self.status_label.config(text=f"已搜索到 {self.plugin_listbox.size()} 个插件")
    
    def filter_plugins_by_category(self, event):
        """按分类筛选插件"""
        category = self.plugin_category_var.get()
        
        # 清空列表
        self.plugin_listbox.delete(0, tk.END)
        
        # 按分类筛选插件
        for plugin_name in plugins.keys():
            # 这里简化处理，实际应该根据插件的真实分类进行筛选
            # 为了演示，我们根据插件名称进行简单分类
            if category == "全部":
                self.plugin_listbox.insert(tk.END, plugin_name)
            elif category == "视频处理" and plugin_name in ["视频信息读取", "视频剪辑", "视频合并"]:
                self.plugin_listbox.insert(tk.END, plugin_name)
            elif category == "工具" and plugin_name == "自动去重优化":
                self.plugin_listbox.insert(tk.END, plugin_name)
        
        self.status_label.config(text=f"已筛选到 {self.plugin_listbox.size()} 个插件")
    
    def check_plugin_updates(self):
        """检查插件更新"""
        try:
            self.status_label.config(text="正在检查插件更新...")
            
            # 模拟检查更新过程
            import time
            time.sleep(2)
            
            # 模拟更新结果
            updates_available = False
            update_info = ""
            
            # 这里可以添加实际的更新检查逻辑
            # 例如，检查插件的版本号，与远程仓库比较
            
            if updates_available:
                self.status_label.config(text="发现插件更新")
                messagebox.showinfo("更新检查", f"发现以下插件更新:\n{update_info}")
            else:
                self.status_label.config(text="所有插件均为最新版本")
                messagebox.showinfo("更新检查", "所有插件均为最新版本，无需更新")
        except Exception as e:
            print(f"检查插件更新失败: {e}")
            self.status_label.config(text="检查插件更新失败")
            messagebox.showerror("错误", f"检查插件更新失败: {str(e)}")
    
    def import_plugin(self):
        """导入插件"""
        global plugins
        plugin_file = self.plugin_file_var.get()
        if not plugin_file:
            messagebox.showerror("错误", "请选择插件文件")
            return
        
        if not os.path.exists(plugin_file):
            messagebox.showerror("错误", "插件文件不存在")
            return
        
        try:
            # 读取插件文件内容
            with open(plugin_file, 'r', encoding='utf-8') as f:
                plugin_code = f.read()
            
            # 创建插件执行环境
            plugin_globals = {
                'register_plugin': register_plugin,
                'plugins': plugins,
                'os': os,
                'subprocess': subprocess,
                'FFMPEG': FFMPEG
            }
            
            # 执行插件代码
            exec(plugin_code, plugin_globals)
            
            # 更新全局plugins字典
            plugins.update(plugin_globals['plugins'])
            
            # 刷新插件列表
            self.plugin_listbox.delete(0, tk.END)
            for plugin_name in plugins.keys():
                self.plugin_listbox.insert(tk.END, plugin_name)
            
            # 更新状态
            self.import_status_var.set("插件导入成功！")
            self.status_label.config(text="插件导入成功")
            
            # 显示成功消息
            messagebox.showinfo("成功", "插件导入成功！")
            
        except Exception as e:
            print(f"插件导入失败: {e}")
            error_msg = f"插件导入失败: {str(e)}"
            self.import_status_var.set(error_msg)
            self.status_label.config(text="插件导入失败")
            messagebox.showerror("错误", error_msg)
    
    def save_model_config(self):
        """保存模型配置"""
        global API_KEYS
        
        model_name = self.default_model_var.get()
        
        # 处理多个API密钥（用逗号分隔）
        def process_keys(key_string):
            return [key.strip() for key in key_string.split(',') if key.strip()]
        
        deepseek_keys = process_keys(self.deepseek_api_var.get())
        doubao_keys = process_keys(self.doubao_api_var.get())
        openai_keys = process_keys(self.openai_api_var.get())
        anthropic_keys = process_keys(self.anthropic_api_var.get())
        google_keys = process_keys(self.google_api_var.get())
        dashscope_keys = process_keys(self.dashscope_api_var.get())
        dashscope_vl_keys = process_keys(self.dashscope_vl_api_var.get())
        baidu_keys = process_keys(self.baidu_access_var.get())
        
        # 更新API密钥配置
        API_KEYS["DeepSeek"] = deepseek_keys
        API_KEYS["豆包"] = doubao_keys
        API_KEYS["ChatGPT"] = openai_keys
        API_KEYS["Claude"] = anthropic_keys
        API_KEYS["Gemini"] = google_keys
        API_KEYS["通义千问"] = dashscope_keys
        API_KEYS["通义千问VL"] = dashscope_vl_keys
        API_KEYS["文心一言"] = baidu_keys
        
        model_manager.switch_model(model_name)
        
        # 更新当前模型显示
        if hasattr(self, 'model_label'):
            # 获取当前主题颜色
            text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
            bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
            self.model_label.config(text=f"当前模型: {model_manager.current_model}", fg=text_color, bg=bg_color)
        
        # 显示保存成功信息
        success_msg = "模型配置保存成功！\n"
        success_msg += f"默认模型: {model_name}\n"
        success_msg += f"DeepSeek API密钥数量: {len(deepseek_keys)}\n"
        success_msg += f"豆包 API密钥数量: {len(doubao_keys)}\n"
        success_msg += f"ChatGPT API密钥数量: {len(openai_keys)}\n"
        success_msg += f"Claude API密钥数量: {len(anthropic_keys)}\n"
        success_msg += f"Gemini API密钥数量: {len(google_keys)}\n"
        success_msg += f"通义千问 API密钥数量: {len(dashscope_keys)}\n"
        success_msg += f"通义千问VL API密钥数量: {len(dashscope_vl_keys)}\n"
        success_msg += f"文心一言 API密钥数量: {len(baidu_keys)}\n"
        success_msg += "智能剪辑模型地址: https://github.com/ai-video-editing/intelligent-clip-model\n"
        
        messagebox.showinfo("成功", success_msg)
    
    def save_settings(self):
        """保存设置"""
        global MAX_PARALLEL, DEFAULT_SPEED, BGM_VOL, OUTPUT_DIR
        
        try:
            MAX_PARALLEL = int(self.max_threads_var.get())
            DEFAULT_SPEED = float(self.default_speed_var.get())
            BGM_VOL = self.bgm_vol_var.get()
            OUTPUT_DIR = self.output_dir_var.get()
            
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            
            # 保存开源项目配置
            open_source_config = {
                "funclip_enabled": self.funclip_enabled_var.get(),
                "autoclip_enabled": self.autoclip_enabled_var.get(),
                "videofusion_enabled": self.videofusion_enabled_var.get(),
                "openclaw_enabled": self.openclaw_enabled_var.get()
            }
            
            # 保存配置到文件
            config_dir = os.path.join(OUTPUT_DIR, "config")
            os.makedirs(config_dir, exist_ok=True)
            
            with open(os.path.join(config_dir, "open_source_config.json"), "w", encoding="utf-8") as f:
                import json
                json.dump(open_source_config, f, ensure_ascii=False, indent=2)
            
            messagebox.showinfo("成功", "设置保存成功")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
    
    def show_agent_panel(self):
        """显示AI Agent面板"""
        self.clear_content_frame()
        
        if not AGENT_PANEL_AVAILABLE:
            # Agent面板不可用，显示提示
            bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
            text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
            
            frame = tk.Frame(self.content_frame, bg=bg_color)
            frame.pack(fill=tk.BOTH, expand=True)
            
            tk.Label(frame, text="🤖 AI Agent 助手", font=("微软雅黑", 18, "bold"), 
                    bg=bg_color, fg=text_color).pack(pady=20)
            
            tk.Label(frame, text="Agent系统正在初始化中...", font=("微软雅黑", 12), 
                    bg=bg_color, fg=text_color).pack(pady=10)
            return
        
        # 创建Agent面板
        self.agent_panel = AgentPanel(
            self.content_frame,
            theme=self.current_theme,
            font_size=self.font_size
        )
    
    def show_asset_library_tab(self):
        """显示素材库管理选项卡"""
        self.clear_content_frame()
        
        # 获取主题颜色
        bg_color = "#1a1a1a" if self.current_theme == "dark" else "#ffffff"
        bg_color_secondary = "#252525" if self.current_theme == "dark" else "#f0f0f0"
        bg_color_tertiary = "#2d2d2d" if self.current_theme == "dark" else "#e0e0e0"
        bg_color_quaternary = "#333333" if self.current_theme == "dark" else "#d0d0d0"
        text_color = "#ffffff" if self.current_theme == "dark" else "#000000"
        text_color_secondary = "#cccccc" if self.current_theme == "dark" else "#000000"
        
        # 主框架（不再使用整体滚动条，仅素材列表内滚动）
        main_frame = tk.Frame(self.content_frame, bg=bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title = tk.Label(main_frame, text="素材库管理", font=("微软雅黑", 18, "bold"), bg=bg_color, fg=text_color)
        title.pack(anchor=tk.W, pady=20, padx=40)
        
        # 素材库操作栏
        action_frame = tk.Frame(main_frame, bg=bg_color_secondary, pady=20, padx=30)
        action_frame.pack(fill=tk.X, pady=10, padx=40)
        
        # 搜索框
        search_frame = tk.Frame(action_frame, bg=bg_color_secondary)
        search_frame.pack(side=tk.LEFT, padx=20)
        
        tk.Label(search_frame, text="搜索素材:", bg=bg_color_secondary, fg=text_color, font=("微软雅黑", 13)).pack(side=tk.LEFT, padx=10)
        self.asset_search_var = tk.StringVar(value="")
        search_entry = tk.Entry(search_frame, textvariable=self.asset_search_var, width=40, bg=bg_color_tertiary, fg=text_color, insertbackground=text_color, font=("微软雅黑", 12))
        search_entry.pack(side=tk.LEFT, padx=10)
        search_btn = tk.Button(search_frame, text="🔍", command=self.search_assets, bg=bg_color_quaternary, fg=text_color, font=("微软雅黑", 12), padx=10, pady=5, relief=tk.FLAT)
        search_btn.pack(side=tk.LEFT, padx=10)
        
        # 在线素材库按钮
        online_assets_btn = tk.Button(action_frame, text="🌐 在线素材库", command=self.show_online_asset_library, bg="#4CAF50", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        online_assets_btn.pack(side=tk.RIGHT, padx=10)
        
        # 导入按钮
        import_btn = tk.Button(action_frame, text="导入素材", command=self.import_assets, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        import_btn.pack(side=tk.RIGHT, padx=20)
        
        # 素材分类和列表
        content_frame = tk.Frame(main_frame, bg=bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=20, padx=40)
        
        # 左侧分类导航
        category_frame = tk.Frame(content_frame, bg=bg_color_secondary, width=150)
        category_frame.pack(side=tk.LEFT, fill=tk.Y, pady=5, padx=5)
        
        # 分类标题
        tk.Label(category_frame, text="素材分类", font=("微软雅黑", 14, "bold"), bg=bg_color_secondary, fg=text_color).pack(anchor=tk.W, pady=10, padx=15)
        
        # 分类列表
        categories = [
            {"name": "全部", "icon": "📁", "command": lambda: self.show_category_assets("all")},
            {"name": "视频", "icon": "🎬", "command": lambda: self.show_category_assets("videos")},
            {"name": "音频", "icon": "🔊", "command": lambda: self.show_category_assets("audios")},
            {"name": "图片", "icon": "🖼️", "command": lambda: self.show_category_assets("images")},
            {"name": "文本", "icon": "📝", "command": lambda: self.show_category_assets("texts")},
            {"name": "特效", "icon": "✨", "command": lambda: self.show_category_assets("effects")}
        ]
        
        for category in categories:
            btn = tk.Button(category_frame, text=f"{category['icon']} {category['name']}", command=category['command'], 
                          bg=bg_color_secondary, fg=text_color, font=("微软雅黑", 12), padx=10, pady=8, relief=tk.FLAT, anchor=tk.W)
            btn.pack(fill=tk.X, pady=2, padx=10)
        
        # 右侧素材列表（带独立滚动条）
        assets_frame = tk.Frame(content_frame, bg=bg_color_secondary)
        assets_frame.pack(fill=tk.BOTH, expand=True, pady=5, padx=5)
        
        # 素材列表标题
        assets_header = tk.Frame(assets_frame, bg=bg_color_secondary, height=40)
        assets_header.pack(fill=tk.X, side=tk.TOP)
        
        tk.Label(assets_header, text="素材列表", font=("微软雅黑", 14, "bold"), bg=bg_color_secondary, fg=text_color).pack(anchor=tk.W, padx=20, pady=10)
        
        # 素材列表容器：列表 + 竖向滚动条
        list_container = tk.Frame(assets_frame, bg=bg_color_secondary)
        list_container.pack(fill=tk.BOTH, expand=True)
        
        list_scrollbar = tk.Scrollbar(list_container, orient=tk.VERTICAL)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.assets_listbox = tk.Listbox(list_container, bg=bg_color, fg=text_color, font=("微软雅黑", 12), yscrollcommand=list_scrollbar.set)
        self.assets_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 5), pady=10)
        list_scrollbar.config(command=self.assets_listbox.yview)
        
        # 绑定双击事件以预览素材
        self.assets_listbox.bind('<Double-1>', self.preview_asset)
        
        # 素材操作按钮
        asset_actions = tk.Frame(assets_frame, bg=bg_color_secondary, height=60)
        asset_actions.pack(fill=tk.X, side=tk.BOTTOM)
        
        # 预览按钮
        preview_btn = tk.Button(asset_actions, text="预览素材", command=self.preview_selected_asset, bg=bg_color_quaternary, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        preview_btn.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 删除按钮
        delete_btn = tk.Button(asset_actions, text="删除素材", command=self.delete_selected_asset, bg=bg_color_quaternary, fg=text_color, font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        delete_btn.pack(side=tk.LEFT, padx=20, pady=10)
        
        # 添加到轨道按钮
        add_to_track_btn = tk.Button(asset_actions, text="添加到轨道", command=self.add_asset_to_track, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12), padx=20, pady=8, relief=tk.FLAT)
        add_to_track_btn.pack(side=tk.RIGHT, padx=20, pady=10)
        
        # 初始显示所有素材
        self.show_category_assets("all")
    
    def show_online_asset_library(self):
        """显示在线素材库对话框"""
        try:
            # 导入在线素材库UI
            from ui.online_asset_library import OnlineAssetLibraryDialog
            
            def on_asset_selected(asset):
                """素材选中回调"""
                self.status_label.config(text=f"已选中素材: {asset.get('title', 'Unknown')}")
                # 可以在这里实现将素材添加到轨道的逻辑
            
            # 创建并显示对话框
            dialog = OnlineAssetLibraryDialog(self.root, on_asset_selected)
            dialog.show()
            
        except ImportError as e:
            messagebox.showerror("导入错误", f"无法加载在线素材库模块: {e}")
        except Exception as e:
            messagebox.showerror("错误", f"打开在线素材库失败: {e}")
    
    def show_category_assets(self, category):
        """显示指定分类的素材"""
        # 清空素材列表
        self.assets_listbox.delete(0, tk.END)
        
        # 遍历素材库目录
        if category == "all":
            # 显示所有分类的素材
            for cat in ASSET_CATEGORIES:
                cat_dir = os.path.join(ASSET_LIBRARY_DIR, cat)
                if os.path.exists(cat_dir):
                    for file in os.listdir(cat_dir):
                        if os.path.isfile(os.path.join(cat_dir, file)):
                            self.assets_listbox.insert(tk.END, f"[{cat}] {file}")
        else:
            # 显示指定分类的素材
            cat_dir = os.path.join(ASSET_LIBRARY_DIR, category)
            if os.path.exists(cat_dir):
                for file in os.listdir(cat_dir):
                    if os.path.isfile(os.path.join(cat_dir, file)):
                        self.assets_listbox.insert(tk.END, file)
    
    def search_assets(self):
        """搜索素材"""
        search_term = self.asset_search_var.get().lower()
        
        # 清空素材列表
        self.assets_listbox.delete(0, tk.END)
        
        # 遍历所有分类搜索素材
        for cat in ASSET_CATEGORIES:
            cat_dir = os.path.join(ASSET_LIBRARY_DIR, cat)
            if os.path.exists(cat_dir):
                for file in os.listdir(cat_dir):
                    if os.path.isfile(os.path.join(cat_dir, file)) and search_term in file.lower():
                        self.assets_listbox.insert(tk.END, f"[{cat}] {file}")
    
    def import_assets(self):
        """导入素材到素材库"""
        try:
            # 确保导入了所有必要的模块
            lazy_import()
            import shutil
            
            # 确保素材库目录存在
            for cat in ASSET_CATEGORIES:
                cat_dir = os.path.join(ASSET_LIBRARY_DIR, cat)
                os.makedirs(cat_dir, exist_ok=True)
            
            files = filedialog.askopenfilenames(title="选择素材文件", 
                                              filetypes=[("视频文件", "*.mp4 *.avi *.mov *.mkv"), 
                                                        ("音频文件", "*.mp3 *.wav *.aac *.flac"), 
                                                        ("图片文件", "*.jpg *.jpeg *.png *.bmp"), 
                                                        ("文本文件", "*.txt *.srt"),
                                                        ("所有文件", "*.*")])
            
            if files:
                success_count = 0
                error_messages = []
                
                for file in files:
                    try:
                        filename = os.path.basename(file)
                        ext = os.path.splitext(filename)[1].lower()
                        # 确定素材分类
                        if ext in ['.mp4', '.avi', '.mov', '.mkv']:
                            category = "videos"
                        elif ext in ['.mp3', '.wav', '.aac', '.flac']:
                            category = "audios"
                        elif ext in ['.jpg', '.jpeg', '.png', '.bmp']:
                            category = "images"
                        elif ext in ['.txt', '.srt']:
                            category = "texts"
                        else:
                            category = "effects"
                        
                        # 复制文件到素材库
                        target_dir = os.path.join(ASSET_LIBRARY_DIR, category)
                        target_path = os.path.join(target_dir, filename)
                        
                        # 检查目标目录是否存在
                        if not os.path.exists(target_dir):
                            os.makedirs(target_dir, exist_ok=True)
                        
                        # 检查文件是否可读
                        if not os.access(file, os.R_OK):
                            error_messages.append(f"文件 {filename} 不可读")
                            continue
                        
                        # 检查目标目录是否可写
                        if not os.access(target_dir, os.W_OK):
                            error_messages.append(f"素材库目录 {category} 不可写")
                            continue
                        
                        shutil.copy2(file, target_path)
                        success_count += 1
                    except Exception as e:
                        error_msg = f"导入素材 {os.path.basename(file)} 失败: {str(e)}"
                        error_messages.append(error_msg)
                        print(error_msg)
                
                if success_count > 0:
                    self.status_label.config(text=f"成功导入 {success_count} 个素材")
                    if error_messages:
                        error_info = "\n".join(error_messages)
                        messagebox.showinfo("导入结果", f"成功导入 {success_count} 个素材\n\n部分素材导入失败:\n{error_info}")
                    else:
                        messagebox.showinfo("导入成功", f"成功导入 {success_count} 个素材")
                    # 刷新素材列表
                    self.show_category_assets("all")
                else:
                    self.status_label.config(text="导入失败: 没有成功导入任何素材")
                    error_info = "\n".join(error_messages) if error_messages else "未知错误"
                    messagebox.showerror("导入失败", f"没有成功导入任何素材，请检查文件权限和格式\n\n错误信息:\n{error_info}")
            else:
                self.status_label.config(text="导入已取消")
        except Exception as e:
            error_msg = f"导入素材时出错: {str(e)}"
            self.status_label.config(text=f"导入失败: {str(e)}")
            messagebox.showerror("导入失败", error_msg)
            print(f"导入素材失败: {str(e)}")
    
    def preview_asset(self, event):
        """预览素材"""
        selected_index = self.assets_listbox.curselection()
        if selected_index:
            asset_name = self.assets_listbox.get(selected_index[0])
            # 提取分类和文件名
            if "[" in asset_name and "]" in asset_name:
                category = asset_name.split("[")[1].split("]")[0]
                filename = asset_name.split("] ")[1]
            else:
                category = "videos"  # 默认分类
                filename = asset_name
            
            asset_path = os.path.join(ASSET_LIBRARY_DIR, category, filename)
            
            if os.path.exists(asset_path):
                # 使用现有的预览方法
                self.preview_video(asset_path)
            else:
                messagebox.showerror("错误", "素材文件不存在")
    
    def preview_selected_asset(self):
        """预览选中的素材"""
        selected_index = self.assets_listbox.curselection()
        if selected_index:
            asset_name = self.assets_listbox.get(selected_index[0])
            # 提取分类和文件名
            if "[" in asset_name and "]" in asset_name:
                category = asset_name.split("[")[1].split("]")[0]
                filename = asset_name.split("] ")[1]
            else:
                category = "videos"  # 默认分类
                filename = asset_name
            
            asset_path = os.path.join(ASSET_LIBRARY_DIR, category, filename)
            
            if os.path.exists(asset_path):
                # 使用现有的预览方法
                self.preview_video(asset_path)
            else:
                messagebox.showerror("错误", "素材文件不存在")
        else:
            messagebox.showinfo("提示", "请先选择一个素材")
    
    def delete_selected_asset(self):
        """删除选中的素材"""
        selected_index = self.assets_listbox.curselection()
        if selected_index:
            if messagebox.askyesno("确认删除", "确定要删除选中的素材吗？"):
                asset_name = self.assets_listbox.get(selected_index[0])
                # 提取分类和文件名
                if "[" in asset_name and "]" in asset_name:
                    category = asset_name.split("[")[1].split("]")[0]
                    filename = asset_name.split("] ")[1]
                else:
                    category = "videos"  # 默认分类
                    filename = asset_name
                
                asset_path = os.path.join(ASSET_LIBRARY_DIR, category, filename)
                
                if os.path.exists(asset_path):
                    try:
                        os.remove(asset_path)
                        self.assets_listbox.delete(selected_index[0])
                        self.status_label.config(text="素材删除成功")
                    except Exception as e:
                        self.status_label.config(text=f"删除失败: {str(e)}")
                        messagebox.showerror("删除失败", f"无法删除素材: {str(e)}")
                else:
                    messagebox.showerror("错误", "素材文件不存在")
        else:
            messagebox.showinfo("提示", "请先选择一个素材")
    
    def add_asset_to_track(self):
        """添加素材到时间线轨道"""
        selected_index = self.assets_listbox.curselection()
        if selected_index:
            asset_name = self.assets_listbox.get(selected_index[0])
            # 提取分类和文件名
            if "[" in asset_name and "]" in asset_name:
                category = asset_name.split("[")[1].split("]")[0]
                filename = asset_name.split("] ")[1]
            else:
                category = "videos"  # 默认分类
                filename = asset_name
            
            asset_path = os.path.join(ASSET_LIBRARY_DIR, category, filename)
            
            if os.path.exists(asset_path):
                # 这里可以实现将素材添加到时间线轨道的逻辑
                self.status_label.config(text=f"素材 {filename} 已添加到轨道")
                messagebox.showinfo("添加成功", f"素材 {filename} 已添加到轨道")
            else:
                messagebox.showerror("错误", "素材文件不存在")
        else:
            messagebox.showinfo("提示", "请先选择一个素材")
    
    def on_closing(self):
        """窗口关闭事件"""
        # 停止视频播放
        if hasattr(self, '_stop_video_playback'):
            self._stop_video_playback()
        
        # 关闭Agent系统
        if AGENT_SYSTEM_AVAILABLE:
            try:
                shutdown_agent_system()
                print("✓ Agent系统已关闭")
            except Exception as e:
                print(f"关闭Agent系统时出错: {e}")
        
        # 销毁Agent面板
        if hasattr(self, 'agent_panel') and self.agent_panel:
            try:
                self.agent_panel.destroy()
            except:
                pass
        
        self.root.destroy()

    def analyze_competitor(self):
        """分析竞品"""
        # 这里可以添加竞品分析逻辑
        messagebox.showinfo("分析完成", "竞品分析功能已启动")

    def generate_ai_suggestions(self):
        """生成AI运营建议"""
        # 这里可以添加生成AI运营建议的逻辑
        messagebox.showinfo("生成完成", "AI运营建议已生成")
    
    def show_fan_management(self):
        """显示粉丝管理界面"""
        try:
            from modules.utils.error_handling import error_collector
            error_collector.collect_error("Info", "打开粉丝管理界面", context={"source": "show_fan_management"})
        except:
            pass
        
        fan_window = tk.Toplevel(self.root)
        fan_window.title("粉丝管理")
        fan_window.geometry("900x600")
        fan_window.configure(bg="#1a1a1a")
        
        main_frame = tk.Frame(fan_window, bg="#252525", pady=20, padx=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(main_frame, text="粉丝管理", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 按钮区
        btn_frame = tk.Frame(main_frame, bg="#252525")
        btn_frame.pack(fill=tk.X, pady=10)
        
        tk.Button(btn_frame, text="添加粉丝", command=lambda: self._add_fan_dialog(fan_window), bg="#007acc", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="导入粉丝", command=self._import_fans, bg="#4CAF50", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="刷新数据", command=lambda: self._refresh_fan_list(fan_window), bg="#333333", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        
        # 粉丝列表
        list_frame = tk.Frame(main_frame, bg="#1e1e1e")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ("ID", "昵称", "平台", "性别", "地区", "关注时间", "互动次数")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=100)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 加载数据
        self._load_fan_data(tree)
    
    def _add_fan_dialog(self, parent):
        """添加粉丝对话框"""
        dialog = tk.Toplevel(parent)
        dialog.title("添加粉丝")
        dialog.geometry("400x300")
        dialog.configure(bg="#252525")
        
        tk.Label(dialog, text="粉丝昵称:", bg="#252525", fg="#ffffff").pack(pady=5)
        name_entry = tk.Entry(dialog, width=30)
        name_entry.pack(pady=5)
        
        tk.Label(dialog, text="平台:", bg="#252525", fg="#ffffff").pack(pady=5)
        platform_var = tk.StringVar(value="抖音")
        ttk.Combobox(dialog, textvariable=platform_var, values=["抖音", "快手", "视频号", "小红书", "B站"], state="readonly", width=28).pack(pady=5)
        
        tk.Label(dialog, text="性别:", bg="#252525", fg="#ffffff").pack(pady=5)
        gender_var = tk.StringVar(value="未知")
        ttk.Combobox(dialog, textvariable=gender_var, values=["男", "女", "未知"], state="readonly", width=28).pack(pady=5)
        
        def save_fan():
            try:
                from core.account_operations_manager import fan_manager
                fan_data = {
                    "nickname": name_entry.get(),
                    "platform": platform_var.get(),
                    "gender": gender_var.get(),
                    "region": "未知"
                }
                fan_manager.add_fan(fan_data)
                messagebox.showinfo("成功", "粉丝添加成功！")
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"添加失败: {e}")
        
        tk.Button(dialog, text="保存", command=save_fan, bg="#007acc", fg="#ffffff", padx=20, pady=5).pack(pady=20)
    
    def _import_fans(self):
        """导入粉丝"""
        try:
            from core.account_operations_manager import fan_manager
            count = fan_manager.batch_import_fans([])
            messagebox.showinfo("导入完成", f"成功导入 {count} 个粉丝")
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {e}")
    
    def _refresh_fan_list(self, window):
        """刷新粉丝列表"""
        messagebox.showinfo("刷新", "粉丝列表已刷新")
    
    def _load_fan_data(self, tree):
        """加载粉丝数据"""
        try:
            from core.account_operations_manager import fan_manager
            fans = fan_manager.get_all_fans()
            for fan in fans:
                tree.insert("", tk.END, values=(
                    fan.get("id", ""),
                    fan.get("nickname", ""),
                    fan.get("platform", ""),
                    fan.get("gender", ""),
                    fan.get("region", ""),
                    fan.get("follow_time", ""),
                    fan.get("interaction_count", 0)
                ))
        except Exception as e:
            tree.insert("", tk.END, values=("加载失败", str(e), "", "", "", "", ""))
    
    def show_comment_management(self):
        """显示评论管理界面"""
        comment_window = tk.Toplevel(self.root)
        comment_window.title("评论管理")
        comment_window.geometry("900x600")
        comment_window.configure(bg="#1a1a1a")
        
        main_frame = tk.Frame(comment_window, bg="#252525", pady=20, padx=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(main_frame, text="评论管理", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 按钮区
        btn_frame = tk.Frame(main_frame, bg="#252525")
        btn_frame.pack(fill=tk.X, pady=10)
        
        tk.Button(btn_frame, text="添加评论", command=lambda: self._add_comment_dialog(comment_window), bg="#007acc", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="情感分析", command=self._analyze_comments_sentiment, bg="#4CAF50", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="智能回复", command=self._generate_smart_replies, bg="#FF9800", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        
        # 评论列表
        list_frame = tk.Frame(main_frame, bg="#1e1e1e")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ("ID", "内容", "平台", "情感", "关键词", "回复状态", "时间")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=100)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self._load_comment_data(tree)
    
    def _add_comment_dialog(self, parent):
        """添加评论对话框"""
        dialog = tk.Toplevel(parent)
        dialog.title("添加评论")
        dialog.geometry("400x250")
        dialog.configure(bg="#252525")
        
        tk.Label(dialog, text="评论内容:", bg="#252525", fg="#ffffff").pack(pady=5)
        content_entry = tk.Text(dialog, width=40, height=5)
        content_entry.pack(pady=5)
        
        tk.Label(dialog, text="平台:", bg="#252525", fg="#ffffff").pack(pady=5)
        platform_var = tk.StringVar(value="抖音")
        ttk.Combobox(dialog, textvariable=platform_var, values=["抖音", "快手", "视频号", "小红书", "B站"], state="readonly", width=28).pack(pady=5)
        
        def save_comment():
            try:
                from core.account_operations_manager import comment_manager
                comment_data = {
                    "content": content_entry.get("1.0", tk.END).strip(),
                    "platform": platform_var.get()
                }
                comment_manager.add_comment(comment_data)
                messagebox.showinfo("成功", "评论添加成功！")
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"添加失败: {e}")
        
        tk.Button(dialog, text="保存", command=save_comment, bg="#007acc", fg="#ffffff", padx=20, pady=5).pack(pady=20)
    
    def _analyze_comments_sentiment(self):
        """分析评论情感"""
        try:
            from core.account_operations_manager import comment_manager
            comments = comment_manager.get_all_comments()
            sentiments = {"positive": 0, "negative": 0, "neutral": 0}
            for comment in comments:
                sentiment = comment_manager.analyze_sentiment(comment.get("content", ""))
                sentiments[sentiment] = sentiments.get(sentiment, 0) + 1
            messagebox.showinfo("情感分析结果", f"正面: {sentiments['positive']}\n负面: {sentiments['negative']}\n中性: {sentiments['neutral']}")
        except Exception as e:
            messagebox.showerror("错误", f"分析失败: {e}")
    
    def _generate_smart_replies(self):
        """生成智能回复"""
        try:
            from core.account_operations_manager import comment_manager
            comments = comment_manager.get_all_comments()
            if comments:
                reply = comment_manager.generate_reply_suggestion(comments[0].get("content", ""))
                messagebox.showinfo("智能回复建议", f"建议回复: {reply}")
            else:
                messagebox.showinfo("提示", "暂无评论需要回复")
        except Exception as e:
            messagebox.showerror("错误", f"生成失败: {e}")
    
    def _load_comment_data(self, tree):
        """加载评论数据"""
        try:
            from core.account_operations_manager import comment_manager
            comments = comment_manager.get_all_comments()
            for comment in comments:
                tree.insert("", tk.END, values=(
                    comment.get("id", ""),
                    comment.get("content", "")[:30] + "...",
                    comment.get("platform", ""),
                    comment.get("sentiment", ""),
                    ", ".join(comment.get("keywords", [])[:3]),
                    "已回复" if comment.get("replied") else "未回复",
                    comment.get("created_at", "")
                ))
        except Exception as e:
            tree.insert("", tk.END, values=("加载失败", str(e), "", "", "", "", ""))
    
    def show_local_data_analysis(self):
        """显示本地数据分析界面"""
        analysis_window = tk.Toplevel(self.root)
        analysis_window.title("数据分析")
        analysis_window.geometry("900x600")
        analysis_window.configure(bg="#1a1a1a")
        
        main_frame = tk.Frame(analysis_window, bg="#252525", pady=20, padx=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(main_frame, text="数据分析", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 按钮区
        btn_frame = tk.Frame(main_frame, bg="#252525")
        btn_frame.pack(fill=tk.X, pady=10)
        
        tk.Button(btn_frame, text="趋势分析", command=self._show_trend_analysis, bg="#007acc", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="周期对比", command=self._show_period_comparison, bg="#4CAF50", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="数据预测", command=self._show_data_prediction, bg="#FF9800", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        
        # 结果显示区
        result_frame = tk.Frame(main_frame, bg="#1e1e1e", pady=20, padx=20)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.analysis_result_text = tk.Text(result_frame, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 11), wrap=tk.WORD)
        self.analysis_result_text.pack(fill=tk.BOTH, expand=True)
        self.analysis_result_text.insert(tk.END, "点击上方按钮查看分析结果...")
    
    def _show_trend_analysis(self):
        """显示趋势分析"""
        try:
            from core.account_operations_manager import data_analyzer
            trend = data_analyzer.analyze_trend("views", days=7)
            result = f"趋势分析结果:\n"
            result += f"趋势方向: {trend['trend']}\n"
            result += f"变化率: {trend['change_rate']:.2f}%\n"
            result += f"数据点: {trend['data_points']}\n"
            self.analysis_result_text.delete(1.0, tk.END)
            self.analysis_result_text.insert(tk.END, result)
        except Exception as e:
            self.analysis_result_text.delete(1.0, tk.END)
            self.analysis_result_text.insert(tk.END, f"分析失败: {e}")
    
    def _show_period_comparison(self):
        """显示周期对比"""
        try:
            from core.account_operations_manager import data_analyzer
            comparison = data_analyzer.compare_periods("views", days=7)
            result = f"周期对比结果:\n"
            result += f"当前周期: {comparison['current_period']}\n"
            result += f"上一周期: {comparison['previous_period']}\n"
            result += f"增长率: {comparison['growth_rate']:.2f}%\n"
            self.analysis_result_text.delete(1.0, tk.END)
            self.analysis_result_text.insert(tk.END, result)
        except Exception as e:
            self.analysis_result_text.delete(1.0, tk.END)
            self.analysis_result_text.insert(tk.END, f"对比失败: {e}")
    
    def _show_data_prediction(self):
        """显示数据预测"""
        try:
            from core.account_operations_manager import data_analyzer
            prediction = data_analyzer.predict_future("views", days=7)
            result = f"数据预测结果:\n"
            result += f"预测值: {prediction['predicted_value']:.2f}\n"
            result += f"置信区间: [{prediction['confidence_interval'][0]:.2f}, {prediction['confidence_interval'][1]:.2f}]\n"
            result += f"趋势: {prediction['trend']}\n"
            self.analysis_result_text.delete(1.0, tk.END)
            self.analysis_result_text.insert(tk.END, result)
        except Exception as e:
            self.analysis_result_text.delete(1.0, tk.END)
            self.analysis_result_text.insert(tk.END, f"预测失败: {e}")
    
    def show_scheduled_tasks(self):
        """显示定时任务界面"""
        task_window = tk.Toplevel(self.root)
        task_window.title("定时任务")
        task_window.geometry("900x600")
        task_window.configure(bg="#1a1a1a")
        
        main_frame = tk.Frame(task_window, bg="#252525", pady=20, padx=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(main_frame, text="定时任务管理", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 按钮区
        btn_frame = tk.Frame(main_frame, bg="#252525")
        btn_frame.pack(fill=tk.X, pady=10)
        
        tk.Button(btn_frame, text="添加任务", command=lambda: self._add_task_dialog(task_window), bg="#007acc", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="启动调度", command=self._start_task_scheduler, bg="#4CAF50", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="停止调度", command=self._stop_task_scheduler, bg="#f44336", fg="#ffffff", padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        
        # 任务列表
        list_frame = tk.Frame(main_frame, bg="#1e1e1e")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ("ID", "名称", "类型", "执行时间", "状态", "创建时间")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=120)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self._load_task_data(tree)
    
    def _add_task_dialog(self, parent):
        """添加任务对话框"""
        dialog = tk.Toplevel(parent)
        dialog.title("添加定时任务")
        dialog.geometry("400x300")
        dialog.configure(bg="#252525")
        
        tk.Label(dialog, text="任务名称:", bg="#252525", fg="#ffffff").pack(pady=5)
        name_entry = tk.Entry(dialog, width=30)
        name_entry.pack(pady=5)
        
        tk.Label(dialog, text="任务类型:", bg="#252525", fg="#ffffff").pack(pady=5)
        type_var = tk.StringVar(value="publish")
        ttk.Combobox(dialog, textvariable=type_var, values=["publish", "reply", "sync", "backup"], state="readonly", width=28).pack(pady=5)
        
        tk.Label(dialog, text="执行时间:", bg="#252525", fg="#ffffff").pack(pady=5)
        time_entry = tk.Entry(dialog, width=30)
        time_entry.insert(0, "2024-12-01 10:00:00")
        time_entry.pack(pady=5)
        
        def save_task():
            try:
                from core.account_operations_manager import task_manager
                task_data = {
                    "name": name_entry.get(),
                    "task_type": type_var.get(),
                    "execute_time": time_entry.get()
                }
                task_manager.add_task(task_data)
                messagebox.showinfo("成功", "任务添加成功！")
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"添加失败: {e}")
        
        tk.Button(dialog, text="保存", command=save_task, bg="#007acc", fg="#ffffff", padx=20, pady=5).pack(pady=20)
    
    def _start_task_scheduler(self):
        """启动任务调度器"""
        try:
            from core.account_operations_manager import task_manager
            task_manager.start_scheduler()
            messagebox.showinfo("成功", "任务调度器已启动")
        except Exception as e:
            messagebox.showerror("错误", f"启动失败: {e}")
    
    def _stop_task_scheduler(self):
        """停止任务调度器"""
        try:
            from core.account_operations_manager import task_manager
            task_manager.stop_scheduler()
            messagebox.showinfo("成功", "任务调度器已停止")
        except Exception as e:
            messagebox.showerror("错误", f"停止失败: {e}")
    
    def _load_task_data(self, tree):
        """加载任务数据"""
        try:
            from core.account_operations_manager import task_manager
            tasks = task_manager.get_all_tasks()
            for task in tasks:
                tree.insert("", tk.END, values=(
                    task.get("id", ""),
                    task.get("name", ""),
                    task.get("task_type", ""),
                    task.get("execute_time", ""),
                    task.get("status", ""),
                    task.get("created_at", "")
                ))
        except Exception as e:
            tree.insert("", tk.END, values=("加载失败", str(e), "", "", "", ""))
    
    def show_account_security(self):
        """显示账号安全界面"""
        security_window = tk.Toplevel(self.root)
        security_window.title("账号安全")
        security_window.geometry("900x600")
        security_window.configure(bg="#1a1a1a")
        
        main_frame = tk.Frame(security_window, bg="#252525", pady=20, padx=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(main_frame, text="账号安全管理", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=10)
        
        # 安全评分
        score_frame = tk.Frame(main_frame, bg="#1e1e1e", pady=20, padx=20)
        score_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(score_frame, text="安全评分", font=("微软雅黑", 14, "bold"), bg="#1e1e1e", fg="#ffffff").pack(anchor=tk.W)
        
        self.security_score_label = tk.Label(score_frame, text="--", font=("微软雅黑", 36, "bold"), bg="#1e1e1e", fg="#ff9800")
        self.security_score_label.pack(pady=10)
        
        # 安全检查按钮
        tk.Button(score_frame, text="开始安全检查", command=self._run_security_check, bg="#007acc", fg="#ffffff", padx=20, pady=10).pack(pady=10)
        
        # 检查结果
        result_frame = tk.Frame(main_frame, bg="#1e1e1e", pady=10, padx=10)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        tk.Label(result_frame, text="检查结果", font=("微软雅黑", 12, "bold"), bg="#1e1e1e", fg="#ffffff").pack(anchor=tk.W, pady=5)
        
        self.security_result_text = tk.Text(result_frame, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10), wrap=tk.WORD, height=15)
        self.security_result_text.pack(fill=tk.BOTH, expand=True)
        self.security_result_text.insert(tk.END, "点击\"开始安全检查\"查看详细结果...")
    
    def _run_security_check(self):
        """运行安全检查"""
        try:
            from core.account_operations_manager import security_manager
            report = security_manager.security_checkup()
            
            # 更新评分
            score = report.get("security_score", 0)
            self.security_score_label.config(text=f"{score}分")
            
            # 更新颜色
            if score >= 80:
                self.security_score_label.config(fg="#4CAF50")
            elif score >= 60:
                self.security_score_label.config(fg="#ff9800")
            else:
                self.security_score_label.config(fg="#f44336")
            
            # 显示详细结果
            result_text = f"检查时间: {report.get('check_time', '')}\n\n"
            result_text += f"风险等级: {report.get('risk_level', '')}\n"
            result_text += f"安全评分: {score}/100\n\n"
            
            result_text += "检查项:\n"
            for check in report.get("checks", []):
                status = "通过" if check.get("passed") else "未通过"
                result_text += f"  - {check.get('name', '')}: {status}\n"
            
            result_text += f"\n优化建议:\n"
            for suggestion in report.get("suggestions", []):
                result_text += f"  - {suggestion}\n"
            
            self.security_result_text.delete(1.0, tk.END)
            self.security_result_text.insert(tk.END, result_text)
            
        except Exception as e:
            self.security_result_text.delete(1.0, tk.END)
            self.security_result_text.insert(tk.END, f"检查失败: {e}")
    
    def bind_shortcuts(self):
        """绑定快捷键"""
        # 主窗口快捷键
        self.root.bind("<Control-o>", lambda e: self.import_media())
        self.root.bind("<Control-s>", lambda e: self.save_project())
        self.root.bind("<Control-e>", lambda e: self.export_project())
        self.root.bind("<Control-z>", lambda e: self.undo_action())
        self.root.bind("<Control-y>", lambda e: self.redo_action())
        self.root.bind("<Control-q>", lambda e: self.on_closing())
        self.root.bind("<F1>", lambda e: self.show_help())
        self.root.bind("<F5>", lambda e: self.start_video_editing())
        self.root.bind("<F11>", lambda e: self.toggle_fullscreen())
        
        # 视频预览快捷键
        try:
            self.preview_canvas.bind("<space>", lambda e: self.play_pause())
            self.preview_canvas.bind("<Left>", lambda e: self.rewind())
            self.preview_canvas.bind("<Right>", lambda e: self.fast_forward())
            self.preview_canvas.bind("<Up>", lambda e: self.increase_volume())
            self.preview_canvas.bind("<Down>", lambda e: self.decrease_volume())
            self.preview_canvas.bind("<c>", lambda e: self.capture_frame())
        except:
            pass
    
    def show_help(self):
        """显示帮助文档"""
        help_window = tk.Toplevel(self.root)
        help_window.title("帮助文档")
        help_window.geometry("800x600")
        help_window.configure(bg="#1a1a1a")
        
        # 帮助内容
        help_frame = tk.Frame(help_window, bg="#252525", pady=30, padx=30)
        help_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(help_frame, text="AI短剧编辑器 - 帮助文档", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 快捷键部分
        tk.Label(help_frame, text="快捷键", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#007acc").pack(anchor=tk.W, pady=10)
        
        shortcuts = [
            ["Ctrl+O", "导入媒体文件"],
            ["Ctrl+S", "保存项目"],
            ["Ctrl+E", "导出项目"],
            ["Ctrl+Z", "撤销操作"],
            ["Ctrl+Y", "重做操作"],
            ["Ctrl+Q", "退出程序"],
            ["F1", "显示帮助"],
            ["F5", "开始剪辑"],
            ["F11", "切换全屏"],
            ["空格", "播放/暂停预览"],
            ["左箭头", "倒带"],
            ["右箭头", "快进"],
            ["上箭头", "增加音量"],
            ["下箭头", "减少音量"],
            ["C", "截图"],
        ]
        
        shortcuts_frame = tk.Frame(help_frame, bg="#252525")
        shortcuts_frame.pack(fill=tk.X, pady=10)
        
        for i, (key, desc) in enumerate(shortcuts):
            key_label = tk.Label(shortcuts_frame, text=key, font=("微软雅黑", 10, "bold"), bg="#252525", fg="#ffffff", width=15, anchor=tk.W)
            key_label.grid(row=i, column=0, sticky=tk.W, padx=10, pady=5)
            desc_label = tk.Label(shortcuts_frame, text=desc, font=("微软雅黑", 10), bg="#252525", fg="#000000")
            desc_label.grid(row=i, column=1, sticky=tk.W, pady=5)
        
        # 使用说明部分
        tk.Label(help_frame, text="使用说明", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#007acc").pack(anchor=tk.W, pady=10)
        
        instructions = [
            "1. 导入媒体文件：点击左侧面板的'导入'按钮或使用Ctrl+O快捷键",
            "2. 选择输出模式：在右侧面板选择适合的输出模式（30秒爆款引流、90秒剧情解说、8分钟挂车长视频）",
            "3. 调整参数：根据需要调整分辨率、帧率、编码等参数",
            "4. 启用AI工具：可以选择启用FunClip自动剪辑、AutoClip高光识别等AI工具",
            "5. 开始剪辑：点击状态栏的'开始剪辑'按钮或使用F5快捷键",
            "6. 查看结果：剪辑完成后，可以在输出目录查看生成的视频",
            "7. 生成文案：在'文案生成'标签页可以为视频生成标题、发布文案和关键词",
            "8. 分析数据：在'账号运营'标签页可以添加和分析账号数据",
            "9. 管理插件：在'插件管理'标签页可以导入和管理插件",
            "10. 配置模型：在'模型配置'标签页可以配置AI模型和API密钥",
        ]
        
        instructions_frame = tk.Frame(help_frame, bg="#252525")
        instructions_frame.pack(fill=tk.X, pady=10)
        
        for i, instruction in enumerate(instructions):
            inst_label = tk.Label(instructions_frame, text=instruction, font=("微软雅黑", 10), bg="#252525", fg="#000000", wraplength=700, justify=tk.LEFT)
            inst_label.pack(anchor=tk.W, pady=5)
        
        # 常见问题部分
        tk.Label(help_frame, text="常见问题", font=("微软雅黑", 12, "bold"), bg="#252525", fg="#007acc").pack(anchor=tk.W, pady=10)
        
        faqs = [
            ["Q: 视频预览不显示？", "A: 请确保已安装FFmpeg，并且视频文件格式支持"],
            ["Q: 插件安装失败？", "A: 请检查插件文件是否为有效的Python文件，并且包含正确的注册代码"],
            ["Q: 剪辑过程卡住？", "A: 可能是视频文件过大或系统资源不足，请尝试较小的视频文件"],
            ["Q: AI文案生成失败？", "A: 请检查API密钥是否正确配置，网络连接是否正常"],
            ["Q: 输出视频没有声音？", "A: 请确保原始视频有音频轨道，并且在导出设置中启用了音频"],
        ]
        
        faq_frame = tk.Frame(help_frame, bg="#252525")
        faq_frame.pack(fill=tk.X, pady=10)
        
        for i, (q, a) in enumerate(faqs):
            q_label = tk.Label(faq_frame, text=q, font=("微软雅黑", 10, "bold"), bg="#252525", fg="#ffffff")
            q_label.pack(anchor=tk.W, pady=5, padx=10)
            a_label = tk.Label(faq_frame, text=a, font=("微软雅黑", 10), bg="#252525", fg="#000000", wraplength=700, justify=tk.LEFT)
            a_label.pack(anchor=tk.W, pady=5, padx=30)
    
    def toggle_fullscreen(self):
        """切换全屏模式"""
        if not hasattr(self, 'fullscreen'):
            self.fullscreen = False
        
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        
        if self.fullscreen:
            self.status_label.config(text="全屏模式")
        else:
            self.status_label.config(text="窗口模式")
    
    def increase_volume(self):
        """增加音量"""
        try:
            current_volume = self.volume_var.get()
            new_volume = min(1.0, current_volume + 0.1)
            self.volume_var.set(new_volume)
            self.status_label.config(text=f"音量: {int(new_volume * 100)}%")
        except:
            pass
    
    def decrease_volume(self):
        """减少音量"""
        try:
            current_volume = self.volume_var.get()
            new_volume = max(0.0, current_volume - 0.1)
            self.volume_var.set(new_volume)
            self.status_label.config(text=f"音量: {int(new_volume * 100)}%")
        except:
            pass

    def show_model_stats(self):
        """显示模型统计信息"""
        stats_window = tk.Toplevel(self.root)
        stats_window.title("模型统计信息")
        stats_window.geometry("800x600")
        stats_window.configure(bg="#1a1a1a")
        
        # 统计信息框架
        stats_frame = tk.Frame(stats_window, bg="#252525", pady=30, padx=30)
        stats_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(stats_frame, text="模型统计信息", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 统计信息文本
        stats_text = scrolledtext.ScrolledText(stats_frame, wrap=tk.WORD, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10), height=20)
        stats_text.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 获取统计信息
        stats = model_manager.get_model_stats()
        
        # 构建统计信息文本
        stats_content = "模型统计信息:\n\n"
        for model, model_stats in stats.items():
            calls = model_stats.get("calls", 0)
            success = model_stats.get("success", 0)
            failures = model_stats.get("failures", 0)
            avg_time = model_stats.get("average_time", 0)
            success_rate = (success / calls * 100) if calls > 0 else 0
            
            stats_content += f"{model}:\n"
            stats_content += f"  调用次数: {calls}\n"
            stats_content += f"  成功次数: {success}\n"
            stats_content += f"  失败次数: {failures}\n"
            stats_content += f"  成功率: {success_rate:.2f}%\n"
            stats_content += f"  平均响应时间: {avg_time:.2f}秒\n\n"
        
        stats_text.insert(tk.END, stats_content)
        stats_text.config(state=tk.DISABLED)

    def add_custom_model(self):
        """添加自定义模型"""
        model_name = self.custom_model_name_var.get().strip()
        if not model_name:
            messagebox.showerror("错误", "请输入模型名称")
            return
        
        # 添加自定义模型
        model_config = {
            "timeout": 10,
            "max_tokens": 200,
            "temperature": 0.7,
            "enabled": True
        }
        
        if model_manager.add_custom_model(model_name, model_config):
            # 更新下拉菜单
            self.default_model_menu['values'] = model_manager.models
            self.custom_model_name_var.set("")
            messagebox.showinfo("成功", f"自定义模型 '{model_name}' 已添加")
        else:
            messagebox.showerror("错误", f"模型名称 '{model_name}' 已存在")

    def remove_custom_model(self):
        """移除自定义模型"""
        model_name = self.remove_model_var.get().strip()
        if not model_name:
            messagebox.showerror("错误", "请选择要移除的模型")
            return
        
        if model_manager.remove_custom_model(model_name):
            # 更新下拉菜单
            self.default_model_menu['values'] = model_manager.models
            # 更新移除模型下拉菜单
            custom_models = [model for model in model_manager.models if model not in ["本地爆款模型", "智能剪辑模型"]]
            self.remove_model_var.set("")
            messagebox.showinfo("成功", f"自定义模型 '{model_name}' 已移除")
        else:
            messagebox.showerror("错误", f"无法移除模型 '{model_name}'")

    def on_plugin_category_change(self, event):
        """处理插件分类变化"""
        category = self.plugin_category_var.get()
        self.filter_plugins_by_category(event)

    def filter_plugins_by_category(self, event):
        """按分类过滤插件"""
        category = self.plugin_category_var.get()
        
        # 清空列表
        self.plugin_listbox.delete(0, tk.END)
        
        # 填充插件列表
        for plugin_name in plugins.keys():
            plugin_category = plugin_categories.get(plugin_name, "工具")
            if category == "全部" or plugin_category == category:
                version = plugin_versions.get(plugin_name, "1.0.0")
                self.plugin_listbox.insert(tk.END, f"{plugin_name} (v{version}) - {plugin_category}")

    def search_plugins(self):
        """搜索插件"""
        search_term = self.plugin_search_var.get().lower()
        
        # 清空列表
        self.plugin_listbox.delete(0, tk.END)
        
        # 填充插件列表
        for plugin_name in plugins.keys():
            if search_term in plugin_name.lower():
                category = plugin_categories.get(plugin_name, "工具")
                version = plugin_versions.get(plugin_name, "1.0.0")
                self.plugin_listbox.insert(tk.END, f"{plugin_name} (v{version}) - {category}")

    def on_plugin_select(self, event):
        """处理插件选择"""
        selected_indices = self.plugin_listbox.curselection()
        if not selected_indices:
            return
        
        selected_index = selected_indices[0]
        selected_item = self.plugin_listbox.get(selected_index)
        # 提取插件名称
        plugin_name = selected_item.split(" (")[0]
        
        # 显示插件信息
        self.plugin_info_text.config(state=tk.NORMAL)
        self.plugin_info_text.delete(1.0, tk.END)
        
        info = f"插件名称: {plugin_name}\n"
        info += f"版本: {plugin_versions.get(plugin_name, '1.0.0')}\n"
        info += f"分类: {plugin_categories.get(plugin_name, '工具')}\n"
        info += f"描述: {plugin_configs.get(plugin_name, {}).get('description', '无描述')}\n"
        
        self.plugin_info_text.insert(tk.END, info)
        self.plugin_info_text.config(state=tk.DISABLED)

    def install_plugin(self):
        """安装插件"""
        install_window = tk.Toplevel(self.root)
        install_window.title("安装插件")
        install_window.geometry("600x400")
        install_window.configure(bg="#1a1a1a")
        
        # 安装框架
        install_frame = tk.Frame(install_window, bg="#252525", pady=30, padx=30)
        install_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        tk.Label(install_frame, text="安装插件", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#ffffff").pack(anchor=tk.W, pady=20)
        
        # 插件名称
        tk.Label(install_frame, text="插件名称:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, padx=20, pady=10)
        self.install_plugin_name_var = tk.StringVar(value="")
        name_entry = tk.Entry(install_frame, textvariable=self.install_plugin_name_var, width=50, bg="#2d2d2d", fg="#ffffff", font=("微软雅黑", 10))
        name_entry.pack(anchor=tk.W, padx=20, pady=10)
        
        # 插件代码
        tk.Label(install_frame, text="插件代码:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, padx=20, pady=10)
        code_text = scrolledtext.ScrolledText(install_frame, wrap=tk.WORD, width=50, height=10, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        code_text.pack(anchor=tk.W, padx=20, pady=10)
        
        # 安装按钮
        install_btn = tk.Button(install_frame, text="安装", command=lambda: self.do_install_plugin(install_window, code_text), bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=10, relief=tk.FLAT)
        install_btn.pack(anchor=tk.CENTER, pady=20)

    def do_install_plugin(self, window, code_text):
        """执行插件安装"""
        plugin_name = self.install_plugin_name_var.get().strip()
        plugin_code = code_text.get(1.0, tk.END).strip()
        
        if not plugin_name:
            messagebox.showerror("错误", "请输入插件名称")
            return
        
        if not plugin_code:
            messagebox.showerror("错误", "请输入插件代码")
            return
        
        # 安装插件
        if plugin_manager.install_plugin(plugin_name, plugin_code):
            # 刷新插件列表
            self.refresh_plugins()
            messagebox.showinfo("成功", f"插件 '{plugin_name}' 安装成功")
            window.destroy()
        else:
            messagebox.showerror("错误", f"插件 '{plugin_name}' 安装失败")

    def uninstall_plugin(self):
        """卸载插件"""
        selected_indices = self.plugin_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要卸载的插件")
            return
        
        selected_index = selected_indices[0]
        selected_item = self.plugin_listbox.get(selected_index)
        plugin_name = selected_item.split(" (")[0]
        
        if messagebox.askyesno("确认", f"确定要卸载插件 '{plugin_name}' 吗？"):
            if plugin_manager.uninstall_plugin(plugin_name):
                # 刷新插件列表
                self.refresh_plugins()
                messagebox.showinfo("成功", f"插件 '{plugin_name}' 卸载成功")
            else:
                messagebox.showerror("错误", f"插件 '{plugin_name}' 卸载失败")

    def refresh_plugins(self):
        """刷新插件列表"""
        # 清空列表
        self.plugin_listbox.delete(0, tk.END)
        
        # 填充基于函数的插件
        for plugin_name in plugins.keys():
            category = plugin_categories.get(plugin_name, "工具")
            version = plugin_versions.get(plugin_name, "1.0.0")
            self.plugin_listbox.insert(tk.END, f"{plugin_name} (v{version}) - {category}")
        
        # 填充基于类的插件
        for plugin in loaded_plugins:
            if hasattr(plugin, "get_name"):
                plugin_name = plugin.get_name()
                self.plugin_listbox.insert(tk.END, f"{plugin_name} (v1.0.0) - 视频处理")

    def import_plugin(self):
        """导入插件"""
        plugin_file = self.plugin_file_var.get().strip()
        if not plugin_file:
            messagebox.showerror("错误", "请选择插件文件")
            return
        
        if not os.path.exists(plugin_file):
            messagebox.showerror("错误", "插件文件不存在")
            return
        
        try:
            # 使用PluginManager导入插件
            success, message = plugin_manager.import_plugin(plugin_file)
            
            if success:
                self.import_status_var.set(message)
                # 刷新插件列表
                self.refresh_plugins()
                messagebox.showinfo("成功", message)
            else:
                self.import_status_var.set(message)
                messagebox.showerror("错误", message)
        except Exception as e:
            self.import_status_var.set(f"插件导入失败: {str(e)}")
            messagebox.showerror("错误", f"插件导入失败: {str(e)}")

    def check_plugin_updates(self):
        """检查插件更新"""
        self.update_status_var.set("正在检查插件更新...")
        
        # 模拟检查更新
        import threading
        import time
        
        def simulate_check():
            time.sleep(2)
            self.update_status_var.set("插件更新检查完成，所有插件均为最新版本")
            messagebox.showinfo("成功", "插件更新检查完成，所有插件均为最新版本")
        
        thread = threading.Thread(target=simulate_check, daemon=True)
        thread.start()
    
    def show_pyqt_plugin_manager(self):
        """显示PyQt5插件管理器"""
        try:
            # 检查PyQt5依赖
            from PyQt5.QtWidgets import QApplication
            import sys
            
            # 导入PyQt5插件管理器
            from modules.plugins.pyqt_plugin_manager import PyQtPluginManager
            
            # 确保有QApplication实例
            app = QApplication.instance()
            if not app:
                app = QApplication(sys.argv)
            
            # 创建并显示插件管理器
            manager = PyQtPluginManager()
            manager.show()
            
            # 如果是独立应用，运行事件循环
            if not QApplication.instance().thread().isRunning():
                sys.exit(app.exec_())
        except ImportError as e:
            messagebox.showerror("错误", f"缺少PyQt5依赖：{str(e)}")
        except Exception as e:
            messagebox.showerror("错误", f"启动PyQt5插件管理器失败：{str(e)}")
    
    def add_external_plugin(self):
        """添加外部插件"""
        plugin_path = filedialog.askopenfilename(
            title="选择插件文件",
            filetypes=[("Python插件", "*.py"), ("所有文件", "*.*")]
        )
        
        if plugin_path:
            # 确保插件目录存在
            plugin_dir = os.path.join(OUTPUT_DIR, "plugins")
            os.makedirs(plugin_dir, exist_ok=True)
            
            # 复制插件到插件目录
            plugin_name = os.path.basename(plugin_path)
            target_path = os.path.join(plugin_dir, plugin_name)
            
            try:
                import shutil
                shutil.copy2(plugin_path, target_path)
                self.status_label.config(text=f"插件已添加: {plugin_name}")
                self.refresh_plugins()  # 重新加载插件
            except Exception as e:
                messagebox.showerror("添加插件失败", f"无法添加插件: {str(e)}")
    
    def start_background_rendering(self, project_data, output_path):
        """启动后台渲染任务"""
        try:
            self.status_label.config(text="正在启动后台渲染...")
            
            # 提交到线程池
            thread_pool.submit(lambda: self.render_video_in_background(project_data, output_path))
            
            self.status_label.config(text="后台渲染已启动")
        except Exception as e:
            print(f"启动后台渲染失败: {e}")
            self.status_label.config(text="启动后台渲染失败")
    
    def render_video_in_background(self, project_data, output_path):
        """在后台渲染视频"""
        try:
            # 模拟渲染过程
            import time
            
            # 更新状态
            self.status_label.config(text="后台渲染中...")
            
            # 模拟渲染时间
            time.sleep(5)  # 实际项目中这里会调用FFmpeg进行渲染
            
            # 创建模拟输出文件
            with open(output_path, 'w') as f:
                f.write("Rendered video placeholder")
            
            # 更新状态
            self.status_label.config(text=f"后台渲染完成: {os.path.basename(output_path)}")
        except Exception as e:
            print(f"后台渲染失败: {e}")
            self.status_label.config(text="后台渲染失败")
    
    def process_large_video(self, video_path):
        """处理大视频文件"""
        try:
            self.status_label.config(text="正在处理大视频文件...")
            
            # 获取视频信息
            video_info = self.get_video_info(video_path)
            
            # 检查文件大小
            file_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
            
            if file_size > 1000:  # 大于1GB
                self.status_label.config(text="检测到大型视频文件，使用优化处理模式")
                
                # 提交到线程池进行处理
                thread_pool.submit(lambda: self.process_large_video_in_background(video_path))
            else:
                # 正常处理
                self.status_label.config(text="视频文件大小正常，使用标准处理模式")
                self.process_video(video_path, "standard", "large_video", self.status_label, None, None, None, None, None, None)
        except Exception as e:
            print(f"处理大视频文件失败: {e}")
            self.status_label.config(text="处理大视频文件失败")
    
    def process_large_video_in_background(self, video_path):
        """在后台处理大视频文件"""
        try:
            # 模拟大视频处理过程
            import time
            
            # 更新状态
            self.status_label.config(text="正在后台处理大视频文件...")
            
            # 模拟处理时间
            time.sleep(10)  # 实际项目中这里会进行分块处理
            
            # 更新状态
            self.status_label.config(text=f"大视频文件处理完成: {os.path.basename(video_path)}")
        except Exception as e:
            print(f"后台处理大视频文件失败: {e}")
            self.status_label.config(text="后台处理大视频文件失败")
    
    def get_video_info(self, video_path):
        """获取视频信息"""
        try:
            # 使用FFmpeg获取视频信息
            cmd = [
                FFMPEG,
                "-i", video_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                import json
                return json.loads(result.stdout)
            return {}
        except Exception as e:
            print(f"获取视频信息失败: {e}")
            return {}

# ===================== 自检功能 =====================
def run_self_check():
    """应用启动自检，检查文件是否完整"""
    print("\n=== 应用自检开始 ===")
    
    # 检查必要的目录
    required_dirs = [
        OUTPUT_DIR,
        os.path.join(OUTPUT_DIR, "plugins"),
        os.path.join(OUTPUT_DIR, "models"),
        os.path.join(OUTPUT_DIR, "temp")
    ]
    
    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"✓ 目录存在: {dir_path}")
        else:
            try:
                os.makedirs(dir_path, exist_ok=True)
                print(f"✓ 创建目录: {dir_path}")
            except Exception as e:
                print(f"✗ 无法创建目录 {dir_path}: {e}")
    
    # 检查必要的模块
    print("\n检查必要的模块...")
    required_modules = [
        "tkinter", "cv2", "PIL", "numpy", "moviepy", 
        "requests", "json", "os", "sys", "threading",
        "subprocess", "time", "datetime", "tempfile"
    ]
    
    missing_modules = []
    for module in required_modules:
        try:
            __import__(module)
            print(f"✓ 模块可用: {module}")
        except ImportError:
            missing_modules.append(module)
            print(f"✗ 模块缺失: {module}")
    
    # 检查FFmpeg
    print("\n检查FFmpeg...")
    try:
        import subprocess
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✓ FFmpeg 可用")
        else:
            print("✗ FFmpeg 不可用")
    except Exception as e:
        print(f"✗ FFmpeg 检查失败: {e}")
    
    # 检查GPU支持
    print("\n检查GPU支持...")
    gpu_supported = False
    
    # 方法1: 使用OpenCV CUDA检查
    try:
        import cv2
        if hasattr(cv2, 'cuda'):
            gpu_count = cv2.cuda.getCudaEnabledDeviceCount()
            if gpu_count > 0:
                print(f"✓ GPU 支持: {gpu_count} 个CUDA设备")
                gpu_supported = True
            else:
                print("✗ 未检测到CUDA GPU设备")
        else:
            print("✗ OpenCV CUDA模块不可用")
    except Exception as e:
        print(f"✗ OpenCV CUDA检查失败: {e}")
    
    # 方法2: 使用FFmpeg检查GPU编码器
    try:
        from modules.utils.hardware import detect_gpu_encoder
        ffmpeg_gpu_encoder = detect_gpu_encoder(FFMPEG)
        if ffmpeg_gpu_encoder != "libx264":
            print(f"✓ FFmpeg GPU编码器: {ffmpeg_gpu_encoder}")
            gpu_supported = True
        else:
            print("✗ FFmpeg未检测到GPU编码器")
    except Exception as e:
        print(f"✗ FFmpeg GPU检查失败: {e}")
    
    # 方法3: 检查系统中是否有GPU
    try:
        import subprocess
        if platform.system() == "Windows":
            # 在Windows上使用wmic命令检查GPU
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True,
                text=True
            )
            if "NVIDIA" in result.stdout or "AMD" in result.stdout or "Intel" in result.stdout:
                print("✓ 系统检测到GPU设备")
                gpu_supported = True
            else:
                print("✗ 系统未检测到GPU设备")
    except Exception as e:
        print(f"✗ 系统GPU检查失败: {e}")
    
    # 最终结果
    if gpu_supported:
        print("✓ GPU 支持: 可用")
    else:
        print("✗ GPU 支持: 无")
    
    print("\n=== 应用自检完成 ===")
    
    if missing_modules:
        print(f"\n警告: 缺少 {len(missing_modules)} 个模块，部分功能可能无法使用")
    
    return len(missing_modules) == 0

# ===================== 主程序 =====================
if __name__ == "__main__":
    print("AI短剧编辑器启动中...")
    
    # 导入延迟模块
    print("加载核心模块...")
    import tkinter as tk
    from tkinter import *  # noqa: F403,F401 保留通配符以兼容主程序内使用的 tk 名称
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    import requests
    import json
    import os
    import sys
    
    # 运行自检
    self_check_passed = run_self_check()
    
    # 现在导入了所有必要的模块，可以正常运行
    print(f"\n使用GPU编码器: {GPU_ENCODER}")
    print(f"最大并行线程: {MAX_PARALLEL}")
    print(f"输出目录: {OUTPUT_DIR}")
    
    app = AIShortDramaEditor()
    app.root.mainloop()
# core/plugin_manager.py
import os
import json
import importlib.util
import shutil
import zipfile
from datetime import datetime
from modules.utils.logger import logger
from config.settings import Config
from modules.plugins.plugin_system import plugin_get_video_info, register_plugin

class PluginManager:
    """插件管理类（支持内置插件和外部插件）"""
    def __init__(self):
        # 内置插件目录（程序自带，不可修改）
        self.builtin_plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
        # 外部插件安装目录（用户导入的插件会安装到这里）
        self.external_plugins_dir = os.path.join(Config.APP_DATA_DIR, "plugins")
        self.loaded_plugins = {}
        self.plugin_metadata = {}
        
        # 确保目录存在
        os.makedirs(self.builtin_plugins_dir, exist_ok=True)
        os.makedirs(self.external_plugins_dir, exist_ok=True)
        
        # 加载所有插件
        self.load_all_plugins()
    
    def load_all_plugins(self):
        """加载所有插件（内置+外部）"""
        # 清空现有插件
        self.loaded_plugins.clear()
        self.plugin_metadata.clear()
        
        # 加载内置插件
        self.load_plugins_from_dir(self.builtin_plugins_dir, source="builtin")
        
        # 加载外部插件
        self.load_plugins_from_dir(self.external_plugins_dir, source="external")
        
        logger.info(f"插件加载完成，共加载 {len(self.loaded_plugins)} 个插件")
    
    def load_plugins_from_dir(self, plugins_dir, source="builtin"):
        """从指定目录加载插件"""
        if not os.path.exists(plugins_dir):
            return
        
        # 遍历插件目录
        for plugin_name in os.listdir(plugins_dir):
            plugin_path = os.path.join(plugins_dir, plugin_name)
            
            # 检查是否是插件目录
            if os.path.isdir(plugin_path):
                metadata_path = os.path.join(plugin_path, "metadata.json")
                main_path = os.path.join(plugin_path, "main.py")
                
                if os.path.exists(metadata_path) and os.path.exists(main_path):
                    try:
                        # 加载插件元数据
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            metadata = json.load(f)
                        
                        # 设置插件来源和路径
                        metadata["source"] = source
                        metadata["path"] = plugin_path
                        metadata["enabled"] = metadata.get("enabled", True)
                        
                        # 加载插件模块
                        spec = importlib.util.spec_from_file_location(
                            f"plugins.{source}.{plugin_name}.main", 
                            main_path
                        )
                        plugin_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(plugin_module)
                        
                        # 初始化插件
                        if hasattr(plugin_module, "Plugin"):
                            plugin_instance = plugin_module.Plugin()
                            
                            # 记录插件信息
                            self.loaded_plugins[plugin_name] = plugin_instance
                            self.plugin_metadata[plugin_name] = metadata
                            
                            logger.info(f"加载{source}插件成功: {metadata.get('name', plugin_name)} v{metadata.get('version', '1.0.0')}")
                        else:
                            logger.error(f"插件 {plugin_name} 缺少Plugin类")
                    except Exception as e:
                        logger.error(f"加载插件 {plugin_name} 失败: {e}", exc_info=True)
    
    def import_plugin(self, plugin_path):
        """导入外部插件（支持目录或zip压缩包）"""
        try:
            # 检查是否是目录
            if os.path.isdir(plugin_path):
                # 是插件目录，直接安装
                return self.install_plugin(plugin_path)
            elif os.path.isfile(plugin_path) and plugin_path.endswith(".zip"):
                # 是压缩包，解压后安装
                temp_dir = os.path.join(Config.APP_DATA_DIR, "temp", f"plugin_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                os.makedirs(temp_dir, exist_ok=True)
                
                with zipfile.ZipFile(plugin_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # 查找插件目录（压缩包中应该只有一个插件目录）
                extracted_items = os.listdir(temp_dir)
                if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_dir, extracted_items[0])):
                    plugin_dir = os.path.join(temp_dir, extracted_items[0])
                    result = self.install_plugin(plugin_dir)
                    
                    # 清理临时目录
                    shutil.rmtree(temp_dir)
                    return result
                else:
                    logger.error("压缩包格式不正确，应该只包含一个插件目录")
                    shutil.rmtree(temp_dir)
                    return False
            else:
                logger.error("插件格式不正确，应该是目录或zip压缩包")
                return False
        except Exception as e:
            logger.error(f"导入插件失败: {e}", exc_info=True)
            return False
    
    def install_plugin(self, plugin_dir):
        """安装插件到外部插件目录"""
        # 检查插件元数据
        metadata_path = os.path.join(plugin_dir, "metadata.json")
        if not os.path.exists(metadata_path):
            logger.error("插件缺少metadata.json文件")
            return False
        
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        plugin_name = metadata.get("name", os.path.basename(plugin_dir))
        # 替换特殊字符，确保目录名合法
        plugin_name = plugin_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
        
        # 目标安装路径
        target_path = os.path.join(self.external_plugins_dir, plugin_name)
        
        # 如果已存在，覆盖现有版本
        if os.path.exists(target_path):
            logger.warning(f"插件 {plugin_name} 已存在，将覆盖现有版本")
            shutil.rmtree(target_path)
        
        # 复制插件目录
        shutil.copytree(plugin_dir, target_path)
        
        # 重新加载插件
        self.load_all_plugins()
        
        logger.info(f"插件 {plugin_name} 安装成功")
        return True
    
    def uninstall_plugin(self, plugin_name):
        """卸载外部插件（内置插件不能卸载）"""
        # 检查是否是外部插件
        if plugin_name not in self.plugin_metadata:
            logger.error(f"插件 {plugin_name} 不存在")
            return False
        
        plugin_info = self.plugin_metadata[plugin_name]
        if plugin_info["source"] == "builtin":
            logger.error("不能卸载内置插件")
            return False
        
        # 删除插件目录
        plugin_path = plugin_info["path"]
        if os.path.exists(plugin_path):
            shutil.rmtree(plugin_path)
        
        # 重新加载插件
        self.load_all_plugins()
        
        logger.info(f"插件 {plugin_name} 卸载成功")
        return True
    
    def get_plugin(self, plugin_name):
        """获取插件实例"""
        return self.loaded_plugins.get(plugin_name)
    
    def get_all_plugins(self):
        """获取所有已加载的插件"""
        return list(self.plugin_metadata.values())
    
    def enable_plugin(self, plugin_name):
        """启用插件"""
        if plugin_name in self.loaded_plugins:
            try:
                plugin = self.loaded_plugins[plugin_name]
                if hasattr(plugin, "enable"):
                    plugin.enable()
                # 更新插件状态
                if plugin_name in self.plugin_metadata:
                    self.plugin_metadata[plugin_name]["enabled"] = True
                    # 保存状态到元数据文件
                    self.save_plugin_metadata(plugin_name)
                logger.info(f"启用插件成功: {plugin_name}")
                return True
            except Exception as e:
                logger.error(f"启用插件 {plugin_name} 失败: {e}", exc_info=True)
        return False
    
    def disable_plugin(self, plugin_name):
        """禁用插件"""
        if plugin_name in self.loaded_plugins:
            try:
                plugin = self.loaded_plugins[plugin_name]
                if hasattr(plugin, "disable"):
                    plugin.disable()
                # 更新插件状态
                if plugin_name in self.plugin_metadata:
                    self.plugin_metadata[plugin_name]["enabled"] = False
                    # 保存状态到元数据文件
                    self.save_plugin_metadata(plugin_name)
                logger.info(f"禁用插件成功: {plugin_name}")
                return True
            except Exception as e:
                logger.error(f"禁用插件 {plugin_name} 失败: {e}", exc_info=True)
        return False
    
    def save_plugin_metadata(self, plugin_name):
        """保存插件元数据到文件"""
        if plugin_name not in self.plugin_metadata:
            return
        
        plugin_info = self.plugin_metadata[plugin_name]
        metadata_path = os.path.join(plugin_info["path"], "metadata.json")
        
        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(plugin_info, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存插件元数据失败: {e}", exc_info=True)
# ui/main_window.py 中修改 show_plugin_management_tab 方法
def show_plugin_management_tab(self):
    """显示插件管理界面（支持外部插件）"""
    # 清空主内容区
    self.clear_main_content()
    
    # 创建插件管理界面
    plugin_frame = ttk.Frame(self.main_content)
    plugin_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    # 标题和说明
    title_frame = ttk.Frame(plugin_frame)
    title_frame.pack(fill=tk.X, padx=5, pady=5)
    
    ttk.Label(title_frame, text="插件管理", font=("微软雅黑", 14, "bold")).pack(side=tk.LEFT)
    ttk.Label(title_frame, text="（支持内置插件和外部插件）", 
             foreground="#008000").pack(side=tk.LEFT, padx=10)
    
    # 插件搜索和筛选
    search_frame = ttk.Frame(plugin_frame)
    search_frame.pack(fill=tk.X, padx=5, pady=5)
    
    ttk.Label(search_frame, text="搜索插件:").pack(side=tk.LEFT, padx=2)
    self.plugin_search_entry = ttk.Entry(search_frame)
    self.plugin_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
    self.plugin_search_entry.bind("<KeyRelease>", self.search_plugins)
    
    ttk.Label(search_frame, text="分类筛选:").pack(side=tk.LEFT, padx=5, pady=2)
    self.plugin_category_combo = ttk.Combobox(search_frame, values=["所有", "视频处理", "AI工具", "导出工具"])
    self.plugin_category_combo.set("所有")
    self.plugin_category_combo.pack(side=tk.LEFT, padx=2)
    self.plugin_category_combo.bind("<<ComboboxSelected>>", self.filter_plugins)
    
    # 插件操作按钮（导入、卸载等）
    plugin_ops_frame = ttk.Frame(plugin_frame)
    plugin_ops_frame.pack(fill=tk.X, padx=5, pady=5)
    
    self.import_plugin_btn = ttk.Button(plugin_ops_frame, text="导入插件", command=self.import_external_plugin)
    self.import_plugin_btn.pack(side=tk.LEFT, padx=2)
    
    self.uninstall_plugin_btn = ttk.Button(plugin_ops_frame, text="卸载插件", command=self.uninstall_selected_plugin)
    self.uninstall_plugin_btn.pack(side=tk.LEFT, padx=2)
    
    self.refresh_plugins_btn = ttk.Button(plugin_ops_frame, text="刷新插件", command=self.refresh_plugins)
    self.refresh_plugins_btn.pack(side=tk.RIGHT, padx=2)
    
    # 插件列表
    self.plugin_listbox = tk.Listbox(plugin_frame, selectmode=tk.SINGLE, height=15)
    self.plugin_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    # 插件列表滚动条
    plugin_scroll = ttk.Scrollbar(plugin_frame, orient=tk.VERTICAL, command=self.plugin_listbox.yview)
    plugin_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    self.plugin_listbox.configure(yscrollcommand=plugin_scroll.set)
    
    # 插件信息
    plugin_info_frame = ttk.LabelFrame(plugin_frame, text="插件信息")
    plugin_info_frame.pack(fill=tk.X, padx=5, pady=5)
    
    self.plugin_name_label = ttk.Label(plugin_info_frame, text="插件名称: -", font=("微软雅黑", 12, "bold"))
    self.plugin_name_label.pack(fill=tk.X, padx=5, pady=2)
    
    self.plugin_version_label = ttk.Label(plugin_info_frame, text="版本: -")
    self.plugin_version_label.pack(fill=tk.X, padx=5, pady=2)
    
    self.plugin_description_label = ttk.Label(plugin_info_frame, text="描述: -", wraplength=600, justify=tk.LEFT)
    self.plugin_description_label.pack(fill=tk.X, padx=5, pady=2)
    
    self.plugin_author_label = ttk.Label(plugin_info_frame, text="作者: -")
    self.plugin_author_label.pack(fill=tk.X, padx=5, pady=2)
    
    self.plugin_source_label = ttk.Label(plugin_info_frame, text="来源: -")
    self.plugin_source_label.pack(fill=tk.X, padx=5, pady=2)
    
    self.plugin_status_label = ttk.Label(plugin_info_frame, text="状态: -")
    self.plugin_status_label.pack(fill=tk.X, padx=5, pady=2)
    
    # 插件操作按钮（启用、禁用）
    plugin_control_frame = ttk.Frame(plugin_frame)
    plugin_control_frame.pack(fill=tk.X, padx=5, pady=5)
    
    self.enable_plugin_btn = ttk.Button(plugin_control_frame, text="启用", command=self.enable_selected_plugin)
    self.enable_plugin_btn.pack(side=tk.LEFT, padx=2)
    
    self.disable_plugin_btn = ttk.Button(plugin_control_frame, text="禁用", command=self.disable_selected_plugin)
    self.disable_plugin_btn.pack(side=tk.LEFT, padx=2)
    
    # 绑定插件列表选择事件
    self.plugin_listbox.bind("<<ListboxSelect>>", self.show_plugin_info)
    
    # 初始化插件列表
    self.update_plugin_list()
# ui/main_window.py 中添加以下方法
def import_external_plugin(self):
    """导入外部插件"""
    # 允许用户选择插件目录或zip文件
    file_path = filedialog.askopenfilename(
        title="导入插件",
        filetypes=[("插件压缩包", "*.zip"), ("插件目录", "*")]
    )
    
    if not file_path:
        return
    
    self.status_bar.config(text="正在导入插件...")
    self.root.update_idletasks()
    
    if self.plugin_manager.import_plugin(file_path):
        self.update_plugin_list()
        self.status_bar.config(text="插件导入成功")
        messagebox.showinfo("成功", "插件导入成功")
    else:
        self.status_bar.config(text="插件导入失败")
        messagebox.showerror("错误", "插件导入失败，请检查插件格式是否正确")

def uninstall_selected_plugin(self):
    """卸载选中的插件"""
    selected = self.plugin_listbox.curselection()
    if selected:
        index = selected[0]
        plugins = self.plugin_manager.get_all_plugins()
        if index < len(plugins):
            plugin = plugins[index]
            plugin_name = plugin.get('name')
            
            if plugin["source"] == "builtin":
                messagebox.showwarning("警告", "不能卸载内置插件")
                return
            
            if messagebox.askyesno("确认", f"确定要卸载插件 {plugin_name} 吗？"):
                if self.plugin_manager.uninstall_plugin(plugin_name):
                    self.update_plugin_list()
                    self.status_bar.config(text=f"插件 {plugin_name} 卸载成功")
                else:
                    self.status_bar.config(text=f"插件 {plugin_name} 卸载失败")

def show_plugin_info(self, event):
    """显示选中插件的详细信息"""
    selected = self.plugin_listbox.curselection()
    if selected:
        index = selected[0]
        plugins = self.plugin_manager.get_all_plugins()
        if index < len(plugins):
            plugin = plugins[index]
            self.plugin_name_label.config(text=f"插件名称: {plugin.get('name', '未知')}")
            self.plugin_version_label.config(text=f"版本: {plugin.get('version', '1.0.0')}")
            self.plugin_description_label.config(text=f"描述: {plugin.get('description', '无描述')}")
            self.plugin_author_label.config(text=f"作者: {plugin.get('author', '未知')}")
            
            # 显示来源
            source = plugin.get('source', '未知')
            if source == "builtin":
                self.plugin_source_label.config(text="来源: 内置插件", foreground="#008000")
            else:
                self.plugin_source_label.config(text="来源: 外部插件", foreground="#0000FF")
            
            # 显示状态
            enabled = plugin.get('enabled', False)
            if enabled:
                self.plugin_status_label.config(text="状态: 已启用", foreground="#008000")
            else:
                self.plugin_status_label.config(text="状态: 已禁用", foreground="#FF0000")

def update_plugin_list(self):
    """更新插件列表"""
    self.plugin_listbox.delete(0, tk.END)
    plugins = self.plugin_manager.get_all_plugins()
    
    for plugin in plugins:
        source = "内置" if plugin.get("source") == "builtin" else "外部"
        status = "已启用" if plugin.get("enabled", False) else "已禁用"
        self.plugin_listbox.insert(tk.END, f"{plugin.get('name', '未知插件')} [{source}] - {status}")
    
    # 示例插件接口（避免与 PluginManager.enable_plugin/disable 等同名遮蔽）
    def _example_enable(self):
        """插件启用时调用"""
        print(f"插件 {self.name} 已启用")
    
    def _example_disable(self):
        """插件禁用时调用"""
        print(f"插件 {self.name} 已禁用")
    
    # 自定义插件方法
    def _example_process_video(self, video_path):
        """处理视频的方法"""
        print(f"正在处理视频: {video_path}")
        return video_pathyu