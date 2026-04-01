import os
import subprocess
import threading
import random
import tkinter as tk
from tkinter import *
from tkinter import ttk, filedialog, messagebox, scrolledtext
import requests
import time
import json
from datetime import datetime
import re

# ===================== 核心配置 =====================
FFMPEG = "ffmpeg.exe"
OUTPUT_DIR = "短剧AI剪辑输出"
os.makedirs(OUTPUT_DIR, exist_ok=True)

MAX_PARALLEL = 15
DEFAULT_SPEED = 1.2
BGM_VOL = "-6dB"

DEEPSEEK_API_KEY = ""
DOUBAO_API_KEY = ""

# 线程管理
task_queue = []
running_task = 0
max_threads = 15
semaphore = threading.Semaphore(max_threads)
task_lock = threading.Lock()

# ===================== 模型管理系统 =====================
class ModelManager:
    def __init__(self):
        self.models = ["本地爆款模型", "DeepSeek", "豆包"]
        self.current_model = "本地爆款模型"

    def switch_model(self, model_name):
        if model_name in self.models:
            self.current_model = model_name

    def generate_content(self, filename):
        if self.current_model == "DeepSeek":
            return self._call_deepseek(filename)
        elif self.current_model == "豆包":
            return self._call_doubao(filename)
        else:
            return self._local_template()

    def _local_template(self):
        titles = [
            "这一脚直接踢出全剧高潮！",
            "本想低调，可实力不允许！",
            "开局30秒燃炸，建议反复观看！",
            "以为青铜，没想到是隐藏大佬！",
            "这反转我真的没猜到！"
        ]
        contents = [
            "全程高能无尿点，看到最后极度舒适！",
            "爽文都不敢这么写，越看越上头！",
            "高能预警！前方极度舒适！"
        ]
        tags = ["短剧", "快手短剧", "爽剧", "高能", "反转", "逆袭", "短剧推广"]
        return random.choice(titles), random.choice(contents), ", ".join(random.sample(tags, 4))

    def _call_deepseek(self, filename):
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            prompt = """你是快手爆款短剧文案专家，严格按照格式输出，只输出结果：
标题|发布文案|关键词（用逗号分隔）"""
            data = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": f"{prompt}\n视频文件名：{filename}"}],
                "max_tokens": 200
            }
            resp = requests.post(url, headers=headers, json=data, timeout=10)
            res = resp.json()["choices"][0]["message"]["content"].strip()
            title, content, keywords = res.split("|")
            return title.strip(), content.strip(), keywords.strip()
        except Exception as e:
            print(f"DeepSeek API调用失败: {e}")
            return self._local_template()

    def _call_doubao(self, filename):
        try:
            url = "https://open.doubao.com/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {DOUBAO_API_KEY}",
                "Content-Type": "application/json"
            }
            prompt = """你是快手爆款短剧文案专家，严格按照格式输出，只输出结果：
标题|发布文案|关键词（用逗号分隔）"""
            data = {
                "model": "doubao-lite",
                "messages": [{"role": "user", "content": f"{prompt}\n视频文件名：{filename}"}],
                "max_tokens": 200
            }
            resp = requests.post(url, headers=headers, json=data, timeout=10)
            res = resp.json()["choices"][0]["message"]["content"].strip()
            title, content, keywords = res.split("|")
            return title.strip(), content.strip(), keywords.strip()
        except Exception as e:
            print(f"豆包API调用失败: {e}")
            return self._local_template()

model_manager = ModelManager()

# ===================== 插件系统 =====================
plugins = {}
def register_plugin(name):
    def decorator(func):
        plugins[name] = func
        return func
    return decorator

@register_plugin("自动去重优化")
def plugin_auto_duplicate():
    offset_x = random.randint(-6, 6)
    offset_y = random.randint(-4, 4)
    hue_value = random.randint(-4, 4)
    return offset_x, offset_y, hue_value

