import asyncio
import json
import time
import uuid
import hashlib
from typing import Dict, List, Optional, Set, Any, Callable, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
import redis
from fastapi import WebSocket, WebSocketDisconnect
import websockets
from concurrent.futures import ThreadPoolExecutor

from app.core.service_decomposition import ServiceType


class CollaborationEventType(Enum):
    """协作事件类型"""
    USER_JOIN = "user_join"
    USER_LEAVE = "user_leave"
    CURSOR_MOVE = "cursor_move"
    TEXT_EDIT = "text_edit"
    SELECTION_CHANGE = "selection_change"
    COMMENT_ADD = "comment_add"
    COMMENT_DELETE = "comment_delete"
    STATUS_CHANGE = "status_change"
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"
    LOCK_REQUEST = "lock_request"
    LOCK_RELEASE = "lock_release"
    HEARTBEAT = "heartbeat"


class UserStatus(Enum):
    """用户状态"""
    ONLINE = "online"
    AWAY = "away"
    BUSY = "busy"
    OFFLINE = "offline"


class LockType(Enum):
    """锁类型"""
    READ = "read"
    WRITE = "write"
    EXCLUSIVE = "exclusive"


@dataclass
class User:
    """用户信息"""
    user_id: str
    username: str
    avatar_url: Optional[str] = None
    color: str = "#3498db"
    status: UserStatus = UserStatus.ONLINE
    joined_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


@dataclass
class CursorPosition:
    """光标位置"""
    user_id: str
    username: str
    line: int
    column: int
    color: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class TextEdit:
    """文本编辑"""
    user_id: str
    operation: str  # insert, delete, replace
    position: int
    content: str
    length: int = 0
    timestamp: float = field(default_factory=time.time)
    version: int = 0


@dataclass
class Selection:
    """选择范围"""
    user_id: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    color: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Comment:
    """评论"""
    comment_id: str
    user_id: str
    username: str
    line: int
    content: str
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    replies: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Lock:
    """锁"""
    lock_id: str
    resource_id: str
    user_id: str
    lock_type: LockType
    acquired_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None


@dataclass
class CollaborationEvent:
    """协作事件"""
    event_type: CollaborationEventType
    user_id: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class OperationalTransform:
    """操作转换算法"""
    
    @staticmethod
    def transform(op1: TextEdit, op2: TextEdit) -> Tuple[TextEdit, TextEdit]:
        """转换两个操作"""
        if op1.position + op1.length <= op2.position:
            return op1, op2
        elif op2.position + op2.length <= op1.position:
            return op1, op2
        else:
            return OperationalTransform._transform_overlap(op1, op2)
    
    @staticmethod
    def _transform_overlap(op1: TextEdit, op2: TextEdit) -> Tuple[TextEdit, TextEdit]:
        """转换重叠操作"""
        if op1.operation == "insert" and op2.operation == "insert":
            if op1.position <= op2.position:
                op2.position += len(op1.content)
            else:
                op1.position += len(op2.content)
        elif op1.operation == "delete" and op2.operation == "insert":
            if op1.position <= op2.position:
                op2.position -= op1.length
        elif op1.operation == "insert" and op2.operation == "delete":
            if op2.position <= op1.position:
                op1.position -= op2.length
        elif op1.operation == "delete" and op2.operation == "delete":
            if op1.position <= op2.position:
                op2.position -= op1.length
                op2.length = max(0, op2.length - (op1.position + op1.length - op2.position))
            else:
                op1.position -= op2.length
                op1.length = max(0, op1.length - (op2.position + op2.length - op1.position))
        
        return op1, op2
    
    @staticmethod
    def compose(op1: TextEdit, op2: TextEdit) -> TextEdit:
        """组合两个操作"""
        if op1.operation == "delete" and op2.operation == "delete":
            if op1.position + op1.length == op2.position:
                return TextEdit(
                    user_id=op1.user_id,
                    operation="delete",
                    position=op1.position,
                    content="",
                    length=op1.length + op2.length,
                    timestamp=max(op1.timestamp, op2.timestamp),
                    version=max(op1.version, op2.version) + 1
                )
        
        return op2


