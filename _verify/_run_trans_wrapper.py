# -*- coding: utf-8 -*-
"""wrapper：subprocess 跑内层验证，规避沙箱 wmic 污染 stdout"""
import subprocess, sys, os

ROOT = r"d:\拾光剪影"
PY = os.path.join(ROOT, ".venv312", "Scripts", "python.exe")
INNER = os.path.join(ROOT, "_verify", "check_transitions.py")
OUT = os.path.join(ROOT, "_verify", "_trans_clean.txt")

r = subprocess.run([PY, INNER], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", cwd=ROOT)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("=== STDOUT ===\n")
    f.write(r.stdout or "(empty)")
    f.write("\n=== STDERR ===\n")
    f.write(r.stderr or "(empty)")
    f.write(f"\n=== EXIT {r.returncode} ===\n")
print("done", r.returncode)
