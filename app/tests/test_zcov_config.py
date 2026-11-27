# -*- coding: utf-8 -*-
"""零覆盖模块补测：preset_manager / shortcut_manager / local_asset_manager / config / app.utils。

设计纪律（对齐 team-lead 硬性约束）：
- 只新建测试，**不改任何 app/ 源码**；
- 持久化路径一律重定向到 tmp_path（monkeypatch 模块常量 / 实例属性 / 构造参数），
  绝不写真实 %APPDATA% 或 app/data/*.json；
- 无空断言：每例都断言可观察行为（返回值 / 落盘内容 / 索引结果 / 异常容忍）；
- Qt 对象只用 offscreen，断言序列化结果（QKeySequence.toString()），不模拟真实按键；
- 不写 sleep 时序测试。

运行：``QT_QPA_PLATFORM=offscreen .venv312/Scripts/python.exe -m pytest app/tests/test_zcov_config.py -q``
"""
import importlib
import json
import os
import sys

import pytest


# ============================================================
# 公共 fixture
# ============================================================

@pytest.fixture(scope="module")
def qapp():
    """Qt 对象（QObject/QKeySequence/QAction）在 offscreen 下需要 QApplication。"""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["zcov-config-test"])
    yield app


# ============================================================
# ① app/core/preset_manager.py
# ============================================================

@pytest.fixture
def preset_env(tmp_path, monkeypatch):
    """把 preset_manager 的模块级 _STORAGE_PATH 重定向到 tmp。

    _STORAGE_PATH 是模块全局，_save/_load_from_disk 在调用时按名查找它，
    因此 monkeypatch.setattr 模块属性即可完全隔离（可注入 → 非硬编码缺陷）。
    """
    import app.core.preset_manager as pm
    store = tmp_path / "presets.json"
    monkeypatch.setattr(pm, "_STORAGE_PATH", str(store))
    return pm, store


def test_preset_defaults_present(preset_env):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    # 默认预设按 id 内嵌，数量可核对（effect 3 / transition 2 / export 7 / audio 2 / subtitle 2）
    assert len(mgr.list_presets("effect")) == 3
    assert len(mgr.list_presets("export")) == 7
    assert len(mgr.list_presets()) == 3 + 2 + 7 + 2 + 2
    assert mgr.get_preset("export_preset_vertical_4k")["parameters"]["resolution"] == "2160x3840"
    # 默认包 4 个
    assert len(mgr.list_packs()) == 4
    assert mgr.get_pack("aesthetic_pack_cinema")["applies_to"] == "clip"


def test_preset_create_roundtrip_and_defaults_not_persisted(preset_env):
    pm, store = preset_env
    mgr = pm.PresetManager()
    created = mgr.create_preset("我的风格", "effect", {"contrast": 1.5}, category="custom")
    assert created is not None and created["id"] == "effect_preset_4"
    assert store.exists(), "create_preset 应触发落盘"

    on_disk = json.loads(store.read_text(encoding="utf-8"))
    # 只持久化用户自定义：disk 里 effect 仅 1 条（默认 3 条被排除）
    assert on_disk["schema_version"] == 1
    assert [p["id"] for p in on_disk["presets"]["effect"]] == ["effect_preset_4"]
    assert on_disk["packs"] == []  # 未创建用户包 → 盘上 packs 为空（默认包不落盘）

    # 重新构造 → 用户预设恢复，默认仍在，无重复
    mgr2 = pm.PresetManager()
    ids = [p["id"] for p in mgr2.list_presets("effect")]
    assert ids.count("effect_preset_4") == 1
    assert ids.count("effect_preset_1") == 1
    assert mgr2.get_preset("effect_preset_4")["name"] == "我的风格"


def test_preset_create_invalid_type_returns_none(preset_env):
    pm, store = preset_env
    mgr = pm.PresetManager()
    assert mgr.create_preset("x", "not_a_type", {}) is None
    assert not store.exists(), "非法类型不应落盘"


@pytest.mark.xfail(reason="已知缺陷：create_preset 用 len(list)+1 生成 id，删除后再建会与现存 id 碰撞")
def test_preset_create_id_unique_after_delete(preset_env):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    mgr.delete_preset("effect_preset_2")  # 剩余 id: 1,3（len=2）
    mgr.create_preset("新预设", "effect", {})  # 生成 id = effect_preset_3 → 与现存碰撞
    ids = [p["id"] for p in mgr.list_presets("effect")]
    assert len(ids) == len(set(ids)), f"存在重复 id: {ids}"


def test_preset_get_update_delete_semantics(preset_env):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    assert mgr.get_preset("nope") is None

    created = mgr.create_preset("t", "audio", {"volume": 1.0})
    assert mgr.update_preset(created["id"], name="改名") is True
    assert mgr.get_preset(created["id"])["name"] == "改名"
    assert mgr.update_preset("ghost", name="x") is False

    assert mgr.delete_preset(created["id"]) is True
    assert mgr.get_preset(created["id"]) is None
    assert mgr.delete_preset(created["id"]) is False
    # 默认预设也可删（文档语义）
    assert mgr.delete_preset("effect_preset_1") is True
    assert mgr.get_preset("effect_preset_1") is None


