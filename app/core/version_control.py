import asyncio
import json
import time
import uuid
import hashlib
import difflib
import shutil
import os
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import redis
import sqlite3
from pathlib import Path
import pickle
import zlib
import base64

from app.core.service_decomposition import ServiceType


class VersionControlStatus(Enum):
    """版本控制状态"""
    UNTRACKED = "untracked"
    MODIFIED = "modified"
    STAGED = "staged"
    COMMITTED = "committed"
    CONFLICTED = "conflicted"


class ObjectType(Enum):
    """对象类型"""
    BLOB = "blob"
    TREE = "tree"
    COMMIT = "commit"
    TAG = "tag"


@dataclass
class Version:
    """版本信息"""
    version_id: str
    parent_id: Optional[str]
    branch_name: str
    author: str
    message: str
    timestamp: float
    tree_hash: str
    file_changes: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileChange:
    """文件变更"""
    file_path: str
    change_type: str  # added, modified, deleted, renamed
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None
    old_path: Optional[str] = None


@dataclass
class Branch:
    """分支信息"""
    branch_name: str
    head_commit_id: str
    created_at: float
    is_protected: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Tag:
    """标签信息"""
    tag_name: str
    commit_id: str
    created_at: float
    author: str
    message: str = ""


@dataclass
class MergeConflict:
    """合并冲突"""
    file_path: str
    base_content: str
    our_content: str
    their_content: str
    conflict_markers: List[Tuple[int, int]]


class HashGenerator:
    """哈希生成器"""
    
    @staticmethod
    def generate_blob_hash(content: bytes) -> str:
        """生成blob对象哈希"""
        header = f"blob {len(content)}\0".encode()
        data = header + content
        return hashlib.sha1(data).hexdigest()
    
    @staticmethod
    def generate_tree_hash(entries: List[Dict[str, Any]]) -> str:
        """生成tree对象哈希"""
        tree_content = ""
        for entry in sorted(entries, key=lambda x: (x["mode"], x["name"])):
            tree_content += f"{entry['mode']} {entry['name']}\0{entry['hash']}"
        
        header = f"tree {len(tree_content)}\0".encode()
        data = header + tree_content.encode()
        return hashlib.sha1(data).hexdigest()
    
    @staticmethod
    def generate_commit_hash(version: Version) -> str:
        """生成commit对象哈希"""
        commit_content = json.dumps({
            "tree": version.tree_hash,
            "parent": version.parent_id,
            "author": version.author,
            "message": version.message,
            "timestamp": version.timestamp,
            "file_changes": version.file_changes,
            "metadata": version.metadata
        }, sort_keys=True)
        
        header = f"commit {len(commit_content)}\0".encode()
        data = header + commit_content.encode()
        return hashlib.sha1(data).hexdigest()