class ConflictFreeReplicatedDataType:
    """无冲突复制数据类型"""
    
    def __init__(self):
        self.document: str = ""
        self.version: int = 0
        self.operations: List[TextEdit] = []
        self.vector_clock: Dict[str, int] = defaultdict(int)
    
    def apply_operation(self, operation: TextEdit) -> bool:
        """应用操作"""
        if operation.version < self.version:
            return False
        
        transformed_ops = []
        for existing_op in self.operations:
            op1, op2 = OperationalTransform.transform(operation, existing_op)
            transformed_ops.append(op2)
        
        self.operations = transformed_ops + [operation]
        
        if operation.operation == "insert":
            self.document = (
                self.document[:operation.position] + 
                operation.content + 
                self.document[operation.position:]
            )
        elif operation.operation == "delete":
            self.document = (
                self.document[:operation.position] + 
                self.document[operation.position + operation.length:]
            )
        elif operation.operation == "replace":
            self.document = (
                self.document[:operation.position] + 
                operation.content + 
                self.document[operation.position + operation.length:]
            )
        
        self.version = operation.version
        self.vector_clock[operation.user_id] = operation.version
        
        return True
    
    def get_document_state(self) -> Dict[str, Any]:
        """获取文档状态"""
        return {
            "content": self.document,
            "version": self.version,
            "vector_clock": dict(self.vector_clock)
        }
    
    def synchronize(self, remote_state: Dict[str, Any]) -> List[TextEdit]:
        """同步远程状态"""
        remote_version = remote_state.get("version", 0)
        remote_vector_clock = remote_state.get("vector_clock", {})
        
        if remote_version <= self.version:
            return []
        
        missing_ops = []
        for op in self.operations:
            if op.version > remote_version:
                missing_ops.append(op)
        
        return missing_ops


