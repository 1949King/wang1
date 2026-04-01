import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import sys
import logging
import json
from moviepy.video.io.VideoFileClip import VideoFileClip

# --- 导入本地模块 ---
try:
    from ai_video_editor_local import AIVideoEditorLocal, check_dependencies
    print("成功导入 AIVideoEditorLocal 和相关函数")
except ImportError as e:
    print(f"导入失败: {e}")
    sys.exit(1)

# --- 导入嘴型同步动画器 ---
try:
    from lip_sync_animator import LipSyncAnimator
    print("成功导入 LipSyncAnimator")
except ImportError as e:
    print(f"导入嘴型同步动画器失败: {e}")
    LipSyncAnimator = None


class AIEditorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI短剧编辑器 v3.0")
        
        # 设置窗口大小和位置
        try:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            window_width = min(1200, int(screen_width * 0.9))
            window_height = min(800, int(screen_height * 0.9))
            self.root.geometry(f"{window_width}x{window_height}")
        except tk.TclError:
            self.root.geometry("1200x800")

        self.root.minsize(1000, 600)

        # 设置深色主题
        self.set_dark_theme()

        # --- 初始化依赖状态和主程序实例 ---
        self.deps_status = check_dependencies()
        self.editor = None
        self.initialize_editor_instance()
        
        # --- 嘴型同步动画器 ---
        # 嘴型同步动画器现在通过 editor 实例初始化和管理
        self.lip_sync_animator = None
        
        # --- 线程管理 ---
        self.running_threads = []
        self.cancel_flags = {}

        # --- 创建UI ---
        self.create_main_layout()

        # --- 绑定窗口关闭事件 ---
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

    def initialize_editor_instance(self):
        """初始化编辑器实例"""
        try:
            self.editor = AIVideoEditorLocal(deps_status=self.deps_status)
            print("AIVideoEditorLocal 实例创建成功。")
        except Exception as e:
            print(f"初始化编辑器实例时出错: {e}")
            messagebox.showerror("错误", f"初始化编辑器失败: {e}")
            # self.editor 保持为 None

    def create_main_layout(self):
        """创建主布局"""
        # 左侧导航栏
        self.left_frame = tk.Frame(self.root, bg="#252525", width=200)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        # 左侧导航栏内容
        self.create_navigation_bar()
        
        # 右侧主内容区
        self.right_frame = tk.Frame(self.root, bg="#1a1a1a")
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 顶部工具栏
        self.top_frame = tk.Frame(self.right_frame, bg="#1a1a1a", height=50)
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
        #  logo
        logo_frame = tk.Frame(self.left_frame, bg="#252525", pady=20)
        logo_frame.pack(fill=tk.X)
        logo_label = tk.Label(logo_frame, text="AI短剧编辑器", font=("微软雅黑", 16, "bold"), bg="#252525", fg="#007acc")
        logo_label.pack(anchor=tk.CENTER)
        
        # 导航项
        nav_items = [
            {"name": "首页", "icon": "🏠", "command": self.show_home_page},
            {"name": "AI脚本驱动", "icon": "🤖", "command": self.show_ai_script_tab},
            {"name": "处理现有视频", "icon": "🎬", "command": self.show_process_existing_tab},
            {"name": "短剧推广", "icon": "📢", "command": self.show_short_drama_tab},
            {"name": "素材管理", "icon": "🎨", "command": self.show_material_management_tab},
            {"name": "批量处理", "icon": "📋", "command": self.show_batch_processing_tab},
            {"name": "高级工具箱", "icon": "🔧", "command": self.show_advanced_tools_tab},
            {"name": "数据复盘", "icon": "📊", "command": self.show_data_analysis_tab},
            {"name": "模型管理", "icon": "🧠", "command": self.show_model_management_tab},
            {"name": "配置管理", "icon": "⚙️", "command": self.show_configuration_tab}
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
                pady=10,
                anchor=tk.W,
                relief=tk.FLAT
            )
            btn.pack(fill=tk.X)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#333333"))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#252525"))
        
        # 底部导航
        bottom_frame = tk.Frame(self.left_frame, bg="#252525", pady=20)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 免费SVIP
        svip_btn = tk.Button(
            bottom_frame,
            text="💎 免费领取SVIP",
            bg="#ff6b6b",
            fg="#ffffff",
            font=("微软雅黑", 10, "bold"),
            padx=10,
            pady=8,
            relief=tk.FLAT
        )
        svip_btn.pack(fill=tk.X, padx=10)

    def create_top_toolbar(self):
        """创建顶部工具栏"""
        # 左侧登录按钮
        login_btn = tk.Button(
            self.top_frame,
            text="点击登录账户",
            bg="#252525",
            fg="#ffffff",
            font=("微软雅黑", 9),
            padx=10,
            pady=5,
            relief=tk.FLAT
        )
        login_btn.pack(side=tk.LEFT, padx=15, pady=10)
        
        # 右侧功能按钮
        right_tools = tk.Frame(self.top_frame, bg="#1a1a1a")
        right_tools.pack(side=tk.RIGHT, padx=15, pady=10)
        
        # 教程按钮
        tutorial_btn = tk.Button(
            right_tools,
            text="教程",
            bg="#252525",
            fg="#ffffff",
            font=("微软雅黑", 9),
            padx=10,
            pady=5,
            relief=tk.FLAT
        )
        tutorial_btn.pack(side=tk.LEFT, padx=5)
        
        # 设置按钮
        settings_btn = tk.Button(
            right_tools,
            text="设置",
            bg="#252525",
            fg="#ffffff",
            font=("微软雅黑", 9),
            padx=10,
            pady=5,
            relief=tk.FLAT
        )
        settings_btn.pack(side=tk.LEFT, padx=5)

    def show_home_page(self):
        """显示首页"""
        self.clear_content_frame()
        
        # 首页内容
        home_frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        home_frame.pack(fill=tk.BOTH, expand=True)
        
        # 中央创作区域
        create_section = tk.Frame(home_frame, bg="#1a1a1a", pady=40)
        create_section.pack(fill=tk.BOTH, expand=True)
        
        # 渐变背景
        gradient_frame = tk.Frame(create_section, bg="#252525", pady=60, padx=40)
        gradient_frame.pack(fill=tk.BOTH, expand=True, padx=40)
        
        # 开始创作按钮
        start_btn = tk.Button(
            gradient_frame,
            text="+ 开始创作",
            command=self.show_ai_script_tab,
            bg="#007acc",
            fg="#ffffff",
            font=("微软雅黑", 18, "bold"),
            padx=40,
            pady=20,
            relief=tk.FLAT,
            bd=0
        )
        start_btn.pack(anchor=tk.CENTER, pady=20)
        
        # 功能模块卡片
        modules_frame = tk.Frame(home_frame, bg="#1a1a1a", pady=40)
        modules_frame.pack(fill=tk.BOTH, expand=True)
        
        # 模块标题
        modules_title = tk.Label(modules_frame, text="快捷功能", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        modules_title.pack(anchor=tk.W, padx=40, pady=10)
        
        # 模块卡片容器
        cards_frame = tk.Frame(modules_frame, bg="#1a1a1a")
        cards_frame.pack(fill=tk.BOTH, expand=True, padx=40)
        
        # 模块卡片
        module_cards = [
            {"name": "AI文字成片", "icon": "✍️", "description": "文字秒变视频，一键创作轻松起步！", "command": self.show_ai_script_tab},
            {"name": "图片设计", "icon": "🖼️", "description": "智能图片处理，打造专业视觉效果", "command": lambda: None},
            {"name": "图文成片", "icon": "📸", "description": "图片加文字，快速生成精美视频", "command": lambda: None},
            {"name": "营销成片", "icon": "📈", "description": "专业营销视频，提升品牌影响力", "command": lambda: None},
            {"name": "AI切片", "icon": "✂️", "description": "智能视频切片，提取精彩片段", "command": lambda: None},
            {"name": "视频翻译", "icon": "🌍", "description": "多语言视频翻译，拓展全球市场", "command": lambda: None}
        ]
        
        # 创建卡片
        for i, card in enumerate(module_cards):
            card_frame = tk.Frame(
                cards_frame,
                bg="#252525",
                width=200,
                height=150,
                relief=tk.RAISED,
                bd=0
            )
            card_frame.grid(row=i//3, column=i%3, padx=15, pady=15, sticky=tk.NSEW)
            
            # 卡片内容
            icon_label = tk.Label(card_frame, text=card["icon"], font=("微软雅黑", 24), bg="#252525", fg="#007acc")
            icon_label.pack(pady=10)
            
            name_label = tk.Label(card_frame, text=card["name"], font=("微软雅黑", 12, "bold"), bg="#252525", fg="#ffffff")
            name_label.pack(pady=5)
            
            desc_label = tk.Label(card_frame, text=card["description"], font=("微软雅黑", 9), bg="#252525", fg="#cccccc", wraplength=180)
            desc_label.pack(pady=5)
            
            # 点击事件
            card_frame.bind("<Button-1>", lambda e, cmd=card["command"]: cmd())
            card_frame.bind("<Enter>", lambda e, frame=card_frame: frame.configure(bg="#2d2d2d"))
            card_frame.bind("<Leave>", lambda e, frame=card_frame: frame.configure(bg="#252525"))
        
        # 专业级功能
        pro_frame = tk.Frame(home_frame, bg="#1a1a1a", pady=40)
        pro_frame.pack(fill=tk.BOTH, expand=True)
        
        # 专业级标题
        pro_title = tk.Label(pro_frame, text="专业级", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        pro_title.pack(anchor=tk.W, padx=40, pady=10)
        
        # 专业级功能卡片
        pro_cards_frame = tk.Frame(pro_frame, bg="#1a1a1a")
        pro_cards_frame.pack(fill=tk.BOTH, expand=True, padx=40)
        
        pro_cards = [
            {"name": "AI文字成片全新升级", "description": "文字秒变视频，一键创作轻松起步！", "image": "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=AI%20video%20creation%20interface%20with%20text%20to%20video%20functionality&image_size=landscape_4_3"},
            {"name": "素材变形透视", "description": "自由调整素材边缘变形", "image": "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=video%20editing%20software%20with%20material%20transformation%20tools&image_size=landscape_4_3"},
            {"name": "基础图形和元素", "description": "一键添加图形元素", "image": "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=graphic%20elements%20and%20shapes%20for%20video%20editing&image_size=landscape_4_3"},
            {"name": "文字蒙板", "description": "文字也能当画布", "image": "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=text%20masking%20effect%20in%20video%20editing&image_size=landscape_4_3"}
        ]
        
        # 创建专业级卡片
        for i, card in enumerate(pro_cards):
            pro_card_frame = tk.Frame(
                pro_cards_frame,
                bg="#252525",
                width=280,
                height=180,
                relief=tk.RAISED,
                bd=0
            )
            pro_card_frame.grid(row=0, column=i, padx=15, pady=15, sticky=tk.NSEW)
            
            # 卡片图片
            img_label = tk.Label(pro_card_frame, bg="#252525")
            img_label.pack(fill=tk.BOTH, expand=True)
            
            # 卡片内容
            content_frame = tk.Frame(pro_card_frame, bg="#252525", pady=10)
            content_frame.pack(fill=tk.X, side=tk.BOTTOM)
            
            name_label = tk.Label(content_frame, text=card["name"], font=("微软雅黑", 11, "bold"), bg="#252525", fg="#ffffff")
            name_label.pack(anchor=tk.W, padx=10, pady=2)
            
            desc_label = tk.Label(content_frame, text=card["description"], font=("微软雅黑", 9), bg="#252525", fg="#cccccc")
            desc_label.pack(anchor=tk.W, padx=10, pady=2)
        
        # 本地草稿
        drafts_frame = tk.Frame(home_frame, bg="#1a1a1a", pady=40)
        drafts_frame.pack(fill=tk.BOTH, expand=True)
        
        # 草稿标题
        drafts_title = tk.Label(drafts_frame, text="本地草稿", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        drafts_title.pack(anchor=tk.W, padx=40, pady=10)
        
        # 草稿内容
        drafts_content = tk.Frame(drafts_frame, bg="#1a1a1a")
        drafts_content.pack(fill=tk.BOTH, expand=True, padx=40)
        
        # 草稿卡片
        draft_cards = [
            {"date": "12月14日", "title": "测试视频1", "views": "15.5K", "duration": "00:05"},
            {"date": "12月14日", "title": "测试视频2", "views": "1.2K", "duration": "00:00"},
            {"date": "12月14日", "title": "测试视频3", "views": "6.4K", "duration": "00:00"},
            {"date": "11月5日", "title": "测试视频4", "views": "6.5K", "duration": "00:00"},
            {"date": "10月1日", "title": "测试视频5", "views": "6.5K", "duration": "00:00"},
            {"date": "9月4日", "title": "测试视频6", "views": "2.9M", "duration": "00:05"}
        ]
        
        # 创建草稿卡片
        for i, draft in enumerate(draft_cards):
            draft_card_frame = tk.Frame(
                drafts_content,
                bg="#252525",
                width=150,
                height=100,
                relief=tk.RAISED,
                bd=0
            )
            draft_card_frame.grid(row=0, column=i, padx=15, pady=15, sticky=tk.NSEW)
            
            # 卡片内容
            date_label = tk.Label(draft_card_frame, text=draft["date"], font=("微软雅黑", 9), bg="#252525", fg="#cccccc")
            date_label.pack(anchor=tk.W, padx=10, pady=5)
            
            views_label = tk.Label(draft_card_frame, text=f"{draft['views']} | {draft['duration']}", font=("微软雅黑", 9), bg="#252525", fg="#cccccc")
            views_label.pack(anchor=tk.W, padx=10, pady=5)

    def clear_content_frame(self):
        """清空内容区域"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def show_ai_script_tab(self):
        """显示AI脚本驱动选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="AI脚本驱动", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        config_frame.pack(fill=tk.X, pady=10)
        
        # 配置项
        row = 0
        
        # 视频主题/提示词
        tk.Label(config_frame, text="视频主题/提示词:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.theme_entry = tk.Entry(config_frame, width=60, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.theme_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=10)
        self.theme_entry.insert(0, "一个关于逆袭的故事")
        row += 1
        
        # 输出文件名
        tk.Label(config_frame, text="输出文件名:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.output_name_entry = tk.Entry(config_frame, width=60, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.output_name_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=10)
        self.output_name_entry.insert(0, "ai_generated_video.mp4")
        row += 1
        
        # 视频风格
        tk.Label(config_frame, text="视频风格:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.style_var = tk.StringVar(value="normal")
        style_options = ["normal", "high_burn", "sweet", "reversal_face_slap", "satisfying"]
        self.style_menu = ttk.Combobox(config_frame, textvariable=self.style_var, values=style_options, state="readonly", width=20)
        self.style_menu.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 目标时长
        tk.Label(config_frame, text="目标时长:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.duration_var = tk.StringVar(value="short")
        duration_options = ["short", "medium", "long"]
        self.duration_menu = ttk.Combobox(config_frame, textvariable=self.duration_var, values=duration_options, state="readonly", width=20)
        self.duration_menu.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 嘴型同步
        self.lip_sync_var = tk.BooleanVar()
        lip_sync_enabled = self.deps_status.get('LIP_SYNC_AVAILABLE', False)
        tk.Checkbutton(config_frame, text="启用嘴型同步", variable=self.lip_sync_var, state='normal' if lip_sync_enabled else 'disabled', bg="#252525", fg="#ffffff", selectcolor="#252525").grid(row=row, column=1, sticky=tk.W, padx=10, pady=10)
        row += 1
        
        # 进度条
        self.progress_var1 = tk.DoubleVar()
        self.progress_bar1 = ttk.Progressbar(frame, variable=self.progress_var1, maximum=100)
        self.progress_bar1.pack(fill=tk.X, pady=10, padx=0)
        self.progress_label1 = tk.Label(frame, text="准备就绪", bg="#1a1a1a", fg="#ffffff")
        self.progress_label1.pack(pady=5)
        
        # 生成按钮
        generate_btn = tk.Button(frame, text="生成视频", command=self.start_generate_from_scratch_threaded, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=10, relief=tk.FLAT)
        generate_btn.pack(anchor=tk.CENTER, pady=20)
        
        # 日志
        log_title = tk.Label(frame, text="日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.log_text1 = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.log_text1.pack(fill=tk.BOTH, expand=True, pady=10)

    def show_process_existing_tab(self):
        """显示处理现有视频选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="处理现有视频", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        config_frame.pack(fill=tk.X, pady=10)
        
        # 配置项
        row = 0
        
        # 视频路径
        tk.Label(config_frame, text="视频路径:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.video_path_var = tk.StringVar()
        self.video_path_entry = tk.Entry(config_frame, textvariable=self.video_path_var, width=50, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.video_path_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=10)
        browse_btn = tk.Button(config_frame, text="浏览", command=lambda: self.browse_file(self.video_path_var, (("Video Files", "*.mp4 *.avi *.mov *.mkv"),)), bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=10, pady=5, relief=tk.FLAT)
        browse_btn.grid(row=row, column=3, padx=10, pady=10)
        row += 1
        
        # 输出文件名
        tk.Label(config_frame, text="输出文件名:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.process_output_name_entry = tk.Entry(config_frame, width=50, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.process_output_name_entry.grid(row=row, column=1, columnspan=2, padx=10, pady=10)
        self.process_output_name_entry.insert(0, "processed_video.mp4")
        row += 1
        
        # 目标时长
        tk.Label(config_frame, text="目标时长:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.process_duration_var = tk.StringVar(value="medium")
        duration_options = ["short", "medium", "long"]
        self.process_duration_menu = ttk.Combobox(config_frame, textvariable=self.process_duration_var, values=duration_options, state="readonly", width=20)
        self.process_duration_menu.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 嘴型同步
        self.process_lip_sync_var = tk.BooleanVar()
        lip_sync_enabled = self.deps_status.get('LIP_SYNC_AVAILABLE', False)
        tk.Checkbutton(config_frame, text="启用嘴型同步", variable=self.process_lip_sync_var, state='normal' if lip_sync_enabled else 'disabled', bg="#252525", fg="#ffffff", selectcolor="#252525").grid(row=row, column=1, sticky=tk.W, padx=10, pady=10)
        row += 1
        
        # 进度条
        self.progress_var2 = tk.DoubleVar()
        self.progress_bar2 = ttk.Progressbar(frame, variable=self.progress_var2, maximum=100)
        self.progress_bar2.pack(fill=tk.X, pady=10, padx=0)
        self.progress_label2 = tk.Label(frame, text="准备就绪", bg="#1a1a1a", fg="#ffffff")
        self.progress_label2.pack(pady=5)
        
        # 处理按钮
        process_btn = tk.Button(frame, text="处理视频", command=self.start_process_existing_video_threaded, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=10, relief=tk.FLAT)
        process_btn.pack(anchor=tk.CENTER, pady=10)
        
        # 嘴型同步按钮
        lip_sync_btn = tk.Button(frame, text="嘴型同步", command=self.start_lip_sync_threaded, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=10, relief=tk.FLAT)
        lip_sync_btn.pack(anchor=tk.CENTER, pady=10)
        
        # 日志
        log_title = tk.Label(frame, text="日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.log_text2 = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.log_text2.pack(fill=tk.BOTH, expand=True, pady=10)

    def show_short_drama_tab(self):
        """显示短剧推广选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="短剧推广", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 模式选择框架
        mode_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        mode_frame.pack(fill=tk.X, pady=10)
        
        # 模式选择
        tk.Label(mode_frame, text="创作模式:", bg="#252525", fg="#ffffff").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        self.drama_mode_var = tk.StringVar(value="mix_cut")
        mode_options = ["mix_cut", "light_narration"]
        mode_combo = ttk.Combobox(mode_frame, textvariable=self.drama_mode_var, values=mode_options, state="readonly", width=20)
        mode_combo.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 配置选项
        config_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        config_frame.pack(fill=tk.X, pady=10)
        
        # 配置项
        row = 0
        
        # 短剧ID
        tk.Label(config_frame, text="短剧ID:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.drama_id_var = tk.StringVar()
        tk.Entry(config_frame, textvariable=self.drama_id_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 题材
        tk.Label(config_frame, text="题材:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.genre_var = tk.StringVar(value="复仇")
        genre_options = ["复仇", "甜宠", "悬疑", "都市"]
        genre_combo = ttk.Combobox(config_frame, textvariable=self.genre_var, values=genre_options, state="readonly", width=20)
        genre_combo.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 平台
        tk.Label(config_frame, text="平台:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.platform_var = tk.StringVar(value="douyin")
        platform_options = ["douyin", "kuaishou"]
        platform_combo = ttk.Combobox(config_frame, textvariable=self.platform_var, values=platform_options, state="readonly", width=20)
        platform_combo.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 输出文件名
        tk.Label(config_frame, text="输出文件名:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.drama_output_var = tk.StringVar(value="drama_output.mp4")
        tk.Entry(config_frame, textvariable=self.drama_output_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 进度条
        self.drama_progress_var = tk.DoubleVar()
        self.drama_progress_bar = ttk.Progressbar(frame, variable=self.drama_progress_var, maximum=100)
        self.drama_progress_bar.pack(fill=tk.X, pady=10, padx=0)
        self.drama_progress_label = tk.Label(frame, text="准备就绪", bg="#1a1a1a", fg="#ffffff")
        self.drama_progress_label.pack(pady=5)
        
        # 生成按钮
        generate_btn = tk.Button(frame, text="生成视频", command=self.start_drama_creation_threaded, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=10, relief=tk.FLAT)
        generate_btn.pack(anchor=tk.CENTER, pady=20)
        
        # 日志
        log_title = tk.Label(frame, text="日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.drama_log_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.drama_log_text.pack(fill=tk.BOTH, expand=True, pady=10)

    def show_material_management_tab(self):
        """显示素材管理选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="素材管理", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 平台素材拉取
        platform_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        platform_frame.pack(fill=tk.X, pady=10)
        
        # 平台选择
        tk.Label(platform_frame, text="平台:", bg="#252525", fg="#ffffff").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        self.material_platform_var = tk.StringVar(value="douyin")
        platform_options = ["douyin", "kuaishou"]
        platform_combo = ttk.Combobox(platform_frame, textvariable=self.material_platform_var, values=platform_options, state="readonly", width=20)
        platform_combo.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 短剧ID
        tk.Label(platform_frame, text="短剧ID:", bg="#252525", fg="#ffffff").grid(row=1, column=0, sticky=tk.W, padx=10, pady=10)
        self.material_drama_id_var = tk.StringVar()
        tk.Entry(platform_frame, textvariable=self.material_drama_id_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=1, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 拉取素材按钮
        fetch_btn = tk.Button(platform_frame, text="拉取素材", command=self.start_fetch_materials_threaded, bg="#007acc", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=5, relief=tk.FLAT)
        fetch_btn.grid(row=2, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 素材列表
        self.material_listbox = tk.Listbox(frame, width=80, height=15, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff")
        self.material_listbox.pack(fill=tk.X, pady=10)
        
        # 本地素材管理
        local_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        local_frame.pack(fill=tk.X, pady=10)
        
        # 本地素材按钮
        analyze_btn = tk.Button(local_frame, text="AI分析素材", command=self.start_analyze_material_threaded, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        analyze_btn.pack(side=tk.LEFT, padx=10)
        
        split_btn = tk.Button(local_frame, text="分割素材", command=self.start_split_material_threaded, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        split_btn.pack(side=tk.LEFT, padx=10)
        
        # 日志
        log_title = tk.Label(frame, text="日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.material_log_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.material_log_text.pack(fill=tk.BOTH, expand=True, pady=10)

    def show_batch_processing_tab(self):
        """显示批量处理选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="批量处理", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 文件列表框架
        file_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        file_frame.pack(fill=tk.X, pady=10)
        
        # 文件列表
        self.batch_files_list = tk.Listbox(file_frame, width=80, height=10, bg="#2d2d2d", fg="#ffffff", selectbackground="#333333", selectforeground="#ffffff")
        self.batch_files_list.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 按钮框架
        button_frame = tk.Frame(frame, bg="#1a1a1a", pady=10)
        button_frame.pack(fill=tk.X, pady=5)
        
        add_files_btn = tk.Button(button_frame, text="添加文件", command=self.batch_add_files, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        add_files_btn.pack(side=tk.LEFT, padx=10)
        
        add_folder_btn = tk.Button(button_frame, text="添加文件夹", command=self.batch_add_folder, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        add_folder_btn.pack(side=tk.LEFT, padx=10)
        
        remove_btn = tk.Button(button_frame, text="移除选中", command=self.batch_remove_selected, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        remove_btn.pack(side=tk.LEFT, padx=10)
        
        clear_btn = tk.Button(button_frame, text="清空列表", command=self.batch_clear_list, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=15, pady=5, relief=tk.FLAT)
        clear_btn.pack(side=tk.LEFT, padx=10)
        
        # 处理选项框架
        options_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        options_frame.pack(fill=tk.X, pady=10)
        
        # 输出目录
        tk.Label(options_frame, text="输出目录:", bg="#252525", fg="#ffffff").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        self.batch_output_dir = tk.Entry(options_frame, width=50, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.batch_output_dir.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        browse_btn = tk.Button(options_frame, text="浏览", command=self.batch_browse_output_dir, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=10, pady=5, relief=tk.FLAT)
        browse_btn.grid(row=0, column=2, padx=10, pady=10)
        
        # 目标时长
        tk.Label(options_frame, text="目标时长:", bg="#252525", fg="#ffffff").grid(row=1, column=0, sticky=tk.W, padx=10, pady=10)
        self.batch_duration_var = tk.StringVar(value="short")
        duration_options = ["short", "medium", "long"]
        duration_combo = ttk.Combobox(options_frame, textvariable=self.batch_duration_var, values=duration_options, state="readonly", width=20)
        duration_combo.grid(row=1, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 嘴型同步
        self.batch_lip_sync_var = tk.BooleanVar(value=False)
        tk.Checkbutton(options_frame, text="启用嘴型同步", variable=self.batch_lip_sync_var, bg="#252525", fg="#ffffff", selectcolor="#252525").grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=10)
        
        # 进度条
        self.batch_progress_var = tk.DoubleVar()
        self.batch_progress_bar = ttk.Progressbar(frame, variable=self.batch_progress_var, maximum=100)
        self.batch_progress_bar.pack(fill=tk.X, pady=10, padx=0)
        self.batch_progress_label = tk.Label(frame, text="准备就绪", bg="#1a1a1a", fg="#ffffff")
        self.batch_progress_label.pack(pady=5)
        
        # 开始处理按钮
        start_btn = tk.Button(frame, text="开始批量处理", command=self.start_batch_processing, bg="#007acc", fg="#ffffff", font=("微软雅黑", 11), padx=30, pady=10, relief=tk.FLAT)
        start_btn.pack(anchor=tk.CENTER, pady=20)
        
        # 日志
        log_title = tk.Label(frame, text="处理日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.batch_log = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.batch_log.pack(fill=tk.BOTH, expand=True, pady=10)

    def show_advanced_tools_tab(self):
        """显示高级工具箱选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="高级工具箱", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        config_frame.pack(fill=tk.X, pady=10)
        
        # 选择工具
        tk.Label(config_frame, text="选择工具:", bg="#252525", fg="#ffffff").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        self.tool_var = tk.StringVar(value="提取音频")
        tool_options = ["提取音频", "提取字幕", "转换格式"]
        tool_menu = ttk.Combobox(config_frame, textvariable=self.tool_var, values=tool_options, state="readonly", width=20)
        tool_menu.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 输入文件
        tk.Label(config_frame, text="输入文件:", bg="#252525", fg="#ffffff").grid(row=1, column=0, sticky=tk.W, padx=10, pady=10)
        self.adv_input_var = tk.StringVar()
        tk.Entry(config_frame, textvariable=self.adv_input_var, width=50, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=1, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        browse_input_btn = tk.Button(config_frame, text="浏览", command=lambda: self.browse_file(self.adv_input_var), bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=10, pady=5, relief=tk.FLAT)
        browse_input_btn.grid(row=1, column=3, padx=10, pady=10)
        
        # 输出文件
        tk.Label(config_frame, text="输出文件:", bg="#252525", fg="#ffffff").grid(row=2, column=0, sticky=tk.W, padx=10, pady=10)
        self.adv_output_var = tk.StringVar()
        tk.Entry(config_frame, textvariable=self.adv_output_var, width=50, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=2, column=1, columnspan=2, padx=10, pady=10, sticky=tk.W)
        
        # 执行按钮
        execute_btn = tk.Button(config_frame, text="执行", command=self.start_run_advanced_tool_threaded, bg="#007acc", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=5, relief=tk.FLAT)
        execute_btn.grid(row=3, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 日志
        log_title = tk.Label(frame, text="日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.log_text4 = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.log_text4.pack(fill=tk.BOTH, expand=True, pady=10)

    def show_data_analysis_tab(self):
        """显示数据复盘选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="数据复盘", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 数据追踪
        track_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        track_frame.pack(fill=tk.X, pady=10)
        
        # 数据追踪项
        row = 0
        
        # 视频ID
        tk.Label(track_frame, text="视频ID:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.track_video_id_var = tk.StringVar()
        tk.Entry(track_frame, textvariable=self.track_video_id_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 播放量
        tk.Label(track_frame, text="播放量:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.track_views_var = tk.StringVar()
        tk.Entry(track_frame, textvariable=self.track_views_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 点赞数
        tk.Label(track_frame, text="点赞数:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.track_likes_var = tk.StringVar()
        tk.Entry(track_frame, textvariable=self.track_likes_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 评论数
        tk.Label(track_frame, text="评论数:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.track_comments_var = tk.StringVar()
        tk.Entry(track_frame, textvariable=self.track_comments_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 转化率
        tk.Label(track_frame, text="转化率:", bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
        self.track_conversions_var = tk.StringVar()
        tk.Entry(track_frame, textvariable=self.track_conversions_var, width=40, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff").grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 记录数据按钮
        record_btn = tk.Button(track_frame, text="记录数据", command=self.track_video_data, bg="#007acc", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=5, relief=tk.FLAT)
        record_btn.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
        row += 1
        
        # 数据分析
        analysis_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        analysis_frame.pack(fill=tk.X, pady=10)
        
        # 分析按钮
        analyze_btn = tk.Button(analysis_frame, text="分析数据", command=self.start_analyze_data_threaded, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        analyze_btn.pack(side=tk.LEFT, padx=10)
        
        # 生成策略按钮
        strategy_btn = tk.Button(analysis_frame, text="生成策略", command=self.start_generate_strategy_threaded, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        strategy_btn.pack(side=tk.LEFT, padx=10)
        
        # 分析结果
        result_title = tk.Label(frame, text="分析结果:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        result_title.pack(anchor=tk.W, pady=10)
        self.analysis_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.analysis_text.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 日志
        log_title = tk.Label(frame, text="日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.data_log_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.data_log_text.pack(fill=tk.BOTH, expand=True, pady=10)

    def show_model_management_tab(self):
        """显示模型管理选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="模型管理", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 模型管理日志
        log_title = tk.Label(frame, text="模型管理日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.log_text3 = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.log_text3.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 按钮框架
        button_frame = tk.Frame(frame, bg="#1a1a1a", pady=10)
        button_frame.pack(fill=tk.X, pady=5)
        
        download_btn = tk.Button(button_frame, text="下载必要模型", command=self.start_download_models_threaded, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        download_btn.pack(side=tk.LEFT, padx=10)
        
        clear_btn = tk.Button(button_frame, text="清理模型缓存", command=self.start_clear_cache_threaded, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        clear_btn.pack(side=tk.LEFT, padx=10)

    def show_configuration_tab(self):
        """显示配置管理选项卡"""
        self.clear_content_frame()
        
        # 创建选项卡内容
        frame = tk.Frame(self.content_frame, bg="#1a1a1a")
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # 标题
        title = tk.Label(frame, text="配置管理", font=("微软雅黑", 16, "bold"), bg="#1a1a1a", fg="#ffffff")
        title.pack(anchor=tk.W, pady=10)
        
        # 配置框架
        config_frame = tk.Frame(frame, bg="#252525", pady=20, padx=20)
        config_frame.pack(fill=tk.X, pady=10)
        
        # 配置项
        config_items = {
            "models_dir": "模型目录",
            "temp_dir": "临时目录",
            "素材库_path": "素材库路径",
            "output_dir": "输出目录",
            "faster_whisper_size": "Whisper模型大小",
            "text_duration_ratio": "文本时长比例"
        }
        
        # 配置输入框
        self.config_entries = {}
        row = 0
        
        for key, label in config_items.items():
            tk.Label(config_frame, text=label, bg="#252525", fg="#ffffff").grid(row=row, column=0, sticky=tk.W, padx=10, pady=10)
            entry = tk.Entry(config_frame, width=50, bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
            entry.grid(row=row, column=1, padx=10, pady=10, sticky=tk.W)
            self.config_entries[key] = entry
            row += 1
        
        # 按钮框架
        button_frame = tk.Frame(frame, bg="#1a1a1a", pady=10)
        button_frame.pack(fill=tk.X, pady=5)
        
        load_btn = tk.Button(button_frame, text="加载配置", command=self.load_config, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        load_btn.pack(side=tk.LEFT, padx=10)
        
        save_btn = tk.Button(button_frame, text="保存配置", command=self.save_config, bg="#333333", fg="#ffffff", font=("微软雅黑", 9), padx=20, pady=10, relief=tk.FLAT)
        save_btn.pack(side=tk.LEFT, padx=10)
        
        # 日志
        log_title = tk.Label(frame, text="配置日志:", font=("微软雅黑", 12, "bold"), bg="#1a1a1a", fg="#ffffff")
        log_title.pack(anchor=tk.W, pady=10)
        self.config_log = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state='disabled', bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff")
        self.config_log.pack(fill=tk.BOTH, expand=True, pady=10)
    
    def start_process_existing_video_threaded(self):
        """在新线程中处理现有视频"""
        if not self.video_path_var.get():
            messagebox.showerror("错误", "请选择视频文件")
            return
        
        # 创建线程处理任务
        self.cancel_flags["process_existing"] = False
        thread = threading.Thread(target=self.process_existing_video)
        thread.daemon = True
        thread.start()
    
    def process_existing_video(self):
        """处理现有视频"""
        pass
    
    def start_lip_sync_threaded(self):
        """在新线程中执行嘴型同步"""
        if not self.video_path_var.get():
            messagebox.showerror("错误", "请选择视频文件")
            return
        
        # 更新进度标签
        if hasattr(self, 'progress_label2'):
            self.progress_label2.config(text="准备执行嘴型同步...")
        
        # 创建线程处理任务
        self.cancel_flags["lip_sync"] = False
        thread = threading.Thread(target=self.perform_lip_sync)
        thread.daemon = True
        thread.start()
    
    def perform_lip_sync(self):
        """执行嘴型同步"""
        if not self.editor or not self.editor.lip_sync_animator:
            if hasattr(self, 'progress_label2'):
                self.progress_label2.config(text="嘴型同步动画器未初始化")
            messagebox.showerror("错误", "嘴型同步动画器未初始化")
            return
        
        video_path = self.video_path_var.get()
        output_path = os.path.join(os.path.dirname(video_path), "lip_sync_output.mp4")
        
        try:
            # 更新进度标签
            if hasattr(self, 'progress_label2'):
                self.progress_label2.config(text="正在提取音频...")
            
            # 提取音频
            audio_path = os.path.join(os.path.dirname(video_path), "temp_audio.wav")
            video_clip = VideoFileClip(video_path)
            video_clip.audio.write_audiofile(audio_path)
            video_clip.close()
            
            # 更新进度标签
            if hasattr(self, 'progress_label2'):
                self.progress_label2.config(text="正在执行嘴型同步...")
            
            # 执行嘴型同步
            success = self.editor.perform_lip_sync(video_path, audio_path, output_path)
            
            # 清理临时文件
            if os.path.exists(audio_path):
                os.remove(audio_path)
            
            # 更新进度标签
            if hasattr(self, 'progress_label2'):
                if success:
                    self.progress_label2.config(text="嘴型同步已完成")
                else:
                    self.progress_label2.config(text="嘴型同步失败")
            
            if success:
                messagebox.showinfo("成功", f"嘴型同步已完成，输出文件: {output_path}")
            else:
                messagebox.showerror("错误", "嘴型同步失败，请查看日志获取更多信息")
        except Exception as e:
            # 更新进度标签
            if hasattr(self, 'progress_label2'):
                self.progress_label2.config(text="嘴型同步失败")
            messagebox.showerror("错误", f"嘴型同步失败: {e}")
            
    def browse_file(self, var, filetypes=None):
        """浏览文件"""
        if filetypes is None:
            filetypes = (("All Files", "*.*"),)
        
        filename = filedialog.askopenfilename(filetypes=filetypes)
        if filename:
            var.set(filename)