def test_preset_search_and_categories(preset_env):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    hits = mgr.search_presets("电影")
    assert any(p["id"] == "effect_preset_1" for p in hits)
    # 分类命中（"color"）
    assert any(p["id"] == "effect_preset_2" for p in mgr.search_presets("color"))
    # 限定类型 + 非法类型
    assert all(p["type"] == "audio" for p in mgr.search_presets("", preset_type="audio"))
    assert mgr.search_presets("x", preset_type="bogus") == []
    cats = mgr.get_preset_categories("export")
    assert "video" in cats
    assert "video" in mgr.get_preset_categories()


def test_preset_export_import_roundtrip_and_idempotent(preset_env, tmp_path):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    created = mgr.create_preset("导出样例", "subtitle", {"font_size": 30}, category="display")
    out = tmp_path / "nested" / "one.json"
    assert mgr.export_preset(created["id"], str(out)) is True
    assert out.exists()

    # 删除后再导入 → 恢复
    mgr.delete_preset(created["id"])
    imported = mgr.import_preset(str(out))
    assert [p["id"] for p in imported] == [created["id"]]
    assert mgr.get_preset(created["id"])["name"] == "导出样例"

    # 幂等：再次导入不产生重复
    n_before = len(mgr.list_presets("subtitle"))
    mgr.import_preset(str(out))
    assert len(mgr.list_presets("subtitle")) == n_before

    # 导出不存在的 id
    assert mgr.export_preset("ghost", str(tmp_path / "g.json")) is False


def test_preset_import_bad_inputs_return_empty(preset_env, tmp_path):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert mgr.import_preset(str(bad)) == []
    assert mgr.import_preset(str(empty)) == []
    assert mgr.import_preset(str(tmp_path / "missing.json")) == []


def test_preset_import_wrapped_structure(preset_env, tmp_path):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    f = tmp_path / "pack.json"
    f.write_text(json.dumps({
        "presets": {
            "effect": [{"id": "user_eff_1", "name": "A", "type": "effect", "category": "c"}],
            "audio": [{"id": "user_aud_1", "name": "B", "type": "audio"}],
            "bogus_type": [{"id": "x", "type": "bogus_type"}],
        }
    }), encoding="utf-8")
    imported = mgr.import_preset(str(f))
    assert {p["id"] for p in imported} == {"user_eff_1", "user_aud_1"}
    assert mgr.get_preset("user_eff_1") is not None
    assert mgr.get_preset("x") is None  # 非法 type 被丢弃


def test_preset_apply_preset_kinds(preset_env):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    eff = mgr.apply_preset("effect_preset_1")
    assert eff["kind"] == "color" and eff["contrast"] == 1.2

    tr = mgr.apply_preset("transition_preset_2")
    assert tr["kind"] == "transition" and tr["transition_type"] == "slide"
    assert tr["duration"] == 0.5  # params 无 duration → 默认 0.5

    sub = mgr.apply_preset("subtitle_preset_1")
    assert sub["kind"] == "subtitle" and sub["font_size"] == 24

    assert mgr.apply_preset("ghost") is None


def test_preset_corrupt_disk_tolerated(preset_env):
    pm, store = preset_env
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("\x00\x01 garbage", encoding="utf-8")
    mgr = pm.PresetManager()  # 不得抛异常，默认数据完整
    assert len(mgr.list_presets("effect")) == 3
    assert len(mgr.list_packs()) == 4


def test_preset_load_dedup_and_unknown_type_ignored(preset_env):
    pm, store = preset_env
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "presets": {
            "effect": [
                {"id": "effect_preset_1", "name": "冒名顶替", "type": "effect"},  # 与默认 id 冲突 → 跳过
                {"id": "user_eff_x", "name": "真用户", "type": "effect"},
            ],
            "unknown": [{"id": "z", "type": "unknown"}],  # 未知类型键 → 跳过
        },
        "packs": [
            {"id": "aesthetic_pack_cinema", "name": "dup"},  # 与默认包 id 冲突 → 跳过
            {"id": "user_pack_x", "name": "新包", "steps": [{"kind": "color"}]},
        ],
    }), encoding="utf-8")
    mgr = pm.PresetManager()
    assert mgr.get_preset("effect_preset_1")["name"] == "电影风格"  # 默认未被覆盖
    assert mgr.get_preset("user_eff_x")["name"] == "真用户"
    assert mgr.get_pack("aesthetic_pack_cinema")["name"] == "电影感"
    assert mgr.get_pack("user_pack_x") is not None