@register_plugin("视频信息读取")
def plugin_get_video_info(video_path):
    try:
        result = subprocess.run(
            [FFMPEG, "-i", video_path],
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        output = result.stderr
        duration_line = [l for l in output.splitlines() if "Duration" in l][0]
        dur_str = duration_line.split()[1].split(",")[0]
        hh, mm, ss = dur_str.split(":")
        total_sec = int(float(hh)*3600 + float(mm)*60 + float(ss))
        size_mb = round(os.path.getsize(video_path) / (1024*1024), 2)
        return f"{total_sec}s | {size_mb}MB"
    except Exception as e:
        print(f"获取视频信息失败: {e}")
        return "未知"

@register_plugin("视频剪辑")
def plugin_video_clip(input_path, output_path, start_time, duration, speed=1.0):
    try:
        cmd = [
            FFMPEG,
            "-i", input_path,
            "-ss", str(start_time),
            "-t", str(duration),
            "-filter:v", f"setpts={1/speed}*PTS",
            "-filter:a", f"atempo={speed}",
            "-c:v", GPU_ENCODER,
            "-c:a", "aac",
            "-b:a", "128k",
            "-y",
            output_path
        ]
        subprocess.run(
            cmd,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except Exception as e:
        print(f"视频剪辑失败: {e}")
        return False

@register_plugin("视频合并")
def plugin_video_merge(input_files, output_path):
    try:
        # 创建文件列表
        list_file = "filelist.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for file in input_files:
                f.write(f"file '{file}'\n")
        
        cmd = [
            FFMPEG,
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
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
        
        # 清理列表文件
        if os.path.exists(list_file):
            os.remove(list_file)
        
        return True
    except Exception as e:
        print(f"视频合并失败: {e}")
        return False

# ===================== GPU 编码器自动检测 =====================
def detect_gpu_encoder():
    try:
        res = subprocess.run(
            f"{FFMPEG} -encoders | findstr h264_nvenc",
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if res.returncode == 0:
            return "h264_nvenc"
    except Exception as e:
        print(f"检测NVIDIA GPU失败: {e}")

    try:
        res = subprocess.run(
            f"{FFMPEG} -encoders | findstr h264_amf",
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if res.returncode == 0:
            return "h264_amf"
    except Exception as e:
        print(f"检测AMD GPU失败: {e}")
    
    try:
        res = subprocess.run(
            f"{FFMPEG} -encoders | findstr h264_qsv",
            shell=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if res.returncode == 0:
            return "h264_qsv"
    except Exception as e:
        print(f"检测Intel GPU失败: {e}")
        
    return "libx264"

GPU_ENCODER = detect_gpu_encoder()
print(f"使用GPU编码器: {GPU_ENCODER}")

# ===================== 剪辑主任务 =====================
def process_video(video_path, mode, task_id, status_label, title_label, content_label, kw_label, info_label, progress_var, progress_label):
    global running_task
    try:
        semaphore.acquire()
        with task_lock:
            running_task += 1
        
        base_name = os.path.basename(video_path)
        output_name = f"[{mode}]_{task_id}_{os.path.splitext(base_name)[0]}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_name)

        # 更新视频信息
        info_label.config(text=plugin_get_video_info(video_path))
        
        # 生成文案
        title, content, keywords = model_manager.generate_content(base_name)
        title_label.config(text=title)
        content_label.config(text=content)
        kw_label.config(text=keywords)

        # 获取去重参数
        ox, oy, hue = plugin_auto_duplicate()

        # 设置目标时长
        if mode == "30秒爆款引流":
            target_duration = 30
            speed = 1.3  # 稍微加速，增强节奏感
        elif mode == "90秒剧情解说":
            target_duration = 90
            speed = 1.1  # 正常速度，保证剧情连贯性
        else:  # 8分钟挂车长视频
            target_duration = 480
            speed = 1.0  # 原速，保证完整性

        progress_var.set(10)
        progress_label.config(text="分析视频...")

        # 分析视频时长
        try:
            result = subprocess.run(
                [FFMPEG, "-i", video_path],
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            output = result.stderr
            duration_line = [l for l in output.splitlines() if "Duration" in l][0]
            dur_str = duration_line.split()[1].split(",")[0]
            hh, mm, ss = dur_str.split(":")
            video_duration = float(hh)*3600 + float(mm)*60 + float(ss)
        except:
            video_duration = 600  # 默认10分钟

        progress_var.set(20)
        progress_label.config(text="生成剪辑方案...")

        # 生成剪辑方案
        clips = []
        if mode == "30秒爆款引流":
            # 30秒模式：前3秒钩子，中间高潮，结尾引导
            clips = [
                (0, 3),  # 前3秒钩子
                (min(10, video_duration-10), 20),  # 中间高潮
                (max(0, video_duration-7), 7)  # 结尾引导
            ]
        elif mode == "90秒剧情解说":
            # 90秒模式：更详细的剧情展示
            clips = [
                (0, 5),  # 开场
                (min(10, video_duration-60), 50),  # 主要剧情
                (max(0, video_duration-35), 35)  # 结尾和引导
            ]
        else:
            # 8分钟模式：完整剧情
            clip_duration = min(60, video_duration / 8)
            for i in range(8):
                start = i * clip_duration
                if start >= video_duration:
                    break
                duration = min(clip_duration, video_duration - start)
                clips.append((start, duration))

        progress_var.set(30)
        progress_label.config(text="开始剪辑...")

        # 执行剪辑
        temp_files = []
        for i, (start, duration) in enumerate(clips):
            temp_file = os.path.join(OUTPUT_DIR, f"temp_{task_id}_{i}.mp4")
            if plugin_video_clip(video_path, temp_file, start, duration, speed):
                temp_files.append(temp_file)
            progress_var.set(30 + (i+1)*50/len(clips))
            progress_label.config(text=f"剪辑片段 {i+1}/{len(clips)}...")

        # 合并片段
        if temp_files:
            progress_var.set(80)
            progress_label.config(text="合并片段...")
            if plugin_video_merge(temp_files, output_path):
                progress_var.set(90)
                progress_label.config(text="添加水印...")
                
                # 添加简单水印
                final_output = output_path.replace('.mp4', '_final.mp4')
                try:
                    cmd = [
                        FFMPEG,
                        "-i", output_path,
                        "-filter_complex", f"drawtext=text='AI短剧编辑器':fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:x=(w-text_w)/2:y=(h-text_h)/2",
                        "-c:v", GPU_ENCODER,
                        "-c:a", "copy",
                        "-y",
                        final_output
                    ]
                    subprocess.run(
                        cmd,
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if os.path.exists(final_output):
                        os.replace(final_output, output_path)
                except:
                    pass
                
                progress_var.set(100)
                progress_label.config(text="剪辑完成！")
                status_label.config(text=f"已完成: {output_name}")
            else:
                status_label.config(text="剪辑失败")
        else:
            status_label.config(text="剪辑失败")

        # 清理临时文件
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    except Exception as e:
        print(f"处理视频失败: {e}")
        status_label.config(text="处理失败")
    finally:
        with task_lock:
            running_task -= 1
        semaphore.release()

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

# ===================== UI界面 =====================
class AIShortDramaEditor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI短剧编辑器 v3.0")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 700)
        
        # 设置深色主题
        self.set_dark_theme()
        
        # 创建主布局
        self.create_main_layout()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
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
            foreground="#ffffff"
        )
        style.configure(
            "TButton",
            background="#333333",
            foreground="#ffffff",
            padding=(10, 5)
        )
        style.configure(
            "Accent.TButton",
            background="#007acc",
            foreground="#ffffff",
            padding=(15, 8)
        )
        style.configure(
            "TEntry",
            fieldbackground="#2d2d2d",
            foreground="#ffffff",
            insertcolor="#ffffff"
        )
        style.configure(
            "TCombobox",
            fieldbackground="#2d2d2d",
            foreground="#ffffff"
        )
        style.configure(
            "TProgressbar",
            background="#007acc",
            troughcolor="#2d2d2d"
        )
        style.configure(
            "TLabelframe",
            background="#1a1a1a",
            foreground="#ffffff"
        )
        style.configure(
            "TLabelframe.Label",
            background="#1a1a1a",
            foreground="#ffffff"
        )
    
    def create_main_layout(self):
        """创建主布局"""
        # 左侧导航栏
        self.left_frame = tk.Frame(self.root, bg="#252525", width=220)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        # 左侧导航栏内容
        self.create_navigation_bar()
        
        # 右侧主内容区
        self.right_frame = tk.Frame(self.root, bg="#1a1a1a")
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 顶部工具栏
        self.top_frame = tk.Frame(self.right_frame, bg="#1a1a1a", height=60)
        self.top_frame.pack(side=tk.TOP, fill=tk.X)
        
        # 创建顶部工具栏
        self.create_top_toolbar()
        
        # 主内容区
        self.content_frame = tk.Frame(self.right_frame, bg="#1a1a1a")
        self.content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # 初始显示首页
        self.show_home_page()
    
    def create_navigation_bar(self):
        """创建左侧导航栏"""
        # Logo
        logo_frame = tk.Frame(self.left_frame, bg="#252525", pady=25)
        logo_frame.pack(fill=tk.X)
        logo_label = tk.Label(logo_frame, text="AI短剧编辑器", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#007acc")
        logo_label.pack(anchor=tk.CENTER)
        
        # 导航项
        nav_items = [
            {"name": "首页", "icon": "🏠", "command": self.show_home_page},
            {"name": "视频剪辑", "icon": "🎬", "command": self.show_video_editing_tab},
            {"name": "文案生成", "icon": "✍️", "command": self.show_copywriting_tab},
            {"name": "账号运营", "icon": "📊", "command": self.show_account_analysis_tab},
            {"name": "插件管理", "icon": "🔌", "command": self.show_plugin_management_tab},
            {"name": "模型配置", "icon": "🧠", "command": self.show_model_config_tab},
            {"name": "设置", "icon": "⚙️", "command": self.show_settings_tab}
        ]
        
        # 创建导航按钮
        for item in nav_items:
            btn = tk.Button(
                self.left_frame,
                text=f"{item['icon']} {item['name']}",
                command=item['command'],
                bg="#252525",
                fg="#ffffff",
                font=("微软雅黑", 10),
                padx=15,
                pady=12,
                anchor=tk.W,
                relief=tk.FLAT
            )
            btn.pack(fill=tk.X)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#333333"))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#252525"))
        
        # 底部信息
        bottom_frame = tk.Frame(self.left_frame, bg="#252525", pady=20)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        # GPU信息
        gpu_info = tk.Label(bottom_frame, text=f"GPU编码器: {GPU_ENCODER}", font=("微软雅黑", 9), bg="#252525", fg="#cccccc")
        gpu_info.pack(anchor=tk.CENTER, pady=5)
        
        # 线程信息
        thread_info = tk.Label(bottom_frame, text=f"最大线程: {MAX_PARALLEL}", font=("微软雅黑", 9), bg="#252525", fg="#cccccc")
        thread_info.pack(anchor=tk.CENTER, pady=5)
    
    def create_top_toolbar(self):
        """创建顶部工具栏"""
        # 左侧信息
        left_info = tk.Frame(self.top_frame, bg="#1a1a1a")
        left_info.pack(side=tk.LEFT, padx=20, pady=15)
        
        # 当前模型
        model_label = tk.Label(left_info, text=f"当前模型: {model_manager.current_model}", font=("微软雅黑", 10), bg="#1a1a1a", fg="#ffffff")
        model_label.pack(side=tk.LEFT, padx=10)
        
        # 右侧功能按钮
        right_tools = tk.Frame(self.top_frame, bg="#1a1a1a")
        right_tools.pack(side=tk.RIGHT, padx=20, pady=15)
        
        # 教程按钮
        tutorial_btn = tk.Button(
            right_tools,
            text="教程",
            bg="#252525",
            fg="#ffffff",
            font=("微软雅黑", 9),
            padx=15,
            pady=7,
            relief=tk.FLAT
        )
        tutorial_btn.pack(side=tk.LEFT, padx=8)
        
        # 帮助按钮
        help_btn = tk.Button(
            right_tools,
            text="帮助",
            bg="#252525",
            fg="#ffffff",
            font=("微软雅黑", 9),
            padx=15,
            pady=7,
            relief=tk.FLAT
        )
        help_btn.pack(side=tk.LEFT, padx=8)
    
    def clear_content_frame(self):
        """清空内容区域"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def show_home_page(self):
        """显示首页"""
        self.clear_content_frame()
        
        # 首页内容
        home_frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        home_frame.pack(fill=tk.BOTH, expand=True)
        
        # 中央创作区域
        create_section = tk.Frame(home_frame, bg="#1a1a1a", pady=60)
        create_section.pack(fill=tk.BOTH, expand=True)
        
        # 渐变背景
        gradient_frame = tk.Frame(create_section, bg="#252525", pady=80, padx=60)
        gradient_frame.pack(fill=tk.BOTH, expand=True, padx=60)
        
        # 开始创作按钮
        start_btn = tk.Button(
            gradient_frame,
            text="+ 开始创作",
            command=self.show_video_editing_tab,
            bg="#007acc",
            fg="#ffffff",
            font=("微软雅黑", 20, "bold"),
            padx=50,
            pady=25,
            relief=tk.FLAT,
            bd=0
        )
        start_btn.pack(anchor=tk.CENTER, pady=30)
        
        # 功能模块卡片
        modules_frame = tk.Frame(home_frame, bg="#1a1a1a", pady=40)
        modules_frame.pack(fill=tk.BOTH, expand=True)
        
        # 模块标题
        modules_title = tk.Label(modules_frame, text="快捷功能", font=("微软雅黑", 18, "bold"), bg="#1a1a1a", fg="#ffffff")
        modules_title.pack(anchor=tk.W, padx=60, pady=20)
        
        # 模块卡片容器
        cards_frame = tk.Frame(modules_frame, bg="#1a1a1a")
        cards_frame.pack(fill=tk.BOTH, expand=True, padx=60)
        
        # 模块卡片
        module_cards = [
            {"name": "30秒爆款引流", "icon": "💥", "description": "打造高点击率短视频，快速吸引流量", "command": lambda: self.show_video_editing_tab("30秒爆款引流")},
            {"name": "90秒剧情解说", "icon": "🎙️", "description": "详细讲解剧情，增强观众理解", "command": lambda: self.show_video_editing_tab("90秒剧情解说")},
            {"name": "8分钟挂车长视频", "icon": "📦", "description": "完整展示剧情，自然融入产品信息", "command": lambda: self.show_video_editing_tab("8分钟挂车长视频")},
            {"name": "AI文案生成", "icon": "🤖", "description": "智能生成标题、文案和关键词", "command": self.show_copywriting_tab},
            {"name": "账号运营分析", "icon": "📈", "description": "分析数据，优化运营策略", "command": self.show_account_analysis_tab},
            {"name": "插件管理", "icon": "🔌", "description": "扩展功能，提升效率", "command": self.show_plugin_management_tab}
        ]
        
        # 创建卡片
        for i, card in enumerate(module_cards):
            card_frame = tk.Frame(
                cards_frame,
                bg="#252525",
                width=220,
                height=180,
                relief=tk.RAISED,
                bd=0
            )
            card_frame.grid(row=i//3, column=i%3, padx=20, pady=20, sticky=tk.NSEW)
            
            # 卡片内容
            icon_label = tk.Label(card_frame, text=card["icon"], font=("微软雅黑", 32), bg="#252525", fg="#007acc")
            icon_label.pack(pady=15)
            
            name_label = tk.Label(card_frame, text=card["name"], font=("微软雅黑", 14, "bold"), bg="#252525", fg="#ffffff")
            name_label.pack(pady=8)
            
            desc_label = tk.Label(card_frame, text=card["description"], font=("微软雅黑", 10), bg="#252525", fg="#cccccc", wraplength=200)
            desc_label.pack(pady=8)
            
            # 点击事件
            card_frame.bind("<Button-1>", lambda e, cmd=card["command"]: cmd())
            card_frame.bind("<Enter>", lambda e, frame=card_frame: frame.configure(bg="#2d2d2d"))
            card_frame.bind("<Leave>", lambda e, frame=card_frame: frame.configure(bg="#252525"))
    
    def show_video_editing_tab(self, default_mode="30秒爆款引流"):
        """显示视频剪辑选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="视频剪辑", font=("微软雅黑", 18, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=20)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        config_frame.pack(fill=tk.X, pady=20)
        
        # 配置项
        row = 0
        
        # 视频路径
        tk.Label(config_frame, text="视频文件:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.video_path_var = tk.StringVar()
        self.video_path_entry = tk.Entry(config_frame, textvariable=self.video_path_var, width=60, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.video_path_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        browse_btn = tk.Button(config_frame, text="浏览", command=lambda: self.browse_file(self.video_path_var, (("视频文件", "*.mp4 *.avi *.mov *.mkv"),)), bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=7, relief=tk.FLAT)
        browse_btn.grid(row=row, column=3, padx=10, pady=15)
        row += 1
        
        # 输出模式
        tk.Label(config_frame, text="输出模式:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.output_mode_var = tk.StringVar(value=default_mode)
        mode_options = ["30秒爆款引流", "90秒剧情解说", "8分钟挂车长视频"]
        self.mode_menu = ttk.Combobox(config_frame, textvariable=self.output_mode_var, values=mode_options, state="readonly", width=25, font=("微软雅黑", 10))
        self.mode_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 文案模型
        tk.Label(config_frame, text="文案模型:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.model_var = tk.StringVar(value=model_manager.current_model)
        model_options = model_manager.models
        self.model_menu = ttk.Combobox(config_frame, textvariable=self.model_var, values=model_options, state="readonly", width=25, font=("微软雅黑", 10))
        self.model_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 视频信息
        tk.Label(config_frame, text="视频信息:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.info_label = tk.Label(config_frame, text="未选择视频", bg="#252525", fg="#cccccc", font=("微软雅黑", 10))
        self.info_label.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 文案预览
        preview_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        preview_frame.pack(fill=tk.X, pady=20)
        
        # 标题预览
        tk.Label(preview_frame, text="生成标题:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=0, column=0, sticky=tk.W, padx=20, pady=10)
        self.title_label = tk.Label(preview_frame, text="点击生成文案预览", bg="#252525", fg="#cccccc", font=("微软雅黑", 10), wraplength=600)
        self.title_label.grid(row=0, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 内容预览
        tk.Label(preview_frame, text="发布文案:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=1, column=0, sticky=tk.W, padx=20, pady=10)
        self.content_label = tk.Label(preview_frame, text="", bg="#252525", fg="#cccccc", font=("微软雅黑", 10), wraplength=600)
        self.content_label.grid(row=1, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 关键词预览
        tk.Label(preview_frame, text="关键词:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=2, column=0, sticky=tk.W, padx=20, pady=10)
        self.kw_label = tk.Label(preview_frame, text="", bg="#252525", fg="#cccccc", font=("微软雅黑", 10))
        self.kw_label.grid(row=2, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 生成文案按钮
        generate_copy_btn = tk.Button(preview_frame, text="生成文案预览", command=self.generate_copywriting_preview, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        generate_copy_btn.grid(row=3, column=1, padx=10, pady=20, sticky=tk.W)
        
        # 进度条
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=20, padx=0)
        self.progress_label = tk.Label(frame, text="准备就绪", bg="#1a1a1a", fg="#ffffff", font=("微软雅黑", 10))
        self.progress_label.pack(pady=10)
        
        # 状态标签
        self.status_label = tk.Label(frame, text="", bg="#1a1a1a", fg="#00cc66", font=("微软雅黑", 10))
        self.status_label.pack(pady=10)
        
        # 按钮框架
        button_frame = tk.Frame(frame, bg="#1a1a1a", pady=20)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 开始剪辑按钮
        start_btn = tk.Button(button_frame, text="开始剪辑", command=self.start_video_editing, bg="#007acc", fg="#ffffff", font=("微软雅黑", 12, "bold"), padx=40, pady=15, relief=tk.FLAT)
        start_btn.pack(anchor=tk.CENTER, pady=20)
    
    def show_copywriting_tab(self):
        """显示文案生成选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="文案生成", font=("微软雅黑", 18, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=20)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        config_frame.pack(fill=tk.X, pady=20)
        
        # 配置项
        row = 0
        
        # 视频文件
        tk.Label(config_frame, text="视频文件:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.copy_video_path_var = tk.StringVar()
        self.copy_video_path_entry = tk.Entry(config_frame, textvariable=self.copy_video_path_var, width=60, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.copy_video_path_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        browse_btn = tk.Button(config_frame, text="浏览", command=lambda: self.browse_file(self.copy_video_path_var, (("视频文件", "*.mp4 *.avi *.mov *.mkv"),)), bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=7, relief=tk.FLAT)
        browse_btn.grid(row=row, column=3, padx=10, pady=15)
        row += 1
        
        # 模型选择
        tk.Label(config_frame, text="AI模型:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.copy_model_var = tk.StringVar(value=model_manager.current_model)
        model_options = model_manager.models
        self.copy_model_menu = ttk.Combobox(config_frame, textvariable=self.copy_model_var, values=model_options, state="readonly", width=25, font=("微软雅黑", 10))
        self.copy_model_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 平台选择
        tk.Label(config_frame, text="目标平台:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.platform_var = tk.StringVar(value="快手")
        platform_options = ["快手", "抖音", "视频号"]
        self.platform_menu = ttk.Combobox(config_frame, textvariable=self.platform_var, values=platform_options, state="readonly", width=25, font=("微软雅黑", 10))
        self.platform_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 文案预览
        preview_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        preview_frame.pack(fill=tk.X, pady=20)
        
        # 标题预览
        tk.Label(preview_frame, text="生成标题:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=0, column=0, sticky=tk.NW, padx=20, pady=10)
        self.copy_title_label = tk.Label(preview_frame, text="点击生成文案", bg="#252525", fg="#cccccc", font=("微软雅黑", 12, "bold"), wraplength=600)
        self.copy_title_label.grid(row=0, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 内容预览
        tk.Label(preview_frame, text="发布文案:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=1, column=0, sticky=tk.NW, padx=20, pady=10)
        self.copy_content_label = tk.Label(preview_frame, text="", bg="#252525", fg="#cccccc", font=("微软雅黑", 10), wraplength=600, justify=tk.LEFT)
        self.copy_content_label.grid(row=1, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 关键词预览
        tk.Label(preview_frame, text="关键词:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=2, column=0, sticky=tk.NW, padx=20, pady=10)
        self.copy_kw_label = tk.Label(preview_frame, text="", bg="#252525", fg="#cccccc", font=("微软雅黑", 10))
        self.copy_kw_label.grid(row=2, column=1, columnspan=3, padx=10, pady=10, sticky=tk.W)
        
        # 生成文案按钮
        generate_btn = tk.Button(preview_frame, text="生成文案", command=self.generate_copywriting, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        generate_btn.grid(row=3, column=1, padx=10, pady=20, sticky=tk.W)
        
        # 保存文案按钮
        save_btn = tk.Button(preview_frame, text="保存文案", command=self.save_copywriting, bg="#333333", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        save_btn.grid(row=3, column=2, padx=10, pady=20, sticky=tk.W)
    
    def show_account_analysis_tab(self):
        """显示账号运营分析选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="账号运营分析", font=("微软雅黑", 18, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=20)
        
        # 数据输入框架
        input_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        input_frame.pack(fill=tk.X, pady=20)
        
        # 数据输入项
        row = 0
        
        # 视频ID
        tk.Label(input_frame, text="视频ID:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.video_id_var = tk.Entry(input_frame, width=30, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.video_id_var.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 标题
        tk.Label(input_frame, text="视频标题:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.video_title_var = tk.Entry(input_frame, width=50, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.video_title_var.grid(row=row, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 播放量
        tk.Label(input_frame, text="播放量:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.views_var = tk.Entry(input_frame, width=20, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.views_var.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 点赞量
        tk.Label(input_frame, text="点赞量:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.likes_var = tk.Entry(input_frame, width=20, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.likes_var.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 评论量
        tk.Label(input_frame, text="评论量:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.comments_var = tk.Entry(input_frame, width=20, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.comments_var.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 分享量
        tk.Label(input_frame, text="分享量:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.shares_var = tk.Entry(input_frame, width=20, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.shares_var.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 转化量
        tk.Label(input_frame, text="转化量:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=10)
        self.conversions_var = tk.Entry(input_frame, width=20, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.conversions_var.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 添加数据按钮
        add_btn = tk.Button(input_frame, text="添加数据", command=self.add_account_data, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=8, relief=tk.FLAT)
        add_btn.grid(row=row, column=1, padx=10, pady=20, sticky=tk.W)
        row += 1
        
        # 分析结果框架
        analysis_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        analysis_frame.pack(fill=tk.BOTH, expand=True, pady=20)
        
        # 分析按钮
        analyze_btn = tk.Button(analysis_frame, text="分析数据", command=self.analyze_account_data, bg="#007acc", fg="#ffffff", font=("微软雅黑", 10), padx=20, pady=10, relief=tk.FLAT)
        analyze_btn.pack(anchor=tk.NW, pady=10)
        
        # 分析结果文本
        self.analysis_text = scrolledtext.ScrolledText(analysis_frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10), height=15)
        self.analysis_text.pack(fill=tk.BOTH, expand=True, pady=20)
    
    def show_plugin_management_tab(self):
        """显示插件管理选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="插件管理", font=("微软雅黑", 18, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=20)
        
        # 插件列表框架
        plugin_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        plugin_frame.pack(fill=tk.X, pady=20)
        
        # 插件列表
        tk.Label(plugin_frame, text="已安装插件:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, padx=20, pady=10)
        
        # 插件列表框
        self.plugin_listbox = tk.Listbox(plugin_frame, width=80, height=10, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff", font=("微软雅黑", 10))
        self.plugin_listbox.pack(fill=tk.X, pady=10)
        
        # 填充插件列表
        for plugin_name in plugins.keys():
            self.plugin_listbox.insert(tk.END, plugin_name)
        
        # 插件信息
        info_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        info_frame.pack(fill=tk.X, pady=20)
        
        # 插件描述
        tk.Label(info_frame, text="插件描述:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).pack(anchor=tk.W, padx=20, pady=10)
        self.plugin_info_text = scrolledtext.ScrolledText(info_frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10), height=5)
        self.plugin_info_text.pack(fill=tk.X, pady=10)
        
        # 绑定列表框选择事件
        self.plugin_listbox.bind('<<ListboxSelect>>', self.on_plugin_select)
    
    def show_model_config_tab(self):
        """显示模型配置选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="模型配置", font=("微软雅黑", 18, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=20)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        config_frame.pack(fill=tk.X, pady=20)
        
        # 配置项
        row = 0
        
        # 默认模型
        tk.Label(config_frame, text="默认模型:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.default_model_var = tk.StringVar(value=model_manager.current_model)
        model_options = model_manager.models
        self.default_model_menu = ttk.Combobox(config_frame, textvariable=self.default_model_var, values=model_options, state="readonly", width=25, font=("微软雅黑", 10))
        self.default_model_menu.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # DeepSeek API Key
        tk.Label(config_frame, text="DeepSeek API Key:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.deepseek_api_var = tk.StringVar(value=DEEPSEEK_API_KEY)
        self.deepseek_api_entry = tk.Entry(config_frame, textvariable=self.deepseek_api_var, width=60, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.deepseek_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 豆包 API Key
        tk.Label(config_frame, text="豆包 API Key:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.doubao_api_var = tk.StringVar(value=DOUBAO_API_KEY)
        self.doubao_api_entry = tk.Entry(config_frame, textvariable=self.doubao_api_var, width=60, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.doubao_api_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 按钮框架
        button_frame = tk.Frame(frame, bg="#1a1a1a", pady=20)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 保存配置按钮
        save_btn = tk.Button(button_frame, text="保存配置", command=self.save_model_config, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=12, relief=tk.FLAT)
        save_btn.pack(anchor=tk.CENTER, pady=20)
    
    def show_settings_tab(self):
        """显示设置选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # 标题
        title = tk.Label(frame, text="设置", font=("微软雅黑", 18, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=20)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=30, padx=30)
        config_frame.pack(fill=tk.X, pady=20)
        
        # 配置项
        row = 0
        
        # 最大线程数
        tk.Label(config_frame, text="最大线程数:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.max_threads_var = tk.StringVar(value=str(MAX_PARALLEL))
        self.max_threads_entry = tk.Entry(config_frame, textvariable=self.max_threads_var, width=20, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.max_threads_entry.grid(row=row, column=1, padx=10, pady=15, sticky=tk.W)
        row += 1
        
        # 输出目录
        tk.Label(config_frame, text="输出目录:", bg="#252525", fg="#ffffff", font=("微软雅黑", 11)).grid(row=row, column=0, sticky=tk.W, padx=20, pady=15)
        self.output_dir_var = tk.StringVar(value=OUTPUT_DIR)
        self.output_dir_entry = tk.Entry(config_frame, textvariable=self.output_dir_var, width=60, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", font=("微软雅黑", 10))
        self.output_dir_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=15, sticky=tk.W)
        browse_dir_btn = tk.Button(config_frame, text="浏览", command=lambda: self.browse_directory(self.output_dir_var), bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=7, relief=tk.FLAT)
        browse_dir_btn.grid(row=row, column=3, padx=10, pady=15)
        row += 1
        
        # 按钮框架
        button_frame = tk.Frame(frame, bg="#1a1a1a", pady=20)
        button_frame.pack(fill=tk.X, pady=10)
        
        # 保存设置按钮
        save_btn = tk.Button(button_frame, text="保存设置", command=self.save_settings, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=12, relief=tk.FLAT)
        save_btn.pack(anchor=tk.CENTER, pady=20)
    
    def browse_file(self, var, filetypes=("All Files", "*.*")):
        """浏览文件"""
        filename = filedialog.askopenfilename(filetypes=filetypes)
        if filename:
            var.set(filename)
    
    def browse_directory(self, var):
        """浏览目录"""
        directory = filedialog.askdirectory()
        if directory:
            var.set(directory)
    
    def generate_copywriting_preview(self):
        """生成文案预览"""
        video_path = self.video_path_var.get()
        if not video_path:
            messagebox.showerror("错误", "请选择视频文件")
            return
        
        # 切换模型
        model_name = self.model_var.get()
        model_manager.switch_model(model_name)
        
        # 生成文案
        base_name = os.path.basename(video_path)
        title, content, keywords = model_manager.generate_content(base_name)
        
        # 更新预览
        self.title_label.config(text=title)
        self.content_label.config(text=content)
        self.kw_label.config(text=keywords)
        
        # 更新视频信息
        self.info_label.config(text=plugin_get_video_info(video_path))
    
    def start_video_editing(self):
        """开始视频剪辑"""
        video_path = self.video_path_var.get()
        if not video_path:
            messagebox.showerror("错误", "请选择视频文件")
            return
        
        if not os.path.exists(video_path):
            messagebox.showerror("错误", "视频文件不存在")
            return
        
        # 切换模型
        model_name = self.model_var.get()
        model_manager.switch_model(model_name)
        
        # 获取输出模式
        mode = self.output_mode_var.get()
        
        # 重置进度
        self.progress_var.set(0)
        self.progress_label.config(text="准备开始...")
        self.status_label.config(text="")
        
        # 生成任务ID
        task_id = f"{int(time.time())}_{random.randint(1000, 9999)}"
        
        # 启动线程处理
        thread = threading.Thread(
            target=process_video,
            args=(video_path, mode, task_id, self.status_label, self.title_label, self.content_label, self.kw_label, self.info_label, self.progress_var, self.progress_label)
        )
        thread.daemon = True
        thread.start()
    
    def generate_copywriting(self):
        """生成文案"""
        video_path = self.copy_video_path_var.get()
        if not video_path:
            messagebox.showerror("错误", "请选择视频文件")
            return
        
        # 切换模型
        model_name = self.copy_model_var.get()
        model_manager.switch_model(model_name)
        
        # 生成文案
        base_name = os.path.basename(video_path)
        title, content, keywords = model_manager.generate_content(base_name)
        
        # 更新预览
        self.copy_title_label.config(text=title)
        self.copy_content_label.config(text=content)
        self.copy_kw_label.config(text=keywords)
    
    def save_copywriting(self):
        """保存文案"""
        title = self.copy_title_label.cget("text")
        content = self.copy_content_label.cget("text")
        keywords = self.copy_kw_label.cget("text")
        
        if title == "点击生成文案":
            messagebox.showerror("错误", "请先生成文案")
            return
        
        # 创建保存目录
        copy_dir = "文案保存"
        os.makedirs(copy_dir, exist_ok=True)
        
        # 生成文件名
        filename = f"{copy_dir}/{int(time.time())}_文案.txt"
        
        # 保存文案
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"标题: {title}\n")
                f.write(f"文案: {content}\n")
                f.write(f"关键词: {keywords}\n")
            messagebox.showinfo("成功", f"文案已保存到: {filename}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")
    
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
            
            # 添加数据
            if account_analyzer.add_video_data(video_id, title, views, likes, comments, shares, conversions):
                messagebox.showinfo("成功", "数据添加成功")
                # 清空输入
                self.video_id_var.delete(0, tk.END)
                self.video_title_var.delete(0, tk.END)
                self.views_var.delete(0, tk.END)
                self.likes_var.delete(0, tk.END)
                self.comments_var.delete(0, tk.END)
                self.shares_var.delete(0, tk.END)
                self.conversions_var.delete(0, tk.END)
            else:
                messagebox.showerror("错误", "数据添加失败")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
        except Exception as e:
            messagebox.showerror("错误", f"添加失败: {e}")
    
    def analyze_account_data(self):
        """分析账号数据"""
        # 分析数据
        analysis_data = account_analyzer.analyze_data()
        
        # 生成建议
        suggestions = account_analyzer.generate_optimization_suggestions(analysis_data)
        
        # 显示结果
        self.analysis_text.config(state='normal')
        self.analysis_text.delete(1.0, tk.END)
        
        if "error" in analysis_data:
            self.analysis_text.insert(tk.END, f"错误: {analysis_data['error']}\n")
        else:
            # 基本数据
            self.analysis_text.insert(tk.END, "=== 账号运营分析报告 ===\n\n")
            self.analysis_text.insert(tk.END, f"总视频数: {analysis_data['total_videos']}\n")
            self.analysis_text.insert(tk.END, f"总播放量: {analysis_data['total_views']}\n")
            self.analysis_text.insert(tk.END, f"总点赞量: {analysis_data['total_likes']}\n")
            self.analysis_text.insert(tk.END, f"总评论量: {analysis_data['total_comments']}\n")
            self.analysis_text.insert(tk.END, f"总分享量: {analysis_data['total_shares']}\n")
            self.analysis_text.insert(tk.END, f"总转化量: {analysis_data['total_conversions']}\n\n")
            
            # 平均值
            self.analysis_text.insert(tk.END, "=== 平均值 ===\n")
            self.analysis_text.insert(tk.END, f"平均播放量: {analysis_data['average_views']:.2f}\n")
            self.analysis_text.insert(tk.END, f"平均点赞量: {analysis_data['average_likes']:.2f}\n")
            self.analysis_text.insert(tk.END, f"平均评论量: {analysis_data['average_comments']:.2f}\n")
            self.analysis_text.insert(tk.END, f"平均分享量: {analysis_data['average_shares']:.2f}\n")
            self.analysis_text.insert(tk.END, f"平均转化量: {analysis_data['average_conversions']:.2f}\n\n")
            
            # 比率
            self.analysis_text.insert(tk.END, "=== 比率 ===\n")
            self.analysis_text.insert(tk.END, f"平均点赞率: {analysis_data['average_like_rate']:.4f}\n")
            self.analysis_text.insert(tk.END, f"平均评论率: {analysis_data['average_comment_rate']:.4f}\n")
            self.analysis_text.insert(tk.END, f"平均分享率: {analysis_data['average_share_rate']:.4f}\n")
            self.analysis_text.insert(tk.END, f"平均转化率: {analysis_data['average_conversion_rate']:.4f}\n\n")
            
            # 表现最好的视频
            self.analysis_text.insert(tk.END, "=== 表现最好的视频 ===\n")
            self.analysis_text.insert(tk.END, "播放量Top3:\n")
            for i, video in enumerate(analysis_data['top_views']):
                self.analysis_text.insert(tk.END, f"{i+1}. {video['title']} - {video['views']}次播放\n")
            
            self.analysis_text.insert(tk.END, "\n转化量Top3:\n")
            for i, video in enumerate(analysis_data['top_conversions']):
                self.analysis_text.insert(tk.END, f"{i+1}. {video['title']} - {video['conversions']}次转化\n")
            
            self.analysis_text.insert(tk.END, "\n转化率Top3:\n")
            for i, video in enumerate(analysis_data['top_conversion_rate']):
                rate = video.get('conversion_rate', 0)
                self.analysis_text.insert(tk.END, f"{i+1}. {video['title']} - {rate:.4f}转化率\n")
            
            # 优化建议
            self.analysis_text.insert(tk.END, "\n=== 优化建议 ===\n")
            self.analysis_text.insert(tk.END, suggestions)
        
        self.analysis_text.config(state='disabled')
    
    def on_plugin_select(self, event):
        """插件选择事件"""
        selection = event.widget.curselection()
        if selection:
            index = selection[0]
            plugin_name = event.widget.get(index)
            
            # 显示插件描述
            descriptions = {
                "自动去重优化": "通过随机调整视频参数，减少重复内容检测的风险",
                "视频信息读取": "读取视频文件的基本信息，如时长、文件大小等",
                "视频剪辑": "根据指定的时间范围剪辑视频片段",
                "视频合并": "将多个视频片段合并为一个完整视频"
            }
            
            desc = descriptions.get(plugin_name, "暂无描述")
            self.plugin_info_text.config(state='normal')
            self.plugin_info_text.delete(1.0, tk.END)
            self.plugin_info_text.insert(tk.END, desc)
            self.plugin_info_text.config(state='disabled')
    
    def save_model_config(self):
        """保存模型配置"""
        try:
            # 切换默认模型
            model_name = self.default_model_var.get()
            model_manager.switch_model(model_name)
            
            # 更新API Key
            global DEEPSEEK_API_KEY, DOUBAO_API_KEY
            DEEPSEEK_API_KEY = self.deepseek_api_var.get()
            DOUBAO_API_KEY = self.doubao_api_var.get()
            
            # 保存到文件
            config_data = {
                "default_model": model_name,
                "deepseek_api_key": DEEPSEEK_API_KEY,
                "doubao_api_key": DOUBAO_API_KEY
            }
            
            with open("model_config.json", "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            messagebox.showinfo("成功", "模型配置保存成功")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")
    
    def save_settings(self):
        """保存设置"""
        try:
            # 获取线程数
            max_threads = int(self.max_threads_var.get())
            if max_threads < 1 or max_threads > 32:
                messagebox.showerror("错误", "线程数应在1-32之间")
                return
            
            # 获取输出目录
            output_dir = self.output_dir_var.get()
            if not output_dir:
                messagebox.showerror("错误", "请填写输出目录")
                return
            
            # 确保目录存在
            os.makedirs(output_dir, exist_ok=True)
            
            # 更新全局变量
            global MAX_PARALLEL, OUTPUT_DIR
            MAX_PARALLEL = max_threads
            OUTPUT_DIR = output_dir
            
            # 保存到文件
            config_data = {
                "max_threads": max_threads,
                "output_dir": output_dir
            }
            
            with open("settings.json", "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            messagebox.showinfo("成功", "设置保存成功")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的线程数")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")
    
    def on_closing(self):
        """窗口关闭事件"""
        # 清理临时文件
        for file in os.listdir('.'):
            if file.startswith('temp_') and file.endswith('.mp4'):
                try:
                    os.remove(file)
                except:
                    pass
        if os.path.exists('filelist.txt'):
            try:
                os.remove('filelist.txt')
            except:
                pass
        
        self.root.destroy()

# ===================== 主程序 =====================
def load_config():
    """加载配置"""
    global DEEPSEEK_API_KEY, DOUBAO_API_KEY, MAX_PARALLEL, OUTPUT_DIR
    
    # 加载模型配置
    if os.path.exists("model_config.json"):
        try:
            with open("model_config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
                model_manager.switch_model(config.get("default_model", "本地爆款模型"))
                DEEPSEEK_API_KEY = config.get("deepseek_api_key", "")
                DOUBAO_API_KEY = config.get("doubao_api_key", "")
        except:
            pass
    
    # 加载设置
    if os.path.exists("settings.json"):
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                config = json.load(f)
                MAX_PARALLEL = config.get("max_threads", 15)
                OUTPUT_DIR = config.get("output_dir", "短剧AI剪辑输出")
                os.makedirs(OUTPUT_DIR, exist_ok=True)
        except:
            pass

if __name__ == "__main__":
    # 加载配置
    load_config()
    
    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 启动应用
    app = AIShortDramaEditor()
    app.root.mainloop()