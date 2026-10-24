# -*- coding: utf-8 -*-
"""画布节点插件资产守卫（2026-10-25）。

背景（血泪）：`canvas_bridge._BUILTIN_PLUGIN_REGISTRY` 里 4 条官方插件声明
`url: /plugins/*.js`，但 `public/plugins/` 与 `dist/plugins/` **都不存在** ——
静态服务的 SPA 兜底把缺文件改写成 `/index.html`（**200 + HTML**，不是 404），
前端把 HTML 当 ESM import：`SyntaxError: Unexpected token '<'`。每次进画布刷
4 条 sync install failed；另有 2 条社区插件指向 `cdn.shiguang.io`（域名不存在）
⇒ `Failed to fetch`。

本守卫把三件事钉死：
1. 注册表里**每条相对 url 都必须有真实文件**（public/plugins/ 下）；
2. **不许出现死地址**（已知死域名清单）；
3. bundle 必须**零 import** —— 宿主用 Blob URL + import() 加载，任何 import 都解析不了。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.canvas_bridge import _BUILTIN_PLUGIN_REGISTRY, _DEAD_PLUGIN_URL_PREFIXES

_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_DIR = _ROOT / "vendor" / "shiguang-canvas" / "public" / "plugins"


def _local_urls() -> list[str]:
    return [str(p.get("url") or "") for p in _BUILTIN_PLUGIN_REGISTRY if str(p.get("url") or "").startswith("/")]


def test_plugin_dir_exists() -> None:
    assert _PLUGIN_DIR.is_dir(), f"插件目录不存在: {_PLUGIN_DIR}"


def test_every_registry_url_has_a_real_file() -> None:
    """注册表 → 文件必须一一对应（缺一个就是启动时的 4 条红字）。"""
    missing = []
    for url in _local_urls():
        rel = url.lstrip("/")
        if not (_PLUGIN_DIR / Path(rel).name).is_file():
            missing.append(url)
    assert not missing, f"注册表声明了不存在的插件产物: {missing}（→ 静态服务会回 404 HTML）"


def test_no_dead_external_urls() -> None:
    """不许再出现「编造的 CDN」——社区插件要么真能取到，要么别登记。"""
    dead = [
        str(p.get("url"))
        for p in _BUILTIN_PLUGIN_REGISTRY
        if str(p.get("url") or "").startswith(_DEAD_PLUGIN_URL_PREFIXES)
    ]
    assert not dead, f"注册表含死地址: {dead}"


def test_index_json_matches_registry() -> None:
    """public/plugins/index.json 必须与注册表的相对 url 一致（防孤儿/漏登记）。"""
    import json

    idx = _PLUGIN_DIR / "index.json"
    assert idx.is_file(), "缺 index.json（plugin-loader 的本地发现入口）"
    listed = json.loads(idx.read_text(encoding="utf-8"))
    assert isinstance(listed, list) and listed
    assert sorted(listed) == sorted(_local_urls()), f"index.json={listed} 与注册表={_local_urls()} 不一致"


def test_bundles_are_import_free_and_export_default() -> None:
    """Blob URL + import() 的硬约束：bundle 里不能有任何 import / require。"""
    offenders = []
    for url in _local_urls():
        f = _PLUGIN_DIR / Path(url).name
        src = f.read_text(encoding="utf-8")
        if re.search(r"^\s*import\s", src, re.M) or re.search(r"\brequire\s*\(", src):
            offenders.append(f.name)
        assert "export default" in src, f"{f.name} 必须 export default（CanvasPlugin 契约）"
    assert not offenders, f"这些 bundle 含 import/require，Blob URL 下必然解析失败: {offenders}"


def test_dead_url_cleanup_in_manifest(tmp_path, monkeypatch) -> None:
    """缓存迁移：manifest 里的死地址条目必须在读取时被清掉并回写。"""
    import json

    import app.core.canvas_bridge as cb

    p = tmp_path / "canvas_plugins.json"
    p.write_text(
        json.dumps(
            [
                {"id": "community:dead", "url": "https://cdn.shiguang.io/plugins/x.js", "enabled": True},
                {"id": "builtin:markdown", "url": "/plugins/markdown.js", "enabled": True},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cb, "_CANVAS_PLUGINS_JSON", str(p))
    kept = cb._load_canvas_plugins_manifest()
    assert [x["id"] for x in kept] == ["builtin:markdown"]
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert [x["id"] for x in on_disk] == ["builtin:markdown"], "清理结果必须回写，否则下次启动又复活"