class ObjectStorage:
    """对象存储"""
    
    def __init__(self, storage_path: str, redis_client: Optional[redis.Redis] = None):
        self.storage_path = Path(storage_path)
        self.redis_client = redis_client
        self.logger = logging.getLogger(__name__)
        
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.objects_dir = self.storage_path / "objects"
        self.objects_dir.mkdir(exist_ok=True)
        
        self.refs_dir = self.storage_path / "refs"
        self.refs_dir.mkdir(exist_ok=True)
        
        self.heads_dir = self.refs_dir / "heads"
        self.heads_dir.mkdir(exist_ok=True)
        
        self.tags_dir = self.refs_dir / "tags"
        self.tags_dir.mkdir(exist_ok=True)
    
    def store_object(self, obj_hash: str, obj_type: ObjectType, data: bytes) -> bool:
        """存储对象"""
        try:
            obj_dir = self.objects_dir / obj_hash[:2]
            obj_dir.mkdir(exist_ok=True)
            
            obj_file = obj_dir / obj_hash[2:]
            
            compressed_data = zlib.compress(data)
            obj_file.write_bytes(compressed_data)
            
            if self.redis_client:
                self._cache_object(obj_hash, obj_type, data)
            
            return True
        except Exception as e:
            self.logger.error(f"Error storing object {obj_hash}: {e}")
            return False
    
    def retrieve_object(self, obj_hash: str) -> Optional[bytes]:
        """检索对象"""
        try:
            obj_file = self.objects_dir / obj_hash[:2] / obj_hash[2:]
            
            if obj_file.exists():
                compressed_data = obj_file.read_bytes()
                return zlib.decompress(compressed_data)
            
            if self.redis_client:
                return self._get_cached_object(obj_hash)
            
            return None
        except Exception as e:
            self.logger.error(f"Error retrieving object {obj_hash}: {e}")
            return None
    
    def _cache_object(self, obj_hash: str, obj_type: ObjectType, data: bytes):
        """缓存对象到Redis"""
        key = f"object:{obj_type.value}:{obj_hash}"
        encoded_data = base64.b64encode(data).decode()
        self.redis_client.setex(key, 3600, encoded_data)
    
    def _get_cached_object(self, obj_hash: str) -> Optional[bytes]:
        """从Redis获取缓存对象"""
        for obj_type in ObjectType:
            key = f"object:{obj_type.value}:{obj_hash}"
            data = self.redis_client.get(key)
            if data:
                return base64.b64decode(data)
        return None
    
    def delete_object(self, obj_hash: str) -> bool:
        """删除对象"""
        try:
            obj_file = self.objects_dir / obj_hash[:2] / obj_hash[2:]
            
            if obj_file.exists():
                obj_file.unlink()
            
            if self.redis_client:
                for obj_type in ObjectType:
                    key = f"object:{obj_type.value}:{obj_hash}"
                    self.redis_client.delete(key)
            
            return True
        except Exception as e:
            self.logger.error(f"Error deleting object {obj_hash}: {e}")
            return False
    
    def object_exists(self, obj_hash: str) -> bool:
        """检查对象是否存在"""
        obj_file = self.objects_dir / obj_hash[:2] / obj_hash[2:]
        return obj_file.exists()
    
    def get_object_stats(self) -> Dict[str, Any]:
        """获取对象存储统计"""
        total_objects = 0
        total_size = 0
        
        for obj_dir in self.objects_dir.iterdir():
            if obj_dir.is_dir():
                for obj_file in obj_dir.iterdir():
                    if obj_file.is_file():
                        total_objects += 1
                        total_size += obj_file.stat().st_size
        
        return {
            "total_objects": total_objects,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }


class IndexManager:
    """索引管理器"""
    
    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path)
        self.index_file = self.storage_path / "index"
        self.logger = logging.getLogger(__name__)
        
        self.staged_files: Dict[str, str] = {}
        self.modified_files: Set[str] = set()
        self.untracked_files: Set[str] = set()
        
        self._load_index()
    
    def _load_index(self):
        """加载索引"""
        if self.index_file.exists():
            try:
                data = json.loads(self.index_file.read_text())
                self.staged_files = data.get("staged_files", {})
                self.modified_files = set(data.get("modified_files", []))
                self.untracked_files = set(data.get("untracked_files", []))
            except Exception as e:
                self.logger.error(f"Error loading index: {e}")
    
    def _save_index(self):
        """保存索引"""
        try:
            data = {
                "staged_files": self.staged_files,
                "modified_files": list(self.modified_files),
                "untracked_files": list(self.untracked_files)
            }
            self.index_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            self.logger.error(f"Error saving index: {e}")
    
    def stage_file(self, file_path: str, content_hash: str):
        """暂存文件"""
        self.staged_files[file_path] = content_hash
        self.modified_files.discard(file_path)
        self.untracked_files.discard(file_path)
        self._save_index()
    
    def unstage_file(self, file_path: str):
        """取消暂存文件"""
        if file_path in self.staged_files:
            del self.staged_files[file_path]
        self._save_index()
    
    def update_file_status(self, file_path: str, status: VersionControlStatus):
        """更新文件状态"""
        if status == VersionControlStatus.MODIFIED:
            self.modified_files.add(file_path)
        elif status == VersionControlStatus.UNTRACKED:
            self.untracked_files.add(file_path)
        self._save_index()
    
    def get_staged_files(self) -> Dict[str, str]:
        """获取暂存文件"""
        return self.staged_files.copy()
    
    def get_modified_files(self) -> Set[str]:
        """获取修改文件"""
        return self.modified_files.copy()
    
    def get_untracked_files(self) -> Set[str]:
        """获取未跟踪文件"""
        return self.untracked_files.copy()
    
    def clear_staging_area(self):
        """清空暂存区"""
        self.staged_files.clear()
        self._save_index()


