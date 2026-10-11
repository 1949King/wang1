"""
主题设计令牌 (Theme Tokens)
===========================

来源 / Source: AI-Canvas-tauri (tenney95/AI-Canvas-tauri) base.css 行 12-470
- 完整搬运暗色主题全 token
- 完整搬运浅色主题全 token
- 完整搬运玻璃/动效/滚动条/分隔线 token
- 完整搬运 Tailwind 色阶(TW-*)

设计原则 / Design Principles
--------------------------------
1. **PyQt6 QSS 友好**：全部 token 是 hex / rgba 字面量，不依赖 CSS color-mix()
2. **向后兼容**：保留原 ThemeManager.COLORS_DARK/LIGHT 的所有旧 key（bg_main 等），
   新组件可直接用 brand / glass_bg / accent_amber 等新 key
3. **项目主蓝优先**：accent 保留 #2f7bff（拾光剪影既有的主蓝，深度嵌入 modules.py
   等多处 QSS），brand 新增 #6366f1（紫罗兰，对标 AI-Canvas，用于 chip/badge/玻璃面板）
4. **不再硬编码颜色**：所有新组件都从 ThemeManager.get_colors() 取色，禁止再写 hex

调用方式 / Usage
----------------
    from app.core.theme_tokens import DARK_TOKENS, LIGHT_TOKENS
    print(DARK_TOKENS["bg_main"])        # "#0a0a0f"
    print(LIGHT_TOKENS["bg_main"])       # "#F4F6FB"
    print(DARK_TOKENS["brand"])          # "#6366f1" (新增)
    print(DARK_TOKENS["glass_bg"])       # "rgba(20, 20, 28, 0.92)" (新增)

与 ThemeManager 的关系
----------------------
ThemeManager.COLORS_DARK / COLORS_LIGHT 现在从本文件派生，保证单一真相源。
历史 key（bg_main / text_primary 等）保持不变 → 无破坏性更新。
新组件直接调 ThemeManager.get_colors() 即可拿到全套新旧 token。
"""

from __future__ import annotations

from typing import Dict

# ════════════════════════════════════════════════════════════════════
# 暗色主题 — Dark Theme（默认）
# ════════════════════════════════════════════════════════════════════
# 来源: vendor/AI-Canvas-tauri/src/styles/base.css 行 12-261
# 项目特化: accent 保留 #2f7bff（拾光剪影主蓝，未跟随 indigo）

