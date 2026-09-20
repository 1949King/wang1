import sys, json, urllib.request, urllib.error
sys.path.insert(0, '.')

# 1) 取 bridge token
from app.core.canvas_bridge import _SESSION_TOKEN, storyboard_breakdown

script = """第一场：黎明，城市废墟。一个穿机甲的女孩从烟雾中走出，手里攥着半块发光的芯片。
第二场：特写芯片，芯片发出蓝光，女孩的眼睛反射着光。
第三场：女孩抬头望向天空，远处有飞艇飞过。
第四场：女孩转身跑入巷弄，镜头跟拍。"""

print("=== Direct call storyboard_breakdown ===")
try:
    res = storyboard_breakdown(script)
    print(f"ok={res.get('ok')} fallback={res.get('fallback')} msg={res.get('message')}")
    shots = res.get("shots", [])
    print(f"shots count: {len(shots)}")
    for s in shots[:3]:
        print(f"  {s}")
except Exception as e:
    print(f"DIRECT EXCEPTION: {type(e).__name__}: {e}")
    import traceback; traceback.print_exc()

print("\n=== HTTP call via bridge ===")
import time
time.sleep(0.5)
try:
    body = json.dumps({"script": script}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:18765/host/storyboard-breakdown",
        data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Shiguang-Token": _SESSION_TOKEN,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"HTTP {resp.status}: ok={data.get('ok')} fallback={data.get('fallback')} shots={len(data.get('shots',[]))}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}")
except Exception as e:
    print(f"HTTP EXCEPTION: {type(e).__name__}: {e}")
