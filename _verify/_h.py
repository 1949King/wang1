import json, hashlib
from pathlib import Path
root = Path(r"D:\拾光剪影")
rel = "vendor/packages/canvas-core/src/styles.css"
def sha(t):
    return hashlib.sha256((t.replace("\r\n","\n").strip()+"\n").encode()).hexdigest()[:16]
cur = sha((root/rel).read_text(encoding="utf-8"))
base = json.loads((root/"docs/knowledge/frozen_zones.hashes.json").read_text(encoding="utf-8"))["hashes"].get("file:"+rel)
print("current :", cur)
print("baseline:", base)
print("MATCH" if cur == base else "DRIFT (baseline is stale)")
