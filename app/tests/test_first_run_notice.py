"""app/tests/test_first_run_notice.py — 进入软件的首个提示（2026-10-06）。

**为什么要有这个提示**：本软件用机器指纹派生密钥来加密配置、做设备绑定；
指纹一变，旧密文就解不开。首启把它讲清楚并**声明责任边界**
（由此产生的数据损失与作者本人及本项目无关），是产品诚实性的一部分。

本测试锁两件事：
  ① **显示时机**：没确认过要显示；确认过不显示；**文本升版要再显示**；状态文件损坏时**宁可显示**。
  ② **内容不许被悄悄删改**：「指纹/加密/解不开/设备绑定/与作者本人及本项目无关/备份」
     这些要点是免责告知的实质，缺一条就等于没告知（故用内容锁看住）。
"""
import json

import pytest

from app.core import first_run_notice as frm


@pytest.fixture()
def state_file(tmp_path):
    return str(tmp_path / "first_run_notice.json")


# ─────────────────────── ① 显示时机 ───────────────────────

def test_show_on_fresh_install(state_file):
    assert frm.should_show(state_file) is True


def test_not_show_after_acknowledged(state_file):
    assert frm.mark_acknowledged(state_file) is True
    assert frm.should_show(state_file) is False


def test_version_bump_shows_again(state_file):
    """文本/条款有实质变化 ⇒ 老用户应**再看一次**（而不是被静默改条款）。"""
    frm.mark_acknowledged(state_file, version=1)
    assert frm.should_show(state_file, version=1) is False
    assert frm.should_show(state_file, version=2) is True


def test_corrupt_state_shows(state_file):
    """状态文件损坏 ⇒ **显示**（这是免责告知，宁可多提示一次，不可漏告知）。"""
    with open(state_file, "w", encoding="utf-8") as fh:
        fh.write("{ 这不是合法 json")
    assert frm.should_show(state_file) is True


def test_non_dict_state_shows(state_file):
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump([1, 2, 3], fh)
    assert frm.should_show(state_file) is True


def test_bad_version_value_shows(state_file):
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump({"acknowledged_version": "abc"}, fh)
    assert frm.should_show(state_file) is True


def test_mark_write_failure_is_safe(tmp_path):
    """写状态失败（如目录不可建）⇒ 返回 False 但**不抛**（绝不阻断启动）。"""
    bad = str(tmp_path / "不存在" / "\x00bad" / "x.json")
    assert frm.mark_acknowledged(bad) is False


def test_state_path_under_data_dir():
    p = frm.state_path()
    assert p.replace("\\", "/").endswith("data/first_run_notice.json")


# ─────────────────────── ② 内容锁（免责告知的实质）───────────────────────

@pytest.mark.parametrize("clause", [
    "指纹",                 # 说明机制
    "加密",                 # 说明用途
    "解不开",               # 说明后果（用大白话，而不是"解密失败"这种术语）
    "设备绑定",             # 第二类后果
    "与作者本人及本项目无关",  # ★ 责任边界（用户明确要求）
    "备份",                 # 给用户的行动建议
    "wmic",                 # 举一个真实会改变查询接口的例子
])
def test_notice_contains_required_clauses(clause):
    assert clause in frm.NOTICE_BODY, f"首启提示缺少要点：{clause}"


def test_notice_title_and_text_nonempty():
    assert frm.NOTICE_TITLE.strip()
    assert len(frm.full_text().strip()) > 120, "提示过短，难以构成有效告知"


def test_notice_version_is_positive_int():
    assert isinstance(frm.NOTICE_VERSION, int) and frm.NOTICE_VERSION >= 1


# ─────────────────────── ③ 弹窗文本渲染（HTML 转义 + 粗体）───────────────────────

def test_html_rendering_escapes_and_bolds():
    from app.modules.lego.notice_dialog import _to_html

    html = _to_html("看 **这里** 与 <script>x</script>")
    assert "<b>这里</b>" in html
    assert "<script>" not in html        # 必须转义（正文虽是我们写的，也别留坏习惯）
    assert "&lt;script&gt;" in html


def test_html_preserves_line_breaks():
    from app.modules.lego.notice_dialog import _to_html

    html = _to_html("a\nb")
    assert "white-space:pre-wrap" in html


# ─────────────────────── ④ 弹窗冒烟（不触碰真实状态文件）───────────────────────

def test_dialog_builds_without_touching_real_state(monkeypatch):
    """构造弹窗不抛异常，且**不写真实的 data/first_run_notice.json**。

    为什么要盯这一点：这条测试若真去调 mark_acknowledged()（默认路径），
    会把**用户本该看到的首启提示**永久标记为已确认 —— 测试污染产品行为。
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])   # noqa: F841

    calls = {"ack": 0}
    monkeypatch.setattr(frm, "should_show", lambda *a, **k: True)
    monkeypatch.setattr(frm, "mark_acknowledged",
                        lambda *a, **k: calls.__setitem__("ack", calls["ack"] + 1) or True)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

    from app.modules.lego.notice_dialog import show_first_run_notice

    shown = show_first_run_notice()
    assert shown is True


def test_dialog_skips_when_acknowledged(monkeypatch):
    monkeypatch.setattr(frm, "should_show", lambda *a, **k: False)
    from app.modules.lego.notice_dialog import show_first_run_notice

    assert show_first_run_notice() is False


def test_dialog_failure_never_blocks_startup(monkeypatch):
    """弹窗内部异常必须被吞掉（返回 False）—— 启动不能被提示框拖死。"""
    def boom(*a, **k):
        raise RuntimeError("模拟弹窗失败")

    monkeypatch.setattr(frm, "should_show", boom)
    from app.modules.lego.notice_dialog import show_first_run_notice

    assert show_first_run_notice() is False
