import asyncio
import json
import time
import uuid
import hashlib
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
import redis
import sqlite3
import markdown
import re
from pathlib import Path
from functools import wraps

from app.core.service_decomposition import ServiceType


class UserRole(Enum):
    """用户角色"""
    ADMIN = "admin"
    MODERATOR = "moderator"
    DEVELOPER = "developer"
    CONTRIBUTOR = "contributor"
    MEMBER = "member"
    GUEST = "guest"


class UserStatus(Enum):
    """用户状态"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"
    PENDING = "pending"


class PostType(Enum):
    """帖子类型"""
    DISCUSSION = "discussion"
    QUESTION = "question"
    ANSWER = "answer"
    TUTORIAL = "tutorial"
    NEWS = "news"
    ANNOUNCEMENT = "announcement"


class PostStatus(Enum):
    """帖子状态"""
    PUBLISHED = "published"
    DRAFT = "draft"
    PENDING = "pending"
    DELETED = "deleted"


class CommentStatus(Enum):
    """评论状态"""
    APPROVED = "approved"
    PENDING = "pending"
    SPAM = "spam"
    DELETED = "deleted"


class ContentType(Enum):
    """内容类型"""
    ARTICLE = "article"
    TUTORIAL = "tutorial"
    API_DOC = "api_doc"
    EXAMPLE = "example"
    FAQ = "faq"
    BLOG = "blog"


class ActivityType(Enum):
    """活动类型"""
    HACKATHON = "hackathon"
    WORKSHOP = "workshop"
    WEBINAR = "webinar"
    CONTEST = "contest"
    MEETUP = "meetup"


class ContributionType(Enum):
    """贡献类型"""
    CODE = "code"
    DOCUMENTATION = "documentation"
    TRANSLATION = "translation"
    BUG_REPORT = "bug_report"
    FEATURE_REQUEST = "feature_request"
    TESTING = "testing"


@dataclass
class User:
    """用户信息"""
    user_id: str
    username: str
    email: str
    password_hash: str
    role: UserRole
    status: UserStatus
    created_at: float
    updated_at: float
    last_login: Optional[float] = None
    profile: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Post:
    """帖子信息"""
    post_id: str
    title: str
    content: str
    author_id: str
    post_type: PostType
    status: PostStatus
    created_at: float
    updated_at: float
    tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    views: int = 0
    likes: int = 0
    comments: int = 0
    featured: bool = False


@dataclass
class Comment:
    """评论信息"""
    comment_id: str
    post_id: str
    author_id: str
    content: str
    status: CommentStatus
    created_at: float
    updated_at: float
    likes: int = 0
    parent_id: Optional[str] = None


@dataclass
class Content:
    """内容信息"""
    content_id: str
    title: str
    content: str
    author_id: str
    content_type: ContentType
    created_at: float
    updated_at: float
    tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    views: int = 0
    likes: int = 0
    featured: bool = False


@dataclass
class Activity:
    """活动信息"""
    activity_id: str
    title: str
    description: str
    organizer: str
    activity_type: ActivityType
    start_time: float
    end_time: float
    location: str
    created_at: float
    updated_at: float
    participants: List[str] = field(default_factory=list)
    max_participants: Optional[int] = None
    registration_open: bool = True
    featured: bool = False


@dataclass
class Contribution:
    """贡献信息"""
    contribution_id: str
    contributor_id: str
    contribution_type: ContributionType
    title: str
    description: str
    status: str  # pending, approved, rejected
    created_at: float
    updated_at: float
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Notification:
    """通知信息"""
    notification_id: str
    user_id: str
    title: str
    message: str
    read: bool
    created_at: float
    notification_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class UserManager:
    """用户管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.users: Dict[str, User] = {}
        self.logger = logging.getLogger(__name__)
    
    def create_user(self, username: str, email: str, password: str, 
                   role: UserRole = UserRole.MEMBER) -> User:
        """创建用户"""
        user_id = str(uuid.uuid4())
        password_hash = self._hash_password(password)
        
        user = User(
            user_id=user_id,
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            status=UserStatus.ACTIVE,
            created_at=time.time(),
            updated_at=time.time()
        )
        
        self.users[user_id] = user
        
        if self.redis_client:
            self._cache_user(user)
        
        self.logger.info(f"Created user: {username}")
        return user
    
    def get_user(self, user_id: str) -> Optional[User]:
        """获取用户"""
        if user_id in self.users:
            return self.users[user_id]
        
        if self.redis_client:
            return self._get_cached_user(user_id)
        
        return None
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """通过用户名获取用户"""
        for user in self.users.values():
            if user.username == username:
                return user
        return None
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """通过邮箱获取用户"""
        for user in self.users.values():
            if user.email == email:
                return user
        return None
    
    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """认证用户"""
        user = self.get_user_by_username(username) or self.get_user_by_email(username)
        if user and self._verify_password(password, user.password_hash):
            user.last_login = time.time()
            user.updated_at = time.time()
            
            if self.redis_client:
                self._update_cached_user(user)
            
            return user
        return None
    
    def update_user(self, user_id: str, **kwargs) -> Optional[User]:
        """更新用户"""
        user = self.get_user(user_id)
        if not user:
            return None
        
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        
        user.updated_at = time.time()
        
        if self.redis_client:
            self._update_cached_user(user)
        
        return user
    
    def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        if user_id in self.users:
            del self.users[user_id]
            
            if self.redis_client:
                self._remove_cached_user(user_id)
            
            return True
        return False
    
    def get_all_users(self) -> List[User]:
        """获取所有用户"""
        return list(self.users.values())
    
    def get_users_by_role(self, role: UserRole) -> List[User]:
        """按角色获取用户"""
        return [user for user in self.users.values() if user.role == role]
    
    def _hash_password(self, password: str) -> str:
        """哈希密码"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """验证密码"""
        return self._hash_password(password) == password_hash
    
    def _cache_user(self, user: User):
        """缓存用户到Redis"""
        key = f"user:{user.user_id}"
        data = json.dumps(asdict(user))
        self.redis_client.setex(key, 3600, data)
    
    def _get_cached_user(self, user_id: str) -> Optional[User]:
        """从Redis获取缓存用户"""
        key = f"user:{user_id}"
        data = self.redis_client.get(key)
        if data:
            user_data = json.loads(data)
            user_data['role'] = UserRole(user_data['role'])
            user_data['status'] = UserStatus(user_data['status'])
            return User(**user_data)
        return None
    
    def _update_cached_user(self, user: User):
        """更新Redis中的用户缓存"""
        key = f"user:{user.user_id}"
        data = json.dumps(asdict(user))
        self.redis_client.setex(key, 3600, data)
    
    def _remove_cached_user(self, user_id: str):
        """从Redis移除用户缓存"""
        key = f"user:{user_id}"
        self.redis_client.delete(key)


class ForumManager:
    """论坛管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.posts: Dict[str, Post] = {}
        self.comments: Dict[str, Comment] = {}
        self.logger = logging.getLogger(__name__)
    
    def create_post(self, title: str, content: str, author_id: str, 
                   post_type: PostType, tags: List[str] = None) -> Post:
        """创建帖子"""
        post_id = str(uuid.uuid4())
        
        post = Post(
            post_id=post_id,
            title=title,
            content=content,
            author_id=author_id,
            post_type=post_type,
            status=PostStatus.PUBLISHED,
            created_at=time.time(),
            updated_at=time.time(),
            tags=tags or []
        )
        
        self.posts[post_id] = post
        
        if self.redis_client:
            self._cache_post(post)
        
        self.logger.info(f"Created post: {title}")
        return post
    
    def get_post(self, post_id: str) -> Optional[Post]:
        """获取帖子"""
        if post_id in self.posts:
            post = self.posts[post_id]
            post.views += 1
            return post
        
        if self.redis_client:
            return self._get_cached_post(post_id)
        
        return None
    
    def update_post(self, post_id: str, **kwargs) -> Optional[Post]:
        """更新帖子"""
        post = self.get_post(post_id)
        if not post:
            return None
        
        for key, value in kwargs.items():
            if hasattr(post, key):
                setattr(post, key, value)
        
        post.updated_at = time.time()
        
        if self.redis_client:
            self._update_cached_post(post)
        
        return post
    
    def delete_post(self, post_id: str) -> bool:
        """删除帖子"""
        if post_id in self.posts:
            del self.posts[post_id]
            
            if self.redis_client:
                self._remove_cached_post(post_id)
            
            return True
        return False
    
    def create_comment(self, post_id: str, author_id: str, content: str, 
                      parent_id: Optional[str] = None) -> Comment:
        """创建评论"""
        comment_id = str(uuid.uuid4())
        
        comment = Comment(
            comment_id=comment_id,
            post_id=post_id,
            author_id=author_id,
            content=content,
            status=CommentStatus.APPROVED,
            created_at=time.time(),
            updated_at=time.time(),
            parent_id=parent_id
        )
        
        self.comments[comment_id] = comment
        
        post = self.get_post(post_id)
        if post:
            post.comments += 1
        
        if self.redis_client:
            self._cache_comment(comment)
        
        return comment
    
    def get_comments(self, post_id: str) -> List[Comment]:
        """获取帖子评论"""
        return [c for c in self.comments.values() if c.post_id == post_id]
    
    def get_posts(self, post_type: Optional[PostType] = None, 
                 tags: Optional[List[str]] = None) -> List[Post]:
        """获取帖子列表"""
        posts = list(self.posts.values())
        
        if post_type:
            posts = [p for p in posts if p.post_type == post_type]
        
        if tags:
            posts = [p for p in posts if any(tag in p.tags for tag in tags)]
        
        return sorted(posts, key=lambda x: x.created_at, reverse=True)
    
    def search_posts(self, query: str) -> List[Post]:
        """搜索帖子"""
        query = query.lower()
        results = []
        
        for post in self.posts.values():
            if (query in post.title.lower() or
                query in post.content.lower() or
                any(query in tag.lower() for tag in post.tags)):
                results.append(post)
        
        return sorted(results, key=lambda x: x.created_at, reverse=True)
    
    def _cache_post(self, post: Post):
        """缓存帖子到Redis"""
        key = f"post:{post.post_id}"
        data = json.dumps(asdict(post))
        self.redis_client.setex(key, 3600, data)
    
    def _get_cached_post(self, post_id: str) -> Optional[Post]:
        """从Redis获取缓存帖子"""
        key = f"post:{post_id}"
        data = self.redis_client.get(key)
        if data:
            post_data = json.loads(data)
            post_data['post_type'] = PostType(post_data['post_type'])
            post_data['status'] = PostStatus(post_data['status'])
            return Post(**post_data)
        return None
    
    def _update_cached_post(self, post: Post):
        """更新Redis中的帖子缓存"""
        key = f"post:{post.post_id}"
        data = json.dumps(asdict(post))
        self.redis_client.setex(key, 3600, data)
    
    def _remove_cached_post(self, post_id: str):
        """从Redis移除帖子缓存"""
        key = f"post:{post_id}"
        self.redis_client.delete(key)
    
    def _cache_comment(self, comment: Comment):
        """缓存评论到Redis"""
        key = f"comment:{comment.comment_id}"
        data = json.dumps(asdict(comment))
        self.redis_client.setex(key, 3600, data)


