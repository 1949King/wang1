from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import subprocess
from datetime import datetime

app = FastAPI(
    title="MCP Server",
    description="Model Context Protocol Server for AI 短剧编辑器",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 读取配置
config = {
    "mcps": [
        {
            "name": "filesystem",
            "enabled": True,
            "config": {
                "root_path": ".",
                "read_only": False,
                "allowed_extensions": ["py", "json", "txt", "md", "jpg", "png", "mp4", "mp3"]
            }
        },
        {
            "name": "git",
            "enabled": True,
            "config": {
                "repository_path": ".",
                "auto_commit": False
            }
        },
        {
            "name": "puppeteer",
            "enabled": True,
            "config": {
                "headless": True,
                "timeout": 60000
            }
        },
        {
            "name": "brave-search",
            "enabled": True,
            "config": {
                "api_key": "",
                "timeout": 30000
            }
        },
        {
            "name": "memory",
            "enabled": True,
            "config": {
                "storage_path": ".trae/memory",
                "max_items": 1000
            }
        },
        {
            "name": "fetch",
            "enabled": True,
            "config": {
                "timeout": 30000,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        }
    ]
}

# 内存存储
memory_store = {}

# 健康检查
@app.get("/")
async def root():
    return {
        "message": "MCP Server is running",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "available_extensions": [mcp["name"] for mcp in config["mcps"] if mcp["enabled"]]
    }

# Filesystem MCP
@app.get("/api/filesystem/read")
async def filesystem_read(path: str):
    try:
        full_path = os.path.join(config["mcps"][0]["config"]["root_path"], path)
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=400, detail="Path is not a file")
        
        # 检查文件扩展名
        ext = os.path.splitext(full_path)[1].lstrip(".")
        allowed_extensions = config["mcps"][0]["config"]["allowed_extensions"]
        if ext and ext not in allowed_extensions:
            raise HTTPException(status_code=400, detail=f"File extension not allowed: {ext}")
        
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        return {
            "success": True,
            "content": content,
            "path": path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Git MCP
@app.post("/api/git/commit")
async def git_commit(message: str):
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=config["mcps"][1]["config"]["repository_path"],
            capture_output=True,
            text=True
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Memory MCP
@app.post("/api/memory/store")
async def memory_store_data(key: str, value: str):
    memory_store[key] = {
        "value": value,
        "timestamp": datetime.utcnow().isoformat()
    }
    return {
        "success": True,
        "key": key
    }

@app.get("/api/memory/retrieve")
async def memory_retrieve_data(key: str):
    if key not in memory_store:
        raise HTTPException(status_code=404, detail="Key not found")
    return {
        "success": True,
        "data": memory_store[key]
    }

# Fetch MCP
@app.get("/api/fetch/get")
async def fetch_get(url: str):
    try:
        import requests
        headers = {
            "User-Agent": config["mcps"][5]["config"]["user_agent"]
        }
        response = requests.get(url, headers=headers, timeout=config["mcps"][5]["config"]["timeout"])
        return {
            "success": True,
            "status_code": response.status_code,
            "content": response.text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
