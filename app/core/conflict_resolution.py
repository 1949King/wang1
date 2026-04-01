import asyncio
import json
import time
import uuid
import difflib
from typing import Dict, List, Optional, Set, Any, Tuple, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
import redis
import hashlib
import re
from pathlib import Path

from app.core.version_control import MergeConflict, FileChange
from app.core.realtime_collaboration import TextEdit, OperationalTransform


class ConflictType(Enum):
    """冲突类型"""
    TEXT_EDIT = "text_edit"
    FILE_CONFLICT = "file_conflict"
    BRANCH_MERGE = "branch_merge"
    RESOURCE_LOCK = "resource_lock"
    DEPENDENCY_CONFLICT = "dependency_conflict"
    CONCURRENT_MODIFICATION = "concurrent_modification"


class ResolutionStrategy(Enum):
    """解决策略"""
    KEEP_OURS = "keep_ours"
    KEEP_THEIRS = "keep_theirs"
    MERGE = "merge"
    CUSTOM = "custom"
    AUTO = "auto"
    ABORT = "abort"


class ConflictStatus(Enum):
    """冲突状态"""
    DETECTED = "detected"
    RESOLVING = "resolving"
    RESOLVED = "resolved"
    UNRESOLVABLE = "unresolvable"
    IGNORED = "ignored"


@dataclass
class Conflict:
    """冲突信息"""
    conflict_id: str
    conflict_type: ConflictType
    resource_id: str  # file path, branch name, etc.
    description: str
    status: ConflictStatus
    created_at: float
    updated_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    resolution: Optional[Dict[str, Any]] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[float] = None


@dataclass
class TextConflict:
    """文本冲突"""
    file_path: str
    start_line: int
    end_line: int
    our_content: str
    their_content: str
    base_content: Optional[str] = None
    conflict_markers: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class FileConflict:
    """文件冲突"""
    file_path: str
    conflict_type: str  # add/add, delete/modify, modify/modify
    our_version: Optional[str] = None
    their_version: Optional[str] = None
    base_version: Optional[str] = None


@dataclass
class BranchConflict:
    """分支冲突"""
    branch_name: str
    merge_base: Optional[str] = None
    our_commit: Optional[str] = None
    their_commit: Optional[str] = None
    file_conflicts: List[FileConflict] = field(default_factory=list)