class ContentManager:
    """内容管理器"""
    
    def __init__(self, content_dir: str, redis_client: Optional[redis.Redis] = None):
        self.content_dir = Path(content_dir)
        self.redis_client = redis_client
        self.content: Dict[str, Content] = {}
        self.logger = logging.getLogger(__name__)
        
        self.content_dir.mkdir(parents=True, exist_ok=True)
        
        self._load_content()
    
    def _load_content(self):
        """加载内容"""
        for content_file in self.content_dir.rglob("*.md"):
            try:
                content_id = content_file.stem
                content = content_file.read_text(encoding='utf-8')
                
                metadata_match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
                if metadata_match:
                    metadata = yaml.safe_load(metadata_match.group(1))
                    content_body = content[metadata_match.end():]
                else:
                    metadata = {}
                    content_body = content
                
                content_obj = Content(
                    content_id=content_id,
                    title=metadata.get("title", content_id),
                    content=content_body,
                    author_id=metadata.get("author", "system"),
                    content_type=ContentType(metadata.get("type", "article")),
                    created_at=metadata.get("created_at", time.time()),
                    updated_at=metadata.get("updated_at", time.time()),
                    tags=metadata.get("tags", []),
                    categories=metadata.get("categories", [])
                )
                
                self.content[content_id] = content_obj
            except Exception as e:
                self.logger.error(f"Error loading content {content_file}: {e}")
    
    def create_content(self, title: str, content: str, author_id: str, 
                      content_type: ContentType, tags: List[str] = None) -> Content:
        """创建内容"""
        content_id = str(uuid.uuid4())
        
        content_obj = Content(
            content_id=content_id,
            title=title,
            content=content,
            author_id=author_id,
            content_type=content_type,
            created_at=time.time(),
            updated_at=time.time(),
            tags=tags or []
        )
        
        self.content[content_id] = content_obj
        self._save_content(content_obj)
        
        if self.redis_client:
            self._cache_content(content_obj)
        
        return content_obj
    
    def _save_content(self, content: Content):
        """保存内容到文件"""
        content_file = self.content_dir / f"{content.content_id}.md"
        
        metadata = {
            "title": content.title,
            "author": content.author_id,
            "type": content.content_type.value,
            "created_at": content.created_at,
            "updated_at": content.updated_at,
            "tags": content.tags,
            "categories": content.categories
        }
        
        content_text = f"---\n{yaml.dump(metadata)}\n---\n{content.content}"
        content_file.write_text(content_text, encoding='utf-8')
    
    def get_content(self, content_id: str) -> Optional[Content]:
        """获取内容"""
        if content_id in self.content:
            content = self.content[content_id]
            content.views += 1
            return content
        
        if self.redis_client:
            return self._get_cached_content(content_id)
        
        return None
    
    def get_content_by_type(self, content_type: ContentType) -> List[Content]:
        """按类型获取内容"""
        return [c for c in self.content.values() if c.content_type == content_type]
    
    def search_content(self, query: str) -> List[Content]:
        """搜索内容"""
        query = query.lower()
        results = []
        
        for content in self.content.values():
            if (query in content.title.lower() or
                query in content.content.lower() or
                any(query in tag.lower() for tag in content.tags)):
                results.append(content)
        
        return sorted(results, key=lambda x: x.created_at, reverse=True)
    
    def _cache_content(self, content: Content):
        """缓存内容到Redis"""
        key = f"content:{content.content_id}"
        data = json.dumps(asdict(content))
        self.redis_client.setex(key, 3600, data)
    
    def _get_cached_content(self, content_id: str) -> Optional[Content]:
        """从Redis获取缓存内容"""
        key = f"content:{content_id}"
        data = self.redis_client.get(key)
        if data:
            content_data = json.loads(data)
            content_data['content_type'] = ContentType(content_data['content_type'])
            return Content(**content_data)
        return None


