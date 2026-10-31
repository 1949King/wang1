# -*- coding: utf-8 -*-
"""团队协作中枢（Team Hub）—— **存储 + 逻辑层**，纯 stdlib，可单测。

## 为什么独立于 canvas_server（这条最容易被误判）

`canvas_server` 绑 `127.0.0.1:18765`，而它的路由能跑 GPU 推理、读写本机文件、
启动子进程。**把它 bind 到 0.0.0.0 就等于把整台机器交给局域网**。
团队协作真正需要的只是「文档同步 + 交接」，所以这里另起一个最小 HTTP 服务，
只认下列几个 JSON 端点，攻击面 = 文档读写。

## 数据模型

| 表 | 作用 |
|---|---|
| `member` | 成员（姓名 / 角色 / 令牌哈希） |
| `project` | 共享项目（当前 rev / 拥有者） |
| `version` | 历史版本（bundle 存**文件**，DB 只存 sha256 —— 画布 bundle 带 data URL 能到几十 MB，塞进 SQLite 会拖死它） |
| `claim` | 编辑锁（带过期，防止有人开着界面走了） |
| `handoff` | 交接单（谁交给谁 / 留言 / 状态） |

## 三条纪律（与项目既有口径一致）

1. **冲突不静默合并**：push 带 `base_rev`，不等于当前 rev 就返回 `conflict` +
   双方作者，让界面提示「张三刚改过，要不要先拉」——**绝不自动 merge 画布图**；
2. **锁有 TTL**：认领（claim）默认 10 分钟过期，避免「同事下班没释放」导致项目死锁；
3. **令牌只存哈希**：LAN 里抓包能拿到明文，但库里不该有可直接重放的令牌。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 项目名 / 成员名的长度上限（防止把 JSON 撑爆）
MAX_NAME = 64
#: 单个 bundle 的硬上限（100MB）：超过说明用户把视频塞进了 data URL，应走媒体库
MAX_BUNDLE_BYTES = 100 * 1024 * 1024
#: 认领默认 TTL（秒）
DEFAULT_CLAIM_TTL = 600


class TeamError(Exception):
    """带 code 的业务错误（服务层据此映射 HTTP 状态码）。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class ConflictError(TeamError):
    def __init__(self, current_rev: int, author: str) -> None:
        super().__init__("conflict", "项目已被 %s 更新到第 %d 版" % (author or "他人", current_rev))
        self.current_rev = current_rev
        self.author = author


class LockedError(TeamError):
    def __init__(self, holder: str, expires_at: float) -> None:
        super().__init__("locked", "项目正被 %s 认领（%d 秒后过期）"
                         % (holder or "他人", max(0, int(expires_at - time.time()))))
        self.holder = holder
        self.expires_at = expires_at


def _now() -> float:
    return time.time()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(("shiguang-team:" + str(token)).encode("utf-8")).hexdigest()


