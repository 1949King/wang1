"""
帮助模块 (HelpModule)
======================
从 settings_module.py 中拆分出来的独立帮助模块。
提供 19 个帮助话题的搜索和浏览功能。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QListWidget, QListWidgetItem,
    QStackedWidget
)
import os
import logging
import webbrowser
from app.version import __version__

from .base_module import BaseModule

logger = logging.getLogger("AI短剧编辑器.help")



class HelpModule(BaseModule):
    """帮助模块 - 覆盖全部13个功能模块"""
    
    module_id = "help"
    module_name = "帮助"
    module_icon = "📚"

    def __init__(self):
        super().__init__()  # BaseModule.__init__() → 设置 EventBus 等 + 调用 _setup_ui()
        self._quick_start()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(185)
        sidebar.setStyleSheet("QFrame{background:#121212;border-right:1px solid #1a1a1a;}")
        sbl = QVBoxLayout(sidebar)
        sbl.setContentsMargins(8, 10, 8, 10)
        sbl.setSpacing(1)

        sbl.addWidget(QLabel("📚 帮助中心"))

        # ── 搜索框 ──
        self._help_search = QLineEdit()
        self._help_search.setPlaceholderText("🔍 搜索帮助...")
        self._help_search.setStyleSheet(
            "QLineEdit{background:#1a1a1a;color:#ccc;border:1px solid #333;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
            "QLineEdit:focus{border:1px solid #1e6bde;}"
        )
        self._help_search.textChanged.connect(self._on_help_search)
        sbl.addWidget(self._help_search)

        # 搜索结果列表（默认隐藏）
        self._help_search_results = QListWidget()
        self._help_search_results.setStyleSheet(
            "QListWidget{background:#121212;border:none;}"
            "QListWidget::item{color:#ccc;padding:6px 10px;font-size:11px;border-bottom:1px solid #1a1a1a;}"
            "QListWidget::item:hover{background:#1e1e1e;color:#fff;}"
        )
        self._help_search_results.itemClicked.connect(self._on_search_result_clicked)
        self._help_search_results.setVisible(False)
        sbl.addWidget(self._help_search_results)

        topics = [
            ("🚀", "快速入门", self._quick_start),
            ("📖", "新手专区 🌟", self._beginner),
            ("🎥", "视频教程 📺", self._video_tutorials),
            ("📡", "API网址大全", self._api_urls),
            ("🏠", "首页", self._home),
            ("🎬", "剪辑功能", self._editor),
            ("⚙️", "内核模式", self._kernel_mode_guide),
            ("✍️", "文案生成", self._copywriting),
            ("📋", "多任务管理", self._tasks),
            ("📁", "素材库", self._materials),
            ("🌐", "素材网站直达", self._material_sites),
            ("🧩", "插件中心", self._plugins),
            ("📊", "性能监控", self._perf),
            ("🤖", "模型广场", self._models),
            ("🎨", "AI画布", self._ai_canvas),
            ("🌐", "外部画布备选", self._canvas_alternatives),
            ("❓", "常见问题", self._faq),
        ]
        self._help_topics = topics  # 保存引用供搜索使用

        self._content = QScrollArea()
        self._content.setWidgetResizable(True)
        self._content.setStyleSheet("QScrollArea{background:#0a0a0a;border:none;}")
        cw = QWidget()
        self._cl = QVBoxLayout(cw)
        self._cl.setContentsMargins(28, 20, 28, 20)
        self._cl.setSpacing(8)
        self._content.setWidget(cw)

        self._help_nav_buttons = []  # 导航按钮列表，搜索时隐藏
        for icon, name, cb in topics:
            btn = QPushButton(f"{icon}  {name}")
            btn.setStyleSheet("QPushButton{background:transparent;color:#888;border:none;border-radius:6px;padding:7px 10px;font-size:11px;text-align:left;}QPushButton:hover{background:#1e1e1e;color:#ccc;}")
            btn.clicked.connect(lambda checked, c=cb: c())
            self._help_nav_buttons.append(btn)
            sbl.addWidget(btn)
        sbl.addStretch()

        layout.addWidget(sidebar)
        layout.addWidget(self._content, 1)

    def _clear(self):
        while self._cl.count():
            item = self._cl.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        cw = self._content.widget()
        if cw:
            cw.updateGeometry()
            cw.adjustSize()
        self._content.updateGeometry()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _title(self, txt):
        t = QLabel(txt)
        t.setStyleSheet("font-size:18px;font-weight:bold;padding-bottom:4px;")
        t.setWordWrap(True)
        self._cl.addWidget(t)

    def _subtitle(self, txt):
        t = QLabel(txt)
        t.setStyleSheet("font-size:13px;font-weight:600;color:#1e6bde;margin-top:10px;")
        t.setWordWrap(True)
        self._cl.addWidget(t)

    def _text(self, txt):
        t = QLabel(txt)
        t.setStyleSheet("color:#aaa;font-size:11px;line-height:1.6;")
        t.setWordWrap(True)
        self._cl.addWidget(t)

    def _bullet(self, items):
        for item in items:
            t = QLabel(f"• {item}")
            t.setStyleSheet("color:#999;font-size:11px;padding-left:12px;line-height:1.5;")
            t.setWordWrap(True)
            self._cl.addWidget(t)

    def _tip(self, txt):
        tip = QFrame()
        tip.setStyleSheet("QFrame{background:#1a2a1a;border-left:3px solid #4caf50;border-radius:4px;}")
        tl = QVBoxLayout(tip)
        tl.setContentsMargins(10, 6, 10, 6)
        lb = QLabel(f"💡 {txt}")
        lb.setStyleSheet("color:#81c784;font-size:10px;")
        lb.setWordWrap(True)
        tl.addWidget(lb)
        self._cl.addWidget(tip)

    def _md_dir(self):
        """获取帮助文档 Markdown 目录"""
        from pathlib import Path
        return Path(__file__).parent.parent.parent.parent / "docs" / "help"

    def _load_markdown_topic(self, topic_id: str) -> bool:
        """从 Markdown 文件加载帮助内容，成功返回 True，失败返回 False"""
        md_path = self._md_dir() / f"{topic_id}.md"
        if not md_path.exists():
            return False
        try:
            import re
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._render_markdown(content)
            return True
        except Exception:
            return False

    def _render_markdown(self, content: str):
        """将简化的 Markdown 渲染为 UI 组件"""
        import re
        lines = content.strip().split('\n')
        i = 0
        bullets_buf = []

        def _flush_bullets():
            nonlocal bullets_buf
            if bullets_buf:
                self._bullet(bullets_buf)
                bullets_buf = []

        while i < len(lines):
            line = lines[i]

            # 标题 # / ##
            if line.startswith('# '):
                _flush_bullets()
                self._title(line[2:].strip())
            elif line.startswith('## '):
                _flush_bullets()
                self._subtitle(line[3:].strip())
            elif line.startswith('### '):
                _flush_bullets()
                self._subtitle(line[4:].strip())

            # 分割线
            elif line.strip() == '---':
                _flush_bullets()

            # 无序列表
            elif line.strip().startswith('- ') or line.strip().startswith('* '):
                item = line.strip()[2:]
                # 处理链接 [text](url)
                item = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', item)
                bullets_buf.append(item)

            # 表格（简单处理为文本行）
            elif '|' in line and i + 2 < len(lines) and '---' in lines[i + 1]:
                _flush_bullets()
                rows = []
                j = i
                while j < len(lines) and '|' in lines[j]:
                    cells = [c.strip() for c in lines[j].split('|') if c.strip()]
                    rows.append(cells)
                    j += 1
                # 只显示数据行
                for cells in rows[2:] if len(rows) > 2 else rows[1:]:
                    self._text(" | ".join(cells))
                i = j
                continue

            # 强调 > 
            elif line.startswith('> '):
                _flush_bullets()
                self._tip(line[2:].strip())

            # 普通文本
            elif line.strip():
                _flush_bullets()
                txt = line.strip()
                # 处理粗体
                txt = re.sub(r'\*\*([^*]+)\*\*', r'\1', txt)
                self._text(txt)

            i += 1

        _flush_bullets()
        self._cl.addStretch()

    def _link(self, label, url):
        btn = QPushButton(f"🔗 {label}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("QPushButton{background:#1a1a2e;color:#3b82f6;border:1px solid #1e3a5f;border-radius:4px;padding:4px 10px;font-size:10px;text-align:left;}QPushButton:hover{background:#1e3a5f;}")
        btn.clicked.connect(lambda _: webbrowser.open(url))
        self._cl.addWidget(btn)

    def _link_row(self, label, url, desc=""):
        row = QHBoxLayout()
        row.setSpacing(6)
        lb = QLabel(label)
        lb.setStyleSheet("color:#aaa;font-size:11px;")
        lb.setWordWrap(True)
        row.addWidget(lb)
        btn = QPushButton("🔗 打开")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedWidth(60)
        btn.setStyleSheet("QPushButton{background:#1e3a5f;color:#3b82f6;border:none;border-radius:3px;padding:3px 6px;font-size:9px;}QPushButton:hover{background:#2850a0;}")
        btn.clicked.connect(lambda _: webbrowser.open(url))
        row.addWidget(btn)
        if desc:
            dl = QLabel(desc)
            dl.setStyleSheet("color:#555;font-size:9px;")
            dl.setWordWrap(True)
            row.addWidget(dl)
        row.addStretch()
        self._cl.addLayout(row)

    def _image(self, label: str, source: str):
        """显示配图占位框（4.3 帮助模块配图）"""
        img_frame = QFrame()
        img_frame.setStyleSheet("QFrame{background:#1a1a2e;border:2px dashed #1e3a5f;border-radius:8px;}")
        img_frame.setMinimumHeight(180)
        ilo = QVBoxLayout(img_frame)
        ilo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ilo.setSpacing(8)

        # 尝试加载本地图片
        from pathlib import Path
        pixmap = None
        try:
            img_path = Path(__file__).parent.parent.parent.parent / "docs" / "help" / "images" / source
            if img_path.exists():
                pixmap = QPixmap(str(img_path))
        except Exception as e:
            logger.debug("加载帮助图片失败 source=%s: %s", source, e)

        if pixmap and not pixmap.isNull():
            img_lbl = QLabel()
            img_lbl.setPixmap(pixmap.scaledToWidth(600, Qt.TransformationMode.SmoothTransformation))
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet("background:transparent;border:none;")
            ilo.addWidget(img_lbl)
        else:
            icon_lbl = QLabel("🖼️")
            icon_lbl.setStyleSheet("font-size:40px;background:transparent;")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ilo.addWidget(icon_lbl)

        caption = QLabel(f"📸 {label}")
        caption.setStyleSheet("color:#888;font-size:10px;background:transparent;")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setWordWrap(True)
        ilo.addWidget(caption)

        tip_lbl = QLabel("💡 截图可放入 docs/help/images/ 目录自动加载")
        tip_lbl.setStyleSheet("color:#555;font-size:9px;background:transparent;")
        tip_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ilo.addWidget(tip_lbl)

        self._cl.addWidget(img_frame)

    def _video_tutorials(self):
        """视频教程入口（4.4 缺少视频教程入口）"""
        self._clear()
        if self._load_markdown_topic("video_tutorials"):
            return
        # 回退：手动构建
        # 如实说明：本软件目前没有自制/官方发布的分镜头视频教程，
        # 此前这里列出了一批带具体时长（"5分钟""8分钟"...）的条目，
        # 容易让人误以为是真实存在、可直接播放的官方教程——实际点了
        # 也只会跳到 B站/YouTube 主页而非对应视频。现在改为如实标注
        # 「建议学习路径」，并用搜索结果链接（和「新手专区」一致的做法）
        # 替代虚构的具体教程标题和时长。
        self._title("🎥 视频教程")
        self._text("拾光剪影目前没有官方录制的分镜头视频教程；下面是按学习路径整理的搜索关键词，点击可跳转到 B站搜索结果，由社区/第三方内容供参考。")

        self._subtitle("新手入门（建议按顺序搜索学习）")
        self._link_row("B站：AI视频剪辑软件入门", "https://search.bilibili.com/all?keyword=AI视频剪辑软件入门", "了解基本操作")
        self._link_row("B站：PyQt6桌面软件界面介绍", "https://search.bilibili.com/all?keyword=视频剪辑软件界面介绍", "了解工作台布局")
        self._link_row("B站：短视频剪辑完整流程", "https://search.bilibili.com/all?keyword=短视频剪辑完整流程", "完整剪辑演示")

        self._subtitle("功能详解")
        self._link_row("B站：AI智能识别精彩片段", "https://search.bilibili.com/all?keyword=AI智能识别视频精彩片段", "对应本软件 AutoClip 功能")
        self._link_row("B站：DeepSeek/豆包 API配置", "https://search.bilibili.com/all?keyword=AI大模型API配置教程", "对应「模型广场」")
        self._link_row("B站：剪辑软件卡顿优化", "https://search.bilibili.com/all?keyword=视频剪辑软件卡顿优化", "通用性能建议")

        self._subtitle("高级技巧")
        self._link_row("B站：批量视频处理技巧", "https://search.bilibili.com/all?keyword=批量视频处理技巧", "多任务场景参考")
        self._link_row("B站：视频转场特效制作", "https://search.bilibili.com/all?keyword=视频转场特效制作", "特效/转场参考")
        self._link_row("B站：爆款标题文案技巧", "https://search.bilibili.com/all?keyword=爆款标题文案技巧", "文案生成参考")

        self._tip("以上均为第三方内容搜索入口，非本软件官方出品，内容质量和适用版本请自行判断")

        self._cl.addStretch()

    def _beginner(self):
        self._clear()
        if self._load_markdown_topic("quick_start"):
            return
        self._title("📖 新手专区")
        self._text("欢迎！本页专为初次使用AI短剧编辑器的用户准备，手把手带你完成从零到发布的完整流程。")
        self._subtitle("🎯 准备工作（必看）")
        self._bullet(["1. 注册一个AI模型平台的账号（推荐DeepSeek或豆包，免费额度友好）",
                      "2. 在对应平台获取API Key（见下方「API网址大全」）",
                      "3. 在本软件中配置并激活模型（见「模型广场」）",
                      "4. 准备一段测试视频（手机拍摄即可）"])
        self._subtitle("📹 零基础三步上手指南")
        self._text("第一步：打开「模型广场」→ 选择「DeepSeek」或「豆包」→ 填入API Key → 点击圆形按钮激活")
        self._text("第二步：打开「剪辑」→ 点击「📁导入」选视频 → 视频出现在时间轴上 → 按▶播放预览")
        self._text("第三步：调整好之后 → 点底部「💾开始导出」→ 选择MP4/1080p → 完成！")
        self._subtitle("📺 视频教程推荐（点击跳转浏览器观看）")
        self._link_row("B站：AI短剧编辑器入门", "https://search.bilibili.com/all?keyword=AI视频剪辑入门", "推荐先看")
        self._link_row("B站：DeepSeek API注册教程", "https://search.bilibili.com/all?keyword=DeepSeek+API注册", "第三方内容")
        self._link_row("B站：Ollama本地模型安装", "https://search.bilibili.com/all?keyword=Ollama安装教程", "通用")
        self._link_row("B站：短视频剪辑新手入门", "https://search.bilibili.com/all?keyword=短视频剪辑新手", "零基础")
        self._subtitle("🆘 遇到问题？")
        self._bullet(["查看左侧「常见问题」栏目",
                      "切换左侧「API网址大全」查看所有平台注册地址"])
        self._cl.addStretch()

    def _api_urls(self):
        self._clear()
        if self._load_markdown_topic("api_urls"):
            return
        self._title("📡 API网址大全")
        self._text("点击「打开」跳转浏览器访问各平台官网。新手推荐标注⭐的平台，注册即送免费额度。")
        apis = [
            ("🆓 DeepSeek (推荐)", "https://platform.deepseek.com", "platform.deepseek.com", "注册送500万tokens", "⭐"),
            ("🆓 豆包/火山引擎", "https://console.volcengine.com/ark", "console.volcengine.com/ark", "字节跳动，性价比高", "⭐"),
            ("🆓 OpenAI / ChatGPT", "https://platform.openai.com/api-keys", "platform.openai.com", "需海外网络，最强模型", "🆓"),
            ("🆓 智谱AI (GLM-4)", "https://open.bigmodel.cn", "open.bigmodel.cn", "国产多模态，视觉理解", "⭐"),
            ("🆓 通义千问 (阿里云)", "https://dashscope.console.aliyun.com", "dashscope.aliyun.com", "阿里云，中文能力强", "⭐"),
            ("🆓 文心一言 (百度)", "https://console.bce.baidu.com/qianfan", "console.bce.baidu.com/qianfan", "百度千帆大模型平台", "🆓"),
            ("🆓 讯飞星火", "https://console.xfyun.cn/services/bm3", "xinghuo.xfyun.cn", "讯飞，语音交互强", "⭐"),
            ("🆓 Kimi (月之暗面)", "https://platform.moonshot.cn", "platform.moonshot.cn", "长文本处理专家", "⭐"),
            ("🆓 百川智能", "https://platform.baichuan-ai.com", "platform.baichuan-ai.com", "国产大模型新锐", "🆓"),
            ("🆓 MiniMax", "https://platform.minimaxi.com", "platform.minimaxi.com", "ABAB系列模型", "🆓"),
            ("🆓 阶跃星辰", "https://platform.stepfun.com", "platform.stepfun.com", "Step系列模型", "🆓"),
            ("🆓 零一万物", "https://platform.lingyiwanwu.com", "platform.lingyiwanwu.com", "Yi系列模型", "🆓"),
            ("Claude (Anthropic)", "https://console.anthropic.com", "console.anthropic.com", "需海外网络，编程强", ""),
            ("🆓 Groq", "https://console.groq.com", "console.groq.com", "超快推理，免费额度", "⭐"),
            ("🆓 硅基流动", "https://cloud.siliconflow.cn", "cloud.siliconflow.cn", "模型聚合平台", "⭐"),
            ("🖥️ ChatGPT2API", "https://github.com/basketikun/chatgpt2api", "github.com/basketikun/chatgpt2api", "自托管 OpenAI 兼容网关，gpt-image-2 生图", "⭐AIGC"),
            ("🖥️ Ollama (本地部署)", "https://ollama.com", "ollama.com", "完全免费本地运行，支持千问、Llama等模型，可在模型广场直接拉取", "⭐免费"),
            ("🆓 腾讯混元", "https://cloud.tencent.com/product/hunyuan", "cloud.tencent.com/product/hunyuan", "腾讯大模型", "🆓"),
            ("🆓 魔搭社区 (ModelScope)", "https://modelscope.cn", "modelscope.cn", "阿里达摩院开源模型平台，可在模型广场直接下载本地部署", "⭐"),
            ("🆓 华为盘古", "https://www.huaweicloud.com/product/pangu.html", "www.huaweicloud.com", "华为大模型", ""),
            ("🆓 网易伏羲", "https://fuxi-copilot.bytedance.net", "fuxi-copilot.bytedance.net", "网易大模型", "🆓"),
            ("🆓 快手AI", "https://ai.kuaishou.com", "ai.kuaishou.com", "快手大模型", "🆓"),
            ("🆓 360智脑", "https://ai.360.cn", "ai.360.cn", "360大模型", "🆓"),
            ("🆓 昆仑万维", "https://www.kunlun.com", "www.kunlun.com", "天工大模型", "🆓"),
            ("🆓 京东言犀", "https://www.jd.com/AI", "ai.jd.com", "京东大模型", "🆓"),
            ("🆓 美团AI", "https://ai.meituan.com", "ai.meituan.com", "美团大模型", "🆓"),
            ("🆓 SambaNova", "https://www.sambanova.ai", "www.sambanova.ai", "企业级AI平台", ""),
            ("🆓 Cohere", "https://dashboard.cohere.com", "dashboard.cohere.com", "企业级LLM", ""),
            ("🆓 Mistral", "https://console.mistral.ai", "console.mistral.ai", "开源模型先驱", "🆓"),
            ("🆓 Together AI", "https://api.together.xyz", "api.together.xyz", "开源模型API", "🆓"),
            ("🆓 Hugging Face", "https://huggingface.co", "huggingface.co", "模型社区平台", "⭐"),
        ]
        for name, url, host, desc, tag in apis:
            row = QHBoxLayout(); row.setSpacing(4)
            nm = QLabel(name)
            nm.setStyleSheet("color:#ccc;font-size:11px;font-weight:600;min-width:130px;")
            nm.setWordWrap(True)
            row.addWidget(nm)
            hl = QLabel(host)
            hl.setStyleSheet("color:#555;font-size:9px;min-width:145px;")
            hl.setWordWrap(True)
            row.addWidget(hl)
            ds = QLabel(desc)
            ds.setStyleSheet("color:#666;font-size:9px;")
            ds.setWordWrap(True)
            row.addWidget(ds, 1)
            if tag:
                tg = QLabel(tag)
                tg.setStyleSheet("color:#22c55e;font-size:9px;font-weight:600;")
                row.addWidget(tg)
            btn = QPushButton("🔗打开")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedWidth(52)
            btn.setStyleSheet("QPushButton{background:#1e3a5f;color:#3b82f6;border:none;border-radius:3px;padding:2px 4px;font-size:9px;}QPushButton:hover{background:#2850a0;}")
            btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            row.addWidget(btn)
            self._cl.addLayout(row)
        self._subtitle("获取API Key 通用步骤（各平台类似）")
        self._bullet(["1. 点击上方「🔗打开」进入平台官网",
                      "2. 注册账号 → 完成实名/企业认证（国内平台通常需要）",
                      "3. 进入「API管理」或「开发者中心」→ 点击「创建API Key」",
                      "4. 复制Key（形如 sk-xxxx...），粘贴到模型广场对应卡片",
                      "5. 在模型广场中「保存」→ 点击圆形按钮激活 → 即可使用",
                      "⚠️ API Key = 钱包密码，不要分享！平台按token用量计费"])
        self._cl.addStretch()

    def _quick_start(self):
        self._clear()
        if self._load_markdown_topic("quick_start"):
            return
        self._title("🚀 快速入门")
        self._text(f"AI短剧编辑器 v{__version__} 是一款集成多种AI大模型的视频编辑工具，覆盖从素材导入、智能剪辑、文案生成到多平台发布的全流程。")
        self._subtitle("第一步：配置AI引擎")
        self._bullet(["打开「模型广场」模块，浏览16个内置AI平台（DeepSeek/豆包/OpenAI/智谱/通义千问等）",
                      "展开目标平台卡片，填写API Key和Base URL，点击保存",
                      "点击卡片右侧圆形按钮激活该模型，状态栏显示绿色「已激活」",
                      "也可点击底部「➕添加自定义模型」接入ChatGPT/OpenRouter等任意兼容平台"])
        self._subtitle("第二步：导入素材")
        self._bullet(["进入「剪辑」模块，点击顶部「📁 导入」按钮选择本地视频文件",
                      "或直接将视频拖拽到左侧导入栏区域",
                      "支持格式：MP4、AVI、MOV、MKV、WebM"])
        self._subtitle("第三步：剪辑与创作")
        self._bullet(["时间轴拖拽片段调整播放顺序，支持多轨道并行编辑",
                      "右侧工具栏提供：属性/调色/特效/文字/音频五大类调整",
                      "轨道标题栏提供：播放控制▶⏸ / 缩放滑块 / AI提示词 / 吸附等功能",
                      "使用「文案生成」模块AI自动生成爆款标题和文案"])
        self._subtitle("第四步：导出与发布")
        self._bullet(["剪辑模块底部设置输出参数（分辨率/帧率/编码/格式）后点击导出",
                      "使用「矩阵发布」功能勾选多账号同时发布到抖音/快手/视频号等平台"])
        self._cl.addStretch()

    def _home(self):
        self._clear(); self._title("🏠 首页")
        self._text("首页是工作台的入口，提供项目概览、快捷操作和系统动态。")
        self._subtitle("核心功能")
        self._bullet(["最近项目列表：快速打开之前编辑的项目，支持搜索和排序",
                      "快捷入口：一键切换到剪辑/文案/素材库等核心模块",
                      "数据看板：展示今日剪辑量、发布数、AI调用次数等关键指标",
                      "系统公告：版本更新、新功能上线、维护通知"])
        self._subtitle("使用技巧")
        self._bullet(["点击最近项目可直接恢复上次编辑状态",
                      "快捷入口支持自定义，在设置中拖拽排序"])
        self._cl.addStretch()

    def _kernel_mode_guide(self):
        """展示统一内核调度器的模式说明。"""
        self._clear(); self._title("⚙️ 统一内核模式")
        self._text("拾光剪影现在使用统一内核调度器管理轻量内核和专业内核。界面只负责选择模式，真正的任务分配、失败回退和执行记录都由核心调度器完成。")
        self._subtitle("三种选择模式")
        self._bullet([
            "自动选择：推荐默认使用。预览、素材探测、普通转码走轻量内核；导出、AI智能剪辑、多轨合成走专业内核。",
            "轻量内核：适合快速预览、简单转码、低成本处理，启动更快，占用更低。",
            "专业内核：适合成片导出、复杂效果、批量任务、AI剪辑，优先使用 MLT C++ 或 FFmpeg CLI 后端。",
        ])
        self._subtitle("调度规则")
        self._bullet([
            "每个任务会先生成任务计划，记录任务类型、推荐内核、回退内核和选择原因。",
            "专业导出失败时会自动回退轻量处理器，尽量保证任务不中断。",
            "AI智能剪辑依赖专业能力，如果专业内核不可用会给出明确失败原因。",
            "最近任务记录会保留内核、状态和错误信息，方便后续诊断和剪辑 Agent 分析。",
        ])
        self._subtitle("建议用法")
        self._bullet([
            "日常剪辑保持“自动选择”，让系统按任务自主切换。",
            "电脑性能较弱或只做预览时选择“轻量内核”。",
            "最终导出、批量处理、复杂剪辑前切到“专业内核”可获得更完整能力。",
        ])
        self._tip("如果不确定该选哪一个，就保持“自动选择”。统一调度器会优先保证稳定性，并在专业路径失败时尝试回退。")
        self._cl.addStretch()

    def _editor(self):
        self._clear(); self._title("🎬 剪辑功能")
        self._text("剪辑模块是核心工作区，提供专业级多轨道视频编辑能力。")
        self._subtitle("界面布局")
        self._bullet(["左侧：导入栏 + 预览窗口（实时预览编辑效果）",
                      "右侧：工具栏（属性/调色/特效/文字/音频 五大标签页）",
                      "下方：轨道系统（时间轴 + 播放控制 + 缩放 + AI提示）"])
        self._subtitle("轨道操作")
        self._bullet(["支持视频/音频/字幕三种轨道类型，点击「➕轨道」添加",
                      "拖拽片段调整位置，滚动查看超宽时间轴",
                      "播放控制：▶/⏸ 播放暂停，⏮/⏭ 前后跳转10秒",
                      "缩放滑块：10%-500%，或点击+/-精细调节，刻度自适应",
                      "时间轴刻度：正常100%显示0.5秒精度，放大至150%+显示0.1秒精度"])
        self._subtitle("工具栏标签页")
        self._bullet(["属性：位置X/Y、缩放、旋转、锚点、不透明度、混合模式、速度、裁剪",
                      "调色：曝光/对比度/高光/阴影，饱和度/色温/色调/锐度，LUT预设（电影/复古/青橙等10种）",
                      "特效：滤镜（12种，含原片/电影/复古/清新/黑白等）、转场（9种，含淡入淡出/滑动/缩放/模糊等）",
                      "文字：字体/字号/颜色/描边/阴影/背景框/位置预设，支持入场/出场动画",
                      "音频：增强/降噪/截取/添加BGM/提取人声，音量/淡入淡出/均衡器/混响"])
        self._subtitle("导出设置")
        self._bullet(["输出模式：自定义/30秒爆款/90秒解说/8分钟挂车",
                      "平台自适应：抖音9:16竖屏 / B站16:9横屏",
                      "视频参数：分辨率/帧率/编码(H.264/H.265/VP9)/格式(MP4/MKV/MOV)/比特率",
                      "音频参数：编码AAC/MP3/WAV，采样率44100/48000，通道立体声/单声道",
                      "硬件加速：NVIDIA NVENC 硬件编码加速"])
        self._tip("使用「🤖 AI提示」按钮输入创作方向，AI将智能调整剪辑策略")
        self._cl.addStretch()

    def _copywriting(self):
        self._clear(); self._title("✍️ 文案生成")
        self._text("AI驱动的爆款文案生成器，支持多平台多风格的标题和文案创作。")
        self._subtitle("核心功能")
        self._bullet(["智能生成：输入关键词/剧情梗概，AI自动生成多个标题变体",
                      "风格选择：搞笑/情感/悬疑/励志/知识/毒舌/温暖等10+风格",
                      "平台适配：抖音/快手/视频号/B站/小红书/微博/头条等自动调整语气",
                      "热度评分：每个标题附带AI预测的热度评分和点击率",
                      "一键复制：点击即可复制文案，支持批量导出"])
        self._subtitle("操作流程")
        self._bullet(["1. 选择目标平台和文案风格",
                      "2. 输入核心关键词或剧情描述",
                      "3. 选择文案类型（标题/简介/话题标签/完整脚本）",
                      "4. 点击「生成」按钮，等候AI输出（需先激活模型）",
                      "5. 从多个候选文案中选择最佳，一键复制使用"])
        self._tip("绿色标签 = 高热度关键词，红色标签 = 需替换的敏感词")
        self._cl.addStretch()

    def _tasks(self):
        self._clear(); self._title("📋 多任务管理")
        self._text("批量处理和任务队列管理，提高内容生产效率。")
        self._subtitle("核心功能")
        self._bullet(["批量剪辑：一次性提交多个视频进行AI剪辑处理",
                      "批量文案：批量生成多个内容平台的适配文案",
                      "批量导出：后台队列导出，支持暂停/取消/重试",
                      "任务状态：已完成/处理中/等待中/失败 四种状态清晰展示",
                      "自动重试：失败任务自动重试3次，支持手动重试"])
        self._subtitle("操作流程")
        self._bullet(["1. 点击「新建任务」选择任务类型",
                      "2. 拖拽或选择待处理的素材文件",
                      "3. 配置处理参数（平台/风格/格式等）",
                      "4. 提交任务到队列，系统自动按序处理",
                      "5. 在任务列表中查看进度，完成后可下载/发布"])
        self._cl.addStretch()



    def _materials(self):
        self._clear(); self._title("📁 素材库")
        self._text("素材库分两个顶部分区：「本地素材」与「提示词库」。"
                    "本地区只管理本机文件（视频/音频/图片/字幕/模板/特效/转场/贴纸）。"
                    "需要外站素材时请到左侧「素材网站直达」打开官网下载，再回到本页导入。")
        self._subtitle("本地素材")
        self._bullet(["支持导入视频（MP4/AVI/MOV/MKV/WebM）",
                      "支持导入音频（MP3/WAV/AAC/FLAC）",
                      "支持导入图片（JPG/PNG/GIF/SVG/BMP）",
                      "按类型分标签页；顶部标签可快速跳转到对应分类",
                      "拖拽或双击/右键「添加到时间线」即可送入剪辑"])
        self._subtitle("提示词库分区")
        self._bullet(["同源 GitHub JSON（yukkcat / stimQQ / NeXra）+ 本地短剧包 / 成人 18+ 包",
                      "左侧细分类（摄影/人像/设计/插画/短剧/成熟/成人）与尺度筛选",
                      "点 ★ 收藏；「我的收藏」可只看已收藏条目",
                      "支持复制提示词、发送到画布；成人源默认关闭需手动勾选"])
        self._subtitle("推荐工作流")
        self._bullet(["在「素材网站直达」打开 Pexels / Pixabay 等站点下载到本地",
                      "回到「素材库」点「导入本地素材」或各分类下的导入/浏览文件夹",
                      "再拖到剪辑时间线精剪与导出",
                      "做 AIGC 时到「提示词库」同步源 → 收藏常用 → 复制或发到画布"])
        self._tip("定期清理不用的素材可释放磁盘空间；完整外链列表见「素材网站直达」。")
        self._cl.addStretch()

    def _material_sites(self):
        """免费/商用素材网站 — 浏览器直达，非软件内置库。"""
        self._clear()
        self._title("🌐 素材网站直达")
        self._text("下列站点在系统浏览器中打开。它们不是本软件内置资源，也不走软件内下载。"
                    "请自行下载到本地后，再回到「素材库」导入或「剪辑」直接导入。"
                    "授权条款、商用限制与费用以各官网为准。")
        self._subtitle("视频 / 图片（常用免费向）")
        self._link_row("Pexels", "https://www.pexels.com/", "免版权视频与图片")
        self._link_row("Pixabay", "https://pixabay.com/", "图片 / 视频 / 音乐")
        self._link_row("Unsplash", "https://unsplash.com/", "高质量图片")
        self._link_row("Mixkit", "https://mixkit.co/", "视频 / 音乐 / 音效")
        self._link_row("Coverr", "https://coverr.co/", "免费库存视频")
        self._link_row("Videvo", "https://www.videvo.net/", "视频与音乐素材")
        self._subtitle("音频 / 音效")
        self._link_row("Freesound", "https://freesound.org/", "社区音效（注意授权）")
        self._link_row("Pixabay Music", "https://pixabay.com/music/", "免版权背景音乐")
        self._subtitle("国内常用素材站（需自行核对授权）")
        self._link_row("爱给网", "https://www.aigei.com/", "音效 / 配乐 / 视频素材")
        self._link_row("包图网", "https://ibaotu.com/", "商用素材（多为付费）")
        self._link_row("摄图网", "https://588ku.com/", "图片 / 视频素材")
        self._subtitle("怎么和本软件配合")
        self._bullet([
            "浏览器下载 → 本地文件夹",
            "「素材库」导入（按类型归类）或「剪辑」里直接加到时间线",
            "精剪、字幕、导出、发布请始终在拾光剪影内完成",
        ])
        self._tip("外链仅作直达入口；本软件不托管、不代理这些网站的内容。")
        self._cl.addStretch()

    def _plugins(self):
        self._clear(); self._title("🧩 插件中心")
        self._text("插件扩展生态系统，增强编辑能力和工作流自动化。")
        self._subtitle("已安装插件")
        self._bullet(["查看所有已安装的插件及其状态（已启用/已禁用）",
                      "每个插件显示：图标+名称+描述+版本号+状态标签",
                      "内置6个基础插件：自动剪辑/字幕生成/去重优化/视频信息/文案生成/数据分析"])
        self._subtitle("插件商店")
        self._bullet(["12个精品插件：批量导出Pro/AI语音合成/智能去水印/动态字幕模板/BGM智能匹配/画质增强等",
                      "分类标签栏：全部/视频处理/AI工具/导出/字幕/音频/特效/运营",
                      "每个插件卡片显示：图标+名称+描述+价格（免费/付费）+安装按钮",
                      "大部分插件免费，少量高级插件付费（¥9.9-¥19.9）",
                      "点击「安装」一键添加到已安装列表"])
        self._subtitle("导入插件")
        self._bullet(["点击顶部「📥导入」按钮，选择.py或.zip格式的第三方插件",
                      "支持社区开发者贡献的自定义插件"])
        self._cl.addStretch()

    def _perf(self):
        self._clear()
        if self._load_markdown_topic("performance"):
            return
        self._title("📊 性能监控")
        self._text("实时系统资源监控，帮助优化编辑性能和排查问题。")
        self._subtitle("监控指标")
        self._bullet(["CPU使用率：实时处理器占用百分比",
                      "内存使用：当前RAM占用及总量",
                      "GPU加速：显卡状态和显存使用（NVIDIA/Intel/AMD）",
                      "磁盘IO：读写速度和可用空间",
                      "任务队列：当前处理中的后台任务数量",
                      "导出速度：最近一次导出的实时速率"])
        self._subtitle("优化建议")
        self._bullet(["使用SSD硬盘可显著提升素材读写速度",
                      "建议32GB以上内存进行4K视频编辑",
                      "NVIDIA RTX系列显卡可开启NVENC硬件编码加速",
                      "导出时可降低预览分辨率以减少CPU负载"])
        self._cl.addStretch()

    def _models(self):
        self._clear(); self._title("🤖 模型广场")
        self._text("AI模型管理中控台，内置主流平台（含 ChatGPT2API 自托管网关），支持自定义添加任意 API。")
        self._subtitle("内置平台")
        self._bullet(["DeepSeek（深度求索）/ 豆包（字节跳动）/ OpenAI（GPT-4o/o1）",
                      "智谱AI（GLM-4）/ 通义千问（阿里云）/ 文心一言（百度）",
                      "讯飞星火 / Kimi（月之暗面）/ 百川 / MiniMax",
                      "Claude（Anthropic）/ Groq / 硅基流动 / 阶跃星辰 / 零一万物 / 魔搭",
                      "ChatGPT2API（自托管，默认本机 :8000，gpt-image-2 生图）",
                      "Ollama（本地模型，支持llama3/deepseek-r1/qwen2.5等）"])
        self._subtitle("操作指南")
        self._bullet(["展开卡片：点击模型名称区域展开/折叠配置面板",
                      "填写配置：API Key + Base URL + 模型选择（可手动输入自定义模型名）",
                      "测试连接：填写后点击「测试连接」验证API可用性",
                      "保存配置：点击「保存」将API Key和参数持久化到本地",
                      "激活模型：点击右侧圆形按钮，状态栏变绿并显示当前激活模型名"])
        self._subtitle("自定义模型")
        self._bullet(["点击底部蓝色虚线按钮「➕添加自定义模型」",
                      "输入：模型名称、API地址、API Key、模型列表（逗号分隔）、图标emoji",
                      "支持所有兼容OpenAI API格式的平台（ChatGPT/OpenRouter等）",
                      "自定义模型持久化保存到custom_providers.json，重启不丢失",
                      "与内置平台同等待遇：支持激活/配置/测试/切换"])
        self._subtitle("🎨 生图/生视频/语音模型怎么配？")
        self._text("生图/生视频/语音模型统一在模型广场卡片里配置（硅基流动、OpenAI、通义、豆包、ChatGPT2API 等）。"
                    "填好 API Key 并激活后，打开「AI 画布」点顶部「🔄 同步模型池」即可自动发现对应能力的模型，"
                    "在画布节点下拉框里就能选到。对话模型（DeepSeek/GPT 等）也在模型广场配置，两者不冲突。")
        self._tip("激活的模型将应用于所有AI功能：文案生成/字幕生成等")
        self._cl.addStretch()

    def _ai_canvas(self):
        self._clear(); self._title("🎨 AI画布")
        self._text("左侧导航「AI 画布」加载自研「拾光导演台」（LibTV 向节点画布，"
                    "vendor/shiguang-canvas）。生成结果经 bridge 送回时间线。")
        self._subtitle("首次使用前置条件")
        self._bullet(["需要 PyQt6-WebEngine：未安装时画布区域会显示红字错误，按提示"
                      "`.venv312\\Scripts\\python.exe -m pip install PyQt6-WebEngine==6.10.0` 装好后完全重启软件",
                      "自研导演台：`cd vendor/shiguang-canvas && npm install && npm run build`（有 dist 则秒开 :3011）",
                      "生图：导演台左侧选 AIGC 模型 →「生成选中节点」（走宿主代理）；无 Key/失败时用占位图仍可入轨"])
        self._subtitle("界面说明")
        self._bullet(["主区域：嵌入式画布，生图/生视频、拖拽排版",
                      "左侧「角色库」（可展开/收起）：新增角色、填写外貌/性格/台词等字段，持久化保存，供生成时挂载参考",
                      "右下角「拾光剪影」浮动面板：",
                      "　- 发送到剪辑：把画布上选中的生成结果推送到时间线（EventBus 回流，不是文件复制）",
                      "　- 同步模型：把模型广场里配置好的 Key 同步给画布内部调用",
                      "　- 连接 Agent：可选，拉起本地 17371 端口给外部 Agent/Codex 接入（`codex mcp add canvas-agent -- npx -y @basketikun/canvas-agent mcp`）",
                      "插帧选项是线性插值补帧，不是 RIFE 等神经网络补帧，追求丝滑请用剪辑模块里的专业补帧功能"])
        self._subtitle("外部云端画布备选（浏览器直达，非本软件内置）")
        self._text("若需要体验更完整的商业「导演台 / Agent 画布」，可打开下列官网试用；"
                    "生成结果请自行下载后，再回到本软件「剪辑」导入或「素材库」入库。"
                    "这些站点与本软件无关，需单独注册账号，费用与隐私政策以对方为准。")
        self._link_row("LibTV（liblib.tv）", "https://www.liblib.tv/", "导演台 / 画布生图生视频")
        self._link_row("TapNow", "https://tapnow.ai/", "Agentic Creative Canvas")
        self._tip("完整说明与链接亦见左侧「🌐 外部画布备选」；内置 AI 画布为自研拾光导演台，成片精剪请回「剪辑」模块。")
        self._cl.addStretch()

    def _canvas_alternatives(self):
        """LibTV / TapNow 等外部云端画布 — 浏览器直达备选，非内置。"""
        self._clear()
        self._title("🌐 外部画布备选")
        self._text("本软件内置的是自研拾光导演台（左侧「AI 画布」）。"
                    "若你想对照或临时使用商业云端「导演台 / Agent 画布」体验，可点下方按钮在系统浏览器中打开官网。"
                    "它们不是本软件的一部分，也不走本地 bridge 自动入轨。")
        self._subtitle("推荐备选（点击「打开」跳转浏览器）")
        self._link_row("LibTV", "https://www.liblib.tv/", "liblib.tv · 画布 / 导演台 / 生图生视频")
        self._link_row("LibTV 画布入口", "https://www.liblib.tv/canvas", "直接进画布页（需登录）")
        self._link_row("TapNow", "https://tapnow.ai/", "tapnow.ai · Agentic Creative Canvas")
        self._link_row("Infinite-Canvas（开源）", "https://github.com/basketikun/infinite-canvas", "内置 AI 画布上游 · 节点画布工作台")
        self._subtitle("怎么和本软件配合")
        self._bullet([
            "日常漫剧分镜：优先用软件内「AI 画布」→「发送到剪辑」入时间线",
            "需要 LibTV / TapNow 特有能力时：浏览器里生成 → 下载到本地 → 回到「剪辑」导入或素材库",
            "模型 Key：本软件「模型广场 / AIGC」只服务于内置画布与剪辑 Agent，不会自动同步到 LibTV/TapNow",
        ])
        self._tip("外链仅作备选体验；精剪、字幕、导出、发布请始终在拾光剪影内完成。")
        self._cl.addStretch()

    # ── 搜索功能 ──

    def _on_help_search(self, text: str):
        """搜索框文本变化时：在全量帮助文本中搜索关键词"""
        text = text.strip()
        if len(text) < 1:
            # 清空搜索 → 恢复导航按钮
            self._help_search_results.setVisible(False)
            self._help_search_results.clear()
            for btn in self._help_nav_buttons:
                btn.setVisible(True)
            return

        # 隐藏导航按钮，显示搜索结果
        for btn in self._help_nav_buttons:
            btn.setVisible(False)
        self._help_search_results.setVisible(True)
        self._help_search_results.clear()

        keyword = text.lower()
        # 遍历所有 topic，收集包含关键词的匹配项
        matches = []  # [(display_text, callback, score)]
        for icon, name, cb in self._help_topics:
            name_lower = name.lower()
            # 名称匹配
            if keyword in name_lower:
                matches.append((f"{icon} {name}", cb, 2))
                continue
            # 内容匹配：提取 topic 页面文本进行搜索
            content_text = self._get_topic_text(cb)
            if keyword in content_text.lower():
                # 找到关键词在内容中的位置，截取上下文
                idx = content_text.lower().find(keyword)
                start = max(0, idx - 20)
                end = min(len(content_text), idx + len(keyword) + 40)
                snippet = content_text[start:end].strip()
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content_text):
                    snippet = snippet + "..."
                matches.append((f"{icon} {name}  — {snippet}", cb, 1))

        # 按分数降序排列
        matches.sort(key=lambda x: -x[2])

        for display, cb, _ in matches[:20]:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, cb)
            self._help_search_results.addItem(item)

        if self._help_search_results.count() == 0:
            item = QListWidgetItem("（未找到匹配结果）")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._help_search_results.addItem(item)

    def _on_search_result_clicked(self, item: QListWidgetItem):
        """点击搜索结果 → 导航到对应 topic 并清空搜索"""
        cb = item.data(Qt.ItemDataRole.UserRole)
        if cb and callable(cb):
            cb()
            # 清空搜索状态
            self._help_search.clear()
            self._help_search_results.setVisible(False)
            self._help_search_results.clear()
            for btn in self._help_nav_buttons:
                btn.setVisible(True)

    def _get_topic_text(self, cb) -> str:
        """获取 topic 页面的纯文本内容（用于搜索索引）"""
        # 利用 _clear + 执行回调 → 收集 QLabel 文本 → 拼接
        # 注意：此方法会临时渲染页面，完成后恢复
        try:
            # 保存当前内容区域状态
            import copy
            self._clear()
            cb()
            texts = []
            for i in range(self._cl.count()):
                item = self._cl.itemAt(i)
                w = item.widget()
                if isinstance(w, QLabel) and w.text():
                    texts.append(w.text())
            return " ".join(texts)
        except Exception:
            return ""

    def _faq(self):
        self._clear()
        if self._load_markdown_topic("faq"):
            return
        self._title("❓ 常见问题")
        faqs = [
            ("如何添加ChatGPT等自定义模型？",
             "在「模型广场」底部点击「➕添加自定义模型」，输入名称（如ChatGPT）、API地址（https://api.openai.com/v1）、你的API Key、模型列表（gpt-4o,gpt-4o-mini），点击添加即可。支持所有兼容OpenAI格式的API。"),
            ("视频导出失败怎么办？",
             "1）检查输出目录是否有写入权限和足够磁盘空间；2）尝试降低输出分辨率或比特率；3）确认FFmpeg已正确安装；4）关闭其他占用GPU的程序。"),
            ("API配置后不生效？",
             "确认三点：1）模型已激活（状态栏显示绿色）；2）API Key填写正确无多余空格；3）网络环境可以访问目标API地址（可能需要代理）。"),
            ("插件安装后不显示？",
             "检查插件是否在「已安装插件」标签页中。如果在，确认状态为「已启用」（绿色）。如仍不显示，尝试重启应用。"),
            ("支持哪些视频格式？",
             "导入支持：MP4/AVI/MOV/MKV/WebM。导出支持：MP4/MKV/AVI/MOV（H.264/H.265/VP9/AV1编码）。音频支持：MP3/WAV/AAC/FLAC。"),
            ("如何提高大视频编辑流畅度？",
             "1）开启GPU硬件加速（设置→常规）；2）降低预览分辨率；3）关闭不必要的后台程序释放内存；4）使用SSD存放素材和缓存文件。"),
        ]
        for q, a in faqs:
            self._subtitle(f"Q: {q}")
            self._text(a)
        self._cl.addStretch()

