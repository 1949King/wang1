# -*- coding: utf-8 -*-
"""正式启动 canvas_bridge (使用项目 venv)"""
import sys, time
sys.path.insert(0, r'd:\拾光剪影')
from app.core.canvas_bridge import CanvasBridgeServer, session_token

PORT = 18765
TOKEN_FILE = r'd:\拾光剪影\.bridge_token'

s = CanvasBridgeServer(port=PORT)
s.start()
time.sleep(2)
tok = session_token()

with open(TOKEN_FILE, 'w') as f:
    f.write(tok)

print(f'✅ canvas_bridge on http://127.0.0.1:{PORT}')
print(f'✅ token={tok[:12]}...  PyQt6 OK')
sys.stdout.flush()

try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    pass