class Hub:
    """团队中枢。线程安全（所有写操作在同一把锁内）。"""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.projects_dir = os.path.join(self.root, "projects")
        os.makedirs(self.projects_dir, exist_ok=True)
        self.db_path = os.path.join(self.root, "team.db")
        self._lock = threading.RLock()
        self._init_db()

    # ── 初始化 ──────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS member (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'editor',
                    token_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    rev INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS version (
                    project_id TEXT NOT NULL,
                    rev INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    author_id TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    PRIMARY KEY (project_id, rev)
                );
                CREATE TABLE IF NOT EXISTS claim (
                    project_id TEXT PRIMARY KEY,
                    member_id TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS handoff (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    from_id TEXT NOT NULL,
                    to_id TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_handoff_to ON handoff (to_id, status);
                """
            )

    # ── 成员 ────────────────────────────────────────────
    def register_member(self, name: str, role: str = "editor") -> Dict[str, Any]:
        """登记成员并返回**明文令牌**（只此一次，库里存哈希）。"""
        clean = str(name or "").strip()[:MAX_NAME]
        if not clean:
            raise TeamError("bad_name", "成员名不能为空")
        token = secrets.token_urlsafe(32)
        mid = "m_" + secrets.token_hex(8)
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO member (id, name, role, token_hash, created_at) VALUES (?,?,?,?,?)",
                (mid, clean, str(role or "editor")[:32], _token_hash(token), _now()),
            )
        return {"member_id": mid, "name": clean, "role": role, "token": token}

    def auth(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT id, name, role FROM member WHERE token_hash = ?", (_token_hash(token),)
            ).fetchone()
        return dict(row) if row else None

    def members(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT id, name, role, created_at FROM member ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    # ── 项目 / 版本 ─────────────────────────────────────
    def _project_row(self, project_id: str) -> sqlite3.Row:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise TeamError("not_found", "项目不存在：%s" % project_id)
        return row

    def _bundle_path(self, project_id: str, rev: int) -> str:
        return os.path.join(self.projects_dir, project_id, "rev-%04d.json" % int(rev))

    def _write_bundle(self, project_id: str, rev: int, bundle: Any) -> Tuple[str, int]:
        raw = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_BUNDLE_BYTES:
            raise TeamError("too_large", "工程过大（%.1fMB > %dMB），请先清理叠卡大图"
                            % (len(raw) / 1048576.0, MAX_BUNDLE_BYTES // 1048576))
        d = os.path.join(self.projects_dir, project_id)
        os.makedirs(d, exist_ok=True)
        path = self._bundle_path(project_id, rev)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)
        return _sha256(raw), len(raw)

    def create_project(self, name: str, owner_id: str, bundle: Any) -> Dict[str, Any]:
        clean = str(name or "").strip()[:MAX_NAME]
        if not clean:
            raise TeamError("bad_name", "项目名不能为空")
        pid = "p_" + secrets.token_hex(8)
        sha, size = self._write_bundle(pid, 1, bundle)
        ts = _now()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO project (id, name, owner_id, rev, updated_at, created_at) VALUES (?,?,?,?,?,?)",
                (pid, clean, owner_id, 1, ts, ts),
            )
            conn.execute(
                "INSERT INTO version (project_id, rev, sha256, bytes, author_id, message, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (pid, 1, sha, size, owner_id, "初始版本", ts),
            )
        return {"project_id": pid, "name": clean, "rev": 1, "sha256": sha, "bytes": size}

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT p.*, m.name AS owner_name FROM project p"
                " LEFT JOIN member m ON m.id = p.owner_id ORDER BY p.updated_at DESC"
            ).fetchall()
            claims = {
                r["project_id"]: r
                for r in conn.execute("SELECT * FROM claim WHERE expires_at > ?", (_now(),)).fetchall()
            }
        out = []
        for r in rows:
            c = claims.get(r["id"])
            out.append({
                "project_id": r["id"], "name": r["name"], "rev": int(r["rev"]),
                "owner": r["owner_name"] or r["owner_id"],
                "updated_at": float(r["updated_at"]),
                "claimed_by": c["member_id"] if c else "",
                "claim_expires_at": float(c["expires_at"]) if c else 0.0,
            })
        return out

    def get_bundle(self, project_id: str, rev: int = 0) -> Dict[str, Any]:
        row = self._project_row(project_id)
        target = int(rev or row["rev"])
        path = self._bundle_path(project_id, target)
        if not os.path.isfile(path):
            raise TeamError("not_found", "版本不存在：rev=%d" % target)
        with open(path, "rb") as f:
            bundle = json.loads(f.read().decode("utf-8"))
        return {"project_id": project_id, "name": row["name"], "rev": target,
                "latest_rev": int(row["rev"]), "bundle": bundle}

    def push(self, project_id: str, member_id: str, bundle: Any,
             base_rev: int = 0, message: str = "") -> Dict[str, Any]:
        """上传新版本。`base_rev` 与当前 rev 不符 ⇒ Conflict（不自动合并）。"""
        with self._lock:
            row = self._project_row(project_id)
            current = int(row["rev"])
            base = int(base_rev or 0)
            if base and base != current:
                author = self._author_of(project_id, current)
                raise ConflictError(current, author)
            new_rev = current + 1
            sha, size = self._write_bundle(project_id, new_rev, bundle)
            ts = _now()
            with self._conn() as conn:
                conn.execute("UPDATE project SET rev = ?, updated_at = ? WHERE id = ?",
                             (new_rev, ts, project_id))
                conn.execute(
                    "INSERT INTO version (project_id, rev, sha256, bytes, author_id, message, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (project_id, new_rev, sha, size, member_id, str(message or "")[:500], ts),
                )
        return {"project_id": project_id, "rev": new_rev, "sha256": sha, "bytes": size}

    def _author_of(self, project_id: str, rev: int) -> str:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT m.name FROM version v LEFT JOIN member m ON m.id = v.author_id"
                " WHERE v.project_id = ? AND v.rev = ?",
                (project_id, rev),
            ).fetchone()
        return str(row["name"]) if row and row["name"] else ""

    def versions(self, project_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT v.*, m.name AS author_name FROM version v"
                " LEFT JOIN member m ON m.id = v.author_id"
                " WHERE v.project_id = ? ORDER BY v.rev DESC",
                (project_id,),
            ).fetchall()
        return [{"rev": int(r["rev"]), "sha256": r["sha256"], "bytes": int(r["bytes"]),
                 "author": r["author_name"] or r["author_id"],
                 "message": r["message"], "created_at": float(r["created_at"])} for r in rows]

    # ── 认领（编辑锁）──────────────────────────────────
    def claim(self, project_id: str, member_id: str, ttl: int = DEFAULT_CLAIM_TTL) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM claim WHERE project_id = ?", (project_id,)).fetchone()
            now = _now()
            if row is not None and row["member_id"] != member_id and float(row["expires_at"]) > now:
                holder = self._member_name(row["member_id"])
                raise LockedError(holder, float(row["expires_at"]))
            expires = now + max(30, int(ttl))
            conn.execute(
                "INSERT INTO claim (project_id, member_id, expires_at) VALUES (?,?,?)"
                " ON CONFLICT(project_id) DO UPDATE SET member_id = excluded.member_id,"
                " expires_at = excluded.expires_at",
                (project_id, member_id, expires),
            )
        return {"project_id": project_id, "member_id": member_id, "expires_at": expires}

    def release(self, project_id: str, member_id: str) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM claim WHERE project_id = ?", (project_id,)).fetchone()
            if row is not None and row["member_id"] != member_id:
                raise TeamError("locked", "锁在 %s 手上，不能代释放" % self._member_name(row["member_id"]))
            conn.execute("DELETE FROM claim WHERE project_id = ?", (project_id,))
        return {"project_id": project_id, "released": True}

    def _member_name(self, member_id: str) -> str:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT name FROM member WHERE id = ?", (member_id,)).fetchone()
        return str(row["name"]) if row else ""

    # ── 交接 ────────────────────────────────────────────
    def handoff(self, project_id: str, from_id: str, to_id: str, message: str = "") -> Dict[str, Any]:
        if not self._member_name(to_id):
            raise TeamError("bad_target", "交接对象不存在")
        hid = "h_" + secrets.token_hex(8)
        ts = _now()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO handoff (id, project_id, from_id, to_id, message, status, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (hid, project_id, from_id, to_id, str(message or "")[:500], "pending", ts),
            )
            # 交接即释放锁：接手的人要能立刻认领
            conn.execute("DELETE FROM claim WHERE project_id = ?", (project_id,))
        return {"handoff_id": hid, "project_id": project_id, "to": to_id, "status": "pending"}

    def inbox(self, member_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT h.*, p.name AS project_name, m.name AS from_name FROM handoff h"
                " LEFT JOIN project p ON p.id = h.project_id"
                " LEFT JOIN member m ON m.id = h.from_id"
                " WHERE h.to_id = ? AND h.status = 'pending' ORDER BY h.created_at DESC",
                (member_id,),
            ).fetchall()
        return [{"handoff_id": r["id"], "project_id": r["project_id"],
                 "project_name": r["project_name"] or "", "from": r["from_name"] or r["from_id"],
                 "message": r["message"], "created_at": float(r["created_at"])} for r in rows]

    def ack_handoff(self, handoff_id: str, member_id: str) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM handoff WHERE id = ?", (handoff_id,)).fetchone()
            if row is None:
                raise TeamError("not_found", "交接单不存在")
            if row["to_id"] != member_id:
                raise TeamError("forbidden", "只能确认发给自己的交接")
            conn.execute("UPDATE handoff SET status = 'accepted' WHERE id = ?", (handoff_id,))
        return {"handoff_id": handoff_id, "status": "accepted"}

    # ── 健康 ────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            projects = conn.execute("SELECT COUNT(*) AS n FROM project").fetchone()["n"]
            members = conn.execute("SELECT COUNT(*) AS n FROM member").fetchone()["n"]
            pending = conn.execute("SELECT COUNT(*) AS n FROM handoff WHERE status='pending'").fetchone()["n"]
        return {"projects": int(projects), "members": int(members), "pending_handoffs": int(pending)}
