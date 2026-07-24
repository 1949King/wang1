# models.py - 视频监控数据模型
# 改进版：连接池、上下文管理、延迟初始化

import sqlite3
import datetime
import threading
from pathlib import Path
from config import DB_PATH


# 确保数据目录存在
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


class VideoSnapshot:
    def __init__(self, id=None, platform=None, video_id=None,
                 play_count=0, digg_count=0, comment_count=0,
                 share_count=0, created_at=None):
        self.id = id
        self.platform = platform
        self.video_id = video_id
        self.play_count = play_count
        self.digg_count = digg_count
        self.comment_count = comment_count
        self.share_count = share_count
        self.created_at = created_at or datetime.datetime.now()


class _DatabaseConnection:
    """线程安全的数据库连接管理"""
    
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()
    
    def get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
    
    def close_all(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


_db = _DatabaseConnection(DB_PATH)


def init_db():
    """初始化数据库表（幂等操作）"""
    conn = _db.get_connection()
    conn.execute('''
    CREATE TABLE IF NOT EXISTS video_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT,
        video_id TEXT,
        play_count INTEGER,
        digg_count INTEGER,
        comment_count INTEGER,
        share_count INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()


def save_snapshot(snapshot: VideoSnapshot):
    """保存快照"""
    conn = _db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO video_snapshots 
        (platform, video_id, play_count, digg_count, comment_count, share_count, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (snapshot.platform, snapshot.video_id, snapshot.play_count,
          snapshot.digg_count, snapshot.comment_count, snapshot.share_count,
          snapshot.created_at))
    snapshot.id = cursor.lastrowid
    conn.commit()


def get_snapshots(platform=None, video_id=None, limit=None):
    """获取快照列表"""
    conn = _db.get_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM video_snapshots WHERE 1=1'
    params = []
    
    if platform:
        query += ' AND platform = ?'
        params.append(platform)
    if video_id:
        query += ' AND video_id = ?'
        params.append(video_id)
    
    query += ' ORDER BY created_at DESC'
    
    if limit:
        query += ' LIMIT ?'
        params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    snapshots = []
    for row in rows:
        created_at = row['created_at']
        if isinstance(created_at, str):
            created_at = datetime.datetime.fromisoformat(created_at)
        snapshot = VideoSnapshot(
            id=row['id'], platform=row['platform'],
            video_id=row['video_id'], play_count=row['play_count'],
            digg_count=row['digg_count'], comment_count=row['comment_count'],
            share_count=row['share_count'], created_at=created_at
        )
        snapshots.append(snapshot)
    
    return snapshots


# 延迟初始化：仅在首次使用时建表，避免模块导入时的副作用
_init_lock = threading.Lock()
_db_initialized = False


def _ensure_db():
    """确保数据库已初始化（延迟、线程安全）"""
    global _db_initialized
    if not _db_initialized:
        with _init_lock:
            if not _db_initialized:
                init_db()
                _db_initialized = True


# 模块加载时不自动建表，由首次调用者触发
# 旧的 init_db() 行已移除