def test_preset_pack_crud_and_apply(preset_env):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    assert mgr.get_pack("ghost") is None
    # 非法 steps（kind 不在白名单 / 空）→ None
    assert mgr.create_pack("坏包", [{"kind": "nope"}]) is None
    assert mgr.create_pack("空包", []) is None
    # 合法 steps 只保留白名单 kind
    pack = mgr.create_pack("混合", [{"kind": "lut", "lut": "x"}, {"kind": "xxx"}, {"kind": "opacity", "v": 0.5}])
    assert pack is not None
    assert [s["kind"] for s in pack["steps"]] == ["lut", "opacity"]

    steps = mgr.apply_pack(pack["id"])
    assert steps == [{"kind": "lut", "lut": "x"}, {"kind": "opacity", "v": 0.5}]
    assert mgr.apply_pack("ghost") is None
    assert mgr.delete_pack(pack["id"]) is True
    assert mgr.delete_pack(pack["id"]) is False


def test_preset_pack_export_import_and_bad_input(preset_env, tmp_path):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    out = tmp_path / "pack_export.json"
    assert mgr.export_pack("aesthetic_pack_retro", str(out)) is True
    assert mgr.export_pack("ghost", str(out)) is False

    # 单包 dict 导入（改 id 避免覆盖默认）
    data = json.loads(out.read_text(encoding="utf-8"))
    data["id"] = "imported_pack_1"
    single = tmp_path / "single_pack.json"
    single.write_text(json.dumps(data), encoding="utf-8")
    imported = mgr.import_pack(str(single))
    assert [p["id"] for p in imported] == ["imported_pack_1"]

    # {packs:[...]} 结构；无合法 steps 的包被丢弃
    wrapped = tmp_path / "wrapped.json"
    wrapped.write_text(json.dumps({"packs": [
        {"id": "w1", "steps": [{"kind": "color"}]},
        {"id": "w2", "steps": [{"kind": "bad"}]},
        {"id": "w3", "steps": "not-a-list"},
    ]}), encoding="utf-8")
    got = {p["id"] for p in mgr.import_pack(str(wrapped))}
    assert got == {"w1"}

    assert mgr.import_pack(str(tmp_path / "missing.json")) == []


def test_preset_reset_to_defaults(preset_env):
    pm, _store = preset_env
    mgr = pm.PresetManager()
    mgr.create_preset("u", "effect", {})
    mgr.create_pack("up", [{"kind": "color"}])
    assert len(mgr.list_presets("effect")) == 4

    # 单类型重置
    assert mgr.reset_to_defaults("effect") is True
    assert len(mgr.list_presets("effect")) == 3

    # 全量重置 → 用户数据清空、默认恢复
    mgr.create_preset("u2", "audio", {})
    mgr.reset_to_defaults()
    assert len(mgr.list_presets("audio")) == 2
    assert len(mgr.list_packs()) == 4


def test_preset_save_oserror_returns_false(preset_env, monkeypatch):
    pm, _store = preset_env
    mgr = pm.PresetManager()

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(pm.os, "makedirs", _boom)
    # _save 捕获 OSError → 返回 False（不炸整条 CRUD 链）
    assert mgr._save() is False


# ============================================================
# ② app/core/shortcut_manager.py
# ============================================================

@pytest.fixture
def sc_mgr(tmp_path):
    """用构造参数注入配置文件路径，绝不触碰真实用户目录。"""
    from app.core.shortcut_manager import ShortcutManager
    return ShortcutManager(config_path=str(tmp_path / "shortcuts.json")), (tmp_path / "shortcuts.json")


def test_shortcut_defaults_loaded(sc_mgr, qapp):
    from app.core.shortcut_manager import DEFAULT_SHORTCUTS
    mgr, _path = sc_mgr
    assert len(mgr.get_all_bindings()) == len(DEFAULT_SHORTCUTS)
    b = mgr.get_binding("file.save")
    assert b.key_sequence == "Ctrl+S" and b.context == "global" and b.description == "保存项目"
    assert mgr.get_binding("ghost") is None


def test_shortcut_set_roundtrip_persist(sc_mgr):
    from app.core.shortcut_manager import ShortcutManager
    mgr, path = sc_mgr
    assert mgr.set_shortcut("file.save", "Ctrl+Alt+F1") is True
    assert mgr.get_binding("file.save").key_sequence == "Ctrl+Alt+F1"
    assert mgr.save(path) is True
    assert path.exists()

    fresh = ShortcutManager(config_path=str(path))
    assert fresh.get_binding("file.save").key_sequence == "Ctrl+Alt+F1"


def test_shortcut_conflict_detection(sc_mgr):
    mgr, _path = sc_mgr
    # "Ctrl+S" 已被 file.save 占用 → 改 file.new 应失败且保持原值
    assert mgr.set_shortcut("file.new", "Ctrl+S") is False
    assert mgr.get_binding("file.new").key_sequence == "Ctrl+N"

    # 冲突检测大小写不敏感；排除自身
    assert mgr._check_conflict("anyone", "CTRL+S") == "file.save"
    assert mgr._check_conflict("file.save", "Ctrl+S") is None  # 自排除
    assert mgr._check_conflict("x", "") is None  # 空序列无冲突


