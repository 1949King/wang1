"""
账号认证模块 (Auth)
==================
本地 SQLite 存储 + 设备绑定
支持：手机号、QQ邮箱注册
限制：一个账号最多绑定3个设备

无需服务器，所有数据本地存储
"""

import sqlite3
import hashlib
import uuid
import platform
import os
import json
import time
import secrets
import re
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import threading


@dataclass
class User:
    id: str
    phone: Optional[str] = None
    email: Optional[str] = None
    nickname: str = ""
    password_hash: str = ""
    created_at: float = 0.0
    last_login: float = 0.0
    devices: List[str] = field(default_factory=list)
    is_vip: bool = False
    vip_expire: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "phone": self.phone,
            "email": self.email,
            "nickname": self.nickname,
            "created_at": self.created_at,
            "last_login": self.last_login,
            "devices": self.devices,
            "is_vip": self.is_vip,
            "vip_expire": self.vip_expire
        }


@dataclass
class DeviceInfo:
    device_id: str
    device_name: str
    first_seen: float
    last_seen: float
    is_trusted: bool = False


class DeviceFingerprint:
    """设备指纹生成器"""
    
    _instance: Optional['DeviceFingerprint'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._device_id: Optional[str] = None
    
    def generate(self) -> str:
        """生成设备指纹"""
        if self._device_id:
            return self._device_id
        
        components = [
            platform.node(),
            platform.system(),
            platform.machine(),
            platform.processor(),
            str(os.cpu_count() or 0),
        ]
        
        try:
            import subprocess
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["wmic", "csproduct", "get", "UUID"],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if result.returncode == 0:
                    components.append(result.stdout.strip())
        except:
            pass
        
        fingerprint = "|".join(components)
        self._device_id = hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
        return self._device_id
    
    def get_device_name(self) -> str:
        """获取设备名称"""
        return f"{platform.system()} - {platform.node()}"


class AuthDatabase:
    """认证数据库"""
    
    _instance: Optional['AuthDatabase'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._db_path = Path(__file__).parent.parent.parent / "data" / "auth.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                phone TEXT UNIQUE,
                email TEXT UNIQUE,
                nickname TEXT,
                password_hash TEXT NOT NULL,
                created_at REAL,
                last_login REAL,
                is_vip INTEGER DEFAULT 0,
                vip_expire REAL DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                device_name TEXT,
                first_seen REAL,
                last_seen REAL,
                is_trusted INTEGER DEFAULT 0,
                UNIQUE(user_id, device_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL,
                code TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at REAL,
                expires_at REAL,
                used INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                created_at REAL,
                expires_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
    
    def create_user(self, user: User) -> bool:
        """创建用户"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (id, phone, email, nickname, password_hash, created_at, last_login, is_vip, vip_expire)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user.id, user.phone, user.email, user.nickname, user.password_hash, 
                  user.created_at, user.last_login, int(user.is_vip), user.vip_expire))
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            return False
    
    def get_user_by_phone(self, phone: str) -> Optional[User]:
        """通过手机号获取用户"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE phone = ?', (phone,))
        row = cursor.fetchone()
        if row:
            return self._row_to_user(row)
        return None
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """通过邮箱获取用户"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        row = cursor.fetchone()
        if row:
            return self._row_to_user(row)
        return None
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """通过ID获取用户"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_user(row)
        return None
    
    def _row_to_user(self, row: sqlite3.Row) -> User:
        """将数据库行转换为User对象"""
        user = User(
            id=row['id'],
            phone=row['phone'],
            email=row['email'],
            nickname=row['nickname'] or "",
            password_hash=row['password_hash'],
            created_at=row['created_at'],
            last_login=row['last_login'],
            is_vip=bool(row['is_vip']),
            vip_expire=row['vip_expire']
        )
        user.devices = self.get_user_devices(row['id'])
        return user
    
    def update_user(self, user: User) -> bool:
        """更新用户信息"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET phone=?, email=?, nickname=?, last_login=?, is_vip=?, vip_expire=?
                WHERE id=?
            ''', (user.phone, user.email, user.nickname, user.last_login, 
                  int(user.is_vip), user.vip_expire, user.id))
            conn.commit()
            return True
        except:
            return False
    
    def add_device(self, user_id: str, device_id: str, device_name: str) -> bool:
        """添加设备"""
        conn = self._get_conn()
        cursor = conn.cursor()
        now = time.time()
        try:
            cursor.execute('''
                INSERT INTO devices (user_id, device_id, device_name, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, device_id, device_name, now, now))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            cursor.execute('''
                UPDATE devices SET last_seen=?, device_name=? WHERE user_id=? AND device_id=?
            ''', (now, device_name, user_id, device_id))
            conn.commit()
            return True
    
    def get_user_devices(self, user_id: str) -> List[str]:
        """获取用户设备列表"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT device_id FROM devices WHERE user_id = ?', (user_id,))
        return [row['device_id'] for row in cursor.fetchall()]
    
    def get_device_count(self, user_id: str) -> int:
        """获取用户设备数量"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM devices WHERE user_id = ?', (user_id,))
        return cursor.fetchone()['count']
    
    def remove_device(self, user_id: str, device_id: str) -> bool:
        """移除设备"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM devices WHERE user_id = ? AND device_id = ?', (user_id, device_id))
        conn.commit()
        return cursor.rowcount > 0
    
    def create_verification_code(self, target: str, code: str, code_type: str, expires_in: int = 300) -> bool:
        """创建验证码"""
        conn = self._get_conn()
        cursor = conn.cursor()
        now = time.time()
        cursor.execute('''
            INSERT INTO verification_codes (target, code, type, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (target, code, code_type, now, now + expires_in))
        conn.commit()
        return True
    
    def verify_code(self, target: str, code: str, code_type: str) -> bool:
        """验证验证码"""
        conn = self._get_conn()
        cursor = conn.cursor()
        now = time.time()
        cursor.execute('''
            SELECT * FROM verification_codes 
            WHERE target=? AND code=? AND type=? AND used=0 AND expires_at>?
            ORDER BY created_at DESC LIMIT 1
        ''', (target, code, code_type, now))
        row = cursor.fetchone()
        if row:
            cursor.execute('UPDATE verification_codes SET used=1 WHERE id=?', (row['id'],))
            conn.commit()
            return True
        return False
    
    def create_session(self, user_id: str, device_id: str, expires_in: int = 86400 * 7) -> str:
        """创建会话"""
        session_id = secrets.token_urlsafe(32)
        conn = self._get_conn()
        cursor = conn.cursor()
        now = time.time()
        cursor.execute('''
            INSERT INTO sessions (id, user_id, device_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (session_id, user_id, device_id, now, now + expires_in))
        conn.commit()
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[str]:
        """验证会话，返回用户ID"""
        conn = self._get_conn()
        cursor = conn.cursor()
        now = time.time()
        cursor.execute('''
            SELECT user_id FROM sessions WHERE id=? AND expires_at>?
        ''', (session_id, now))
        row = cursor.fetchone()
        if row:
            return row['user_id']
        return None
    
    def delete_session(self, session_id: str):
        """删除会话"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE id=?', (session_id,))
        conn.commit()


class AuthService:
    """认证服务"""
    
    _instance: Optional['AuthService'] = None
    _lock = threading.Lock()
    
    MAX_DEVICES = 3
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._db = AuthDatabase()
        self._device_fp = DeviceFingerprint()
        self._current_user: Optional[User] = None
        self._session_id: Optional[str] = None
    
    @property
    def current_user(self) -> Optional[User]:
        return self._current_user
    
    @property
    def is_logged_in(self) -> bool:
        return self._current_user is not None
    
    def _hash_password(self, password: str) -> str:
        """密码哈希"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _validate_phone(self, phone: str) -> bool:
        """验证手机号格式"""
        return bool(re.match(r'^1[3-9]\d{9}$', phone))
    
    def _validate_email(self, email: str) -> bool:
        """验证邮箱格式"""
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@qq\.com$', email, re.IGNORECASE))
    
    def _generate_code(self) -> str:
        """生成6位验证码"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(6)])
    
    def send_phone_verification(self, phone: str) -> Tuple[bool, str]:
        """发送短信验证码"""
        if not self._validate_phone(phone):
            return False, "手机号格式不正确"
        
        # 生成6位验证码
        code = self._generate_code()
        
        # 保存验证码到数据库
        if self._db.create_verification_code(phone, code, 'phone'):
            # 这里应该调用实际的短信发送服务
            # 暂时模拟发送成功
            print(f"短信验证码已发送到 {phone}: {code}")
            return True, "验证码已发送"
        return False, "发送失败"
    
    def verify_phone_code(self, phone: str, code: str) -> bool:
        """验证手机号验证码"""
        return self._db.verify_code(phone, code, 'phone')
    
    def register_with_phone(self, phone: str, password: str, code: str, nickname: str = "") -> Tuple[bool, str]:
        """手机号注册"""
        if not self._validate_phone(phone):
            return False, "手机号格式不正确"
        
        if not code:
            return False, "请输入验证码"
        
        if not self.verify_phone_code(phone, code):
            return False, "验证码错误或已过期"
        
        if len(password) < 6:
            return False, "密码至少6位"
        
        if self._db.get_user_by_phone(phone):
            return False, "该手机号已注册"
        
        user = User(
            id=str(uuid.uuid4()),
            phone=phone,
            nickname=nickname or f"用户{phone[-4:]}",
            password_hash=self._hash_password(password),
            created_at=time.time(),
            last_login=time.time()
        )
        
        if self._db.create_user(user):
            return True, "注册成功"
        return False, "注册失败"
    
    def register_with_email(self, email: str, password: str, code: str, nickname: str = "") -> Tuple[bool, str]:
        """QQ邮箱注册"""
        if not self._validate_email(email):
            return False, "请使用QQ邮箱注册"
        
        if not code:
            return False, "请输入验证码"
        
        if len(password) < 6:
            return False, "密码至少6位"
        
        if self._db.get_user_by_email(email):
            return False, "该邮箱已注册"
        
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            nickname=nickname or f"用户{email.split('@')[0][-4:]}",
            password_hash=self._hash_password(password),
            created_at=time.time(),
            last_login=time.time()
        )
        
        if self._db.create_user(user):
            return True, "注册成功"
        return False, "注册失败"
    
    def login_with_phone(self, phone: str, password: str) -> Tuple[bool, str]:
        """手机号登录"""
        if not self._validate_phone(phone):
            return False, "手机号格式不正确"
        
        user = self._db.get_user_by_phone(phone)
        if not user:
            return False, "用户不存在"
        
        if user.password_hash != self._hash_password(password):
            return False, "密码错误"
        
        return self._do_login(user)
    
    def login_with_email(self, email: str, password: str) -> Tuple[bool, str]:
        """邮箱登录"""
        if not self._validate_email(email):
            return False, "请使用QQ邮箱登录"
        
        user = self._db.get_user_by_email(email)
        if not user:
            return False, "用户不存在"
        
        if user.password_hash != self._hash_password(password):
            return False, "密码错误"
        
        return self._do_login(user)
    
    def _do_login(self, user: User) -> Tuple[bool, str]:
        """执行登录逻辑"""
        device_id = self._device_fp.generate()
        device_name = self._device_fp.get_device_name()
        
        device_count = self._db.get_device_count(user.id)
        existing_devices = self._db.get_user_devices(user.id)
        
        if device_id not in existing_devices and device_count >= self.MAX_DEVICES:
            return False, f"设备数量已达上限({self.MAX_DEVICES}台)，请先解绑其他设备"
        
        self._db.add_device(user.id, device_id, device_name)
        
        user.last_login = time.time()
        self._db.update_user(user)
        
        self._session_id = self._db.create_session(user.id, device_id)
        self._current_user = user
        
        return True, "登录成功"
    
    def logout(self):
        """登出"""
        if self._session_id:
            self._db.delete_session(self._session_id)
        self._session_id = None
        self._current_user = None
    
    def get_my_devices(self) -> List[DeviceInfo]:
        """获取当前账号的设备列表"""
        if not self._current_user:
            return []
        
        conn = self._db._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT device_id, device_name, first_seen, last_seen, is_trusted 
            FROM devices WHERE user_id = ?
        ''', (self._current_user.id,))
        
        devices = []
        for row in cursor.fetchall():
            devices.append(DeviceInfo(
                device_id=row['device_id'],
                device_name=row['device_name'],
                first_seen=row['first_seen'],
                last_seen=row['last_seen'],
                is_trusted=bool(row['is_trusted'])
            ))
        return devices
    
    def remove_device(self, device_id: str) -> Tuple[bool, str]:
        """移除设备"""
        if not self._current_user:
            return False, "未登录"
        
        current_device = self._device_fp.generate()
        if device_id == current_device:
            return False, "不能移除当前设备"
        
        if self._db.remove_device(self._current_user.id, device_id):
            return True, "设备已移除"
        return False, "移除失败"
    
    def try_auto_login(self) -> bool:
        """尝试自动登录"""
        session_file = Path(__file__).parent.parent.parent / "data" / "session.json"
        if not session_file.exists():
            return False
        
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
            session_id = data.get('session_id')
            if not session_id:
                return False
            
            user_id = self._db.validate_session(session_id)
            if not user_id:
                return False
            
            user = self._db.get_user_by_id(user_id)
            if not user:
                return False
            
            self._session_id = session_id
            self._current_user = user
            return True
        except:
            return False
    
    def save_session(self):
        """保存会话到文件"""
        if not self._session_id:
            return
        
        session_file = Path(__file__).parent.parent.parent / "data" / "session.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(session_file, 'w') as f:
            json.dump({'session_id': self._session_id}, f)
    
    def clear_session(self):
        """清除会话文件"""
        session_file = Path(__file__).parent.parent.parent / "data" / "session.json"
        if session_file.exists():
            session_file.unlink()


auth_service = AuthService()
