# -*- coding: utf-8 -*-
"""校验 shiguang-genre.json 题材设定包：文件存在、JSON 合法、四要素齐全、双库三处一致、promptLibrary 已注册。"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

MAIN = r"D:\拾光剪影\vendor\shiguang-canvas"
SUB = r"D:\拾光剪影\vendor\AI-Canvas-tauri"

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  " + detail if detail else ""))
    if not cond:
        fails.append(name)

# 1) 主库 JSON 合法 + 结构
data = json.load(open(MAIN + r"\public\prompts\shiguang-genre.json", encoding="utf-8"))
check("条目数==8", len(data) == 8, f"实际 {len(data)}")
check("字段集合==5", all(set(x) == {"id", "title", "category", "tags", "prompt"} for x in data))
check("category 全为 genre", all(x["category"] == "genre" for x in data))
check("id 唯一", len({x["id"] for x in data}) == len(data))
check("四要素齐全(世界观/主线/角色位/禁忌)",
      all(all(k in x["prompt"] for k in ("世界观", "主线", "角色位", "禁忌")) for x in data))
check("含 LibTV 对标四题材",
      all(any(k in x["title"] for x in data) for k in ("末世生存", "重生复仇", "非遗国潮", "仙门团宠")))

# 2) 双库三处字节一致
main_bytes = open(MAIN + r"\public\prompts\shiguang-genre.json", "rb").read()
for label, p in [("副库 public", SUB + r"\public\prompts\shiguang-genre.json"),
                 ("副库 dist", SUB + r"\dist\prompts\shiguang-genre.json")]:
    try:
        check(f"双库一致[{label}]", open(p, "rb").read() == main_bytes)
    except FileNotFoundError:
        check(f"双库一致[{label}]", False, "文件不存在")

# 3) promptLibrary.ts 双库均已注册
for label, p in [("主库", MAIN + r"\src\promptLibrary.ts"),
                 ("副库", SUB + r"\src\libtv\promptLibrary.ts")]:
    src = open(p, encoding="utf-8").read()
    check(f"已注册[{label}]", '"shiguang-genre-pack"' in src and '"shiguang-genre.json"' in src)

print()
print("RESULT:", "ALL_PASS" if not fails else f"FAILURES={fails}")
sys.exit(1 if fails else 0)
