"""
转场系统 (Transition System)
=============================
对标 OpenShot 的 400+ 转场 (这里补齐 50+ 实用转场)

特性:
- 8 大类转场: 基础/擦除/滑动/缩放/旋转/卷曲/3D/光效
- 50+ 内置转场
- 可扩展注册自定义转场
- FFmpeg 渲染支持
"""
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("AI短剧编辑器.transitions")


class TransitionCategory(str, Enum):
    """转场类别"""
    BASIC = "基础"
    WIPE = "擦除"
    SLIDE = "滑动"
    ZOOM = "缩放"
    SPIN = "旋转"
    CURL = "卷曲"
    THREE_D = "3D"
    LIGHT = "光效"
    GLITCH = "故障"
    CINEMA = "电影"


@dataclass
class TransitionDef:
    """转场定义"""
    id: str
    name: str                # 中文名
    category: TransitionCategory
    ffmpeg_filter: str       # FFmpeg 滤镜表达式 (使用 {a} {b} {duration} 占位符)
    duration_default: float = 0.5
    description: str = ""
    params: List[str] = None  # 额外参数
    # 别名：本条目与另一个转场共用同一个 ffmpeg xfade 效果（无独立实现）。
    # 用于对「看起来是两个转场、实际渲染完全相同」如实标注，UI 可据此折叠展示。
    alias_of: Optional[str] = None


# ffmpeg xfade 支持的 transition= 名全集（本机 ffmpeg 8.x 实测，共 58 个）。
# 用途：新增转场时自检，防止写入拼错/臆造的滤镜名（渲染时才报错，排查成本高）。
# 注意 `custom` 需配合 expr 参数，不在此列。
KNOWN_XFADE_NAMES = frozenset({
    "fade", "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "circlecrop", "rectcrop", "distance", "fadeblack", "fadewhite", "radial",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circleopen", "circleclose", "vertopen", "vertclose",
    "horzopen", "horzclose", "dissolve", "pixelize",
    "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice", "hblur", "fadegrays",
    "wipetl", "wipetr", "wipebl", "wipebr", "squeezeh", "squeezev",
    "zoomin", "fadefast", "fadeslow",
    "hlwind", "hrwind", "vuwind", "vdwind",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
})


def _xfade_name_of(ffmpeg_filter: str) -> str:
    """从滤镜表达式里抽出 transition= 名（无则返回空串）。"""
    marker = "transition="
    idx = ffmpeg_filter.find(marker)
    if idx < 0:
        return ""
    rest = ffmpeg_filter[idx + len(marker):]
    return rest.split(":", 1)[0].strip()