class ActivityManager:
    """活动管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.activities: Dict[str, Activity] = {}
        self.logger = logging.getLogger(__name__)
    
    def create_activity(self, title: str, description: str, organizer: str, 
                       activity_type: ActivityType, start_time: float, 
                       end_time: float, location: str) -> Activity:
        """创建活动"""
        activity_id = str(uuid.uuid4())
        
        activity = Activity(
            activity_id=activity_id,
            title=title,
            description=description,
            organizer=organizer,
            activity_type=activity_type,
            start_time=start_time,
            end_time=end_time,
            location=location,
            created_at=time.time(),
            updated_at=time.time()
        )
        
        self.activities[activity_id] = activity
        
        if self.redis_client:
            self._cache_activity(activity)
        
        return activity
    
    def get_activity(self, activity_id: str) -> Optional[Activity]:
        """获取活动"""
        if activity_id in self.activities:
            return self.activities[activity_id]
        
        if self.redis_client:
            return self._get_cached_activity(activity_id)
        
        return None
    
    def register_for_activity(self, activity_id: str, user_id: str) -> bool:
        """注册活动"""
        activity = self.get_activity(activity_id)
        if not activity:
            return False
        
        if activity.max_participants and len(activity.participants) >= activity.max_participants:
            return False
        
        if user_id not in activity.participants:
            activity.participants.append(user_id)
            activity.updated_at = time.time()
            
            if self.redis_client:
                self._update_cached_activity(activity)
            
            return True
        
        return False
    
    def get_upcoming_activities(self) -> List[Activity]:
        """获取即将到来的活动"""
        now = time.time()
        return [a for a in self.activities.values() if a.start_time > now]
    
    def get_past_activities(self) -> List[Activity]:
        """获取过去的活动"""
        now = time.time()
        return [a for a in self.activities.values() if a.end_time < now]
    
    def _cache_activity(self, activity: Activity):
        """缓存活动到Redis"""
        key = f"activity:{activity.activity_id}"
        data = json.dumps(asdict(activity))
        self.redis_client.setex(key, 3600, data)
    
    def _get_cached_activity(self, activity_id: str) -> Optional[Activity]:
        """从Redis获取缓存活动"""
        key = f"activity:{activity_id}"
        data = self.redis_client.get(key)
        if data:
            activity_data = json.loads(data)
            activity_data['activity_type'] = ActivityType(activity_data['activity_type'])
            return Activity(**activity_data)
        return None
    
    def _update_cached_activity(self, activity: Activity):
        """更新Redis中的活动缓存"""
        key = f"activity:{activity.activity_id}"
        data = json.dumps(asdict(activity))
        self.redis_client.setex(key, 3600, data)


class ContributionManager:
    """贡献管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.contributions: Dict[str, Contribution] = {}
        self.logger = logging.getLogger(__name__)
    
    def create_contribution(self, contributor_id: str, contribution_type: ContributionType, 
                          title: str, description: str, url: Optional[str] = None) -> Contribution:
        """创建贡献"""
        contribution_id = str(uuid.uuid4())
        
        contribution = Contribution(
            contribution_id=contribution_id,
            contributor_id=contributor_id,
            contribution_type=contribution_type,
            title=title,
            description=description,
            status="pending",
            created_at=time.time(),
            updated_at=time.time(),
            url=url
        )
        
        self.contributions[contribution_id] = contribution
        
        if self.redis_client:
            self._cache_contribution(contribution)
        
        return contribution
    
    def get_contribution(self, contribution_id: str) -> Optional[Contribution]:
        """获取贡献"""
        if contribution_id in self.contributions:
            return self.contributions[contribution_id]
        
        if self.redis_client:
            return self._get_cached_contribution(contribution_id)
        
        return None
    
    def update_contribution_status(self, contribution_id: str, status: str) -> bool:
        """更新贡献状态"""
        contribution = self.get_contribution(contribution_id)
        if not contribution:
            return False
        
        contribution.status = status
        contribution.updated_at = time.time()
        
        if self.redis_client:
            self._update_cached_contribution(contribution)
        
        return True
    
    def get_contributions_by_type(self, contribution_type: ContributionType) -> List[Contribution]:
        """按类型获取贡献"""
        return [c for c in self.contributions.values() if c.contribution_type == contribution_type]
    
    def get_contributions_by_status(self, status: str) -> List[Contribution]:
        """按状态获取贡献"""
        return [c for c in self.contributions.values() if c.status == status]
    
    def _cache_contribution(self, contribution: Contribution):
        """缓存贡献到Redis"""
        key = f"contribution:{contribution.contribution_id}"
        data = json.dumps(asdict(contribution))
        self.redis_client.setex(key, 3600, data)
    
    def _get_cached_contribution(self, contribution_id: str) -> Optional[Contribution]:
        """从Redis获取缓存贡献"""
        key = f"contribution:{contribution_id}"
        data = self.redis_client.get(key)
        if data:
            contribution_data = json.loads(data)
            contribution_data['contribution_type'] = ContributionType(contribution_data['contribution_type'])
            return Contribution(**contribution_data)
        return None
    
    def _update_cached_contribution(self, contribution: Contribution):
        """更新Redis中的贡献缓存"""
        key = f"contribution:{contribution.contribution_id}"
        data = json.dumps(asdict(contribution))
        self.redis_client.setex(key, 3600, data)