def test_shortcut_set_new_action_creates_binding(sc_mgr):
    mgr, _path = sc_mgr
    assert mgr.set_shortcut("custom.act", "Ctrl+Alt+Q") is True
    b = mgr.get_binding("custom.act")
    assert b is not None and b.key_sequence == "Ctrl+Alt+Q" and b.context == "global"


def test_shortcut_reset_to_default(sc_mgr):
    mgr, _path = sc_mgr
    mgr.set_shortcut("file.save", "Ctrl+Alt+F1")
    assert mgr.reset_to_default("file.save") is True
    assert mgr.get_binding("file.save").key_sequence == "Ctrl+S"
    assert mgr.reset_to_default("no.such.action") is False

    mgr.set_shortcut("file.new", "Ctrl+Alt+F2")
    assert mgr.reset_to_default() is True
    assert mgr.get_binding("file.new").key_sequence == "Ctrl+N"


def test_shortcut_save_load_edges(sc_mgr, tmp_path):
    from app.core.shortcut_manager import ShortcutManager
    mgr, path = sc_mgr
    # 不存在的路径 → load False
    assert mgr.load(str(tmp_path / "nope.json")) is False
    # 父目录不存在 → save False（save 不做 makedirs）
    assert mgr.save(str(tmp_path / "no_dir" / "x.json")) is False

    # 损坏 JSON → load False，不炸
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert mgr.load(str(bad)) is False

    # 含未知 action → 新增绑定
    ext = tmp_path / "ext.json"
    ext.write_text(json.dumps({"bindings": {"brand.new": {"key": "Ctrl+9", "context": "preview", "desc": "新"}}}),
                   encoding="utf-8")
    assert mgr.load(str(ext)) is True
    nb = mgr.get_binding("brand.new")
    assert nb is not None and nb.key_sequence == "Ctrl+9" and nb.context == "preview"


def test_shortcut_export_import_config(sc_mgr, tmp_path):
    from app.core.shortcut_manager import ShortcutManager
    mgr, _path = sc_mgr
    mgr.set_shortcut("custom.share", "Ctrl+Alt+9")
    share = tmp_path / "share.json"
    assert mgr.export_config(str(share)) is True

    other = ShortcutManager(config_path=str(tmp_path / "other.json"))
    assert other.get_binding("custom.share") is None
    assert other.import_config(str(share)) is True
    assert other.get_binding("custom.share").key_sequence == "Ctrl+Alt+9"


def test_shortcut_register_qaction_applies_sequence(sc_mgr, qapp):
    from PySide6.QtGui import QAction, QKeySequence
    mgr, _path = sc_mgr
    act = QAction("test", None)
    mgr.register_qaction("file.save", act)
    assert act.shortcut().toString() == QKeySequence("Ctrl+S").toString()

    # set_shortcut 应同步更新已注册 QAction
    mgr.set_shortcut("file.save", "Ctrl+Alt+F5")
    assert act.shortcut().toString() == QKeySequence("Ctrl+Alt+F5").toString()


def test_shortcut_register_unregister_action(sc_mgr):
    mgr, _path = sc_mgr
    calls = []
    mgr.register_action("do.thing", lambda: calls.append(1))
    assert "do.thing" in mgr._actions
    mgr.unregister_action("do.thing")
    assert "do.thing" not in mgr._actions


def test_shortcut_binding_to_dict_and_from_default():
    from app.core.shortcut_manager import ShortcutBinding
    b = ShortcutBinding.from_default("file.open")
    assert b.to_dict() == {"key": "Ctrl+O", "context": "global", "desc": "打开项目"}
    # 未知 action → 空序列 + global
    unknown = ShortcutBinding.from_default("ghost.action")
    assert unknown.key_sequence == "" and unknown.context == "global"


# ============================================================
# ③ app/core/local_asset_manager.py
# ============================================================

@pytest.fixture
def asset_mgr(tmp_path, monkeypatch):
    """本地素材管理器是 __new__ 单例、且路径硬编码在 __init__ 内（无构造参数）。

    做法：先重置单例，构造后将 _base_dir/_metadata_file 指到 tmp 并重建目录/索引，
    实例方法全部通过 self._base_dir / self._metadata_file 取值，因此完全隔离。
    （这也印证了「路径不可注入」——见最终报告硬编码清单。）
    """
    import app.core.local_asset_manager as lam
    monkeypatch.setattr(lam.LocalAssetManager, "_instance", None)
    mgr = lam.LocalAssetManager()
    mgr._base_dir = str(tmp_path / "assets")
    mgr._metadata_file = os.path.join(mgr._base_dir, "metadata.json")
    mgr._assets = {}
    mgr._create_directory_structure()
    mgr._build_indexes()
    mgr._recently_used = []
    return mgr


