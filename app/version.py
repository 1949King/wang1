__version__ = "4.40.56"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 40,
    "patch": 56,
    "codename": "门禁加固",
    "release_date": "2026-10-07",
    "description": (
        "V4.40.56: 门禁加固 —— ruff 卡点由「整文件判定」改为**逐文件存量棘轮**（非功能变更）。"
        "本轮固化 16 天累积改动时，hook ① 把 11 个遗留文件的 237 处**历史**违规当成「本次新增」"
        "拦下，其中 `app/modules/lego/editor_module.py`（冻结区、9479 行、50 处存量违规）"
        "**等于核心文件永远无法提交**。实测归因：白名单下 167 个文件带 1016 处存量违规，"
        "而这些文件最后一次提交多在 2026-09-21/22，早于 hook 诞生（09-26），从未被扫过。"
        "改法：按 stability_gate 的既有范式做逐文件基线棘轮"
        "（`scripts/ruff_gate.py` + `docs/knowledge/ruff_gate_baseline.json`）。"
        "**门禁未放松**：新文件 >0 违规、或已有文件超过其基线，一律拦；"
        "逐文件（而非全局计数）防此消彼长；`--update` 抬高既有权或为新文件建基线需显式 `--force`。"
        "上一版 V4.40.55「机位电影级视锥」见 docs/CHANGELOG.md。"
    ),
}