class BranchManager:
    """分支管理器"""
    
    def __init__(self, storage_path: str, redis_client: Optional[redis.Redis] = None):
        self.storage_path = Path(storage_path)
        self.redis_client = redis_client
        self.heads_dir = self.storage_path / "refs" / "heads"
        self.heads_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        
        self.head_file = self.storage_path / "HEAD"
        self.current_branch = self._load_current_branch()
    
    def _load_current_branch(self) -> str:
        """加载当前分支"""
        if self.head_file.exists():
            content = self.head_file.read_text().strip()
            if content.startswith("ref: refs/heads/"):
                return content.replace("ref: refs/heads/", "")
        return "main"
    
    def _save_current_branch(self):
        """保存当前分支"""
        self.head_file.write_text(f"ref: refs/heads/{self.current_branch}")
    
    def create_branch(self, branch_name: str, commit_id: str, 
                     is_protected: bool = False) -> bool:
        """创建分支"""
        try:
            branch_file = self.heads_dir / branch_name
            branch_file.write_text(commit_id)
            
            if self.redis_client:
                self._cache_branch(branch_name, commit_id, is_protected)
            
            self.logger.info(f"Created branch: {branch_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error creating branch {branch_name}: {e}")
            return False
    
    def delete_branch(self, branch_name: str) -> bool:
        """删除分支"""
        if branch_name == self.current_branch:
            self.logger.error("Cannot delete current branch")
            return False
        
        try:
            branch_file = self.heads_dir / branch_name
            if branch_file.exists():
                branch_file.unlink()
                
                if self.redis_client:
                    self._remove_cached_branch(branch_name)
                
                self.logger.info(f"Deleted branch: {branch_name}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error deleting branch {branch_name}: {e}")
            return False
    
    def switch_branch(self, branch_name: str) -> bool:
        """切换分支"""
        branch_file = self.heads_dir / branch_name
        if not branch_file.exists():
            self.logger.error(f"Branch {branch_name} does not exist")
            return False
        
        self.current_branch = branch_name
        self._save_current_branch()
        self.logger.info(f"Switched to branch: {branch_name}")
        return True
    
    def get_branch_head(self, branch_name: str) -> Optional[str]:
        """获取分支头提交"""
        branch_file = self.heads_dir / branch_name
        if branch_file.exists():
            return branch_file.read_text().strip()
        return None
    
    def update_branch_head(self, branch_name: str, commit_id: str) -> bool:
        """更新分支头提交"""
        try:
            branch_file = self.heads_dir / branch_name
            branch_file.write_text(commit_id)
            
            if self.redis_client:
                self._update_cached_branch(branch_name, commit_id)
            
            return True
        except Exception as e:
            self.logger.error(f"Error updating branch head {branch_name}: {e}")
            return False
    
    def list_branches(self) -> List[Branch]:
        """列出所有分支"""
        branches = []
        for branch_file in self.heads_dir.iterdir():
            if branch_file.is_file():
                branch_name = branch_file.name
                commit_id = branch_file.read_text().strip()
                is_protected = branch_name in ["main", "master", "develop"]
                
                branches.append(Branch(
                    branch_name=branch_name,
                    head_commit_id=commit_id,
                    created_at=branch_file.stat().st_ctime,
                    is_protected=is_protected
                ))
        
        return sorted(branches, key=lambda x: x.created_at)
    
    def get_current_branch(self) -> str:
        """获取当前分支"""
        return self.current_branch
    
    def _cache_branch(self, branch_name: str, commit_id: str, is_protected: bool):
        """缓存分支到Redis"""
        key = f"branch:{branch_name}"
        data = json.dumps({
            "commit_id": commit_id,
            "is_protected": is_protected,
            "cached_at": time.time()
        })
        self.redis_client.setex(key, 3600, data)
    
    def _update_cached_branch(self, branch_name: str, commit_id: str):
        """更新Redis中的分支缓存"""
        key = f"branch:{branch_name}"
        data = self.redis_client.get(key)
        if data:
            branch_data = json.loads(data)
            branch_data["commit_id"] = commit_id
            branch_data["cached_at"] = time.time()
            self.redis_client.setex(key, 3600, json.dumps(branch_data))
    
    def _remove_cached_branch(self, branch_name: str):
        """从Redis移除分支缓存"""
        key = f"branch:{branch_name}"
        self.redis_client.delete(key)


