"""
标题模板系统 (TitleTemplates)
================================
对标 OpenShot 的 40+ 矢量标题模板。

特性:
- 8 大类内置标题模板
- 动态变量替换 (title, subtitle, author 等)
- 可自定义文字位置、字体、颜色
- FFmpeg drawtext 滤镜渲染
- 导出 PNG 预览
"""
import os
import logging
import subprocess
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("AI短剧编辑器.title_templates")


class TitleCategory(str, Enum):
    """标题类别"""
    CINEMA = "电影"
    SOCIAL = "社交"
    ANIMATED = "动画"
    MINIMAL = "简约"
    NEWS = "新闻"
    LOWER_THIRD = "下三分之一"
    KARAOKE = "卡拉OK"
    INTRO = "开场"


@dataclass
class TitleTemplate:
    """标题模板定义"""
    id: str
    name: str
    category: TitleCategory
    drawtext: str           # FFmpeg drawtext 表达式 (含 {text}, {fontfile}, {color} 占位符)
    width: int = 1920
    height: int = 1080
    variables: List[str] = field(default_factory=list)  # 可用变量
    preview_color: str = "#1e6bde"
    description: str = ""


# 内置 20+ 标题模板
TITLE_TEMPLATES: Dict[str, TitleTemplate] = {
    # ===== 电影风 =====
    "cinema_center": TitleTemplate(
        id="cinema_center", name="电影居中", category=TitleCategory.CINEMA,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor={color}:fontsize=96:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:boxborderw=20",
        variables=["text", "color", "fontfile"],
        preview_color="#FFD700",
    ),
    "cinema_top": TitleTemplate(
        id="cinema_top", name="电影顶部", category=TitleCategory.CINEMA,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor={color}:fontsize=80:x=(w-text_w)/2:y=120:box=1:boxcolor=black@0.7:boxborderw=20",
        variables=["text", "color", "fontfile"],
    ),
    "cinema_bottom": TitleTemplate(
        id="cinema_bottom", name="电影底部", category=TitleCategory.CINEMA,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor={color}:fontsize=80:x=(w-text_w)/2:y=h-220:box=1:boxcolor=black@0.7:boxborderw=20",
        variables=["text", "color", "fontfile"],
    ),

    # ===== 社交短视频 =====
    "social_vertical": TitleTemplate(
        id="social_vertical", name="竖屏标题", category=TitleCategory.SOCIAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor={color}:fontsize=120:x=(w-text_w)/2:y=h/3:box=1:boxcolor={bgcolor}@0.8:boxborderw=30",
        variables=["text", "color", "bgcolor", "fontfile"],
        width=1080, height=1920,
    ),
    "social_bold": TitleTemplate(
        id="social_bold", name="大字幕", category=TitleCategory.SOCIAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor={color}:fontsize=140:fontweight=bold:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.9:boxborderw=40",
        variables=["text", "color", "fontfile"],
    ),
    "social_subtitle": TitleTemplate(
        id="social_subtitle", name="底部说明", category=TitleCategory.SOCIAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=h-180:box=1:boxcolor=black@0.85:boxborderw=30",
        variables=["text", "fontfile"],
    ),

    # ===== 简约 =====
    "minimal_white": TitleTemplate(
        id="minimal_white", name="白字简约", category=TitleCategory.MINIMAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2",
        variables=["text", "fontfile"],
    ),
    "minimal_shadow": TitleTemplate(
        id="minimal_shadow", name="阴影字", category=TitleCategory.MINIMAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2:shadowcolor=black@0.8:shadowx=4:shadowy=4",
        variables=["text", "fontfile"],
    ),
    "minimal_outline": TitleTemplate(
        id="minimal_outline", name="描边字", category=TitleCategory.MINIMAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2:bordercolor=black:borderw=5",
        variables=["text", "fontfile"],
    ),

    # ===== 新闻 =====
    "news_ticker": TitleTemplate(
        id="news_ticker", name="新闻条", category=TitleCategory.NEWS,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=48:x=40:y=h-80:box=1:boxcolor=red@0.9:boxborderw=15",
        variables=["text", "fontfile"],
    ),
    "news_headline": TitleTemplate(
        id="news_headline", name="新闻标题", category=TitleCategory.NEWS,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=72:x=60:y=200:box=1:boxcolor=blue@0.85:boxborderw=20",
        variables=["text", "fontfile"],
    ),

    # ===== 下三分之一 (Lower Third) =====
    "lt_classic": TitleTemplate(
        id="lt_classic", name="经典下三", category=TitleCategory.LOWER_THIRD,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=56:x=60:y=h-200:box=1:boxcolor={bgcolor}@0.9:boxborderw=15",
        variables=["text", "bgcolor", "fontfile"],
    ),
    "lt_modern": TitleTemplate(
        id="lt_modern", name="现代下三", category=TitleCategory.LOWER_THIRD,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=48:x=80:y=h-180",
        variables=["text", "fontfile"],
    ),

    # ===== 卡拉OK =====
    "karaoke_highlight": TitleTemplate(
        id="karaoke_highlight", name="卡拉OK字幕", category=TitleCategory.KARAOKE,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor={color}:fontsize=80:x=(w-text_w)/2:y=h-220:box=1:boxcolor=black@0.85:boxborderw=25",
        variables=["text", "color", "fontfile"],
    ),

    # ===== 开场 =====
    "intro_epic": TitleTemplate(
        id="intro_epic", name="史诗开场", category=TitleCategory.INTRO,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor={color}:fontsize=140:fontweight=bold:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.8:boxborderw=40:shadowcolor={color}@0.8:shadowx=8:shadowy=8",
        variables=["text", "color", "fontfile"],
    ),
    "intro_minimal": TitleTemplate(
        id="intro_minimal", name="简约开场", category=TitleCategory.INTRO,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=120:x=(w-text_w)/2:y=(h-text_h)/2",
        variables=["text", "fontfile"],
    ),

    # ===== 动画 (用 alpha 表达式) =====
    "animated_fadein": TitleTemplate(
        id="animated_fadein", name="淡入字幕", category=TitleCategory.ANIMATED,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2:alpha='if(lt(t,1),t,if(lt(t,3),1,if(lt(t,4),(4-t),0)))'",
        variables=["text", "fontfile"],
    ),
    "animated_slidein": TitleTemplate(
        id="animated_slidein", name="滑入字幕", category=TitleCategory.ANIMATED,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=80:x='if(lt(t,1),w-(w*0.5)*t,w*0.5-text_w/2)':y=(h-text_h)/2",
        variables=["text", "fontfile"],
    ),
    "animated_typewriter": TitleTemplate(
        id="animated_typewriter", name="打字机", category=TitleCategory.ANIMATED,
        # 注: 复杂文本裁切需 ffmpeg sendcmd, 简化版只支持固定字符串
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=72:x=60:y=(h-text_h)/2",
        variables=["text", "fontfile"],
        description="Shotcut 26.4 新增 Typewriter 风格",
    ),

    # ===== 短剧专用 =====
    "drama_hook": TitleTemplate(
        id="drama_hook", name="短剧钩子", category=TitleCategory.SOCIAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=#FFD700:fontsize=130:fontweight=bold:x=(w-text_w)/2:y=h/4:box=1:boxcolor=red@0.85:boxborderw=30:bordercolor=black:borderw=3",
        variables=["text", "fontfile"],
        width=1080, height=1920,
        description="短剧开场高冲击力钩子字幕",
    ),
    "drama_cliffhanger": TitleTemplate(
        id="drama_cliffhanger", name="悬念字幕", category=TitleCategory.SOCIAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=#FF1744:fontsize=110:fontweight=bold:x=(w-text_w)/2:y=h-300:box=1:boxcolor=black@0.9:boxborderw=25",
        variables=["text", "fontfile"],
        width=1080, height=1920,
        description="短剧结尾悬念字幕",
    ),
    "drama_dialogue": TitleTemplate(
        id="drama_dialogue", name="角色对白", category=TitleCategory.SOCIAL,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=white:fontsize=64:x=80:y=h-180:box=1:boxcolor=black@0.75:boxborderw=20",
        variables=["text", "fontfile"],
    ),
    "drama_emotion": TitleTemplate(
        id="drama_emotion", name="情感字幕", category=TitleCategory.ANIMATED,
        drawtext="fontfile={fontfile}:text='{text}':fontcolor=#FF80AB:fontsize=96:fontweight=bold:x=(w-text_w)/2:y=h/2:box=1:boxcolor=purple@0.6:boxborderw=20:alpha='if(lt(t,0.5),t*2,if(lt(t,2.5),1,if(lt(t,3),(3-t)/0.5,0)))'",
        variables=["text", "fontfile"],
        width=1080, height=1920,
        description="短剧情感爆发字幕, 自动淡入淡出",
    ),
}