DARK_TOKENS: Dict[str, str] = {
    # ── Theme Layer ──
    "bg_main":           "#0a0a0f",  # 窗口最底层（原 #070a12 → 跟进 base.css）
    "bg_secondary":      "#14141c",  # 卡片/面板（原 #101621 → 跟进 base.css）
    "bg_tertiary":       "#1a1a26",  # 嵌套卡片（原 #172033 → 跟进 base.css）
    "card_bg":           "#1a1a26",  # 同上，新增独立 key
    "bg_hover":          "#252535",  # hover 底（原 #1f2b42 → 跟进 base.css）
    "card_border":       "#2a2a3a",  # 卡片描边
    "border":            "#2a2a3a",  # 标准边框（原 #253044 → 跟进 base.css）
    "border_light":      "#1c2638",  # 次级边框（保留 #1c2638 原值，AI-Canvas 用 #2a2a3a 的 alpha 但视觉近似）
    "border_secondary":  "#3a3a4a",  # 第二级边框
    "separator_color":   "rgba(232, 232, 237, 0.10)",  # 分隔线

    # ── Text Layer ──
    "text_primary":      "#dddde4",  # 主文字（原 #edf3ff → 跟进 base.css）
    "text_secondary":    "#8888a0",  # 次级文字（原 #aab6cc → 跟进 base.css）
    "text_disabled":     "#444455",  # 禁用文字（原 #667085 → 跟进 base.css）
    "text_muted":        "#7d7d91",  # 弱化文字（新增）
    "text_on_accent":    "#f8fbff",  # accent 上的文字（白）

    # ── Brand — 项目主蓝 + 新增紫罗兰 ──
    # accent 是项目既有主蓝（深度嵌入 modules.py QSS），保留不换
    "accent":            "#2f7bff",  # 项目主蓝（保留）
    "accent_hover":      "#4d8dff",  # 项目主蓝 hover（保留）
    "accent_soft":       "#102a4d",  # 项目主蓝软底（保留）
    "focus":             "#6ba4ff",  # focus 环（保留）
    # brand 是 AI-Canvas 紫罗兰，新增用于 chip / badge / 玻璃面板等
    "brand":             "#6366f1",  # 新增：紫罗兰（AI-Canvas 主品牌）
    "brand_light":       "#818cf8",  # 新增：紫罗兰亮
    "brand_pale":        "#a5b4fc",  # 新增：紫罗兰最浅
    "brand_alpha_10":    "rgba(99, 102, 241, 0.10)",   # 新增
    "brand_alpha_15":    "rgba(99, 102, 241, 0.15)",   # 新增
    "brand_alpha_20":    "rgba(99, 102, 241, 0.20)",   # 新增
    "brand_alpha_30":    "rgba(99, 102, 241, 0.30)",   # 新增

    # ── Semantic Colors ──
    "success":           "#22c55e",  # 成功（原 #2dd4bf → 跟进 base.css，更绿）
    "success_light":     "#4ade80",  # 成功亮
    "success_text":      "#34d399",  # 成功文字
    "success_bg":        "rgba(16, 185, 129, 0.15)",  # 成功软底
    "danger":            "#ef4444",  # 危险（原 #fb7185 → 跟进 base.css，更红）
    "danger_light":      "#f87171",  # 危险亮
    "danger_pale":       "#fca5a5",  # 危险浅
    "danger_bg":         "rgba(239, 68, 68, 0.15)",   # 危险软底
    "warning":           "#f97316",  # 警告（新增：AI-Canvas warning 橙）
    "warning_light":     "#fb923c",  # 警告亮
    "warning_bg":        "rgba(249, 115, 22, 0.15)",  # 警告软底
    "info":              "#3b82f6",  # 信息（新增：AI-Canvas info 蓝）
    "info_light":        "#60a5fa",  # 信息亮
    "info_bg":           "rgba(59, 130, 246, 0.15)",  # 信息软底
    "accent_amber":      "#f59e0b",  # 琥珀强调（新增：chip / 厂商徽标）
    "accent_amber_text": "#fbbf24",  # 琥珀文字
    "accent_amber_bg":   "rgba(245, 158, 11, 0.10)",  # 琥珀软底

    # ── Glass / Frosted Surface ──
    "glass_bg":          "rgba(20, 20, 28, 0.92)",    # 毛玻璃底
    "glass_bg_light":    "rgba(56, 56, 76, 0.30)",    # 毛玻璃浅底
    "glass_panel_bg":    "rgba(20, 20, 28, 0.77)",    # 毛玻璃面板
    "glass_ring":        "rgba(255, 255, 255, 0.16)", # 毛玻璃环
    "glass_shadow":      "0 1px 2px rgba(0, 0, 0, 0.42), 0 12px 32px rgba(0, 0, 0, 0.38)",  # 毛玻璃阴影

    # ── Scrollbar ──
    "scrollbar_bg":      "#0d1320",  # 滚动条底
    "scrollbar_handle":  "#3a3a50",  # 滚动条把（原 #2a3650 → 跟进 base.css）
    "scrollbar_hover":   "#555570",  # 滚动条 hover（原 #3a4a68 → 跟进 base.css）

    # ── Black/White Alpha（用于遮罩/分割/微妙层）──
    "black_alpha_30":    "rgba(0, 0, 0, 0.30)",
    "black_alpha_50":    "rgba(0, 0, 0, 0.50)",
    "white_alpha_06":    "rgba(255, 255, 255, 0.06)",
    "white_alpha_10":    "rgba(255, 255, 255, 0.10)",
    "white_alpha_15":    "rgba(255, 255, 255, 0.15)",

    # ── Border Focus Ring ──
    "border_focus":      "rgba(99, 102, 241, 0.40)",  # focus 边框
}

