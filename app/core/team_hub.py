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
| `asset` | 附件登记（视频/图片/音频的字节存 `blobs/<sha256>.<ext>`，DB 只记元信息） |

## 附件为什么单独一层（2026-11-02）

bundle 是 JSON，媒体只能以两种形式进去：base64（1 张 512² 图 ≈ 300~500KB，
200 张就撞 100MB 上限）或本地路径（`/inbox_file/x.mp4`，**同事机上不存在 ⇒ 404**）。
所以大文件一律走 `asset`：字节按内容哈希独立存盘，bundle 里只留
`mediaIndex: { "/inbox_file/x.mp4": "<sha256>" }` 这张映射表，同事端渲染时
把本地路径改写成团队 URL。**同一份内容换台机器传两遍不会变成两份文件**（sha256 去重）。

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
#: 单个附件的硬上限（512MB）：一条 1 分钟 1080p 成片约 50~200MB，够用；
#: 再大说明该走网盘而不是团队服务（8GB 机器流式落盘也不能让它扛几个 G）
MAX_ASSET_BYTES = 512 * 1024 * 1024
#: 附件名长度上限
MAX_ASSET_NAME = 120
#: 认领默认 TTL（秒）
DEFAULT_CLAIM_TTL = 600

#: 附件扩展名白名单（**不信任客户端给的后缀**，宁可落 `.bin` 也不让 `..%2f` 之类穿透目录）
_ASSET_EXTS = frozenset([
    ".mp4", ".webm", ".mov", ".mkv", ".m4v",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac",
    ".json", ".txt", ".md", ".srt", ".csv",
])


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


# ── 版本差异（纯函数 · 可单测）──────────────────────────────
#: 节点里跟**内容**无关的 UI 状态。拖动/选中/重算测量值都不算「改了内容」——
#: 尤其是 `position`：React Flow 在布局回写时会带浮点微差，算进去就是满屏假差异。
_NODE_NOISE = frozenset([
    "selected", "dragging", "measured", "width", "height",
    "positionAbsolute", "position", "resizing",
])


def _node_payload(node: Any) -> str:
    """节点里参与差异判定的部分（去掉 UI 状态，键序稳定 ⇒ 可直接比字符串）。"""
    if not isinstance(node, dict):
        return repr(node)
    try:
        clean = {k: v for k, v in node.items() if k not in _NODE_NOISE}
        return json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return repr(node)