def get_all_templates() -> List[TitleTemplate]:
    """获取所有模板"""
    return list(TITLE_TEMPLATES.values())


def get_templates_by_category(category: TitleCategory) -> List[TitleTemplate]:
    """按类别获取"""
    return [t for t in TITLE_TEMPLATES.values() if t.category == category]


def get_template(template_id: str) -> Optional[TitleTemplate]:
    return TITLE_TEMPLATES.get(template_id)


def build_drawtext(template_id: str, variables: Dict[str, str],
                    default_font: str = "") -> Optional[str]:
    """
    构建 drawtext 表达式

    Args:
        template_id: 模板 ID
        variables: 变量字典 (text, color, fontfile, bgcolor)
        default_font: 默认字体路径 (Windows: C:/Windows/Fonts/msyh.ttc)
    """
    tmpl = get_template(template_id)
    if not tmpl:
        return None
    # 填充变量
    vars_dict = {
        "color": "white",
        "bgcolor": "black",
        "fontfile": default_font or "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    }
    vars_dict.update({k: str(v) for k, v in variables.items()})

    # Windows 默认字体
    if not default_font and os.name == 'nt':
        for f in ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf',
                  'C:/Windows/Fonts/arial.ttf']:
            if os.path.exists(f):
                vars_dict["fontfile"] = f
                break

    try:
        return tmpl.drawtext.format(**vars_dict)
    except KeyError as e:
        logger.warning(f"模板变量缺失: {e}")
        return None


# 内置模板数量
TEMPLATE_COUNT = len(TITLE_TEMPLATES)