@dataclass
class Resolution:
    """冲突解决方案"""
    resolution_id: str
    conflict_id: str
    strategy: ResolutionStrategy
    resolved_content: Optional[str] = None
    resolved_files: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class ConflictDetector:
    """冲突检测器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def detect_text_conflict(self, base_content: str, 
                           our_content: str, 
                           their_content: str) -> List[TextConflict]:
        """检测文本冲突"""
        conflicts = []
        
        base_lines = base_content.splitlines(True)
        our_lines = our_content.splitlines(True)
        their_lines = their_content.splitlines(True)
        
        s = difflib.SequenceMatcher(None, base_lines, our_lines)
        our_changes = list(s.get_opcodes())
        
        t = difflib.SequenceMatcher(None, base_lines, their_lines)
        their_changes = list(t.get_opcodes())
        
        for our_op in our_changes:
            if our_op[0] == 'replace' or our_op[0] == 'delete' or our_op[0] == 'insert':
                our_start, our_end = our_op[1], our_op[2]
                
                for their_op in their_changes:
                    if their_op[0] == 'replace' or their_op[0] == 'delete' or their_op[0] == 'insert':
                        their_start, their_end = their_op[1], their_op[2]
                        
                        if not (our_end <= their_start or our_start >= their_end):
                            conflict = TextConflict(
                                file_path="",
                                start_line=min(our_start, their_start),
                                end_line=max(our_end, their_end),
                                our_content=''.join(our_lines[our_start:our_end]),
                                their_content=''.join(their_lines[their_start:their_end]),
                                base_content=''.join(base_lines[max(0, min(our_start, their_start)-1):min(len(base_lines), max(our_end, their_end)+1)]),
                                conflict_markers=[(our_start, our_end), (their_start, their_end)]
                            )
                            conflicts.append(conflict)
        
        return conflicts
    
    def detect_file_conflict(self, our_files: Dict[str, str], 
                           their_files: Dict[str, str],
                           base_files: Dict[str, str]) -> List[FileConflict]:
        """检测文件冲突"""
        conflicts = []
        
        all_files = set(our_files.keys()) | set(their_files.keys()) | set(base_files.keys())
        
        for file_path in all_files:
            our_hash = our_files.get(file_path)
            their_hash = their_files.get(file_path)
            base_hash = base_files.get(file_path)
            
            if file_path not in base_files:
                if file_path in our_files and file_path in their_files:
                    if our_hash != their_hash:
                        conflicts.append(FileConflict(
                            file_path=file_path,
                            conflict_type="add/add",
                            our_version=our_hash,
                            their_version=their_hash
                        ))
            else:
                if file_path not in our_files:
                    if file_path in their_files:
                        conflicts.append(FileConflict(
                            file_path=file_path,
                            conflict_type="delete/modify",
                            our_version=None,
                            their_version=their_hash,
                            base_version=base_hash
                        ))
                elif file_path not in their_files:
                    conflicts.append(FileConflict(
                        file_path=file_path,
                        conflict_type="modify/delete",
                        our_version=our_hash,
                        their_version=None,
                        base_version=base_hash
                    ))
                else:
                    if our_hash != their_hash and our_hash != base_hash and their_hash != base_hash:
                        conflicts.append(FileConflict(
                            file_path=file_path,
                            conflict_type="modify/modify",
                            our_version=our_hash,
                            their_version=their_hash,
                            base_version=base_hash
                        ))
        
        return conflicts
    
    def detect_branch_conflict(self, our_commit: str, 
                              their_commit: str, 
                              merge_base: Optional[str]) -> BranchConflict:
        """检测分支冲突"""
        return BranchConflict(
            branch_name="",
            merge_base=merge_base,
            our_commit=our_commit,
            their_commit=their_commit
        )


class ConflictResolver:
    """冲突解决器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def resolve_text_conflict(self, conflict: TextConflict, 
                             strategy: ResolutionStrategy, 
                             custom_content: Optional[str] = None) -> str:
        """解决文本冲突"""
        if strategy == ResolutionStrategy.KEEP_OURS:
            return conflict.our_content
        elif strategy == ResolutionStrategy.KEEP_THEIRS:
            return conflict.their_content
        elif strategy == ResolutionStrategy.MERGE:
            return self._merge_text(conflict)
        elif strategy == ResolutionStrategy.CUSTOM and custom_content:
            return custom_content
        else:
            return conflict.our_content
    
    def _merge_text(self, conflict: TextConflict) -> str:
        """合并文本冲突"""
        merged_lines = []
        
        if conflict.base_content:
            merged_lines.append("<<<<<<< BASE")
            merged_lines.append(conflict.base_content)
            merged_lines.append("=======")
        
        merged_lines.append("<<<<<<< OURS")
        merged_lines.append(conflict.our_content)
        merged_lines.append("=======")
        merged_lines.append(">>>>>>> THEIRS")
        merged_lines.append(conflict.their_content)
        merged_lines.append(">>>>>>>")
        
        return ''.join(merged_lines)
    
    def resolve_file_conflict(self, conflict: FileConflict, 
                             strategy: ResolutionStrategy, 
                             our_content: Optional[str] = None,
                             their_content: Optional[str] = None) -> Optional[str]:
        """解决文件冲突"""
        if strategy == ResolutionStrategy.KEEP_OURS:
            return our_content
        elif strategy == ResolutionStrategy.KEEP_THEIRS:
            return their_content
        elif strategy == ResolutionStrategy.MERGE:
            if conflict.conflict_type == "add/add" and our_content and their_content:
                return self._merge_files(our_content, their_content)
            return our_content
        else:
            return None
    
    def _merge_files(self, our_content: str, their_content: str) -> str:
        """合并文件"""
        our_lines = set(our_content.splitlines())
        their_lines = set(their_content.splitlines())
        
        merged_lines = sorted(our_lines | their_lines)
        return '\n'.join(merged_lines)
    
    def resolve_branch_conflict(self, conflict: BranchConflict, 
                               strategy: ResolutionStrategy, 
                               resolved_files: Optional[Dict[str, str]] = None) -> List[str]:
        """解决分支冲突"""
        resolved = []
        
        for file_conflict in conflict.file_conflicts:
            if strategy == ResolutionStrategy.KEEP_OURS:
                resolved.append(file_conflict.file_path)
            elif strategy == ResolutionStrategy.KEEP_THEIRS:
                resolved.append(file_conflict.file_path)
        
        return resolved


