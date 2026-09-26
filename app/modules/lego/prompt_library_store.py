"""
素材库 · 提示词库数据层
========================
复用画布同源 GitHub JSON + 本地包；细分类 / 成熟度 / 收藏持久化。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.prompt_library")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_PROMPTS_DIR = _REPO_ROOT / "vendor" / "shiguang-canvas" / "public" / "prompts"
_BUNDLED_DIR = _LOCAL_PROMPTS_DIR / "bundled"
_FAV_PATH = _REPO_ROOT / "app" / "data" / "prompt_favorites.json"
_CACHE_DIR = _REPO_ROOT / "app" / "data" / "prompt_cache"
_CACHE_TTL_S = 60 * 60

YUKKCAT_BASE = "https://raw.githubusercontent.com/yukkcat/image-prompts/main/dist/sources"

MINOR_HARD = re.compile(
    r"(?i)\b(loli|shota|lolita|underage|minor|child|children|kid|kids|toddler|infant|baby|schoolgirl|schoolboy)\b"
    r"|萝莉|正太|幼女|儿童|小孩|未成年|小学生|初中生|幼化|稚嫩脸|儿化"
)
MINOR_SOFT = re.compile(r"少女|少年|高中生|中学生|JK制服|学生妹|女高中生|男高中生")
NSFW_HINT = re.compile(
    r"(?i)\b(nsfw|nude|naked|explicit|porn|sex|erotic|lingerie|bikini|breast|nipple)\b"
    r"|裸|半裸|性感|内衣|蕾丝|亲密|床戏|性爱|成人|18\+|露出"
)
MATURE_HINT = re.compile(
    r"(?i)\b(sensual|glamour|seductive|cleavage|swimsuit|bodysuit)\b"
    r"|暧昧|魅力|晚礼服|深V|吊带|泳装|身材|低胸"
)

CATEGORY_GROUPS = [
    "摄影写实",
    "人像角色",
    "设计商业",
    "插画二次元",
    "短剧分镜",
    "成熟向",
    "成人向 18+",
    "其他",
]

# id -> (label, group, maturity, aliases)
_TAXONOMY: List[Tuple[str, str, str, str, List[str]]] = [
    ("photo-realism", "摄影·照片级写实", "摄影写实", "sfw", ["摄影与照片级写实", "photo", "photography", "写实"]),
    ("lifestyle", "生活日常", "摄影写实", "sfw", ["生活", "lifestyle", "daily", "street"]),
    ("food", "美食静物", "摄影写实", "sfw", ["food", "美食"]),
    ("architecture", "建筑空间", "摄影写实", "sfw", ["architecture", "建筑", "interior", "real-estate"]),
    ("product", "产品静物", "摄影写实", "sfw", ["product", "产品"]),
    ("portrait", "人像肖像", "人像角色", "sfw", ["portrait", "人像", "avatar", "头像"]),
    ("character", "角色设定", "人像角色", "sfw", ["character", "角色", "oc"]),
    ("fashion", "时尚穿搭", "人像角色", "sfw", ["fashion", "时尚", "穿搭"]),
    ("cosplay", "Cosplay", "人像角色", "sfw", ["cosplay", "coser"]),
    ("ui-ux", "UI / UX / 社交媒资", "设计商业", "sfw", ["ui / ux 与社交媒体", "ui", "ux", "webdesign", "社交媒体"]),
    ("poster", "海报主视觉", "设计商业", "sfw", ["poster", "海报", "主视觉", "kv"]),
    ("ecommerce", "电商主图", "设计商业", "sfw", ["ecommerce", "电商", "主图"]),
    ("infographic", "信息图 / 文档", "设计商业", "sfw", ["infographic", "信息图", "信息图与演示文档"]),
    ("typography", "排版与海报字", "设计商业", "sfw", ["创意排版与海报文字", "typography", "排版"]),
    ("social", "社交媒体图", "设计商业", "sfw", ["social", "小红书", "instagram"]),
    ("thumbnail", "缩略图 / 封面", "设计商业", "sfw", ["thumbnail", "缩略图", "封面", "youtube"]),
    ("design", "平面设计综合", "设计商业", "sfw", ["design", "设计", "creative", "创意"]),
    ("work", "工作办公", "设计商业", "sfw", ["工作", "office"]),
    ("learn", "学习教育", "设计商业", "sfw", ["学习", "education"]),
    ("illustration", "插画", "插画二次元", "sfw", ["illustration", "插画", "绘本"]),
    ("anime", "二次元 / 动漫", "插画二次元", "sfw", ["anime", "二次元", "动漫", "manga", "漫画"]),
    ("game-3d", "游戏 / 3D", "插画二次元", "sfw", ["游戏与3d", "game", "3d", "toy"]),
    ("comic", "分格漫画", "插画二次元", "sfw", ["comic", "漫画分格", "四格"]),
    ("fun", "趣味梗图", "插画二次元", "sfw", ["有趣", "meme", "趣味", "梗图"]),
    ("storyboard", "短剧分镜", "短剧分镜", "sfw", ["storyboard", "分镜", "短剧", "镜头", "cinematic"]),
    ("video-edit", "视频编辑拼贴", "短剧分镜", "sfw", ["视频编辑与拼贴", "video", "montage"]),
    ("style-transfer", "风格迁移 / 图编辑", "短剧分镜", "sfw", ["图像编辑与风格迁移", "style-transfer", "img2img"]),
    ("consistency", "角色一致性", "短剧分镜", "sfw", ["角色一致性", "consistency"]),
    ("mature-glamour", "成熟魅力写真", "成熟向", "mature", ["glamour", "魅力", "成熟写真", "性感时尚"]),
    ("mature-lingerie", "内衣 / 泳装", "成熟向", "mature", ["lingerie", "内衣", "泳装", "bikini", "swimsuit", "蕾丝"]),
    ("mature-body", "身材 / 运动塑形", "成熟向", "mature", ["fitness", "身材", "塑形", "运动内衣"]),
    ("mature-atmosphere", "暧昧氛围", "成熟向", "mature", ["暧昧", "氛围感", "晚礼服"]),
    ("nsfw-artistic-nude", "艺术人体 / 半裸", "成人向 18+", "nsfw", ["artistic nude", "艺术人体", "半裸", "nude art"]),
    ("nsfw-intimate", "亲密场景", "成人向 18+", "nsfw", ["intimate", "亲密", "双人亲密", "bedroom"]),
    ("nsfw-explicit", "露骨成人", "成人向 18+", "nsfw", ["nsfw", "explicit", "成人", "18+", "色情"]),
    ("nsfw-fetish-light", "轻向癖好 / 道具氛围", "成人向 18+", "nsfw", ["fetish", "束缚", "乳胶", "道具氛围"]),
    ("nsfw-cosplay", "成人 Cos / 角色", "成人向 18+", "nsfw", ["nsfw cosplay", "成人cos", "性感cos"]),
    ("other", "未归类", "其他", "sfw", ["other", "未分类", "misc", "unknown", "gpt-image-2", "gpt4o", "nano-banana-pro"]),
]

_ALIAS_INDEX: Dict[str, Tuple[str, str, str, str]] = {}
for _id, _label, _group, _mat, _aliases in _TAXONOMY:
    _ALIAS_INDEX[_id.lower()] = (_id, _label, _group, _mat)
    _ALIAS_INDEX[_label.lower()] = (_id, _label, _group, _mat)
    for a in _aliases:
        _ALIAS_INDEX[a.lower()] = (_id, _label, _group, _mat)


@dataclass
class PromptSource:
    id: str
    name: str
    url: str
    homepage: str
    enabled: bool = True
    adult: bool = False
    local: bool = False


@dataclass
class PromptItem:
    id: str
    title: str
    prompt: str
    description: str = ""
    cover_url: str = ""
    tags: List[str] = field(default_factory=list)
    source_id: str = ""
    source_name: str = ""
    category_id: str = "other"
    category: str = "未归类"
    category_group: str = "其他"
    maturity: str = "sfw"
    github_url: str = ""
    favorite: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def default_sources() -> List[PromptSource]:
    regs = [
        ("banana-prompt-quicker", "Banana Prompt Quicker", "https://glidea.github.io/banana-prompt-quicker/"),
        ("davidwu-gpt-image2-prompts", "DavidWu GPT Image 2", "https://github.com/davidwuw0811-boop/awesome-gpt-image2-prompts"),
        ("freestylefly-gpt-image-2", "Freestylefly GPT Image 2", "https://github.com/freestylefly/awesome-gpt-image-2"),
        ("awesome-gpt-image", "Awesome GPT Image", "https://github.com/ZeroLu/awesome-gpt-image"),
        ("awesome-gpt4o-image-prompts", "Awesome GPT-4o", "https://github.com/ImgEdify/Awesome-GPT4o-Image-Prompts"),
        ("youmind-gpt-image-2", "YouMind GPT Image 2", "https://github.com/YouMind-OpenLab/awesome-gpt-image-2"),
        ("youmind-nano-banana-pro", "YouMind Nano Banana Pro", "https://github.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts"),
        ("stimqq-gpt-image-2", "StimQQ GPT Image 2", "https://github.com/stimQQ/gpt-image-2-prompts"),
        ("nexra-ai-image-prompts", "NeXra AI Image Prompts", "https://github.com/NeXra-AI/awesome-ai-image-prompts"),
    ]
    out: List[PromptSource] = []
    for sid, name, home in regs:
        bundled = _BUNDLED_DIR / f"{sid}.json"
        if bundled.is_file():
            out.append(PromptSource(sid, name, bundled.as_uri(), home, enabled=True, local=True))
        else:
            out.append(PromptSource(sid, name, f"{YUKKCAT_BASE}/{sid}.json", home, enabled=True))
    drama = _LOCAL_PROMPTS_DIR / "shiguang-drama.json"
    curated = _LOCAL_PROMPTS_DIR / "shiguang-curated.json"
    adult = _LOCAL_PROMPTS_DIR / "shiguang-adult-18plus.json"
    out.append(
        PromptSource(
            "shiguang-curated",
            "拾光·精选离线包",
            curated.as_uri() if curated.exists() else str(curated),
            "local://shiguang-curated",
            enabled=True,
            local=True,
        )
    )
    out.append(
        PromptSource(
            "shiguang-drama-pack",
            "拾光·短剧分镜包",
            drama.as_uri() if drama.exists() else str(drama),
            "local://shiguang-drama",
            enabled=True,
            local=True,
        )
    )
    out.append(
        PromptSource(
            "shiguang-adult-18plus",
            "拾光·成人向 18+",
            adult.as_uri() if adult.exists() else str(adult),
            "local://shiguang-adult",
            enabled=False,
            adult=True,
            local=True,
        )
    )
    return out


def categories_grouped() -> List[Tuple[str, List[Tuple[str, str, str]]]]:
    """[(group, [(id, label, maturity), ...]), ...]"""
    by_group: Dict[str, List[Tuple[str, str, str]]] = {g: [] for g in CATEGORY_GROUPS}
    for cid, label, group, mat, _ in _TAXONOMY:
        by_group.setdefault(group, []).append((cid, label, mat))
    return [(g, by_group[g]) for g in CATEGORY_GROUPS if by_group.get(g)]


def maturity_label(m: str) -> str:
    return {"nsfw": "18+", "mature": "成熟", "sfw": "全龄"}.get(m, m)


def _resolve_category(raw: str, tags: List[str], title: str, prompt: str) -> Tuple[str, str, str, str]:
    for c in [raw, *tags]:
        hit = _ALIAS_INDEX.get(str(c or "").strip().lower())
        if hit and hit[0] != "other":
            return hit
    blob = f"{title} {prompt} {raw} {' '.join(tags)}"
    if NSFW_HINT.search(blob):
        if re.search(r"亲密|双人|bedroom|intimate", blob, re.I):
            return _ALIAS_INDEX["亲密场景"]
        if re.search(r"内衣|lingerie|蕾丝|泳装|bikini", blob, re.I):
            return _ALIAS_INDEX["内衣 / 泳装"]
        if re.search(r"裸|nude|半裸", blob, re.I):
            return _ALIAS_INDEX["艺术人体 / 半裸"]
        return _ALIAS_INDEX["nsfw"]
    if MATURE_HINT.search(blob):
        return _ALIAS_INDEX["mature-glamour"]
    return _ALIAS_INDEX["other"]


def _resolve_maturity(cat_mat: str, tags: List[str], text: str) -> str:
    if cat_mat == "nsfw":
        return "nsfw"
    if any(re.search(r"nsfw|18\+|成人|explicit", t, re.I) for t in tags):
        return "nsfw"
    if NSFW_HINT.search(text):
        return "nsfw"
    if cat_mat == "mature" or MATURE_HINT.search(text):
        return "mature"
    return "sfw"


def _is_minor_unsafe(text: str, maturity: str) -> bool:
    if MINOR_HARD.search(text or ""):
        return True
    if maturity in ("nsfw", "mature") and MINOR_SOFT.search(text or ""):
        return True
    return False


def _pick_str(*vals: Any) -> str:
    for v in vals:
        s = str(v or "").strip()
        if s:
            return s
    return ""


def _pick_tags(rec: Dict[str, Any]) -> List[str]:
    raw = rec.get("tags") or rec.get("seo_keywords")
    if isinstance(raw, list):
        return [str(t) for t in raw if t]
    if isinstance(raw, dict):
        out: List[str] = []
        for k in ("zh", "en"):
            v = raw.get(k)
            if isinstance(v, list):
                out.extend(str(x) for x in v if x)
        return out
    return []


def _as_rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "prompts", "data", "list"):
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    raise ValueError("根节点不是数组")


def normalize_items(data: Any, source: PromptSource) -> List[PromptItem]:
    rows = _as_rows(data)
    seen = set()
    items: List[PromptItem] = []
    for i, rec in enumerate(rows):
        title = _pick_str(rec.get("title"), rec.get("title_zh"), rec.get("name_zh"), rec.get("name_en"), rec.get("name"), rec.get("id"))
        prompt = _pick_str(rec.get("prompt"), rec.get("prompt_zh"), rec.get("prompt_en"), rec.get("text"), rec.get("content"))
        if not title or not prompt:
            continue
        tags = _pick_tags(rec)
        raw_cat = _pick_str(rec.get("category"), rec.get("category_label"), rec.get("category_raw"), rec.get("type"))
        cid, clabel, cgroup, cmat = _resolve_category(raw_cat, tags, title, prompt)
        blob = f"{title}\n{prompt}\n{_pick_str(rec.get('description'))}"
        maturity = _resolve_maturity(cmat, tags, blob)
        if _is_minor_unsafe(blob, maturity):
            continue
        pid = _pick_str(rec.get("id")) or f"{source.id}-{i + 1:04d}"
        if pid in seen:
            continue
        seen.add(pid)
        cover = _pick_str(rec.get("coverUrl"), rec.get("image_url"), rec.get("image"), rec.get("cover"))
        items.append(
            PromptItem(
                id=pid,
                title=title,
                prompt=prompt,
                description=_pick_str(rec.get("description"), rec.get("desc")),
                cover_url=cover,
                tags=tags,
                source_id=source.id,
                source_name=source.name,
                category_id=cid,
                category=clabel,
                category_group=cgroup,
                maturity=maturity,
                github_url=_pick_str(rec.get("sourceUrl"), rec.get("source_url"), rec.get("url")) or source.homepage,
            )
        )
    return items


class PromptLibraryStore:
    """提示词库：源开关、缓存拉取、收藏、查询。"""

    def __init__(self) -> None:
        self.sources: List[PromptSource] = default_sources()
        self._items_by_source: Dict[str, List[PromptItem]] = {}
        self._favorites: List[str] = []  # "sourceId::id"
        self._lock = threading.Lock()
        self._load_favorites()
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _fav_key(self, source_id: str, item_id: str) -> str:
        return f"{source_id}::{item_id}"

    def _load_favorites(self) -> None:
        try:
            if _FAV_PATH.exists():
                data = json.loads(_FAV_PATH.read_text(encoding="utf-8"))
                self._favorites = list(data.get("favorites") or [])
        except Exception as e:
            logger.debug(f"加载收藏失败: {e}")
            self._favorites = []

    def save_favorites(self) -> None:
        try:
            _FAV_PATH.parent.mkdir(parents=True, exist_ok=True)
            _FAV_PATH.write_text(
                json.dumps({"favorites": self._favorites, "updated_at": time.time()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存收藏失败: {e}")

    def is_favorite(self, source_id: str, item_id: str) -> bool:
        return self._fav_key(source_id, item_id) in self._favorites

    def toggle_favorite(self, source_id: str, item_id: str) -> bool:
        key = self._fav_key(source_id, item_id)
        if key in self._favorites:
            self._favorites.remove(key)
            self.save_favorites()
            return False
        self._favorites.append(key)
        self.save_favorites()
        return True

    def favorite_keys(self) -> List[str]:
        return list(self._favorites)

    def set_source_enabled(self, source_id: str, enabled: bool) -> None:
        for s in self.sources:
            if s.id == source_id:
                s.enabled = enabled
                break

    def _read_local(self, source: PromptSource) -> Any:
        mapping = {
            "shiguang-curated": _LOCAL_PROMPTS_DIR / "shiguang-curated.json",
            "shiguang-drama-pack": _LOCAL_PROMPTS_DIR / "shiguang-drama.json",
            "shiguang-adult-18plus": _LOCAL_PROMPTS_DIR / "shiguang-adult-18plus.json",
        }
        path = mapping.get(source.id)
        if path is None:
            bundled = _BUNDLED_DIR / f"{source.id}.json"
            if bundled.is_file():
                path = bundled
        if path is None:
            # 自定义 file:// 或绝对路径
            raw = source.url
            if raw.startswith("file:"):
                from urllib.parse import urlparse, unquote
                u = urlparse(raw)
                path = Path(unquote(u.path))
                # Windows: /D:/...
                if os.name == "nt" and path.as_posix().startswith("/") and len(path.as_posix()) > 2 and path.as_posix()[2] == ":":
                    path = Path(path.as_posix()[1:])
            else:
                path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"本地提示词文件不存在: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _cache_path(self, source_id: str) -> Path:
        return _CACHE_DIR / f"{source_id}.json"

    def _fetch_remote(self, source: PromptSource) -> Any:
        cache = self._cache_path(source.id)
        if cache.exists() and time.time() - cache.stat().st_mtime < _CACHE_TTL_S:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                logger.debug("提示词缓存读取失败，改走远端拉取: %s", cache, exc_info=True)
        req = urllib.request.Request(source.url, headers={"User-Agent": "ShiguangPromptLib/1.0"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        try:
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.debug("提示词缓存写入失败（不影响本次结果）", exc_info=True)
        return data

    def load_source(self, source: PromptSource) -> List[PromptItem]:
        try:
            bundled = _BUNDLED_DIR / f"{source.id}.json"
            if source.local or source.id.startswith("shiguang-") or bundled.is_file():
                data = self._read_local(source)
            else:
                data = self._fetch_remote(source)
            items = normalize_items(data, source)
            for it in items:
                it.favorite = self.is_favorite(it.source_id, it.id)
            with self._lock:
                self._items_by_source[source.id] = items
            return items
        except Exception as e:
            logger.warning(f"加载提示词源失败 [{source.name}]: {e}")
            cache = self._cache_path(source.id)
            if cache.exists():
                try:
                    items = normalize_items(json.loads(cache.read_text(encoding="utf-8")), source)
                    for it in items:
                        it.favorite = self.is_favorite(it.source_id, it.id)
                    with self._lock:
                        self._items_by_source[source.id] = items
                    return items
                except Exception:
                    logger.debug("提示词源降级缓存同样不可用: %s", source.id, exc_info=True)
            with self._lock:
                self._items_by_source[source.id] = []
            return []

    def refresh_enabled(self, progress=None) -> Tuple[int, int, int]:
        """返回 (ok, fail, total_items)"""
        enabled = [s for s in self.sources if s.enabled]
        ok = fail = total = 0
        for i, s in enumerate(enabled):
            if progress:
                progress(i + 1, len(enabled), s.name)
            before = self._items_by_source.get(s.id)
            items = self.load_source(s)
            if items:
                ok += 1
                total += len(items)
            elif before is None and not items:
                fail += 1
            else:
                # 空源或清空：记失败仅当远程
                if not s.local:
                    fail += 1
                else:
                    ok += 1
        return ok, fail, total

    def ensure_loaded(self) -> None:
        for s in self.sources:
            if s.enabled and s.id not in self._items_by_source:
                self.load_source(s)

    def query(
        self,
        *,
        keyword: str = "",
        category_id: str = "all",
        category_group: str = "all",
        maturity: str = "all",
        tag: str = "",
        favorites_only: bool = False,
        source_id: str = "all",
    ) -> List[PromptItem]:
        self.ensure_loaded()
        with self._lock:
            pools = []
            for s in self.sources:
                if not s.enabled:
                    continue
                if source_id != "all" and s.id != source_id:
                    continue
                pools.extend(self._items_by_source.get(s.id, []))
        # refresh favorite flags
        fav_set = set(self._favorites)
        for it in pools:
            it.favorite = self._fav_key(it.source_id, it.id) in fav_set

        kw = (keyword or "").strip().lower()
        out: List[PromptItem] = []
        for it in pools:
            if favorites_only and not it.favorite:
                continue
            if maturity != "all" and it.maturity != maturity:
                continue
            if category_id != "all" and it.category_id != category_id:
                continue
            if category_group != "all" and it.category_group != category_group:
                continue
            if tag and tag not in it.tags:
                continue
            if kw:
                blob = " ".join([it.title, it.prompt, it.description, it.category, it.category_group, *it.tags]).lower()
                if kw not in blob:
                    continue
            out.append(it)
        return out

    def get_item(self, source_id: str, item_id: str) -> Optional[PromptItem]:
        self.ensure_loaded()
        for it in self._items_by_source.get(source_id, []):
            if it.id == item_id:
                it.favorite = self.is_favorite(source_id, item_id)
                return it
        # search all
        for items in self._items_by_source.values():
            for it in items:
                if it.source_id == source_id and it.id == item_id:
                    it.favorite = self.is_favorite(source_id, item_id)
                    return it
        return None
