# -*- coding: utf-8 -*-
"""从 Unihan 生成 pypinyin 缺口补丁表（正式工具，可重复运行）。

用法：
  1. 下载 https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip
     到 %TEMP%/Unihan.zip
  2. python scripts/gen_unihan_pinyin_patch.py
  3. python _verify/check_pinyin_dict.py  复核

何时重跑：Unihan 发布新版本 / 调整筛选口径 / 补丁表损坏时。
产物：app/core/ai/pinyin_unihan_patch.py（编译进代码，零打包配置）

产物：app/core/ai/pinyin_unihan_patch.py（编译进代码，零打包配置）
"""
import io
import os
import sys
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pypinyin import Style, lazy_pinyin  # noqa: E402

ZIP = os.path.join(os.environ.get("TEMP", "/tmp"), "Unihan.zip")
OUT = os.path.join(ROOT, "app", "core", "ai", "pinyin_unihan_patch.py")

# ── 1) 解析 kMandarin + 版本信息 ──
version_note = ""
km: dict = {}
with zipfile.ZipFile(ZIP) as z:
    name = [n for n in z.namelist() if "Readings" in n][0]
    with z.open(name) as f:
        for line in io.TextIOWrapper(f, encoding="utf-8"):
            if line.startswith("#") and not version_note:
                cand = line.strip("# \n")
                if "Unihan" in cand or "Version" in cand:
                    version_note = cand
            if "\tkMandarin\t" not in line:
                continue
            cp, _f, val = line.rstrip("\n").split("\t", 2)
            ch = chr(int(cp[2:], 16))
            v = val.strip()
            if v:
                km[ch] = v

print("Unihan 版本注释:", version_note[:120] or "(未读到)")
print("kMandarin 总条目:", len(km))

# ── 2) 只保留 pypinyin 查不到的字 ──
patch: dict = {}
for ch, v in km.items():
    cp = ord(ch)
    if not (0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or cp >= 0x20000):
        continue
    r = lazy_pinyin(ch, style=Style.TONE)
    if r and r[0] != ch:
        continue                      # pypinyin 已有 → 不进补丁
    patch[ch] = v

print("补丁条数:", len(patch))
blocks = {"扩展A": 0, "扩展B+": 0, "其他": 0}
for ch in patch:
    cp = ord(ch)
    if 0x3400 <= cp <= 0x4DBF:
        blocks["扩展A"] += 1
    elif cp >= 0x20000:
        blocks["扩展B+"] += 1
    else:
        blocks["其他"] += 1
print("分布:", blocks)

# ── 3) 生成 .py（ascii 转义，避免非 BMP 字符在编辑器里出错）──
items = sorted(patch.items(), key=lambda kv: ord(kv[0]))
lines = []
buf = []
for ch, py in items:
    buf.append(f'    "\\U{ord(ch):08X}": "{py}",')
    if len(buf) == 4:
        lines.append("".join(buf))
        buf = []
if buf:
    lines.append("".join(buf))

header = f'''# -*- coding: utf-8 -*-
"""pypinyin 缺口补丁表 —— 由 Unihan 数据库生成（**自动生成，勿手改**）

来源：Unicode 官方 Unihan 数据库 kMandarin 字段（普通话读音）
      {version_note or "UCD latest"}
生成方法：scripts 侧一次性脚本 `_gen_unihan_patch.py`（临时工具，生成后删除）：
  1. 解压 Unihan.zip → Unihan_Readings.txt
  2. 取全部 kMandarin（{len(km)} 条），NFC 规范化为带声调拼音
  3. **仅保留 pypinyin 已查不到的字**（避免与主词典重复、表最小化）
  4. 按码点升序输出为本文件的 dict 字面量

为什么编译进 .py 而非 JSON：
  · `data/*.json` 被 .gitignore 排除（进不了仓库）
  · PyInstaller 打包需额外配置数据文件；编译进代码则零配置、必定随包发布
  · 项目既有先例：pypinyin 自身也是把词典编译进 .py

覆盖统计（生成时实测）：共 {len(patch)} 条 —— 扩展 A {blocks["扩展A"]} · 扩展 B+ {blocks["扩展B+"]} · 其他 {blocks["其他"]}
消费方：app/core/ai/pinyin_dict.py 的 `_load_unihan_patch()`（仅在主字典查不到时兜底）

⚠️ 数据性质：Unihan kMandarin 是**Unicode 官方字段**，但部分生僻字读音存在
   古音/异读争议；查得即用，查不到仍标 unknown —— **绝不编造读音**。
"""

# 码点 → 带声调拼音（键为字符本身，生成时用 \\UXXXXXXXX 转义）
UNIHAN_K_MANDARIN_PATCH: dict = {{
'''

tail = '''}
'''

with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write(header + "\n".join(lines) + "\n" + tail)

size = os.path.getsize(OUT)
print(f"\n已写出: {OUT}")
print(f"体积: {size / 1024:.1f} KB")

# ── 4) 自校验：重新加载并抽查 ──
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("_unihan_patch_check", OUT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
loaded = mod.UNIHAN_K_MANDARIN_PATCH
print(f"回读校验: {len(loaded)} 条（与生成数一致: {len(loaded) == len(patch)}）")
sample = list(loaded.items())[:5]
print("样例:", [(c, p) for c, p in sample])