class ConflictManager:
    """冲突管理器"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.conflicts: Dict[str, Conflict] = {}
        self.resolutions: Dict[str, Resolution] = {}
        self.conflict_queue: deque = deque()
        self.logger = logging.getLogger(__name__)
    
    def create_conflict(self, conflict_type: ConflictType, 
                       resource_id: str, 
                       description: str, 
                       metadata: Optional[Dict[str, Any]] = None) -> Conflict:
        """创建冲突"""
        conflict = Conflict(
            conflict_id=str(uuid.uuid4()),
            conflict_type=conflict_type,
            resource_id=resource_id,
            description=description,
            status=ConflictStatus.DETECTED,
            created_at=time.time(),
            updated_at=time.time(),
            metadata=metadata or {}
        )
        
        self.conflicts[conflict.conflict_id] = conflict
        self.conflict_queue.append(conflict.conflict_id)
        
        if self.redis_client:
            self._cache_conflict(conflict)
        
        self.logger.info(f"Created conflict: {conflict.conflict_id}")
        return conflict
    
    def resolve_conflict(self, conflict_id: str, 
                        strategy: ResolutionStrategy, 
                        resolved_by: str, 
                        resolved_content: Optional[str] = None,
                        resolved_files: Optional[List[str]] = None,
                        metadata: Optional[Dict[str, Any]] = None) -> Resolution:
        """解决冲突"""
        conflict = self.conflicts.get(conflict_id)
        if not conflict:
            raise ValueError(f"Conflict {conflict_id} not found")
        
        resolution = Resolution(
            resolution_id=str(uuid.uuid4()),
            conflict_id=conflict_id,
            strategy=strategy,
            resolved_content=resolved_content,
            resolved_files=resolved_files or [],
            metadata=metadata or {}
        )
        
        conflict.status = ConflictStatus.RESOLVED
        conflict.resolution = asdict(resolution)
        conflict.resolved_by = resolved_by
        conflict.resolved_at = time.time()
        conflict.updated_at = time.time()
        
        self.resolutions[resolution.resolution_id] = resolution
        
        if self.redis_client:
            self._cache_resolution(resolution)
            self._update_cached_conflict(conflict)
        
        self.logger.info(f"Resolved conflict: {conflict_id} with strategy {strategy.value}")
        return resolution
    
    def get_conflict(self, conflict_id: str) -> Optional[Conflict]:
        """获取冲突"""
        if conflict_id in self.conflicts:
            return self.conflicts[conflict_id]
        
        if self.redis_client:
            return self._get_cached_conflict(conflict_id)
        
        return None
    
    def get_all_conflicts(self, status: Optional[ConflictStatus] = None) -> List[Conflict]:
        """获取所有冲突"""
        if status:
            return [c for c in self.conflicts.values() if c.status == status]
        return list(self.conflicts.values())
    
    def get_pending_conflicts(self) -> List[Conflict]:
        """获取待解决的冲突"""
        return [c for c in self.conflicts.values() 
                if c.status in [ConflictStatus.DETECTED, ConflictStatus.RESOLVING]]
    
    def update_conflict_status(self, conflict_id: str, status: ConflictStatus) -> bool:
        """更新冲突状态"""
        conflict = self.conflicts.get(conflict_id)
        if not conflict:
            return False
        
        conflict.status = status
        conflict.updated_at = time.time()
        
        if self.redis_client:
            self._update_cached_conflict(conflict)
        
        return True
    
    def delete_conflict(self, conflict_id: str) -> bool:
        """删除冲突"""
        if conflict_id in self.conflicts:
            del self.conflicts[conflict_id]
            
            if self.redis_client:
                self._remove_cached_conflict(conflict_id)
            
            return True
        return False
    
    def get_conflict_stats(self) -> Dict[str, Any]:
        """获取冲突统计"""
        stats = defaultdict(int)
        for conflict in self.conflicts.values():
            stats[conflict.status.value] += 1
        
        return dict(stats)
    
    def _cache_conflict(self, conflict: Conflict):
        """缓存冲突到Redis"""
        key = f"conflict:{conflict.conflict_id}"
        data = json.dumps(asdict(conflict))
        self.redis_client.setex(key, 3600, data)
    
    def _get_cached_conflict(self, conflict_id: str) -> Optional[Conflict]:
        """从Redis获取缓存冲突"""
        key = f"conflict:{conflict_id}"
        data = self.redis_client.get(key)
        if data:
            conflict_data = json.loads(data)
            conflict_data['conflict_type'] = ConflictType(conflict_data['conflict_type'])
            conflict_data['status'] = ConflictStatus(conflict_data['status'])
            return Conflict(**conflict_data)
        return None
    
    def _update_cached_conflict(self, conflict: Conflict):
        """更新Redis中的冲突缓存"""
        key = f"conflict:{conflict.conflict_id}"
        data = json.dumps(asdict(conflict))
        self.redis_client.setex(key, 3600, data)
    
    def _remove_cached_conflict(self, conflict_id: str):
        """从Redis移除冲突缓存"""
        key = f"conflict:{conflict_id}"
        self.redis_client.delete(key)
    
    def _cache_resolution(self, resolution: Resolution):
        """缓存解决方案到Redis"""
        key = f"resolution:{resolution.resolution_id}"
        data = json.dumps(asdict(resolution))
        self.redis_client.setex(key, 3600, data)


class OperationalConflictResolver:
    """操作冲突解决器"""
    
    def __init__(self):
        self.ot = OperationalTransform()
        self.logger = logging.getLogger(__name__)
    
    def resolve_concurrent_edits(self, edits: List[TextEdit]) -> List[TextEdit]:
        """解决并发编辑冲突"""
        sorted_edits = sorted(edits, key=lambda x: x.timestamp)
        resolved_edits = []
        
        for i, edit in enumerate(sorted_edits):
            for j, existing_edit in enumerate(resolved_edits):
                edit, existing_edit = self.ot.transform(edit, existing_edit)
                resolved_edits[j] = existing_edit
            resolved_edits.append(edit)
        
        return resolved_edits
    
    def apply_resolved_edits(self, content: str, edits: List[TextEdit]) -> str:
        """应用已解决的编辑"""
        for edit in edits:
            if edit.operation == "insert":
                content = content[:edit.position] + edit.content + content[edit.position:]
            elif edit.operation == "delete":
                content = content[:edit.position] + content[edit.position + edit.length:]
            elif edit.operation == "replace":
                content = content[:edit.position] + edit.content + content[edit.position + edit.length:]
        
        return content
    
    def detect_operation_conflicts(self, edit1: TextEdit, edit2: TextEdit) -> bool:
        """检测操作冲突"""
        return not (
            edit1.position + edit1.length <= edit2.position or
            edit2.position + edit2.length <= edit1.position
        )


class ConflictResolutionEngine:
    """冲突解决引擎"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.conflict_manager = ConflictManager(redis_client)
        self.conflict_detector = ConflictDetector()
        self.conflict_resolver = ConflictResolver()
        self.operational_resolver = OperationalConflictResolver()
        self.logger = logging.getLogger(__name__)
    
    async def detect_and_resolve_conflicts(self, 
                                         resource_id: str, 
                                         our_content: str, 
                                         their_content: str, 
                                         base_content: str, 
                                         user_id: str) -> Dict[str, Any]:
        """检测并解决冲突"""
        text_conflicts = self.conflict_detector.detect_text_conflict(
            base_content, our_content, their_content
        )
        
        if not text_conflicts:
            return {
                "has_conflicts": False,
                "resolved_content": our_content,
                "conflicts": []
            }
        
        resolved_content = our_content
        resolved_conflicts = []
        
        for conflict in text_conflicts:
            conflict_obj = self.conflict_manager.create_conflict(
                ConflictType.TEXT_EDIT,
                resource_id,
                f"Text conflict in {resource_id}",
                {
                    "file_path": resource_id,
                    "conflict_details": asdict(conflict)
                }
            )
            
            resolution = self.conflict_resolver.resolve_text_conflict(
                conflict, ResolutionStrategy.MERGE
            )
            
            self.conflict_manager.resolve_conflict(
                conflict_obj.conflict_id,
                ResolutionStrategy.MERGE,
                user_id,
                resolved_content=resolution
            )
            
            resolved_conflicts.append({
                "conflict_id": conflict_obj.conflict_id,
                "resolved_content": resolution
            })
        
        return {
            "has_conflicts": True,
            "resolved_content": resolved_content,
            "conflicts": resolved_conflicts
        }
    
    async def resolve_merge_conflicts(self, 
                                    branch_name: str, 
                                    our_commit: str, 
                                    their_commit: str, 
                                    merge_base: Optional[str],
                                    file_conflicts: List[FileConflict],
                                    user_id: str) -> Dict[str, Any]:
        """解决合并冲突"""
        branch_conflict = self.conflict_detector.detect_branch_conflict(
            our_commit, their_commit, merge_base
        )
        branch_conflict.branch_name = branch_name
        branch_conflict.file_conflicts = file_conflicts
        
        conflict_obj = self.conflict_manager.create_conflict(
            ConflictType.BRANCH_MERGE,
            branch_name,
            f"Merge conflict in branch {branch_name}",
            {
                "branch_conflict": asdict(branch_conflict)
            }
        )
        
        resolved_files = self.conflict_resolver.resolve_branch_conflict(
            branch_conflict, ResolutionStrategy.KEEP_OURS
        )
        
        self.conflict_manager.resolve_conflict(
            conflict_obj.conflict_id,
            ResolutionStrategy.KEEP_OURS,
            user_id,
            resolved_files=resolved_files
        )
        
        return {
            "conflict_id": conflict_obj.conflict_id,
            "resolved_files": resolved_files,
            "strategy": ResolutionStrategy.KEEP_OURS.value
        }
    
    async def resolve_resource_conflicts(self, 
                                       resource_id: str, 
                                       user_id: str,
                                       conflict_type: ConflictType,
                                       metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """解决资源冲突"""
        conflict_obj = self.conflict_manager.create_conflict(
            conflict_type,
            resource_id,
            f"Resource conflict in {resource_id}",
            metadata
        )
        
        self.conflict_manager.resolve_conflict(
            conflict_obj.conflict_id,
            ResolutionStrategy.KEEP_OURS,
            user_id
        )
        
        return {
            "conflict_id": conflict_obj.conflict_id,
            "resolved": True
        }
    
    async def resolve_operational_conflicts(self, 
                                          resource_id: str,
                                          edits: List[TextEdit],
                                          user_id: str) -> Dict[str, Any]:
        """解决操作冲突"""
        resolved_edits = self.operational_resolver.resolve_concurrent_edits(edits)
        
        conflict_obj = self.conflict_manager.create_conflict(
            ConflictType.CONCURRENT_MODIFICATION,
            resource_id,
            f"Concurrent modification in {resource_id}",
            {
                "edit_count": len(edits),
                "resolved_count": len(resolved_edits)
            }
        )
        
        self.conflict_manager.resolve_conflict(
            conflict_obj.conflict_id,
            ResolutionStrategy.AUTO,
            user_id,
            metadata={
                "resolved_edits": [asdict(edit) for edit in resolved_edits]
            }
        )
        
        return {
            "conflict_id": conflict_obj.conflict_id,
            "resolved_edits": [asdict(edit) for edit in resolved_edits]
        }
    
    def get_conflict_history(self, resource_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取冲突历史"""
        conflicts = self.conflict_manager.get_all_conflicts()
        
        if resource_id:
            conflicts = [c for c in conflicts if c.resource_id == resource_id]
        
        history = []
        for conflict in conflicts:
            history.append({
                "conflict_id": conflict.conflict_id,
                "conflict_type": conflict.conflict_type.value,
                "resource_id": conflict.resource_id,
                "status": conflict.status.value,
                "created_at": conflict.created_at,
                "resolved_at": conflict.resolved_at,
                "resolved_by": conflict.resolved_by,
                "resolution": conflict.resolution
            })
        
        return sorted(history, key=lambda x: x["created_at"], reverse=True)
    
    def get_conflict_stats(self) -> Dict[str, Any]:
        """获取冲突统计"""
        status_stats = self.conflict_manager.get_conflict_stats()
        
        conflict_type_stats = defaultdict(int)
        for conflict in self.conflict_manager.get_all_conflicts():
            conflict_type_stats[conflict.conflict_type.value] += 1
        
        return {
            "status_stats": status_stats,
            "type_stats": dict(conflict_type_stats),
            "total_conflicts": len(self.conflict_manager.get_all_conflicts()),
            "pending_conflicts": len(self.conflict_manager.get_pending_conflicts())
        }


_global_conflict_engine: Optional[ConflictResolutionEngine] = None


def get_conflict_engine(redis_client: Optional[redis.Redis] = None) -> ConflictResolutionEngine:
    """获取冲突解决引擎实例"""
    global _global_conflict_engine
    
    if _global_conflict_engine is None:
        _global_conflict_engine = ConflictResolutionEngine(redis_client)
    
    return _global_conflict_engine


def create_conflict_engine(redis_client: Optional[redis.Redis] = None) -> ConflictResolutionEngine:
    """创建冲突解决引擎"""
    return ConflictResolutionEngine(redis_client)