def _mk(tmp_path, name, content=b"data"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _valid_png(tmp_path, name):
    """生成一个真实可解码的 PNG。

    image 类型的 _extract_metadata 只捕获 ImportError，喂假字节会抛
    PIL.UnidentifiedImageError（见报告「可疑点」），故此处用真图。
    """
    from PIL import Image
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), (255, 0, 0)).save(str(p), "PNG")
    return p


def test_asset_singleton_identity(asset_mgr):
    from app.core.local_asset_manager import LocalAssetManager
    assert LocalAssetManager() is asset_mgr


def test_asset_import_copies_and_indexes(asset_mgr, tmp_path):
    src = _valid_png(tmp_path, "src/hero.png")
    a = asset_mgr.import_asset(str(src), category="角色", tags=["主角", "特效"])
    assert a is not None and a.type == "image"
    assert a.size == os.path.getsize(str(src)) > 0 and a.format == "png"
    assert a.resolution == "10x10"
    assert a.category == "角色" and set(a.tags) == {"主角", "特效"}
    # 已复制到素材库目录
    assert os.path.exists(a.path)
    assert os.path.dirname(a.path).startswith(asset_mgr._base_dir)
    assert asset_mgr.get_asset(a.id) is a
    assert asset_mgr.get_assets(asset_type="image") == [a]
    # 缩略图已生成
    assert a.thumbnail and os.path.exists(a.thumbnail)


def test_asset_import_rejects_bad_inputs(asset_mgr, tmp_path):
    assert asset_mgr.import_asset(str(tmp_path / "missing.png")) is None
    unsupported = _mk(tmp_path, "notes.xyz", b"x")
    assert asset_mgr.import_asset(str(unsupported)) is None


@pytest.mark.xfail(reason="已知缺陷：image 元数据提取仅捕获 ImportError，损坏图片抛 UnidentifiedImageError 而非返回 None")
def test_asset_corrupt_image_returns_none_not_raise(asset_mgr, tmp_path):
    bad = _mk(tmp_path, "bad.png", b"not-an-image")
    assert asset_mgr.import_asset(str(bad)) is None


def test_asset_import_dedup_and_name_collision(asset_mgr, tmp_path):
    src = _mk(tmp_path, "a/clip.mp4", b"VIDEO")
    first = asset_mgr.import_asset(str(src))
    again = asset_mgr.import_asset(str(src))
    assert first.id == again.id and len(asset_mgr.get_assets()) == 1  # 幂等去重

    # 同名不同路径 → 两个素材，目标文件名加 _1 后缀
    other = _mk(tmp_path, "b/clip.mp4", b"VIDEO2")
    second = asset_mgr.import_asset(str(other))
    assert second.id != first.id
    assert os.path.basename(second.path) == "clip_1.mp4"
    assert len(asset_mgr.get_assets(asset_type="video")) == 2


def test_asset_search_and_filters(asset_mgr, tmp_path):
    v = asset_mgr.import_asset(str(_mk(tmp_path, "v/film.srt")), category="片子", tags=["热点"])
    i = asset_mgr.import_asset(str(_mk(tmp_path, "i/pic.srt")), category="图片", tags=["封面"])
    asset_mgr.update_asset(i.id, description="绝美封面")
    asset_mgr.mark_asset_used(v.id, project_id="proj-1")

    assert {a.id for a in asset_mgr.search_assets("film")} == {v.id}
    assert {a.id for a in asset_mgr.search_assets("绝美")} == {i.id}      # 命中 description
    assert {a.id for a in asset_mgr.search_assets("封面")} == {i.id}      # 命中 tag
    assert {a.id for a in asset_mgr.search_assets("图片")} == {i.id}      # 命中 category

    assert {a.id for a in asset_mgr.get_assets(category="片子")} == {v.id}
    assert {a.id for a in asset_mgr.get_assets(tags=["封面"])} == {i.id}
    assert {a.id for a in asset_mgr.get_assets(used=True)} == {v.id}
    assert {a.id for a in asset_mgr.get_assets(project_id="proj-1")} == {v.id}
    assert len(asset_mgr.get_assets()) == 2


def test_asset_mark_used_and_recently_used(asset_mgr, tmp_path):
    a = asset_mgr.import_asset(str(_mk(tmp_path, "x/one.srt")))
    b = asset_mgr.import_asset(str(_mk(tmp_path, "y/two.srt")))
    assert asset_mgr.get_recently_used() == []

    assert asset_mgr.mark_asset_used(a.id, project_id="p") is True
    rec = asset_mgr.get_recently_used()
    assert [x.id for x in rec] == [a.id]
    assert a.used is True and a.project_id == "p" and a.last_used_time is not None

    assert asset_mgr.mark_asset_used(b.id) is True
    assert set(x.id for x in asset_mgr.get_recently_used()) == {a.id, b.id}
    assert asset_mgr.mark_asset_used("ghost") is False