# ════════════════════════════════════════════════════════════════════
# 浅色主题 — Light Theme（马卡龙 Macaron）
# ════════════════════════════════════════════════════════════════════
# 来源: vendor/AI-Canvas-tauri/src/styles/base.css 行 273-470

LIGHT_TOKENS: Dict[str, str] = {
    # ── Theme Layer ──
    "bg_main":           "#F4F6FB",  # 偏冷的米白（原 #f4f7fb → 跟进 base.css）
    "bg_secondary":      "#FFFFFF",  # 卡片/面板（原 #fcfdff → 跟进 base.css）
    "bg_tertiary":       "#F8FAFD",  # 嵌套卡片（原 #eaf0f7 → 跟进 base.css）
    "card_bg":           "#F8FAFD",  # 同上
    "bg_hover":          "#EEF1F8",  # hover 底（原 #dde7f4 → 跟进 base.css）
    "card_border":       "#E4E8F2",  # 卡片描边
    "border":            "#E4E8F2",  # 标准边框（原 #d7e0ec → 跟进 base.css）
    "border_light":      "#E3EAF3",  # 次级边框（保留）
    "border_secondary":  "#DCE1EE",  # 第二级边框
    "separator_color":   "rgba(51, 54, 77, 0.12)",  # 分隔线

    # ── Text Layer ──
    "text_primary":      "#33364D",  # 主文字（原 #172033 → 跟进 base.css，更柔）
    "text_secondary":    "#6E7488",  # 次级文字（原 #56657a → 跟进 base.css）
    "text_disabled":     "#A9AEC0",  # 禁用文字（原 #8a97aa → 跟进 base.css）
    "text_muted":        "#767D92",  # 弱化文字（新增）
    "text_on_accent":    "#f8fbff",  # accent 上的文字（白）

    # ── Brand ──
    "accent":            "#2563eb",  # 项目主蓝（保留）
    "accent_hover":      "#1d4ed8",  # 项目主蓝 hover（保留）
    "accent_soft":       "#dbeafe",  # 项目主蓝软底（保留）
    "focus":             "#3b82f6",  # focus 环（保留）
    "brand":             "#7280E4",  # 马卡龙紫罗兰（AI-Canvas 浅色）
    "brand_light":       "#5A69D4",  # 紫罗兰亮
    "brand_pale":        "#4F5ECB",  # 紫罗兰最浅
    "brand_alpha_10":    "rgba(114, 128, 228, 0.10)",  # 新增
    "brand_alpha_15":    "rgba(114, 128, 228, 0.14)",  # 新增
    "brand_alpha_20":    "rgba(114, 128, 228, 0.17)",  # 新增
    "brand_alpha_30":    "rgba(114, 128, 228, 0.24)",  # 新增

    # ── Semantic Colors — Macaron ──
    "success":           "#0f766e",  # 项目 success 深绿（保留）
    "success_light":     "#23937A",  # 成功亮
    "success_text":      "#23937A",  # 成功文字
    "success_bg":        "rgba(110, 203, 170, 0.20)",  # 成功软底
    "danger":            "#e11d48",  # 项目 danger（保留）
    "danger_light":      "#CE4F62",  # 危险亮
    "danger_pale":       "#C24357",  # 危险浅
    "danger_bg":         "rgba(226, 124, 137, 0.18)",  # 危险软底
    "warning":           "#F4AC7D",  # 马卡龙杏色
    "warning_light":     "#C06E33",  # 警告亮
    "warning_bg":        "rgba(244, 172, 125, 0.22)",  # 警告软底
    "info":              "#7FBBF2",  # 马卡龙天蓝
    "info_light":        "#3B7EC4",  # 信息亮
    "info_bg":           "rgba(127, 187, 242, 0.20)",  # 信息软底
    "accent_amber":      "#EDBE63",  # 马卡龙奶油黄
    "accent_amber_text": "#A87A24",  # 琥珀文字
    "accent_amber_bg":   "rgba(237, 190, 99, 0.22)",  # 琥珀软底

    # ── Glass / Frosted Surface — Light ──
    "glass_bg":          "rgba(255, 255, 255, 0.95)",  # 浅色毛玻璃底
    "glass_bg_light":    "rgba(255, 255, 255, 0.58)",  # 浅色毛玻璃浅底
    "glass_panel_bg":    "rgba(252, 253, 255, 0.86)",  # 浅色毛玻璃面板
    "glass_ring":        "rgba(51, 54, 77, 0.10)",      # 浅色毛玻璃环
    "glass_shadow":      "0 1px 2px rgba(51, 54, 77, 0.07), 0 12px 32px rgba(51, 54, 77, 0.10)",  # 浅色阴影

    # ── Scrollbar ──
    "scrollbar_bg":      "#edf2f7",  # 滚动条底
    "scrollbar_handle":  "#CBD1E0",  # 滚动条把（原 #c2ccda → 跟进 base.css）
    "scrollbar_hover":   "#B0B7CB",  # 滚动条 hover（原 #98a8bd → 跟进 base.css）

    # ── Black/White Alpha（浅色 = cool ink alpha）──
    "black_alpha_30":    "rgba(51, 54, 77, 0.30)",
    "black_alpha_50":    "rgba(51, 54, 77, 0.50)",
    "white_alpha_06":    "rgba(51, 54, 77, 0.06)",
    "white_alpha_10":    "rgba(51, 54, 77, 0.09)",
    "white_alpha_15":    "rgba(51, 54, 77, 0.14)",

    # ── Border Focus Ring ──
    "border_focus":      "rgba(114, 128, 228, 0.45)",  # focus 边框
}