class NotificationManager:
    """通知管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.notifications: Dict[str, Notification] = {}
        self.user_notifications: Dict[str, List[str]] = defaultdict(list)
        self.logger = logging.getLogger(__name__)
    
    def create_notification(self, user_id: str, title: str, message: str, 
                          notification_type: str, metadata: Optional[Dict[str, Any]] = None) -> Notification:
        """创建通知"""
        notification_id = str(uuid.uuid4())
        
        notification = Notification(
            notification_id=notification_id,
            user_id=user_id,
            title=title,
            message=message,
            read=False,
            created_at=time.time(),
            notification_type=notification_type,
            metadata=metadata or {}
        )
        
        self.notifications[notification_id] = notification
        self.user_notifications[user_id].append(notification_id)
        
        if self.redis_client:
            self._cache_notification(notification)
        
        return notification
    
    def get_user_notifications(self, user_id: str, unread_only: bool = False) -> List[Notification]:
        """获取用户通知"""
        notification_ids = self.user_notifications.get(user_id, [])
        notifications = [self.notifications.get(nid) for nid in notification_ids if self.notifications.get(nid)]
        
        if unread_only:
            notifications = [n for n in notifications if not n.read]
        
        return sorted(notifications, key=lambda x: x.created_at, reverse=True)
    
    def mark_notification_read(self, notification_id: str) -> bool:
        """标记通知为已读"""
        notification = self.notifications.get(notification_id)
        if not notification:
            return False
        
        notification.read = True
        
        if self.redis_client:
            self._update_cached_notification(notification)
        
        return True
    
    def mark_all_notifications_read(self, user_id: str) -> bool:
        """标记所有通知为已读"""
        notification_ids = self.user_notifications.get(user_id, [])
        for nid in notification_ids:
            notification = self.notifications.get(nid)
            if notification and not notification.read:
                notification.read = True
                
                if self.redis_client:
                    self._update_cached_notification(notification)
        
        return True
    
    def _cache_notification(self, notification: Notification):
        """缓存通知到Redis"""
        key = f"notification:{notification.notification_id}"
        data = json.dumps(asdict(notification))
        self.redis_client.setex(key, 3600, data)
    
    def _update_cached_notification(self, notification: Notification):
        """更新Redis中的通知缓存"""
        key = f"notification:{notification.notification_id}"
        data = json.dumps(asdict(notification))
        self.redis_client.setex(key, 3600, data)


class DeveloperCommunity:
    """开发者社区"""
    
    def __init__(self, content_dir: str = "./content", 
                 redis_client: Optional[redis.Redis] = None):
        self.content_dir = content_dir
        self.redis_client = redis_client
        
        self.user_manager = UserManager(redis_client)
        self.forum_manager = ForumManager(redis_client)
        self.content_manager = ContentManager(content_dir, redis_client)
        self.activity_manager = ActivityManager(redis_client)
        self.contribution_manager = ContributionManager(redis_client)
        self.notification_manager = NotificationManager(redis_client)
        
        self.logger = logging.getLogger(__name__)
    
    def register_user(self, username: str, email: str, password: str) -> User:
        """注册用户"""
        return self.user_manager.create_user(username, email, password)
    
    def login_user(self, username: str, password: str) -> Optional[User]:
        """用户登录"""
        return self.user_manager.authenticate_user(username, password)
    
    def create_post(self, title: str, content: str, author_id: str, 
                   post_type: PostType, tags: List[str] = None) -> Post:
        """创建帖子"""
        post = self.forum_manager.create_post(title, content, author_id, post_type, tags)
        
        self.notification_manager.create_notification(
            author_id,
            "帖子已发布",
            f"你的帖子 '{title}' 已成功发布",
            "post_creation"
        )
        
        return post
    
    def create_content(self, title: str, content: str, author_id: str, 
                      content_type: ContentType, tags: List[str] = None) -> Content:
        """创建内容"""
        content_obj = self.content_manager.create_content(title, content, author_id, content_type, tags)
        
        self.notification_manager.create_notification(
            author_id,
            "内容已发布",
            f"你的内容 '{title}' 已成功发布",
            "content_creation"
        )
        
        return content_obj
    
    def create_activity(self, title: str, description: str, organizer: str, 
                       activity_type: ActivityType, start_time: float, 
                       end_time: float, location: str) -> Activity:
        """创建活动"""
        activity = self.activity_manager.create_activity(
            title, description, organizer, activity_type, start_time, end_time, location
        )
        
        # 通知所有用户
        for user in self.user_manager.get_all_users():
            self.notification_manager.create_notification(
                user.user_id,
                "新活动",
                f"新活动 '{title}' 已发布",
                "activity_creation"
            )
        
        return activity
    
    def submit_contribution(self, contributor_id: str, contribution_type: ContributionType, 
                          title: str, description: str, url: Optional[str] = None) -> Contribution:
        """提交贡献"""
        contribution = self.contribution_manager.create_contribution(
            contributor_id, contribution_type, title, description, url
        )
        
        # 通知管理员
        for admin in self.user_manager.get_users_by_role(UserRole.ADMIN):
            self.notification_manager.create_notification(
                admin.user_id,
                "新贡献",
                f"新贡献 '{title}' 已提交",
                "contribution_submission"
            )
        
        return contribution
    
    def get_community_stats(self) -> Dict[str, Any]:
        """获取社区统计"""
        users = self.user_manager.get_all_users()
        posts = self.forum_manager.get_posts()
        content = self.content_manager.content
        activities = self.activity_manager.activities
        contributions = self.contribution_manager.contributions
        
        stats = {
            "users": {
                "total": len(users),
                "active": len([u for u in users if u.status == UserStatus.ACTIVE]),
                "by_role": defaultdict(int)
            },
            "forum": {
                "posts": len(posts),
                "comments": len(self.forum_manager.comments),
                "by_type": defaultdict(int)
            },
            "content": {
                "total": len(content),
                "by_type": defaultdict(int)
            },
            "activities": {
                "total": len(activities),
                "upcoming": len(self.activity_manager.get_upcoming_activities()),
                "past": len(self.activity_manager.get_past_activities())
            },
            "contributions": {
                "total": len(contributions),
                "by_type": defaultdict(int),
                "by_status": defaultdict(int)
            }
        }
        
        for user in users:
            stats["users"]["by_role"][user.role.value] += 1
        
        for post in posts:
            stats["forum"]["by_type"][post.post_type.value] += 1
        
        for c in content.values():
            stats["content"]["by_type"][c.content_type.value] += 1
        
        for contribution in contributions.values():
            stats["contributions"]["by_type"][contribution.contribution_type.value] += 1
            stats["contributions"]["by_status"][contribution.status] += 1
        
        stats["users"]["by_role"] = dict(stats["users"]["by_role"])
        stats["forum"]["by_type"] = dict(stats["forum"]["by_type"])
        stats["content"]["by_type"] = dict(stats["content"]["by_type"])
        stats["contributions"]["by_type"] = dict(stats["contributions"]["by_type"])
        stats["contributions"]["by_status"] = dict(stats["contributions"]["by_status"])
        
        return stats


_global_community: Optional[DeveloperCommunity] = None


def get_developer_community(content_dir: str = "./content",
                          redis_client: Optional[redis.Redis] = None) -> DeveloperCommunity:
    """获取开发者社区实例"""
    global _global_community
    
    if _global_community is None:
        _global_community = DeveloperCommunity(content_dir, redis_client)
    
    return _global_community


def create_developer_community(content_dir: str = "./content",
                             redis_client: Optional[redis.Redis] = None) -> DeveloperCommunity:
    """创建开发者社区"""
    return DeveloperCommunity(content_dir, redis_client)