def _node_title(node: Any) -> str:
    """给人看的节点名：优先 data.title，退到 type，最后「节点」。"""
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict):
            for k in ("title", "name", "label"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()[:40]
        t = node.get("type")
        if isinstance(t, str) and t.strip():
            return t.strip()[:40]
    return "节点"


def _clips_of(bundle: Any) -> List[dict]:
    if not isinstance(bundle, dict):
        return []
    tl = bundle.get("timeline")
    if not isinstance(tl, dict):
        return []
    cs = tl.get("clips")
    return [c for c in cs if isinstance(c, dict)] if isinstance(cs, list) else []


def _clip_key(clip: Any) -> str:
    """片段稳定主键：id 优先，path@start_time 兜底（与 project_snapshot 同口径）。"""
    if not isinstance(clip, dict):
        return ""
    cid = clip.get("id")
    if cid is not None and cid != "":
        return "id:" + str(cid)
    return "path:%s@%s" % (clip.get("path") or "", clip.get("start_time") or 0)


def _clip_payload(clip: Any) -> str:
    try:
        return json.dumps(clip, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return repr(clip)


def _index_by(seq: Any, key_of) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(seq, list):
        return out
    for item in seq:
        if not isinstance(item, dict):
            continue
        k = key_of(item)
        if k:
            out[k] = item
    return out


def diff_bundle(old: Any, new: Any) -> Dict[str, Any]:
    """两份 bundle 的摘要差异 —— 回答「同事到底改了哪」。

    只回**计数 + 少量标题**，不回整份内容：目的是让人一眼判断「要不要拉」，
    真要逐字比就自己拉下来看。
    """
    o = old if isinstance(old, dict) else {}
    n = new if isinstance(new, dict) else {}

    on = _index_by(o.get("nodes"), lambda x: str(x.get("id") or ""))
    nn = _index_by(n.get("nodes"), lambda x: str(x.get("id") or ""))
    n_added = [k for k in nn if k not in on]
    n_removed = [k for k in on if k not in nn]
    n_changed = [k for k in nn if k in on and _node_payload(on[k]) != _node_payload(nn[k])]

    oe = _index_by(o.get("edges"), lambda x: str(x.get("id") or ""))
    ne = _index_by(n.get("edges"), lambda x: str(x.get("id") or ""))
    e_added = [k for k in ne if k not in oe]
    e_removed = [k for k in oe if k not in ne]

    oc = _index_by(_clips_of(o), _clip_key)
    nc = _index_by(_clips_of(n), _clip_key)
    c_added = [k for k in nc if k not in oc]
    c_removed = [k for k in oc if k not in nc]
    c_changed = [k for k in nc if k in oc and _clip_payload(oc[k]) != _clip_payload(nc[k])]

    def titles(keys: List[str], idx: Dict[str, Any], limit: int = 6) -> List[str]:
        return [_node_title(idx[k]) for k in keys[:limit]]

    title_o = str(o.get("dramaTitle") or "")
    title_n = str(n.get("dramaTitle") or "")

    return {
        "nodes": {
            "added": len(n_added), "removed": len(n_removed), "changed": len(n_changed),
            "added_titles": titles(n_added, nn),
            "removed_titles": titles(n_removed, on),
            "changed_titles": titles(n_changed, nn),
        },
        "edges": {"added": len(e_added), "removed": len(e_removed)},
        "timeline": {
            "before": len(oc), "after": len(nc),
            "added": len(c_added), "removed": len(c_removed), "changed": len(c_changed),
        },
        "title": {"before": title_o, "after": title_n, "changed": title_o != title_n},
    }


class Hub:
    """团队中枢。线程安全（所有写操作在同一把锁内）。"""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.projects_dir = os.path.join(self.root, "projects")
        #: 附件字节库（按内容哈希命名，跨项目共享去重）
        self.blobs_dir = os.path.join(self.root, "blobs")
        os.makedirs(self.projects_dir, exist_ok=True)
        os.makedirs(self.blobs_dir, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS asset (
                    project_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'file',
                    mime TEXT NOT NULL DEFAULT '',
                    bytes INTEGER NOT NULL,
                    author_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    PRIMARY KEY (project_id, sha256)
                );
                """
            )
            self._migrate_asset_columns(conn)

    @staticmethod
    def _migrate_asset_columns(conn: sqlite3.Connection) -> None:
        """给 `asset` 补后来才加的列（幂等）。

        SQLite 没有 `ADD COLUMN IF NOT EXISTS`，所以先查 `PRAGMA table_info`。
        老库升级后列值取默认值，不需要回填 —— 早期上传的附件本来就没这些信息，
        编一个出来反而是假数据。
        """
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(asset)").fetchall()}
        #: 归属提示：来自哪个镜 / 哪个片段（`镜 03`），空串表示无从得知
        if "owner" not in cols:
            conn.execute("ALTER TABLE asset ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        #: 封面附件的 sha256（视频首帧），空串表示没有
        if "poster" not in cols:
            conn.execute("ALTER TABLE asset ADD COLUMN poster TEXT NOT NULL DEFAULT ''")

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

    def _read_bundle(self, project_id: str, rev: int) -> Any:
        path = self._bundle_path(project_id, rev)
        if not os.path.isfile(path):
            raise TeamError("not_found", "版本不存在：rev=%d" % int(rev))
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))

    def diff(self, project_id: str, from_rev: int, to_rev: int) -> Dict[str, Any]:
        """对比两个版本，给「同事到底改了哪」一个能读的答案。

        为什么不让前端拉两个 bundle 自己比：一个含内嵌图的 bundle 几十 MB，
        拉两遍只为看差异是浪费。这里在服务端读文件比对，只回摘要。
        """
        row = self._project_row(project_id)
        latest = int(row["rev"])
        a = int(from_rev or 0)
        b = int(to_rev or 0)
        # 0 = 不指定（界面默认走这条），不是「第 0 版」
        if b <= 0:
            b = latest
        if a <= 0:
            a = max(1, b - 1)
        # 🔴 超范围的 rev **报错而不是悄悄夹到最新**：夹了会给出一份「看起来对、
        # 其实不是你问的那两版」的差异，比报错难查得多。
        if a < 1 or b < 1:
            raise TeamError("not_found", "版本不存在：rev=%d" % (a if a < 1 else b))
        if a > latest or b > latest:
            raise TeamError("not_found", "版本不存在：rev %d（最新 rev %d）"
                            % (a if a > latest else b, latest))
        if a > b:
            a, b = b, a      # 传反了不报错，交换即可
        if a == b:
            return {"project_id": project_id, "from_rev": a, "to_rev": b,
                    "revisions": 0, "same": True, "nodes": {}, "edges": {},
                    "timeline": {}, "title": {}}
        return {"project_id": project_id, "revisions": b - a, "same": False,
                **diff_bundle(self._read_bundle(project_id, a),
                              self._read_bundle(project_id, b)),
                "from_rev": a, "to_rev": b}

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

    # ── 附件（视频 / 图片 / 音频 / 剧本文件）───────────
    @staticmethod
    def _safe_ext(name: str) -> str:
        """只从**白名单**取后缀：客户端给的名字不进路径，防目录穿透。"""
        ext = os.path.splitext(str(name or ""))[1].lower()
        return ext if ext in _ASSET_EXTS else ".bin"

    def _asset_path(self, project_id: str, sha: str, name: str = "") -> str:
        # 一个 sha 一种扩展名：首次落盘时定下，后续按同样规则算，不依赖调用方传 name
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT name FROM asset WHERE project_id = ? AND sha256 = ?", (project_id, sha)
            ).fetchone()
        ext = self._safe_ext(str(row["name"]) if row else name)
        # blobs 全局共享（不含 project_id）：跨项目同一份素材只占一份盘
        return os.path.join(self.blobs_dir, sha + ext)

    def _upsert_asset(self, project_id: str, sha: str, name: str, kind: str,
                      mime: str, size: int, member_id: str,
                      owner: str = "", poster: str = "") -> Dict[str, Any]:
        clean = str(name or "").strip()[:MAX_ASSET_NAME] or (sha[:12] + ".bin")
        clean_owner = str(owner or "").strip()[:MAX_ASSET_NAME]
        clean_poster = str(poster or "").strip()[:64]
        ts = _now()
        with self._lock, self._conn() as conn:
            has_project = conn.execute("SELECT 1 FROM project WHERE id = ?", (project_id,)).fetchone()
            if has_project is None:
                raise TeamError("not_found", "项目不存在：%s" % project_id)
            # 空值不覆盖已记下的信息：同一份素材会被多个节点引用，后一次上传
            # 往往没带 owner/poster，不该把前一次记的抹掉。
            conn.execute(
                "INSERT INTO asset (project_id, sha256, name, kind, mime, bytes, author_id,"
                " created_at, owner, poster) VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(project_id, sha256) DO UPDATE SET name = excluded.name,"
                " kind = excluded.kind, mime = excluded.mime,"
                " owner = CASE WHEN excluded.owner != '' THEN excluded.owner ELSE asset.owner END,"
                " poster = CASE WHEN excluded.poster != '' THEN excluded.poster ELSE asset.poster END",
                (project_id, sha, clean, str(kind or "file")[:16], str(mime or "")[:120],
                 int(size), member_id, ts, clean_owner, clean_poster),
            )
        return {"sha256": sha, "name": clean, "kind": str(kind or "file")[:16],
                "mime": str(mime or "")[:120], "bytes": int(size),
                "owner": clean_owner, "poster": clean_poster}

    def save_asset(self, project_id: str, member_id: str, name: str, data: bytes,
                   kind: str = "file", mime: str = "",
                   owner: str = "", poster: str = "") -> Dict[str, Any]:
        """小文件路径（≤ 单测 / 截图）：整块进内存，落盘后登记。"""
        raw = bytes(data or b"")
        if not raw:
            raise TeamError("bad_asset", "附件内容为空（0 字节不登记，免得同事点开是白屏）")
        if len(raw) > MAX_ASSET_BYTES:
            raise TeamError("too_large", "附件过大（%.0fMB > %dMB），成片请先压缩或走网盘"
                            % (len(raw) / 1048576.0, MAX_ASSET_BYTES // 1048576))
        sha = _sha256(raw)
        path = self._asset_path(project_id, sha, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.isfile(path):
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, path)
        return self._upsert_asset(project_id, sha, name, kind, mime, len(raw), member_id,
                                  owner, poster)

    def commit_asset_file(self, project_id: str, member_id: str, name: str,
                          tmp_path: str, sha: str, size: int,
                          kind: str = "file", mime: str = "",
                          owner: str = "", poster: str = "") -> Dict[str, Any]:
        """生产路径：服务层**边收边写**到 tmp 后调这里收编（512MB 视频不进内存）。"""
        if size <= 0:
            try:
                os.remove(tmp_path)
            except OSError:
                # 清理临时文件失败不该盖住真正的错误（0 字节），但也不能静默
                logger.debug("[team] 临时文件清理失败 %s", tmp_path, exc_info=True)
            raise TeamError("bad_asset", "附件内容为空（0 字节不登记）")
        if size > MAX_ASSET_BYTES:
            try:
                os.remove(tmp_path)
            except OSError:
                logger.debug("[team] 临时文件清理失败 %s", tmp_path, exc_info=True)
            raise TeamError("too_large", "附件过大（%.0fMB > %dMB），成片请先压缩或走网盘"
                            % (size / 1048576.0, MAX_ASSET_BYTES // 1048576))
        path = self._asset_path(project_id, sha, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.isfile(path):
            os.remove(tmp_path)          # 内容已存在（跨机器重传），tmp 丢掉即可
        else:
            os.replace(tmp_path, path)
        return self._upsert_asset(project_id, sha, name, kind, mime, size, member_id,
                                  owner, poster)

    def list_assets(self, project_id: str) -> List[Dict[str, Any]]:
        """项目里的附件（**封面附件不列出来**）。

        封面本身也是一张附件（这样同事那边也能拿到那张 JPEG），但它对用户没有
        独立意义 —— 列出来只会变成「成片.mp4 / 成片.mp4.poster.jpg」两行，
        把本来要解决的「分不清哪个是哪个」又变成「多了一倍的条目」。
        规则：谁的 sha 被别的行 `poster` 引用，谁就不进列表（仍可按 sha 取字节）。
        """
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT a.*, m.name AS author_name FROM asset a"
                " LEFT JOIN member m ON m.id = a.author_id"
                " WHERE a.project_id = ?"
                "   AND a.sha256 NOT IN (SELECT poster FROM asset"
                "                         WHERE project_id = ? AND poster != '')"
                " ORDER BY a.created_at",
                (project_id, project_id),
            ).fetchall()
        return [{"sha256": r["sha256"], "name": r["name"], "kind": r["kind"],
                 "mime": r["mime"], "bytes": int(r["bytes"]),
                 "author": r["author_name"] or r["author_id"],
                 "created_at": float(r["created_at"]),
                 "owner": r["owner"] or "", "poster": r["poster"] or ""} for r in rows]

    def asset_path_of(self, project_id: str, sha: str) -> Tuple[str, Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM asset WHERE project_id = ? AND sha256 = ?", (project_id, sha)
            ).fetchone()
        if row is None:
            raise TeamError("not_found", "附件不存在：%s" % sha[:12])
        path = os.path.join(self.blobs_dir, row["sha256"] + self._safe_ext(row["name"]))
        if not os.path.isfile(path):
            # 登记还在但文件没了（手删 blobs / 拷库没拷附件）⇒ 如实报，别回空字节
            raise TeamError("not_found", "附件字节已丢失：%s（重传一次即可）" % row["name"])
        return path, dict(row)

    def delete_asset(self, project_id: str, sha: str) -> Dict[str, Any]:
        """删登记；**全表无引用**才真删字节（另一个项目还挂着就不能删）。"""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT name FROM asset WHERE project_id = ? AND sha256 = ?", (project_id, sha)
            ).fetchone()
            if row is None:
                raise TeamError("not_found", "附件不存在：%s" % sha[:12])
            conn.execute("DELETE FROM asset WHERE project_id = ? AND sha256 = ?", (project_id, sha))
            still = conn.execute("SELECT COUNT(*) AS n FROM asset WHERE sha256 = ?", (sha,)).fetchone()
        removed = False
        if int(still["n"] if still else 0) == 0:
            path = os.path.join(self.blobs_dir, sha + self._safe_ext(row["name"]))
            try:
                os.remove(path)
                removed = True
            except FileNotFoundError:
                removed = True
            except OSError:
                logger.debug("[team] 附件字节删除失败 %s", path, exc_info=True)
        return {"sha256": sha, "removed": removed}

    # ── 健康 ────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock, self._conn() as conn:
            projects = conn.execute("SELECT COUNT(*) AS n FROM project").fetchone()["n"]
            members = conn.execute("SELECT COUNT(*) AS n FROM member").fetchone()["n"]
            pending = conn.execute("SELECT COUNT(*) AS n FROM handoff WHERE status='pending'").fetchone()["n"]
            assets = conn.execute("SELECT COUNT(*) AS n FROM asset").fetchone()["n"]
            asset_bytes = conn.execute("SELECT COALESCE(SUM(bytes),0) AS n FROM asset").fetchone()["n"]
        return {"projects": int(projects), "members": int(members),
                "pending_handoffs": int(pending), "assets": int(assets),
                "asset_bytes": int(asset_bytes)}