# 50+ 转场定义
TRANSITIONS: Dict[str, TransitionDef] = {
    # ========== 基础 (Basic) ==========
    "fade": TransitionDef(
        id="fade", name="淡入淡出", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=fade:duration={duration}:offset={offset}",
        description="最常用的基础转场",
    ),
    "dissolve": TransitionDef(
        id="dissolve", name="溶解", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=dissolve:duration={duration}:offset={offset}",
    ),
    "fadeblack": TransitionDef(
        id="fadeblack", name="黑场过渡", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=fadeblack:duration={duration}:offset={offset}",
    ),
    "fadewhite": TransitionDef(
        id="fadewhite", name="白场过渡", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=fadewhite:duration={duration}:offset={offset}",
    ),
    "wipeleft": TransitionDef(
        id="wipeleft", name="向左擦除", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=wipeleft:duration={duration}:offset={offset}",
    ),
    "wiperight": TransitionDef(
        id="wiperight", name="向右擦除", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=wiperight:duration={duration}:offset={offset}",
    ),
    "wipeup": TransitionDef(
        id="wipeup", name="向上擦除", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=wipeup:duration={duration}:offset={offset}",
    ),
    "wipedown": TransitionDef(
        id="wipedown", name="向下擦除", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=wipedown:duration={duration}:offset={offset}",
    ),

    # ========== 擦除 (Wipe) ==========
    "wipe_tl": TransitionDef(
        id="wipe_tl", name="左上擦除", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=wipebl:duration={duration}:offset={offset}",
    ),
    "wipe_tr": TransitionDef(
        id="wipe_tr", name="右上擦除", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=wipebr:duration={duration}:offset={offset}",
    ),
    "wipe_bl": TransitionDef(
        id="wipe_bl", name="左下擦除", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=wipetl:duration={duration}:offset={offset}",
    ),
    "wipe_br": TransitionDef(
        id="wipe_br", name="右下擦除", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=wipetr:duration={duration}:offset={offset}",
    ),
    "diagtl": TransitionDef(
        id="diagtl", name="对角擦除 TL", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=diagtl:duration={duration}:offset={offset}",
    ),
    "diagtr": TransitionDef(
        id="diagtr", name="对角擦除 TR", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=diagtr:duration={duration}:offset={offset}",
    ),
    "diagbl": TransitionDef(
        id="diagbl", name="对角擦除 BL", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=diagbl:duration={duration}:offset={offset}",
    ),
    "diagbr": TransitionDef(
        id="diagbr", name="对角擦除 BR", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=diagbr:duration={duration}:offset={offset}",
    ),
    "hlslice": TransitionDef(
        id="hlslice", name="水平切片", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=hlslice:duration={duration}:offset={offset}",
    ),
    "hrslice": TransitionDef(
        id="hrslice", name="水平反向切片", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=hrslice:duration={duration}:offset={offset}",
    ),
    "vuslice": TransitionDef(
        id="vuslice", name="垂直切片", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=vuslice:duration={duration}:offset={offset}",
    ),
    "vdslice": TransitionDef(
        id="vdslice", name="垂直反向切片", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=vdslice:duration={duration}:offset={offset}",
    ),
    "hblur": TransitionDef(
        id="hblur", name="水平模糊擦除", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=hblur:duration={duration}:offset={offset}",
    ),
    "fadegrays": TransitionDef(
        id="fadegrays", name="灰度擦除", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=fadegrays:duration={duration}:offset={offset}",
    ),
    "wipetl": TransitionDef(
        id="wipetl", name="顶部擦除", category=TransitionCategory.WIPE,
        ffmpeg_filter="xfade=transition=wipetl:duration={duration}:offset={offset}",
    ),

    # ========== 滑动 (Slide) ==========
    "slideleft": TransitionDef(
        id="slideleft", name="左滑", category=TransitionCategory.SLIDE,
        ffmpeg_filter="xfade=transition=slideleft:duration={duration}:offset={offset}",
    ),
    "slideright": TransitionDef(
        id="slideright", name="右滑", category=TransitionCategory.SLIDE,
        ffmpeg_filter="xfade=transition=slideright:duration={duration}:offset={offset}",
    ),
    "slideup": TransitionDef(
        id="slideup", name="上滑", category=TransitionCategory.SLIDE,
        ffmpeg_filter="xfade=transition=slideup:duration={duration}:offset={offset}",
    ),
    "slidedown": TransitionDef(
        id="slidedown", name="下滑", category=TransitionCategory.SLIDE,
        ffmpeg_filter="xfade=transition=slidedown:duration={duration}:offset={offset}",
    ),
    # 修正（2026-10-11）：ffmpeg xfade 无 slide*_push 变体（原写死名渲染必报错），
    # 已改映射到 slideleft / slideright 并标 alias_of（推进与滑动在 xfade 上无独立实现）。
    "slideleft_push": TransitionDef(
        id="slideleft_push", name="左推", category=TransitionCategory.SLIDE,
        ffmpeg_filter="xfade=transition=slideleft:duration={duration}:offset={offset}",
        description="左向推进（ffmpeg 无 push 变体，复用 slideleft）",
        alias_of="slideleft",
    ),
    "slideright_push": TransitionDef(
        id="slideright_push", name="右推", category=TransitionCategory.SLIDE,
        ffmpeg_filter="xfade=transition=slideright:duration={duration}:offset={offset}",
        description="右向推进（ffmpeg 无 push 变体，复用 slideright）",
        alias_of="slideright",
    ),

    # ========== 缩放 (Zoom) ==========
    "zoomin": TransitionDef(
        id="zoomin", name="放大进入", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=zoomin:duration={duration}:offset={offset}",
    ),
    "fadefast": TransitionDef(
        id="fadefast", name="快速淡入", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=fadefast:duration={duration}:offset={offset}",
    ),
    "fadeslow": TransitionDef(
        id="fadeslow", name="慢速淡入", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=fadeslow:duration={duration}:offset={offset}",
    ),
    "smoothleft": TransitionDef(
        id="smoothleft", name="平滑左移", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=smoothleft:duration={duration}:offset={offset}",
    ),
    "smoothright": TransitionDef(
        id="smoothright", name="平滑右移", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=smoothright:duration={duration}:offset={offset}",
    ),
    "smoothup": TransitionDef(
        id="smoothup", name="平滑上移", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=smoothup:duration={duration}:offset={offset}",
    ),
    "smoothdown": TransitionDef(
        id="smoothdown", name="平滑下移", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=smoothdown:duration={duration}:offset={offset}",
    ),
    "circleopen": TransitionDef(
        id="circleopen", name="圆形展开", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=circleopen:duration={duration}:offset={offset}",
    ),
    "circleclose": TransitionDef(
        id="circleclose", name="圆形闭合", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=circleclose:duration={duration}:offset={offset}",
    ),
    "horzopen": TransitionDef(
        id="horzopen", name="水平展开", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=horzopen:duration={duration}:offset={offset}",
    ),
    "horzclose": TransitionDef(
        id="horzclose", name="水平闭合", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=horzclose:duration={duration}:offset={offset}",
    ),
    "vertopen": TransitionDef(
        id="vertopen", name="垂直展开", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=vertopen:duration={duration}:offset={offset}",
    ),
    "vertclose": TransitionDef(
        id="vertclose", name="垂直闭合", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=vertclose:duration={duration}:offset={offset}",
    ),

    # ========== 旋转 (Spin) ==========
    "hlwind": TransitionDef(
        id="hlwind", name="百叶窗", category=TransitionCategory.SPIN,
        ffmpeg_filter="xfade=transition=hlwind:duration={duration}:offset={offset}",
    ),
    "hrwind": TransitionDef(
        id="hrwind", name="反向百叶窗", category=TransitionCategory.SPIN,
        ffmpeg_filter="xfade=transition=hrwind:duration={duration}:offset={offset}",
    ),
    "vuwind": TransitionDef(
        id="vuwind", name="垂直百叶窗", category=TransitionCategory.SPIN,
        ffmpeg_filter="xfade=transition=vuwind:duration={duration}:offset={offset}",
    ),
    "vdwind": TransitionDef(
        id="vdwind", name="反向垂直百叶窗", category=TransitionCategory.SPIN,
        ffmpeg_filter="xfade=transition=vdwind:duration={duration}:offset={offset}",
    ),

    # ========== 3D 转场 ==========
    "coverleft": TransitionDef(
        id="coverleft", name="左翻页", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=coverleft:duration={duration}:offset={offset}",
    ),
    "coverright": TransitionDef(
        id="coverright", name="右翻页", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=coverright:duration={duration}:offset={offset}",
    ),
    "coverup": TransitionDef(
        id="coverup", name="上翻页", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=coverup:duration={duration}:offset={offset}",
    ),
    "coverdown": TransitionDef(
        id="coverdown", name="下翻页", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=coverdown:duration={duration}:offset={offset}",
    ),
    "revealleft": TransitionDef(
        id="revealleft", name="左揭开", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=revealleft:duration={duration}:offset={offset}",
    ),
    "revealright": TransitionDef(
        id="revealright", name="右揭开", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=revealright:duration={duration}:offset={offset}",
    ),

    # ========== 光效 (Light) ==========
    "pixelize": TransitionDef(
        id="pixelize", name="像素化", category=TransitionCategory.LIGHT,
        ffmpeg_filter="xfade=transition=pixelize:duration={duration}:offset={offset}",
    ),
    "radial": TransitionDef(
        id="radial", name="径向擦除", category=TransitionCategory.LIGHT,
        ffmpeg_filter="xfade=transition=radial:duration={duration}:offset={offset}",
    ),
    # 修正（2026-10-11）：原 transition=hlreplace 非 ffmpeg xfade 支持名（渲染必报错），
    # 已改映射到语义最近的 fadegrays（经灰度过渡），并标 alias_of 如实说明无独立实现。
    "hlreplace": TransitionDef(
        id="hlreplace", name="亮度替换", category=TransitionCategory.LIGHT,
        ffmpeg_filter="xfade=transition=fadegrays:duration={duration}:offset={offset}",
        description="经灰度的亮度过渡（ffmpeg 无 luma 专用 xfade，复用 fadegrays）",
        alias_of="fadegrays",
    ),

    # ========== 故障 (Glitch) ==========
    # 如实标注：ffmpeg 无 glitch xfade，本项复用 pixelize（alias_of），
    # 真实「RGB 错位/块位移」由 transition_plugin_registry 的 bake 路径承担。
    "glitch": TransitionDef(
        id="glitch", name="故障效果", category=TransitionCategory.GLITCH,
        ffmpeg_filter="xfade=transition=pixelize:duration={duration}:offset={offset}",
        description="模拟信号故障（xfade 复用 pixelize，精确效果走插件烘焙）",
        alias_of="pixelize",
    ),

    # ========== 电影 (Cinema) ==========
    "iris_in": TransitionDef(
        id="iris_in", name="光圈进入", category=TransitionCategory.CINEMA,
        ffmpeg_filter="xfade=transition=circleopen:duration={duration}:offset={offset}",
        description="经典老电影风格",
        alias_of="circleopen",
    ),
    "iris_out": TransitionDef(
        id="iris_out", name="光圈退出", category=TransitionCategory.CINEMA,
        ffmpeg_filter="xfade=transition=circleclose:duration={duration}:offset={offset}",
        alias_of="circleclose",
    ),
    "wipe_circle": TransitionDef(
        id="wipe_circle", name="圆形擦除", category=TransitionCategory.CINEMA,
        ffmpeg_filter="xfade=transition=radial:duration={duration}:offset={offset}",
        alias_of="radial",
    ),

    # ========== 补齐（2026-10-11）：ffmpeg 支持但原表缺失的 7 个真转场 ==========
    "circlecrop": TransitionDef(
        id="circlecrop", name="圆形裁剪", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=circlecrop:duration={duration}:offset={offset}",
        description="以圆形窗口裁剪过渡",
    ),
    "rectcrop": TransitionDef(
        id="rectcrop", name="矩形裁剪", category=TransitionCategory.ZOOM,
        ffmpeg_filter="xfade=transition=rectcrop:duration={duration}:offset={offset}",
        description="以矩形窗口裁剪过渡",
    ),
    "distance": TransitionDef(
        id="distance", name="距离过渡", category=TransitionCategory.BASIC,
        ffmpeg_filter="xfade=transition=distance:duration={duration}:offset={offset}",
        description="基于距离场的过渡（形状先在远处溶解）",
    ),
    "revealup": TransitionDef(
        id="revealup", name="上揭开", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=revealup:duration={duration}:offset={offset}",
    ),
    "revealdown": TransitionDef(
        id="revealdown", name="下揭开", category=TransitionCategory.THREE_D,
        ffmpeg_filter="xfade=transition=revealdown:duration={duration}:offset={offset}",
    ),
    "squeezeh": TransitionDef(
        id="squeezeh", name="水平挤压", category=TransitionCategory.SPIN,
        ffmpeg_filter="xfade=transition=squeezeh:duration={duration}:offset={offset}",
        description="画面横向挤压收束",
    ),
    "squeezev": TransitionDef(
        id="squeezev", name="垂直挤压", category=TransitionCategory.SPIN,
        ffmpeg_filter="xfade=transition=squeezev:duration={duration}:offset={offset}",
        description="画面纵向挤压收束",
    ),
}


