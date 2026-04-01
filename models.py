# models.py
import sqlite3
import datetime
from config import DB_PATH

class VideoSnapshot:
    def __init__(self, id=None, platform=None, video_id=None, play_count=0, digg_count=0, comment_count=0, share_count=0, created_at=None):
        self.id = id
        self.platform = platform
        self.video_id = video_id
        self.play_count = play_count
        self.digg_count = digg_count
        self.comment_count = comment_count
        self.share_count = share_count
        self.created_at = created_at or datetime.datetime.now()

# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
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
    conn.close()

# 保存快照
def save_snapshot(snapshot):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO video_snapshots (platform, video_id, play_count, digg_count, comment_count, share_count, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (snapshot.platform, snapshot.video_id, snapshot.play_count, snapshot.digg_count, snapshot.comment_count, snapshot.share_count, snapshot.created_at))
    snapshot.id = cursor.lastrowid
    conn.commit()
    conn.close()

# 获取快照
def get_snapshots(platform=None, video_id=None, limit=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    conn.close()
    
    snapshots = []
    for row in rows:
        snapshot = VideoSnapshot(
            id=row['id'],
            platform=row['platform'],
            video_id=row['video_id'],
            play_count=row['play_count'],
            digg_count=row['digg_count'],
            comment_count=row['comment_count'],
            share_count=row['share_count'],
            created_at=datetime.datetime.fromisoformat(row['created_at'])
        )
        snapshots.append(snapshot)
    
    return snapshots

# 初始化数据库
init_db()
