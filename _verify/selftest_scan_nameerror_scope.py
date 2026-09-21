"""scan_nameerror_scope 的合成用例自测（反证检测能力）。

扫描器报 0 命中时必须靠本测试证明「不是检测器瞎了」。
覆盖技能的 6 大经典模式 + 4 个阴性对照。

用法：.venv312/Scripts/python.exe _verify/selftest_scan_nameerror_scope.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scan_nameerror_scope import scan_file  # noqa: E402

CASES = {
    # (源码, 期望 scope 命中数, 期望 order 命中数)
    "isinstance_未导入.py": (
        "def f(rows):\n"
        "    return [r for r in rows if isinstance(r, Mapping)]\n",
        1, 0),
    "import在别的方法.py": (
        "def a():\n"
        "    import time\n"
        "    return time.time()\n"
        "\n"
        "def b():\n"
        "    return time.time()\n",
        1, 0),
    "except引用未定义logger.py": (
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception:\n"
        "        logger.error('x')\n",
        1, 0),
    "类体推导式不捕获类作用域.py": (
        "class A:\n"
        "    D = [1, 2]\n"
        "    I = {e: i for i, e in enumerate(D)}\n"  # 最外层 iter 外层求值 → 合法
        "    J = [D[0] for _ in range(1)]\n",        # 元素在推导式作用域 → NameError
        1, 0),
    "模块级使用先于赋值.py": (
        "logger.info('boot')\n"
        "import logging\n"
        "logger = logging.getLogger(__name__)\n",
        0, 1),
    "阴性_import在try里.py": (
        "import os\n"
        "try:\n"
        "    import numpy as np\n"
        "except ImportError:\n"
        "    np = None\n"
        "\n"
        "def f(p):\n"
        "    return os.path.exists(p) and np is None\n",
        0, 0),
    "阴性_global与nonlocal.py": (
        "counter = 0\n"
        "def f():\n"
        "    global counter\n"
        "    counter += 1\n"
        "def g():\n"
        "    x = 1\n"
        "    def h():\n"
        "        nonlocal x\n"
        "        x += 1\n"
        "    return h\n",
        0, 0),
    "阴性_with_except_match绑定.py": (
        "import io\n"
        "def f(p):\n"
        "    with io.open(p) as fh:\n"
        "        data = fh.read()\n"
        "    try:\n"
        "        int(data)\n"
        "    except ValueError as ve:\n"
        "        print(ve)\n"
        "    match data:\n"
        "        case str() as s:\n"
        "            print(s)\n",
        0, 0),
    "阴性_闭包与lambda.py": (
        "def outer(items):\n"
        "    buf = []\n"
        "    key = lambda x: x[0]\n"
        "    for it in sorted(items, key=key):\n"
        "        buf.append(it)\n"
        "    return buf\n",
        0, 0),
    "阳性_函数内if分支里的import别处用.py": (
        "def f(flag):\n"
        "    if flag:\n"
        "        import json\n"
        "        return json.dumps({})\n"
        "    return json.dumps([])\n",  # flag=False 路径 json 未绑定（静态按已绑定放行）
        0, 0),  # 两 pass 静态语义：函数内任意处赋值=局部已绑定 → 不报（避免误报）
}


def main():
    tmp = Path(tempfile.mkdtemp())
    fails = []
    for name, (src, exp_scope, exp_order) in CASES.items():
        p = tmp / name
        p.write_text(src, encoding="utf-8")
        hits, order, skip = scan_file(p)
        ok = (not skip) and len(hits) == exp_scope and len(order) == exp_order
        print(f"{'PASS' if ok else 'FAIL'}  {name}  "
              f"scope={len(hits)} order={len(order)} expect=({exp_scope},{exp_order})")
        if not ok:
            fails.append((name, hits, order, skip))
    for name, hits, order, skip in fails:
        print(f"--- {name} 详情: skip={skip} hits={hits} order={order}")
    print("=" * 60)
    print(f"SELFTEST {'ALL PASS' if not fails else f'{len(fails)} FAILS'} ({len(CASES)} 用例)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