class LockManager:
    """锁管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.local_locks: Dict[str, Lock] = {}
        self.lock_waiters: Dict[str, List[str]] = defaultdict(list)
        self.logger = logging.getLogger(__name__)
    
    async def acquire_lock(self, resource_id: str, user_id: str, 
                          lock_type: LockType = LockType.WRITE,
                          timeout: int = 30) -> Optional[Lock]:
        """获取锁"""
        lock_id = f"{resource_id}:{user_id}:{uuid.uuid4().hex}"
        
        if self.redis_client:
            return await self._acquire_redis_lock(lock_id, resource_id, user_id, lock_type, timeout)
        else:
            return self._acquire_local_lock(lock_id, resource_id, user_id, lock_type, timeout)
    
    async def _acquire_redis_lock(self, lock_id: str, resource_id: str, 
                                  user_id: str, lock_type: LockType, timeout: int) -> Optional[Lock]:
        """通过Redis获取锁"""
        key = f"lock:{resource_id}"
        value = json.dumps({
            "lock_id": lock_id,
            "user_id": user_id,
            "lock_type": lock_type.value,
            "acquired_at": time.time()
        })
        
        acquired = self.redis_client.set(key, value, nx=True, ex=timeout)
        
        if acquired:
            lock = Lock(
                lock_id=lock_id,
                resource_id=resource_id,
                user_id=user_id,
                lock_type=lock_type,
                expires_at=time.time() + timeout
            )
            return lock
        
        return None
    
    def _acquire_local_lock(self, lock_id: str, resource_id: str, 
                           user_id: str, lock_type: LockType, timeout: int) -> Optional[Lock]:
        """本地获取锁"""
        existing_lock = self.local_locks.get(resource_id)
        
        if existing_lock and existing_lock.expires_at and existing_lock.expires_at > time.time():
            if existing_lock.user_id == user_id:
                return existing_lock
            return None
        
        lock = Lock(
            lock_id=lock_id,
            resource_id=resource_id,
            user_id=user_id,
            lock_type=lock_type,
            expires_at=time.time() + timeout
        )
        
        self.local_locks[resource_id] = lock
        return lock
    
    async def release_lock(self, lock_id: str, resource_id: str, user_id: str) -> bool:
        """释放锁"""
        if self.redis_client:
            return await self._release_redis_lock(lock_id, resource_id, user_id)
        else:
            return self._release_local_lock(lock_id, resource_id, user_id)
    
    async def _release_redis_lock(self, lock_id: str, resource_id: str, user_id: str) -> bool:
        """通过Redis释放锁"""
        key = f"lock:{resource_id}"
        value = self.redis_client.get(key)
        
        if value:
            lock_data = json.loads(value)
            if lock_data.get("lock_id") == lock_id and lock_data.get("user_id") == user_id:
                self.redis_client.delete(key)
                return True
        
        return False
    
    def _release_local_lock(self, lock_id: str, resource_id: str, user_id: str) -> bool:
        """本地释放锁"""
        existing_lock = self.local_locks.get(resource_id)
        
        if existing_lock and existing_lock.lock_id == lock_id and existing_lock.user_id == user_id:
            del self.local_locks[resource_id]
            return True
        
        return False
    
    def get_lock(self, resource_id: str) -> Optional[Lock]:
        """获取锁信息"""
        if self.redis_client:
            key = f"lock:{resource_id}"
            value = self.redis_client.get(key)
            if value:
                lock_data = json.loads(value)
                return Lock(**lock_data)
        else:
            return self.local_locks.get(resource_id)
        
        return None
    
    def get_all_locks(self) -> Dict[str, Lock]:
        """获取所有锁"""
        if self.redis_client:
            locks = {}
            pattern = "lock:*"
            keys = self.redis_client.keys(pattern)
            for key in keys:
                value = self.redis_client.get(key)
                if value:
                    lock_data = json.loads(value)
                    resource_id = key.decode().replace("lock:", "")
                    locks[resource_id] = Lock(**lock_data)
            return locks
        else:
            return self.local_locks.copy()


class PresenceManager:
    """在线状态管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.local_users: Dict[str, User] = {}
        self.project_users: Dict[str, Set[str]] = defaultdict(set)
        self.logger = logging.getLogger(__name__)
    
    def user_join(self, project_id: str, user: User):
        """用户加入"""
        self.local_users[user.user_id] = user
        self.project_users[project_id].add(user.user_id)
        
        if self.redis_client:
            self._sync_user_join(project_id, user)
        
        self.logger.info(f"User {user.username} joined project {project_id}")
    
    def user_leave(self, project_id: str, user_id: str):
        """用户离开"""
        if user_id in self.local_users:
            del self.local_users[user_id]
        
        if project_id in self.project_users:
            self.project_users[project_id].discard(user_id)
            if not self.project_users[project_id]:
                del self.project_users[project_id]
        
        if self.redis_client:
            self._sync_user_leave(project_id, user_id)
        
        self.logger.info(f"User {user_id} left project {project_id}")
    
    def update_user_status(self, user_id: str, status: UserStatus):
        """更新用户状态"""
        if user_id in self.local_users:
            self.local_users[user_id].status = status
            self.local_users[user_id].last_activity = time.time()
            
            if self.redis_client:
                self._sync_user_status(user_id, status)
    
    def get_user(self, user_id: str) -> Optional[User]:
        """获取用户信息"""
        if user_id in self.local_users:
            return self.local_users[user_id]
        
        if self.redis_client:
            return self._get_user_from_redis(user_id)
        
        return None
    
    def get_project_users(self, project_id: str) -> List[User]:
        """获取项目用户列表"""
        user_ids = self.project_users.get(project_id, set())
        users = []
        
        for user_id in user_ids:
            user = self.get_user(user_id)
            if user:
                users.append(user)
        
        return users
    
    def _sync_user_join(self, project_id: str, user: User):
        """同步用户加入"""
        key = f"presence:{project_id}:{user.user_id}"
        value = json.dumps(asdict(user))
        self.redis_client.setex(key, 300, value)
        
        project_key = f"presence:project:{project_id}"
        self.redis_client.sadd(project_key, user.user_id)
        self.redis_client.expire(project_key, 300)
    
    def _sync_user_leave(self, project_id: str, user_id: str):
        """同步用户离开"""
        key = f"presence:{project_id}:{user_id}"
        self.redis_client.delete(key)
        
        project_key = f"presence:project:{project_id}"
        self.redis_client.srem(project_key, user_id)
    
    def _sync_user_status(self, user_id: str, status: UserStatus):
        """同步用户状态"""
        pattern = f"presence:*:{user_id}"
        keys = self.redis_client.keys(pattern)
        
        for key in keys:
            value = self.redis_client.get(key)
            if value:
                user_data = json.loads(value)
                user_data["status"] = status.value
                user_data["last_activity"] = time.time()
                self.redis_client.setex(key, 300, json.dumps(user_data))
    
    def _get_user_from_redis(self, user_id: str) -> Optional[User]:
        """从Redis获取用户"""
        pattern = f"presence:*:{user_id}"
        keys = self.redis_client.keys(pattern)
        
        if keys:
            value = self.redis_client.get(keys[0])
            if value:
                user_data = json.loads(value)
                return User(**user_data)
        
        return None