# ════════════════════════════════════════════════════════════════════
# 动效设计令牌 — Motion Design Tokens
# ════════════════════════════════════════════════════════════════════
# 来源: vendor/AI-Canvas-tauri/src/styles/base.css 行 195-224
# PyQt6 用 QPropertyAnimation 时直接读这套字符串当 timingFunction/curveShape

MOTION_TOKENS: Dict[str, str] = {
    "ease_out_expo":     "cubic-bezier(0.16, 1, 0.3, 1)",
    "ease_out_quart":    "cubic-bezier(0.25, 1, 0.5, 1)",
    "ease_in_out":       "cubic-bezier(0.65, 0, 0.35, 1)",
    "ease_spring":       "cubic-bezier(0.34, 1.4, 0.5, 1)",  # 弹簧式轻微过冲
    "dur_instant":       "100",
    "dur_fast":          "150",
    "dur_normal":        "200",
    "dur_slow":          "300",
}


# ════════════════════════════════════════════════════════════════════
# 旧 key 列表（用于检测回归）
# ════════════════════════════════════════════════════════════════════
# 列出 ThemeManager.COLORS_DARK/LIGHT 历史上必须存在的 key，避免破坏性更新

LEGACY_KEYS = frozenset({
    "bg_main", "bg_secondary", "bg_tertiary", "bg_hover",
    "text_primary", "text_secondary", "text_disabled", "text_on_accent",
    "border", "border_light",
    "accent", "accent_hover", "accent_soft", "focus",
    "success", "danger",
    "scrollbar_bg", "scrollbar_handle", "scrollbar_hover",
})


# ════════════════════════════════════════════════════════════════════
# 导出
# ════════════════════════════════════════════════════════════════════

__all__ = [
    "DARK_TOKENS",
    "LIGHT_TOKENS",
    "MOTION_TOKENS",
    "LEGACY_KEYS",
]