def get_all_transitions() -> List[TransitionDef]:
    """获取全部转场"""
    return list(TRANSITIONS.values())


def get_transitions_by_category(category: TransitionCategory) -> List[TransitionDef]:
    """按类别获取转场"""
    return [t for t in TRANSITIONS.values() if t.category == category]


def get_categories() -> List[Tuple[str, int]]:
    """获取所有类别及转场数量"""
    cats = {}
    for t in TRANSITIONS.values():
        cats[t.category.value] = cats.get(t.category.value, 0) + 1
    return sorted(cats.items(), key=lambda x: -x[1])


def get_transition(trans_id: str) -> Optional[TransitionDef]:
    """获取转场定义"""
    return TRANSITIONS.get(trans_id)


def build_transition_filter(trans_id: str, duration: float, offset: float) -> str:
    """
    构建转场 FFmpeg 滤镜表达式

    Args:
        trans_id: 转场 ID
        duration: 转场时长(秒)
        offset: 第一个片段的结束时间(秒)
    """
    td = get_transition(trans_id)
    if not td:
        return f"xfade=transition=fade:duration={duration}:offset={offset}"
    return td.ffmpeg_filter.format(duration=duration, offset=offset)


def get_unique_transitions() -> List[TransitionDef]:
    """获取「有独立实现」的转场（剔除 alias_of 别名/复用项）。

    UI 展示、能力计数应优先用它，避免把「左推/左滑」「故障/像素化」这类
    xfade 完全相同、仅命名不同的条目当成两个转场。
    """
    return [t for t in TRANSITIONS.values() if not t.alias_of]