class CollaborationRoom:
    """协作房间"""
    
    def __init__(self, room_id: str, redis_client: Optional[redis.Redis] = None):
        self.room_id = room_id
        self.redis_client = redis_client
        
        self.crdt = ConflictFreeReplicatedDataType()
        self.lock_manager = LockManager(redis_client)
        self.presence_manager = PresenceManager(redis_client)
        
        self.cursors: Dict[str, CursorPosition] = {}
        self.selections: Dict[str, Selection] = {}
        self.comments: Dict[str, Comment] = {}
        
        self.participants: Dict[str, WebSocket] = {}
        self.event_queue: deque = deque()
        
        self.logger = logging.getLogger(__name__)
    
    async def join(self, websocket: WebSocket, user: User) -> bool:
        """加入房间"""
        await websocket.accept()
        self.participants[user.user_id] = websocket
        self.presence_manager.user_join(self.room_id, user)
        
        await self.broadcast_event(CollaborationEvent(
            event_type=CollaborationEventType.USER_JOIN,
            user_id=user.user_id,
            data=asdict(user)
        ))
        
        return True
    
    async def leave(self, user_id: str):
        """离开房间"""
        if user_id in self.participants:
            del self.participants[user_id]
        
        self.presence_manager.user_leave(self.room_id, user_id)
        
        await self.broadcast_event(CollaborationEvent(
            event_type=CollaborationEventType.USER_LEAVE,
            user_id=user_id,
            data={"user_id": user_id}
        ))
    
    async def broadcast_event(self, event: CollaborationEvent, exclude_user: Optional[str] = None):
        """广播事件"""
        message = json.dumps({
            "event_type": event.event_type.value,
            "user_id": event.user_id,
            "data": event.data,
            "timestamp": event.timestamp,
            "event_id": event.event_id
        })
        
        disconnected_users = []
        
        for user_id, websocket in self.participants.items():
            if exclude_user and user_id == exclude_user:
                continue
            
            try:
                await websocket.send_text(message)
            except Exception as e:
                self.logger.error(f"Error sending message to {user_id}: {e}")
                disconnected_users.append(user_id)
        
        for user_id in disconnected_users:
            await self.leave(user_id)
    
    async def handle_text_edit(self, user_id: str, operation: str, 
                              position: int, content: str, length: int = 0) -> bool:
        """处理文本编辑"""
        edit = TextEdit(
            user_id=user_id,
            operation=operation,
            position=position,
            content=content,
            length=length,
            version=self.crdt.version + 1
        )
        
        if self.crdt.apply_operation(edit):
            await self.broadcast_event(CollaborationEvent(
                event_type=CollaborationEventType.TEXT_EDIT,
                user_id=user_id,
                data=asdict(edit)
            ))
            return True
        
        return False
    
    async def handle_cursor_move(self, user_id: str, line: int, column: int, color: str):
        """处理光标移动"""
        cursor = CursorPosition(
            user_id=user_id,
            username=self.presence_manager.get_user(user_id).username,
            line=line,
            column=column,
            color=color
        )
        
        self.cursors[user_id] = cursor
        
        await self.broadcast_event(CollaborationEvent(
            event_type=CollaborationEventType.CURSOR_MOVE,
            user_id=user_id,
            data=asdict(cursor)
        ), exclude_user=user_id)
    
    async def add_comment(self, user_id: str, line: int, content: str) -> str:
        """添加评论"""
        comment = Comment(
            comment_id=str(uuid.uuid4()),
            user_id=user_id,
            username=self.presence_manager.get_user(user_id).username,
            line=line,
            content=content
        )
        
        self.comments[comment.comment_id] = comment
        
        await self.broadcast_event(CollaborationEvent(
            event_type=CollaborationEventType.COMMENT_ADD,
            user_id=user_id,
            data=asdict(comment)
        ))
        
        return comment.comment_id
    
    def get_document_state(self) -> Dict[str, Any]:
        """获取文档状态"""
        return {
            "document": self.crdt.get_document_state(),
            "cursors": [asdict(cursor) for cursor in self.cursors.values()],
            "selections": [asdict(selection) for selection in self.selections.values()],
            "comments": [asdict(comment) for comment in self.comments.values()],
            "participants": [
                asdict(user) for user in self.presence_manager.get_project_users(self.room_id)
            ]
        }


