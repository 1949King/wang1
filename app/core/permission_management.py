"""
权限管理系统
==============
实现完善的用户权限和访问控制
"""

import os
import json
import logging
import threading
import time
import hashlib
from typing import Dict, Any, List, Optional, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from datetime import datetime, timedelta

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import SecurityError, ErrorCode

logger = logging.getLogger(__name__)


class Permission(Enum):
    """权限类型"""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    ADMIN = "admin"
    MANAGE_USERS = "manage_users"
    MANAGE_PERMISSIONS = "manage_permissions"
    MANAGE_PLUGINS = "manage_plugins"
    MANAGE_SYSTEM = "manage_system"


class Role(Enum):
    """用户角色"""
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    GUEST = "guest"


class ResourceType(Enum):
    """资源类型"""
    PROJECT = "project"
    ASSET = "asset"
    PLUGIN = "plugin"
    SYSTEM = "system"
    LOGS = "logs"
    CONFIG = "config"


@dataclass
class User:
    """用户对象"""
    user_id: str
    username: str
    email: str
    role: Role
    permissions: Set[Permission]
    created_at: float
    last_login: Optional[float] = None
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def has_permission(self, permission: Permission) -> bool:
        """检查用户是否有权限"""
        return permission in self.permissions
    
    def has_role(self, role: Role) -> bool:
        """检查用户是否有角色"""
        return self.role == role
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（不包含敏感信息）"""
        return {
            'user_id': self.user_id,
            'username': self.username,
            'email': self.email,
            'role': self.role.value,
            'permissions': [p.value for p in self.permissions],
            'created_at': self.created_at,
            'last_login': self.last_login,
            'is_active': self.is_active,
            'metadata': self.metadata
        }


@dataclass
class PermissionPolicy:
    """权限策略"""
    policy_id: str
    name: str
    description: str
    resource_type: ResourceType
    required_permissions: Set[Permission]
    conditions: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    is_active: bool = True
    
    def check_access(self, user: User, 
                   resource_id: str,
                   context: Optional[Dict[str, Any]] = None) -> bool:
        """检查访问权限"""
        if not user.is_active:
            return False
        
        # 检查角色权限
        if user.role == Role.ADMIN:
            return True
        
        # 检查具体权限
        for permission in self.required_permissions:
            if not user.has_permission(permission):
                return False
        
        # 检查条件
        if self.conditions:
            if not self._evaluate_conditions(user, resource_id, context):
                return False
        
        return True
    
    def _evaluate_conditions(self, user: User, 
                          resource_id: str,
                          context: Optional[Dict[str, Any]]) -> bool:
        """评估访问条件"""
        for condition_name, condition_value in self.conditions.items():
            if condition_name == "time_range":
                if not self._check_time_range(condition_value, user):
                    return False
            elif condition_name == "ip_whitelist":
                if not self._check_ip_whitelist(condition_value, context):
                    return False
            elif condition_name == "user_whitelist":
                if not self._check_user_whitelist(condition_value, user):
                    return False
        
        return True
    
    def _check_time_range(self, time_range: Dict[str, Any], 
                       user: User) -> bool:
        """检查时间范围"""
        current_time = time.time()
        start_time = time_range.get('start', 0)
        end_time = time_range.get('end', float('inf'))
        
        if start_time <= current_time <= end_time:
            return True
        return False
    
    def _check_ip_whitelist(self, whitelist: List[str], 
                          context: Optional[Dict[str, Any]]) -> bool:
        """检查IP白名单"""
        if not whitelist or not context:
            return True
        
        client_ip = context.get('client_ip', '')
        return client_ip in whitelist
    
    def _check_user_whitelist(self, whitelist: List[str], 
                            user: User) -> bool:
        """检查用户白名单"""
        if not whitelist:
            return True
        
        return user.user_id in whitelist


@dataclass
class AccessLog:
    """访问日志"""
    log_id: str
    user_id: str
    resource_type: ResourceType
    resource_id: str
    action: str
    granted: bool
    timestamp: float
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'log_id': self.log_id,
            'user_id': self.user_id,
            'resource_type': self.resource_type.value,
            'resource_id': self.resource_id,
            'action': self.action,
            'granted': self.granted,
            'timestamp': self.timestamp,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'metadata': self.metadata
        }


class PermissionManager:
    """权限管理器"""
    
    def __init__(self, users_file: str = "users.json",
                 policies_file: str = "policies.json",
                 access_log_file: str = "access_logs.json"):
        self.users_file = users_file
        self.policies_file = policies_file
        self.access_log_file = access_log_file
        
        self._users: Dict[str, User] = {}
        self._policies: Dict[str, PermissionPolicy] = {}
        self._access_logs: List[AccessLog] = []
        self._lock = threading.RLock()
        
        self._role_permissions: Dict[Role, Set[Permission]] = {
            Role.ADMIN: {
                Permission.READ, Permission.WRITE, Permission.DELETE, 
                Permission.EXECUTE, Permission.ADMIN, Permission.MANAGE_USERS,
                Permission.MANAGE_PERMISSIONS, Permission.MANAGE_PLUGINS, Permission.MANAGE_SYSTEM
            },
            Role.EDITOR: {
                Permission.READ, Permission.WRITE, Permission.EXECUTE
            },
            Role.VIEWER: {
                Permission.READ
            },
            Role.GUEST: set()
        }
        
        self._session_cache: Dict[str, Dict[str, Any]] = {}
        self._stats = {
            'total_users': 0,
            'active_users': 0,
            'total_policies': 0,
            'active_policies': 0,
            'total_access_logs': 0,
            'denied_access': 0
        }
        
        self._load_data()
    
    def _load_data(self):
        """加载数据"""
        # 加载用户数据
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    users_data = json.load(f)
                
                for user_data in users_data:
                    user = User(
                        user_id=user_data['user_id'],
                        username=user_data['username'],
                        email=user_data['email'],
                        role=Role(user_data['role']),
                        permissions=set(Permission(p) for p in user_data.get('permissions', [])),
                        created_at=user_data.get('created_at', time.time()),
                        last_login=user_data.get('last_login'),
                        is_active=user_data.get('is_active', True),
                        metadata=user_data.get('metadata', {})
                    )
                    
                    self._users[user.user_id] = user
                
                logger.info(f"已加载 {len(self._users)} 个用户")
            except Exception as e:
                logger.error(f"用户数据加载失败: {e}")
        
        # 加载策略数据
        if os.path.exists(self.policies_file):
            try:
                with open(self.policies_file, 'r', encoding='utf-8') as f:
                    policies_data = json.load(f)
                
                for policy_data in policies_data:
                    policy = PermissionPolicy(
                        policy_id=policy_data['policy_id'],
                        name=policy_data['name'],
                        description=policy_data['description'],
                        resource_type=ResourceType(policy_data['resource_type']),
                        required_permissions=set(Permission(p) for p in policy_data.get('required_permissions', [])),
                        conditions=policy_data.get('conditions', {}),
                        created_at=policy_data.get('created_at', time.time()),
                        is_active=policy_data.get('is_active', True)
                    )
                    
                    self._policies[policy.policy_id] = policy
                
                logger.info(f"已加载 {len(self._policies)} 个权限策略")
            except Exception as e:
                logger.error(f"策略数据加载失败: {e}")
        
        # 加载访问日志
        if os.path.exists(self.access_log_file):
            try:
                with open(self.access_log_file, 'r', encoding='utf-8') as f:
                    logs_data = json.load(f)
                    
                    for log_data in logs_data:
                        log = AccessLog(**log_data)
                        self._access_logs.append(log)
                
                logger.info(f"已加载 {len(self._access_logs)} 条访问日志")
            except Exception as e:
                logger.error(f"访问日志加载失败: {e}")
        
        # 更新统计
        self._update_stats()
    
    def _update_stats(self):
        """更新统计信息"""
        self._stats['total_users'] = len(self._users)
        self._stats['active_users'] = sum(1 for u in self._users.values() if u.is_active)
        self._stats['total_policies'] = len(self._policies)
        self._stats['active_policies'] = sum(1 for p in self._policies.values() if p.is_active)
        self._stats['total_access_logs'] = len(self._access_logs)
        self._stats['denied_access'] = sum(1 for log in self._access_logs if not log.granted)
    
    def _save_data(self):
        """保存数据"""
        try:
            # 保存用户数据
            users_data = [user.to_dict() for user in self._users.values()]
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(users_data, f, ensure_ascii=False, indent=2)
            
            # 保存策略数据
            policies_data = [policy.to_dict() for policy in self._policies.values()]
            with open(self.policies_file, 'w', encoding='utf-8') as f:
                json.dump(policies_data, f, ensure_ascii=False, indent=2)
            
            # 保存访问日志
            logs_data = [log.to_dict() for log in self._access_logs]
            with open(self.access_log_file, 'w', encoding='utf-8') as f:
                json.dump(logs_data, f, ensure_ascii=False, indent=2)
            
            logger.debug("数据已保存")
        except Exception as e:
            logger.error(f"数据保存失败: {e}")
            raise SecurityError(
                ErrorCode.SECURITY_ERROR,
                f"数据保存失败: {str(e)}"
            )
    
    @monitor_performance(threshold_warning=0.5, threshold_critical=2.0)
    def create_user(self, username: str, email: str, 
                   role: Role = Role.VIEWER,
                   password: str = None) -> User:
        """创建用户
        
        Args:
            username: 用户名
            email: 邮箱
            role: 角色
            password: 密码（可选）
        
        Returns:
            用户对象
        """
        user_id = f"user_{int(time.time())}"
        
        # 获取角色权限
        permissions = self._role_permissions.get(role, set())
        
        user = User(
            user_id=user_id,
            username=username,
            email=email,
            role=role,
            permissions=permissions,
            created_at=time.time(),
            is_active=True
        )
        
        with self._lock:
            self._users[user_id] = user
            self._save_data()
            self._update_stats()
        
        logger.info(f"用户创建成功: {username}")
        return user
    
    def update_user_role(self, user_id: str, new_role: Role) -> bool:
        """更新用户角色
        
        Args:
            user_id: 用户ID
            new_role: 新角色
        
        Returns:
            是否更新成功
        """
        with self._lock:
            if user_id not in self._users:
                logger.warning(f"用户不存在: {user_id}")
                return False
            
            user = self._users[user_id]
            user.role = new_role
            user.permissions = self._role_permissions.get(new_role, set())
            
            self._save_data()
            self._update_stats()
        
        logger.info(f"用户角色更新成功: {user_id} -> {new_role.value}")
        return True
    
    def grant_permission(self, user_id: str, permission: Permission) -> bool:
        """授予权限
        
        Args:
            user_id: 用户ID
            permission: 权限
        
        Returns:
            是否授予权限成功
        """
        with self._lock:
            if user_id not in self._users:
                logger.warning(f"用户不存在: {user_id}")
                return False
            
            user = self._users[user_id]
            user.permissions.add(permission)
            
            self._save_data()
        
        logger.info(f"权限已授予: {user_id} -> {permission.value}")
        return True
    
    def revoke_permission(self, user_id: str, permission: Permission) -> bool:
        """撤销权限
        
        Args:
            user_id: 用户ID
            permission: 权限
        
        Returns:
            是否撤销权限成功
        """
        with self._lock:
            if user_id not in self._users:
                logger.warning(f"用户不存在: {user_id}")
                return False
            
            user = self._users[user_id]
            
            if permission in user.permissions:
                user.permissions.remove(permission)
            else:
                logger.warning(f"用户没有此权限: {user_id} -> {permission.value}")
                return False
            
            self._save_data()
        
        logger.info(f"权限已撤销: {user_id} -> {permission.value}")
        return True
    
    def check_permission(self, user_id: str, permission: Permission) -> bool:
        """检查权限
        
        Args:
            user_id: 用户ID
            permission: 权限
        
        Returns:
            是否有权限
        """
        with self._lock:
            if user_id not in self._users:
                return False
            
            return self._users[user_id].has_permission(permission)
    
    def check_access(self, user_id: str, resource_type: ResourceType,
                   resource_id: str, action: str,
                   context: Optional[Dict[str, Any]] = None) -> bool:
        """检查访问权限
        
        Args:
            user_id: 用户ID
            resource_type: 资源类型
            resource_id: 资源ID
            action: 操作
            context: 上下文信息
        
        Returns:
            是否允许访问
        """
        with self._lock:
            if user_id not in self._users:
                return False
            
            user = self._users[user_id]
            
            # 查找适用的策略
            applicable_policies = [
                policy for policy in self._policies.values()
                if policy.resource_type == resource_type and policy.is_active
            ]
            
            # 检查策略
            for policy in applicable_policies:
                if not policy.check_access(user, resource_id, context):
                    # 记录拒绝访问
                    access_log = AccessLog(
                        log_id=f"access_{int(time.time())}",
                        user_id=user_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        action=action,
                        granted=False,
                        timestamp=time.time(),
                        ip_address=context.get('client_ip') if context else None,
                        user_agent=context.get('user_agent') if context else None
                    )
                    
                    self._access_logs.append(access_log)
                    self._save_data()
                    self._update_stats()
                    
                    logger.warning(f"访问被拒绝: {user_id} -> {resource_id}")
                    return False
            
            # 记录允许访问
            access_log = AccessLog(
                log_id=f"access_{int(time.time())}",
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                granted=True,
                timestamp=time.time(),
                ip_address=context.get('client_ip') if context else None,
                user_agent=context.get('user_agent') if context else None
            )
            
            self._access_logs.append(access_log)
            self._save_data()
            self._update_stats()
            
            logger.info(f"访问已允许: {user_id} -> {resource_id}")
            return True
    
    def create_policy(self, name: str, description: str,
                   resource_type: ResourceType,
                   required_permissions: Set[Permission],
                   conditions: Optional[Dict[str, Any]] = None) -> PermissionPolicy:
        """创建权限策略
        
        Args:
            name: 策略名称
            description: 策略描述
            resource_type: 资源类型
            required_permissions: 需要的权限
            conditions: 访问条件
        
        Returns:
            权限策略对象
        """
        policy_id = f"policy_{int(time.time())}"
        
        policy = PermissionPolicy(
            policy_id=policy_id,
            name=name,
            description=description,
            resource_type=resource_type,
            required_permissions=required_permissions,
            conditions=conditions or {},
            created_at=time.time()
        )
        
        with self._lock:
            self._policies[policy_id] = policy
            self._save_data()
            self._update_stats()
        
        logger.info(f"权限策略创建成功: {name}")
        return policy
    
    def get_user(self, user_id: str) -> Optional[User]:
        """获取用户信息"""
        with self._lock:
            return self._users.get(user_id)
    
    def get_all_users(self, active_only: bool = False) -> List[User]:
        """获取所有用户"""
        with self._lock:
            users = list(self._users.values())
            
            if active_only:
                users = [u for u in users if u.is_active]
            
            return users
    
    def get_access_logs(self, user_id: Optional[str] = None,
                   resource_type: Optional[ResourceType] = None,
                   limit: int = 100) -> List[AccessLog]:
        """获取访问日志"""
        with self._lock:
            logs = self._access_logs.copy()
            
            if user_id:
                logs = [log for log in logs if log.user_id == user_id]
            if resource_type:
                logs = [log for log in logs if log.resource_type == resource_type]
            
            return logs[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return self._stats.copy()
    
    def cleanup_old_logs(self, older_than_days: int = 30):
        """清理旧日志"""
        cutoff_time = time.time() - (older_than_days * 24 * 3600)
        
        with self._lock:
            original_count = len(self._access_logs)
            
            # 创建新列表，只保留新日志
            self._access_logs = [
                log for log in self._access_logs
                if log.timestamp >= cutoff_time
            ]
            
            removed_count = original_count - len(self._access_logs)
            self._save_data()
            self._update_stats()
        
        logger.info(f"清理旧访问日志: {removed_count} 条")


# 全局实例
_global_permission_manager: Optional[PermissionManager] = None


def get_permission_manager(users_file: str = "users.json",
                       policies_file: str = "policies.json",
                       access_log_file: str = "access_logs.json") -> PermissionManager:
    """获取全局权限管理器"""
    global _global_permission_manager
    
    if _global_permission_manager is None:
        _global_permission_manager = PermissionManager(
            users_file=users_file,
            policies_file=policies_file,
            access_log_file=access_log_file
        )
    
    return _global_permission_manager