class TagManager:
    """标签管理器"""
    
    def __init__(self, storage_path: str, redis_client: Optional[redis.Redis] = None):
        self.storage_path = Path(storage_path)
        self.redis_client = redis_client
        self.tags_dir = self.storage_path / "refs" / "tags"
        self.tags_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
    
    def create_tag(self, tag_name: str, commit_id: str, 
                  author: str, message: str = "") -> bool:
        """创建标签"""
        try:
            tag_data = {
                "commit_id": commit_id,
                "author": author,
                "message": message,
                "created_at": time.time()
            }
            
            tag_file = self.tags_dir / tag_name
            tag_file.write_text(json.dumps(tag_data, indent=2))
            
            if self.redis_client:
                self._cache_tag(tag_name, tag_data)
            
            self.logger.info(f"Created tag: {tag_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error creating tag {tag_name}: {e}")
            return False
    
    def delete_tag(self, tag_name: str) -> bool:
        """删除标签"""
        try:
            tag_file = self.tags_dir / tag_name
            if tag_file.exists():
                tag_file.unlink()
                
                if self.redis_client:
                    self._remove_cached_tag(tag_name)
                
                self.logger.info(f"Deleted tag: {tag_name}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error deleting tag {tag_name}: {e}")
            return False
    
    def get_tag(self, tag_name: str) -> Optional[Tag]:
        """获取标签"""
        tag_file = self.tags_dir / tag_name
        if tag_file.exists():
            tag_data = json.loads(tag_file.read_text())
            return Tag(
                tag_name=tag_name,
                commit_id=tag_data["commit_id"],
                created_at=tag_data["created_at"],
                author=tag_data["author"],
                message=tag_data.get("message", "")
            )
        return None
    
    def list_tags(self) -> List[Tag]:
        """列出所有标签"""
        tags = []
        for tag_file in self.tags_dir.iterdir():
            if tag_file.is_file():
                tag = self.get_tag(tag_file.name)
                if tag:
                    tags.append(tag)
        
        return sorted(tags, key=lambda x: x.created_at, reverse=True)
    
    def _cache_tag(self, tag_name: str, tag_data: Dict[str, Any]):
        """缓存标签到Redis"""
        key = f"tag:{tag_name}"
        self.redis_client.setex(key, 3600, json.dumps(tag_data))
    
    def _remove_cached_tag(self, tag_name: str):
        """从Redis移除标签缓存"""
        key = f"tag:{tag_name}"
        self.redis_client.delete(key)