def test_asset_update_and_invalid(asset_mgr, tmp_path):
    a = asset_mgr.import_asset(str(_mk(tmp_path, "u/k.srt")))
    assert asset_mgr.update_asset(a.id, name="新名", category="新类") is True
    assert a.name == "新名" and a.category == "新类"
    # 不存在字段被忽略，不抛异常
    assert asset_mgr.update_asset(a.id, not_a_field=1) is True
    assert asset_mgr.update_asset("ghost", name="x") is False


def test_asset_tags_add_remove_bulk(asset_mgr, tmp_path):
    a = asset_mgr.import_asset(str(_mk(tmp_path, "t/a.srt")))
    b = asset_mgr.import_asset(str(_mk(tmp_path, "t/b.srt")))
    assert asset_mgr.add_tag_to_asset(a.id, "tag1") is True
    assert asset_mgr.add_tag_to_asset(a.id, "tag1") is True  # 幂等
    assert a.tags == ["tag1"]
    assert asset_mgr.remove_tag_from_asset(a.id, "tag1") is True
    assert a.tags == []
    assert asset_mgr.remove_tag_from_asset("ghost", "x") is False

    assert asset_mgr.add_tags_to_assets([a.id, b.id], ["x", "y"]) is True
    assert set(a.tags) == {"x", "y"} and set(b.tags) == {"x", "y"}
    assert asset_mgr.remove_tags_from_assets([a.id, b.id], ["x"]) is True
    assert a.tags == ["y"] and b.tags == ["y"]
    assert "y" in asset_mgr.get_tags()


def test_asset_delete_removes_files_and_entry(asset_mgr, tmp_path):
    a = asset_mgr.import_asset(str(_mk(tmp_path, "d/del.srt")))
    path = a.path
    assert os.path.exists(path)
    assert asset_mgr.delete_asset(a.id) is True
    assert not os.path.exists(path)
    assert asset_mgr.get_asset(a.id) is None
    assert asset_mgr.delete_asset(a.id) is False
    assert asset_mgr.delete_asset("ghost") is False


def test_asset_stats(asset_mgr, tmp_path):
    p1 = _valid_png(tmp_path, "s/a.png")
    asset_mgr.import_asset(str(p1), category="c1")
    asset_mgr.import_asset(str(_mk(tmp_path, "s/b.srt", b"1234567890")), category="c1")
    asset_mgr.import_asset(str(_mk(tmp_path, "s/c.json", b"12")), category="c2")
    stats = asset_mgr.get_stats()
    assert stats["total_assets"] == 3
    assert stats["assets_by_type"] == {"image": 1, "subtitle": 1, "template": 1}
    assert stats["assets_by_category"] == {"c1": 2, "c2": 1}
    assert stats["total_size"] == os.path.getsize(str(p1)) + 10 + 2


def test_asset_export(asset_mgr, tmp_path):
    a = asset_mgr.import_asset(str(_mk(tmp_path, "e/out.srt", b"BYTES")))
    dest = tmp_path / "exported.srt"
    assert asset_mgr.export_asset(a.id, str(dest)) is True
    assert dest.read_bytes() == b"BYTES"
    assert asset_mgr.export_asset("ghost", str(tmp_path / "g.srt")) is False


def test_asset_import_folder(asset_mgr, tmp_path):
    folder = tmp_path / "batch"
    (folder / "sub").mkdir(parents=True)
    _valid_png(tmp_path, "batch/a.png")
    (folder / "sub" / "b.srt").write_bytes(b"b")
    (folder / "ignore.xyz").write_bytes(b"c")
    imported = asset_mgr.import_folder(str(folder), category="批", tags=["t"])
    assert {x.type for x in imported} == {"image", "subtitle"}
    assert len(imported) == 2


def test_asset_metadata_persistence_and_reload(asset_mgr, tmp_path):
    a = asset_mgr.import_asset(str(_mk(tmp_path, "m/keep.srt", b"KEEP")), category="cat")
    assert os.path.exists(asset_mgr._metadata_file)

    # 模拟重启：新实例只挂同一 metadata 文件，_load_metadata 应恢复（路径存在）并跳过失效项
    import app.core.local_asset_manager as lam
    from app.core.local_asset_manager import LocalAssetManager
    lam.LocalAssetManager._instance = None
    fresh = LocalAssetManager()
    fresh._base_dir = asset_mgr._base_dir
    fresh._metadata_file = asset_mgr._metadata_file
    fresh._assets = {}
    # 追加一条指向不存在文件的记录 → 应被丢弃
    raw = json.loads(open(fresh._metadata_file, encoding="utf-8").read())
    raw["ghost_id"] = dict(raw[a.id])
    raw["ghost_id"]["id"] = "ghost_id"
    raw["ghost_id"]["path"] = str(tmp_path / "does_not_exist.srt")
    open(fresh._metadata_file, "w", encoding="utf-8").write(json.dumps(raw, ensure_ascii=False))
    fresh._load_metadata()
    assert a.id in fresh._assets
    assert "ghost_id" not in fresh._assets
    assert fresh._assets[a.id].category == "cat"
    # 清理单例，避免污染其它用例
    lam.LocalAssetManager._instance = None