class RealtimeCollaborationEngine:
    """实时协作引擎"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.rooms: Dict[str, CollaborationRoom] = {}
        self.logger = logging.getLogger(__name__)
    
    def get_or_create_room(self, room_id: str) -> CollaborationRoom:
        """获取或创建房间"""
        if room_id not in self.rooms:
            self.rooms[room_id] = CollaborationRoom(room_id, self.redis_client)
        return self.rooms[room_id]
    
    def remove_room(self, room_id: str):
        """移除房间"""
        if room_id in self.rooms:
            del self.rooms[room_id]
            self.logger.info(f"Room {room_id} removed")
    
    def get_room_stats(self, room_id: str) -> Optional[Dict[str, Any]]:
        """获取房间统计"""
        if room_id not in self.rooms:
            return None
        
        room = self.rooms[room_id]
        return {
            "room_id": room_id,
            "participant_count": len(room.participants),
            "document_version": room.crdt.version,
            "comment_count": len(room.comments),
            "active_cursors": len(room.cursors)
        }
    
    def get_all_rooms_stats(self) -> Dict[str, Any]:
        """获取所有房间统计"""
        return {
            "total_rooms": len(self.rooms),
            "total_participants": sum(len(room.participants) for room in self.rooms.values()),
            "rooms": {
                room_id: self.get_room_stats(room_id)
                for room_id in self.rooms.keys()
            }
        }


_global_collaboration_engine: Optional[RealtimeCollaborationEngine] = None


def get_collaboration_engine(redis_client: Optional[redis.Redis] = None) -> RealtimeCollaborationEngine:
    """获取全局协作引擎实例"""
    global _global_collaboration_engine
    
    if _global_collaboration_engine is None:
        _global_collaboration_engine = RealtimeCollaborationEngine(redis_client)
    
    return _global_collaboration_engine


async def websocket_endpoint(websocket: WebSocket, room_id: str, user_id: str, username: str):
    """WebSocket端点"""
    engine = get_collaboration_engine()
    room = engine.get_or_create_room(room_id)
    
    user = User(
        user_id=user_id,
        username=username,
        color=f"#{hashlib.md5(username.encode()).hexdigest()[:6]}"
    )
    
    await room.join(websocket, user)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            event_type = message.get("event_type")
            
            if event_type == CollaborationEventType.TEXT_EDIT.value:
                await room.handle_text_edit(
                    user_id=user_id,
                    operation=message["data"]["operation"],
                    position=message["data"]["position"],
                    content=message["data"]["content"],
                    length=message["data"].get("length", 0)
                )
            elif event_type == CollaborationEventType.CURSOR_MOVE.value:
                await room.handle_cursor_move(
                    user_id=user_id,
                    line=message["data"]["line"],
                    column=message["data"]["column"],
                    color=user.color
                )
            elif event_type == CollaborationEventType.COMMENT_ADD.value:
                await room.add_comment(
                    user_id=user_id,
                    line=message["data"]["line"],
                    content=message["data"]["content"]
                )
            elif event_type == CollaborationEventType.HEARTBEAT.value:
                room.presence_manager.update_user_status(user_id, UserStatus.ONLINE)
                
    except WebSocketDisconnect:
        await room.leave(user_id)
    except Exception as e:
        room.logger.error(f"Error in websocket connection: {e}")
        await room.leave(user_id)