class VersionControlEngine:
    """版本控制引擎"""
    
    def __init__(self, project_path: str, redis_client: Optional[redis.Redis] = None):
        self.project_path = Path(project_path)
        self.vcs_path = self.project_path / ".vcs"
        self.redis_client = redis_client
        self.logger = logging.getLogger(__name__)
        
        self.vcs_path.mkdir(parents=True, exist_ok=True)
        
        self.object_storage = ObjectStorage(str(self.vcs_path), redis_client)
        self.index_manager = IndexManager(str(self.vcs_path))
        self.branch_manager = BranchManager(str(self.vcs_path), redis_client)
        self.tag_manager = TagManager(str(self.vcs_path), redis_client)
        
        self.hash_generator = HashGenerator()
    
    def init_repository(self, initial_branch: str = "main") -> bool:
        """初始化仓库"""
        try:
            self.branch_manager.create_branch(initial_branch, "")
            self.logger.info(f"Initialized repository with branch: {initial_branch}")
            return True
        except Exception as e:
            self.logger.error(f"Error initializing repository: {e}")
            return False
    
    def add_file(self, file_path: str, content: bytes) -> bool:
        """添加文件到暂存区"""
        try:
            content_hash = self.hash_generator.generate_blob_hash(content)
            
            self.object_storage.store_object(content_hash, ObjectType.BLOB, content)
            self.index_manager.stage_file(file_path, content_hash)
            
            self.logger.info(f"Added file to staging: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Error adding file {file_path}: {e}")
            return False
    
    def commit(self, author: str, message: str) -> Optional[str]:
        """提交更改"""
        try:
            staged_files = self.index_manager.get_staged_files()
            
            if not staged_files:
                self.logger.warning("No files to commit")
                return None
            
            current_branch = self.branch_manager.get_current_branch()
            parent_commit_id = self.branch_manager.get_branch_head(current_branch)
            
            tree_entries = []
            file_changes = []
            
            for file_path, content_hash in staged_files.items():
                tree_entries.append({
                    "mode": "100644",
                    "name": file_path,
                    "hash": content_hash
                })
                
                file_changes.append(FileChange(
                    file_path=file_path,
                    change_type="modified" if parent_commit_id else "added",
                    new_hash=content_hash
                ).__dict__)
            
            tree_hash = self.hash_generator.generate_tree_hash(tree_entries)
            tree_data = json.dumps(tree_entries).encode()
            self.object_storage.store_object(tree_hash, ObjectType.TREE, tree_data)
            
            version = Version(
                version_id="",
                parent_id=parent_commit_id,
                branch_name=current_branch,
                author=author,
                message=message,
                timestamp=time.time(),
                tree_hash=tree_hash,
                file_changes=file_changes
            )
            
            commit_hash = self.hash_generator.generate_commit_hash(version)
            version.version_id = commit_hash
            
            commit_data = json.dumps(asdict(version)).encode()
            self.object_storage.store_object(commit_hash, ObjectType.COMMIT, commit_data)
            
            self.branch_manager.update_branch_head(current_branch, commit_hash)
            self.index_manager.clear_staging_area()
            
            self.logger.info(f"Committed changes: {commit_hash}")
            return commit_hash
            
        except Exception as e:
            self.logger.error(f"Error committing: {e}")
            return None
    
    def checkout(self, commit_id: Optional[str] = None, branch_name: Optional[str] = None) -> bool:
        """检出提交或分支"""
        try:
            if branch_name:
                if not self.branch_manager.switch_branch(branch_name):
                    return False
                commit_id = self.branch_manager.get_branch_head(branch_name)
            
            if not commit_id:
                self.logger.error("No commit ID or branch name provided")
                return False
            
            commit_data = self.object_storage.retrieve_object(commit_id)
            if not commit_data:
                self.logger.error(f"Commit {commit_id} not found")
                return False
            
            commit_info = json.loads(commit_data.decode())
            tree_hash = commit_info["tree"]
            
            self._restore_tree(tree_hash)
            
            self.logger.info(f"Checked out: {commit_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking out: {e}")
            return False
    
    def _restore_tree(self, tree_hash: str):
        """恢复树结构"""
        tree_data = self.object_storage.retrieve_object(tree_hash)
        if not tree_data:
            return
        
        tree_entries = json.loads(tree_data.decode())
        
        for entry in tree_entries:
            if entry["mode"] == "100644":
                blob_data = self.object_storage.retrieve_object(entry["hash"])
                if blob_data:
                    file_path = self.project_path / entry["name"]
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(blob_data)
    
    def merge(self, source_branch: str, author: str, message: str) -> Tuple[bool, Optional[str], List[MergeConflict]]:
        """合并分支"""
        try:
            current_branch = self.branch_manager.get_current_branch()
            source_commit_id = self.branch_manager.get_branch_head(source_branch)
            target_commit_id = self.branch_manager.get_branch_head(current_branch)
            
            if not source_commit_id or not target_commit_id:
                self.logger.error("One or both branches have no commits")
                return False, None, []
            
            common_ancestor = self._find_common_ancestor(source_commit_id, target_commit_id)
            
            if common_ancestor == source_commit_id:
                self.logger.info("Already up to date")
                return True, target_commit_id, []
            
            conflicts = self._detect_conflicts(source_commit_id, target_commit_id, common_ancestor)
            
            if conflicts:
                self.logger.warning(f"Merge conflicts detected: {len(conflicts)}")
                return False, None, conflicts
            
            merge_commit_id = self._create_merge_commit(
                source_commit_id,
                target_commit_id,
                author,
                message
            )
            
            self.branch_manager.update_branch_head(current_branch, merge_commit_id)
            
            self.logger.info(f"Merged {source_branch} into {current_branch}: {merge_commit_id}")
            return True, merge_commit_id, []
            
        except Exception as e:
            self.logger.error(f"Error merging: {e}")
            return False, None, []
    
    def _find_common_ancestor(self, commit_id1: str, commit_id2: str) -> Optional[str]:
        """查找共同祖先"""
        ancestors1 = self._get_all_ancestors(commit_id1)
        ancestors2 = self._get_all_ancestors(commit_id2)
        
        common = ancestors1 & ancestors2
        if common:
            return max(common, key=lambda x: self._get_commit_timestamp(x))
        return None
    
    def _get_all_ancestors(self, commit_id: str) -> Set[str]:
        """获取所有祖先提交"""
        ancestors = set()
        visited = {commit_id}
        queue = [commit_id]
        
        while queue:
            current = queue.pop(0)
            ancestors.add(current)
            
            commit_data = self.object_storage.retrieve_object(current)
            if commit_data:
                commit_info = json.loads(commit_data.decode())
                parent_id = commit_info.get("parent")
                if parent_id and parent_id not in visited:
                    visited.add(parent_id)
                    queue.append(parent_id)
        
        return ancestors
    
    def _get_commit_timestamp(self, commit_id: str) -> float:
        """获取提交时间戳"""
        commit_data = self.object_storage.retrieve_object(commit_id)
        if commit_data:
            commit_info = json.loads(commit_data.decode())
            return commit_info.get("timestamp", 0)
        return 0
    
    def _detect_conflicts(self, source_commit_id: str, target_commit_id: str, 
                         common_ancestor: str) -> List[MergeConflict]:
        """检测冲突"""
        conflicts = []
        
        source_tree = self._get_tree_contents(source_commit_id)
        target_tree = self._get_tree_contents(target_commit_id)
        ancestor_tree = self._get_tree_contents(common_ancestor)
        
        all_files = set(source_tree.keys()) | set(target_tree.keys()) | set(ancestor_tree.keys())
        
        for file_path in all_files:
            source_content = source_tree.get(file_path, "")
            target_content = target_tree.get(file_path, "")
            ancestor_content = ancestor_tree.get(file_path, "")
            
            if source_content != target_content:
                if source_content != ancestor_content and target_content != ancestor_content:
                    conflicts.append(MergeConflict(
                        file_path=file_path,
                        base_content=ancestor_content,
                        our_content=target_content,
                        their_content=source_content,
                        conflict_markers=[]
                    ))
        
        return conflicts
    
    def _get_tree_contents(self, commit_id: str) -> Dict[str, str]:
        """获取树内容"""
        contents = {}
        
        commit_data = self.object_storage.retrieve_object(commit_id)
        if not commit_data:
            return contents
        
        commit_info = json.loads(commit_data.decode())
        tree_hash = commit_info["tree"]
        
        tree_data = self.object_storage.retrieve_object(tree_hash)
        if not tree_data:
            return contents
        
        tree_entries = json.loads(tree_data.decode())
        
        for entry in tree_entries:
            if entry["mode"] == "100644":
                blob_data = self.object_storage.retrieve_object(entry["hash"])
                if blob_data:
                    contents[entry["name"]] = blob_data.decode()
        
        return contents
    
    def _create_merge_commit(self, source_commit_id: str, target_commit_id: str,
                            author: str, message: str) -> str:
        """创建合并提交"""
        current_branch = self.branch_manager.get_current_branch()
        
        source_tree = self._get_tree_contents(source_commit_id)
        target_tree = self._get_tree_contents(target_commit_id)
        
        merged_tree = {**target_tree, **source_tree}
        
        tree_entries = []
        file_changes = []
        
        for file_path, content in merged_tree.items():
            content_hash = self.hash_generator.generate_blob_hash(content.encode())
            
            tree_entries.append({
                "mode": "100644",
                "name": file_path,
                "hash": content_hash
            })
            
            if file_path in source_tree and file_path in target_tree:
                if source_tree[file_path] != target_tree[file_path]:
                    file_changes.append(FileChange(
                        file_path=file_path,
                        change_type="modified",
                        old_hash=self.hash_generator.generate_blob_hash(target_tree[file_path].encode()),
                        new_hash=content_hash
                    ).__dict__)
            elif file_path in source_tree:
                file_changes.append(FileChange(
                    file_path=file_path,
                    change_type="added",
                    new_hash=content_hash
                ).__dict__)
        
        tree_hash = self.hash_generator.generate_tree_hash(tree_entries)
        tree_data = json.dumps(tree_entries).encode()
        self.object_storage.store_object(tree_hash, ObjectType.TREE, tree_data)
        
        version = Version(
            version_id="",
            parent_id=target_commit_id,
            branch_name=current_branch,
            author=author,
            message=f"Merge: {message}",
            timestamp=time.time(),
            tree_hash=tree_hash,
            file_changes=file_changes,
            metadata={"merge_parent": source_commit_id}
        )
        
        commit_hash = self.hash_generator.generate_commit_hash(version)
        version.version_id = commit_hash
        
        commit_data = json.dumps(asdict(version)).encode()
        self.object_storage.store_object(commit_hash, ObjectType.COMMIT, commit_data)
        
        return commit_hash
    
    def get_log(self, limit: int = 10, branch_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取提交历史"""
        if branch_name:
            commit_id = self.branch_manager.get_branch_head(branch_name)
        else:
            commit_id = self.branch_manager.get_branch_head(
                self.branch_manager.get_current_branch()
            )
        
        if not commit_id:
            return []
        
        logs = []
        visited = set()
        queue = [commit_id]
        
        while queue and len(logs) < limit:
            current = queue.pop(0)
            
            if current in visited:
                continue
            visited.add(current)
            
            commit_data = self.object_storage.retrieve_object(current)
            if commit_data:
                commit_info = json.loads(commit_data.decode())
                logs.append(commit_info)
                
                parent_id = commit_info.get("parent")
                if parent_id:
                    queue.append(parent_id)
        
        return logs
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "staged_files": list(self.index_manager.get_staged_files().keys()),
            "modified_files": list(self.index_manager.get_modified_files()),
            "untracked_files": list(self.index_manager.get_untracked_files()),
            "current_branch": self.branch_manager.get_current_branch(),
            "branches": [b.branch_name for b in self.branch_manager.list_branches()],
            "tags": [t.tag_name for t in self.tag_manager.list_tags()]
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "object_storage": self.object_storage.get_object_stats(),
            "branches": len(self.branch_manager.list_branches()),
            "tags": len(self.tag_manager.list_tags()),
            "staged_files": len(self.index_manager.get_staged_files()),
            "modified_files": len(self.index_manager.get_modified_files())
        }


_global_vcs_engine: Optional[VersionControlEngine] = None


def get_vcs_engine(project_path: str, redis_client: Optional[redis.Redis] = None) -> VersionControlEngine:
    """获取版本控制引擎实例"""
    global _global_vcs_engine
    
    if _global_vcs_engine is None:
        _global_vcs_engine = VersionControlEngine(project_path, redis_client)
    
    return _global_vcs_engine


def create_repository(project_path: str, redis_client: Optional[redis.Redis] = None) -> VersionControlEngine:
    """创建新仓库"""
    engine = VersionControlEngine(project_path, redis_client)
    engine.init_repository()
    return engine