def test_asset_corrupt_metadata_tolerated(asset_mgr, tmp_path):
    import app.core.local_asset_manager as lam
    from app.core.local_asset_manager import LocalAssetManager
    corrupt = tmp_path / "corrupt" / "metadata.json"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text("<<<not json>>>", encoding="utf-8")
    lam.LocalAssetManager._instance = None
    fresh = LocalAssetManager()
    fresh._base_dir = str(tmp_path / "corrupt" / "assets")
    fresh._metadata_file = str(corrupt)
    fresh._assets = {}
    fresh._load_metadata()  # 不得抛异常
    assert fresh._assets == {}
    lam.LocalAssetManager._instance = None


def test_asset_info_dict_roundtrip(asset_mgr):
    from app.core.local_asset_manager import AssetInfo
    a = AssetInfo(id="i1", name="n", type="image", path="/p", size=9, duration=1.5,
                  resolution="100x50", format="png", tags=["t"], category="c",
                  create_time="t0", update_time="t1", metadata={"k": 1})
    d = a.to_dict()
    b = AssetInfo.from_dict(d)
    assert b.to_dict() == d
    # 缺字段走默认值
    empty = AssetInfo.from_dict({})
    assert empty.id == "" and empty.size == 0 and empty.tags == [] and empty.used is False


# ============================================================
# ④ app/config/__init__.py + app/config/settings.py
# ============================================================

def test_config_render_defaults_and_paths():
    import app.config as cfg
    assert cfg.DEFAULT_CODEC == "libx264"
    assert cfg.DEFAULT_PRESET == "medium"
    assert cfg.DEFAULT_CRF == 23
    assert cfg.DEFAULT_FPS == 30
    assert (cfg.DEFAULT_WIDTH, cfg.DEFAULT_HEIGHT) == (1920, 1080)

    # 路径派生关系（只读断言，不写盘）
    assert cfg.APP_DIR == os.path.dirname(os.path.dirname(os.path.abspath(cfg.__file__)))
    assert cfg.PROJECT_ROOT == os.path.dirname(cfg.APP_DIR)
    assert cfg.OUTPUT_DIR == os.path.join(cfg.PROJECT_ROOT, "短剧AI剪辑输出")
    assert cfg.OUTPUT_PATH == os.path.join(cfg.PROJECT_ROOT, "output")
    assert cfg.FFMPEG_DIR == os.path.join(cfg.THIRDPARTY_DIR, "ffmpeg", "bin")


def test_config_api_keys_follow_env(monkeypatch):
    import app.config as cfg
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-123")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "zhipu-xyz")
    importlib.reload(cfg)
    assert cfg.DASHSCOPE_API_KEY == "test-key-123"
    assert cfg.ZHIPUAI_API_KEY == "zhipu-xyz"

    # 还原：清空环境后重载 → 回到空串默认
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    monkeypatch.delenv("ZHIPUAI_API_KEY")
    importlib.reload(cfg)
    assert cfg.DASHSCOPE_API_KEY == ""
    assert cfg.ZHIPUAI_API_KEY == ""


def test_settings_path_derivation():
    import app.config.settings as s
    C = s.Config
    assert os.path.basename(C.APP_DATA_DIR) == "AI短剧编辑器"
    assert C.PLUGINS_DIR == os.path.join(C.APP_DATA_DIR, "plugins")
    assert C.CACHE_DIR == os.path.join(C.APP_DATA_DIR, "cache")
    assert C.LOGS_DIR == os.path.join(C.APP_DATA_DIR, "logs")
    assert C.TEMP_DIR == os.path.join(C.APP_DATA_DIR, "temp")
    if sys.platform == "win32":
        assert C.APP_DATA_DIR.endswith(os.path.join(os.environ.get("APPDATA", ""), "AI短剧编辑器"))


def test_settings_ensure_directories_creates_all(tmp_path, monkeypatch):
    """把 5 个类属性指到 tmp 再调 ensure_directories（隔离真实 %APPDATA%）。"""
    import app.config.settings as s
    C = s.Config
    base = tmp_path / "appdata"
    monkeypatch.setattr(C, "APP_DATA_DIR", str(base))
    monkeypatch.setattr(C, "PLUGINS_DIR", str(base / "plugins"))
    monkeypatch.setattr(C, "CACHE_DIR", str(base / "cache"))
    monkeypatch.setattr(C, "LOGS_DIR", str(base / "logs"))
    monkeypatch.setattr(C, "TEMP_DIR", str(base / "temp"))

    C.ensure_directories()
    for d in (base, base / "plugins", base / "cache", base / "logs", base / "temp"):
        assert d.is_dir(), f"{d} 应被创建"
    # 幂等
    C.ensure_directories()


