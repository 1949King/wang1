import sys, json, urllib.request, urllib.error, time

# 从运行中的 bridge health 拿到 session token？不，直接读 canvas_runtime 生成 token 的方式
sys.path.insert(0, '.')
from app.core.canvas_bridge import _SESSION_TOKEN

print(f"Script-side _SESSION_TOKEN = {_SESSION_TOKEN[:20]}...")

# 但 PyQt6 里的 bridge 用的是它自己生成的 token
# 看 health 接口能不能拿到实际 session
try:
    with urllib.request.urlopen("http://127.0.0.1:18765/health", timeout=5) as resp:
        h = json.loads(resp.read().decode())
        print(f"bridge health: {h}")
except Exception as e:
    print(f"health fail: {e}")

# 试下 query string token 方式（前端 inject 注入的 token 跟 bridge 一致）
# 其实 Python 脚本里的 _SESSION_TOKEN 应该就是同一个模块——如果 PyQt6 进程加载了这个模块
# 那就应该是同一个 token。让我用 HTTP /host/storyboard-breakdown?token=xxx 试试
script = "第一场：女孩走进城市废墟。\n第二场：特写芯片发光。"

# 方式 A: body + header (标准前端方式)
try:
    body = json.dumps({"script": script}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:18765/host/storyboard-breakdown?token={urllib.parse.quote(_SESSION_TOKEN)}",
        data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Shiguang-Token": _SESSION_TOKEN,
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        dt = time.time() - t0
        print(f"[A] HTTP {resp.status} ({dt:.1f}s): ok={data.get('ok')} shots={len(data.get('shots',[]))} fallback={data.get('fallback')}")
except urllib.error.HTTPError as e:
    dt = time.time() - t0
    body_text = e.read().decode("utf-8", errors="replace")[:300]
    print(f"[A] HTTP {e.code} ({dt:.1f}s): {body_text}")
except Exception as e:
    print(f"[A] EXCEPTION: {type(e).__name__}: {e}")