def get_aliases() -> Dict[str, str]:
    """别名映射 {别名 id: 复用的真实转场 id}。"""
    return {t.id: t.alias_of for t in TRANSITIONS.values() if t.alias_of}


def validate_transition_names() -> List[str]:
    """自检：返回引用了非 ffmpeg xfade 支持名的转场 id 列表（空 = 全部合法）。

    新增转场时调用；防止再次写入 hlreplace / slideleft_push 这类渲染必报错的臆造名。
    """
    bad: List[str] = []
    for t in TRANSITIONS.values():
        name = _xfade_name_of(t.ffmpeg_filter)
        if name and name not in KNOWN_XFADE_NAMES:
            bad.append(t.id)
    return bad


# 注册自定义转场
def register_transition(trans_def: TransitionDef):
    """注册自定义转场"""
    name = _xfade_name_of(trans_def.ffmpeg_filter)
    if name and name not in KNOWN_XFADE_NAMES:
        logger.warning(
            "转场 %s 引用未知 xfade 名 %r —— ffmpeg 渲染时会报错", trans_def.id, name
        )
    TRANSITIONS[trans_def.id] = trans_def
    logger.info(f"注册自定义转场: {trans_def.id}")


# 统计
TRANSITION_COUNT = len(TRANSITIONS)
TRANSITION_UNIQUE_COUNT = len(get_unique_transitions())