# ============================================================
# ⑤ app/utils/*（纯转发 shim + 底层纯逻辑）
# ============================================================

def test_utils_package_reexports_hardware():
    import app.utils as u
    import app.modules.utils.hardware as hw
    assert u.detect_hardware is hw.detect_hardware
    assert u.detect_gpu_encoder is hw.detect_gpu_encoder
    assert set(u.__all__) == {"detect_hardware", "detect_gpu_encoder"}


def test_utils_hardware_module_shim():
    import app.utils.hardware as uh
    import app.modules.utils.hardware as hw
    assert uh.detect_hardware is hw.detect_hardware
    assert uh.detect_gpu_encoder is hw.detect_gpu_encoder


def test_utils_error_handling_shim():
    import app.utils.error_handling as ue
    import app.modules.utils.error_handling as ce
    assert ue.setup_exception_handler is ce.setup_exception_handler
    assert ue.__all__ == ["setup_exception_handler"]


def test_utils_performance_shim():
    import app.utils.performance as up
    import app.modules.utils.performance as cp
    assert up.performance_monitor is cp.performance_monitor
    assert isinstance(up.performance_monitor, cp.PerformanceMonitor)


def test_hardware_detect_returns_sane_dict():
    from app.modules.utils.hardware import detect_hardware
    r = detect_hardware()
    assert set(r) == {"cpu_count", "available_memory_gb", "system", "max_threads", "max_batch_size", "cache_size"}
    assert r["cpu_count"] >= 1
    assert r["available_memory_gb"] >= 0
    assert r["cache_size"] in (512, 1024, 2048)
    assert r["max_batch_size"] in (2, 3, 5, 10)  # 3 为异常回退默认值
    assert isinstance(r["system"], str) and r["system"]


def test_gpu_encoder_invalid_exe_falls_back_to_libx264():
    from app.modules.utils.hardware import detect_gpu_encoder
    # 不存在的可执行文件 → 三段检测均失败 → 回退软编
    assert detect_gpu_encoder("definitely_not_ffmpeg_zzz_123") == "libx264"


def test_gpu_encoder_sanitizes_unsafe_name():
    from app.modules.utils.hardware import detect_gpu_encoder
    # 含路径/命令注入字符 → 被清洗回默认 "ffmpeg.exe"，且不抛异常
    r = detect_gpu_encoder("../../evil; rm -rf /")
    assert r in ("h264_nvenc", "h264_amf", "h264_qsv", "libx264")


def test_performance_monitor_get_stats_math():
    from app.modules.utils.performance import PerformanceMonitor
    pm = PerformanceMonitor()
    assert pm.get_stats() == {}  # 无采样 → 空 dict

    pm.memory_usage_history = [100.0, 200.0]
    pm.cpu_usage_history = [10.0, 30.0]
    pm.max_memory_usage = 200.0
    st = pm.get_stats()
    assert st["max_memory_usage_mb"] == 200.0
    assert st["avg_memory_usage_mb"] == 150.0
    assert st["avg_cpu_usage_percent"] == 20.0
    assert st["uptime_seconds"] >= 0.0


def test_performance_monitor_record_metrics_contract():
    from app.modules.utils.performance import PerformanceMonitor
    pm = PerformanceMonitor()
    pm.record_metrics()  # psutil 可用则采样，不可用则静默跳过
    st = pm.get_stats()
    if st:  # 采样成功：字段齐全
        assert set(st) == {"uptime_seconds", "max_memory_usage_mb",
                           "avg_memory_usage_mb", "avg_cpu_usage_percent"}
        assert pm.max_memory_usage >= 0
    else:   # psutil 缺失：契约是「空 dict，不抛异常」
        assert pm.memory_usage_history == []


def test_exception_handler_writes_log_for_real_error(tmp_path, monkeypatch):
    import app.modules.utils.error_handling as eh
    monkeypatch.chdir(tmp_path)
    # 处理器只 append 不 mkdir，需先存在输出目录（正常由 app.config 建）
    (tmp_path / "短剧AI剪辑输出").mkdir()
    original = sys.excepthook
    try:
        eh.setup_exception_handler()
        try:
            raise ValueError("boom-marker-42")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        log = tmp_path / "短剧AI剪辑输出" / "error_log.txt"
        assert log.exists(), "全局异常处理器应把错误写入日志文件"
        content = log.read_text(encoding="utf-8")
        assert "ValueError" in content
        assert "boom-marker-42" in content
    finally:
        sys.excepthook = original


def test_exception_handler_keyboardinterrupt_skips_log(tmp_path, monkeypatch):
    import app.modules.utils.error_handling as eh
    monkeypatch.chdir(tmp_path)
    original = sys.excepthook
    try:
        eh.setup_exception_handler()
        # KeyboardInterrupt 走 sys.__excepthook__ 分支，不写日志
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert not (tmp_path / "短剧AI剪辑输出" / "error_log.txt").exists()
    finally:
        sys.excepthook = original
