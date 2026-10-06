# -*- coding: utf-8 -*-
"""本地模型接线守卫（2026-09-30）。

钉死五件事 —— 都是「漏了不报错、只是功能悄悄失效」的类型：

  ① **画布模型列表必须并入本机 Ollama 已装模型** —— 静态表里 ollama.models 是 `[]`，
     少了这一步，用户装了 qwen 也**在下拉里选不到**（这正是本次修的 bug）。
  ② **探测必须惰性** —— `model_config` 模块顶层**不得**调用 discover/merge
     （那会在 import 期同步打一次 Ollama，实测约 2.1s，把冷启动从 ~1s 打回 ~3s）。
  ③ **默认模型不得硬编码版本号** —— 原先写死 `qwen2:7b`，本机没装 ⇒ 必然 404。
  ④ **用户可见文案不得推荐过时模型名**（如 `qwen2.5:7b`）。
  ⑤ 探测失败**不得抛异常**（Ollama 没装也要能正常启动）。

零项目依赖：只读源码 + AST，不 import app 包。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MC_REL = os.path.join("app", "modules", "lego", "model_config.py")
HOST_REL = os.path.join("app", "core", "project_agent_host.py")
PROV_REL = os.path.join("app", "modules", "lego", "cloud_providers", "providers.py")

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def main() -> int:
    print("== 本地模型接线守卫 ==")

    mc = _read(MC_REL)
    host = _read(HOST_REL)
    prov = _read(PROV_REL)

    # ① 画布模型列表并入本地模型
    check("model_config 提供 discover_local_models",
          "def discover_local_models(" in mc)
    check("model_config 提供 merge_local_models_into_providers",
          "def merge_local_models_into_providers(" in mc)
    check("画布 list_chat_models 调用了 merge_local_models_into_providers",
          "merge_local_models_into_providers()" in host)

    # ② import 期不得探测（冷启动纪律）
    top_level = []
    tree = ast.parse(mc)
    for node in tree.body:                       # 只看模块级语句
        if isinstance(node, ast.Expr):
            try:
                top_level.append(ast.unparse(node))
            except Exception:
                pass
    banned = [ln for ln in top_level
              if "discover_local_models" in ln
              or "merge_local_models_into_providers" in ln]
    check("★ import 期不探测 Ollama（保冷启动 ~1s）", not banned, str(banned))
    check("模块顶层仍保留 merge_aigc_into_providers()（既有行为不变）",
          any("merge_aigc_into_providers()" in ln for ln in top_level))

    # ③ 默认模型不硬编码版本号
    m = re.search(r"class OllamaProvider\b.*?(?=\nclass |\Z)", prov, re.S)
    check("OllamaProvider 类可定位", bool(m))
    if m:
        body = m.group(0)
        dm = re.search(r"def default_model\(self\).*?(?=\n    @|\n    def |\Z)",
                       body, re.S)
        check("OllamaProvider.default_model 可定位", bool(dm))
        if dm:
            seg = dm.group(0)
            hard = re.search(r'return\s+"[^"]*:[^"]*"', seg)   # 形如 "xxx:yyy"
            check("★ 默认模型不再硬编码 `名字:标签` 版本号",
                  not hard, hard.group(0) if hard else "")
            check("默认模型优先取本机已装（调用 discover_local_models）",
                  "discover_local_models" in seg)

    # ④ 用户可见文案不得推荐过时模型
    #    （注释/docstring 里提历史不算；查的是**字符串字面量**）
    stale = []
    for rel in (MC_REL, PROV_REL, HOST_REL,
                os.path.join("app", "modules", "lego", "model_card.py"),
                os.path.join("app", "core", "ai", "llm_clipper.py")):
        try:
            src = _read(rel)
        except OSError:
            continue
        for s in re.findall(r'"([^"\n]{6,})"', src):
            if "ollama pull" in s and re.search(r"qwen\d[\d.]*:\s*\d", s):
                stale.append(f"{os.path.basename(rel)}: {s[:48]}")
    check("★ 不向用户推荐过时模型名（ollama pull <旧版本>）", not stale, str(stale))

    # ⑤ 探测失败不抛异常
    dm_func = re.search(r"def discover_local_models\(.*?(?=\ndef |\n_local|\Z)",
                        mc, re.S)
    check("discover_local_models 有异常兜底（except -> 返回空）",
          bool(dm_func) and "except Exception" in dm_func.group(0))

    print()
    if _fails:
        print(f"FAILED {len(_fails)}: {_fails}")
        return 1
    print("OK 本地模型接线一致（画布可列出自部署模型）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
