"""
流程编排器（FlowOrchestrator）
============================
积木串联、并联、条件执行的核心
支持：串联、并联、循环、条件判断
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import threading
import time

from .base_block import LegoBlock, BlockResult, BlockState
from .core import EventBus, EventType


class NodeType(Enum):
    BLOCK = "block"
    START = "start"
    END = "end"
    CONDITION = "condition"
    PARALLEL = "parallel"
    LOOP = "loop"


class FlowState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class FlowNode:
    id: str
    node_type: NodeType
    block_name: str = ""
    block_instance: Optional[LegoBlock] = None
    config: Dict[str, Any] = field(default_factory=dict)
    position: tuple = (0, 0)
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]


@dataclass
class FlowConnection:
    id: str
    source_id: str
    target_id: str
    output_key: str = "output"
    input_key: str = "input"
    condition: Optional[Callable[[Dict], bool]] = None
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]


@dataclass
class FlowResult:
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    error: Optional[str] = None
    node_results: Dict[str, BlockResult] = field(default_factory=dict)


class FlowOrchestrator:
    """
    流程编排器 - 管理积木的执行流程
    
    支持：
    - 串联执行：A → B → C
    - 并联执行：A → [B, C] → D
    - 条件执行：if condition then A else B
    - 循环执行：while condition do A
    """
    
    def __init__(self):
        self._nodes: Dict[str, FlowNode] = {}
        self._connections: Dict[str, FlowConnection] = {}
        self._adjacency: Dict[str, List[str]] = {}
        self._reverse_adjacency: Dict[str, List[str]] = {}
        self._state = FlowState.IDLE
        self._current_node: Optional[str] = None
        self._data_context: Dict[str, Any] = {}
        self._event_bus = EventBus.get_instance()
        self._lock = threading.Lock()
        self._progress_callback: Optional[Callable[[float, str], None]] = None
    
    @property
    def state(self) -> FlowState:
        return self._state
    
    @property
    def current_node(self) -> Optional[str]:
        return self._current_node
    
    def set_progress_callback(self, callback: Callable[[float, str], None]):
        self._progress_callback = callback
    
    def _report_progress(self, progress: float, message: str):
        if self._progress_callback:
            self._progress_callback(progress, message)
    
    def add_node(self, node: FlowNode) -> str:
        """添加节点"""
        with self._lock:
            self._nodes[node.id] = node
            if node.id not in self._adjacency:
                self._adjacency[node.id] = []
            if node.id not in self._reverse_adjacency:
                self._reverse_adjacency[node.id] = []
        return node.id
    
    def remove_node(self, node_id: str) -> bool:
        """移除节点"""
        with self._lock:
            if node_id not in self._nodes:
                return False
            
            del self._nodes[node_id]
            
            if node_id in self._adjacency:
                for target_id in self._adjacency[node_id]:
                    if target_id in self._reverse_adjacency:
                        self._reverse_adjacency[target_id] = [
                            x for x in self._reverse_adjacency[target_id] if x != node_id
                        ]
                del self._adjacency[node_id]
            
            if node_id in self._reverse_adjacency:
                for source_id in self._reverse_adjacency[node_id]:
                    if source_id in self._adjacency:
                        self._adjacency[source_id] = [
                            x for x in self._adjacency[source_id] if x != node_id
                        ]
                del self._reverse_adjacency[node_id]
            
            conns_to_remove = [
                cid for cid, c in self._connections.items()
                if c.source_id == node_id or c.target_id == node_id
            ]
            for cid in conns_to_remove:
                del self._connections[cid]
            
            return True
    
    def connect(self, source_id: str, target_id: str, 
                output_key: str = "output", input_key: str = "input",
                condition: Callable[[Dict], bool] = None) -> str:
        """连接两个节点"""
        with self._lock:
            connection = FlowConnection(
                id="",
                source_id=source_id,
                target_id=target_id,
                output_key=output_key,
                input_key=input_key,
                condition=condition
            )
            self._connections[connection.id] = connection
            
            if source_id not in self._adjacency:
                self._adjacency[source_id] = []
            self._adjacency[source_id].append(target_id)
            
            if target_id not in self._reverse_adjacency:
                self._reverse_adjacency[target_id] = []
            self._reverse_adjacency[target_id].append(source_id)
            
            return connection.id
    
    def disconnect(self, connection_id: str) -> bool:
        """断开连接"""
        with self._lock:
            if connection_id not in self._connections:
                return False
            
            conn = self._connections[connection_id]
            
            if conn.source_id in self._adjacency:
                self._adjacency[conn.source_id] = [
                    x for x in self._adjacency[conn.source_id] if x != conn.target_id
                ]
            
            if conn.target_id in self._reverse_adjacency:
                self._reverse_adjacency[conn.target_id] = [
                    x for x in self._reverse_adjacency[conn.target_id] if x != conn.source_id
                ]
            
            del self._connections[connection_id]
            return True
    
    def get_start_nodes(self) -> List[str]:
        """获取起始节点（没有入边的节点）"""
        return [
            node_id for node_id in self._nodes
            if node_id not in self._reverse_adjacency or not self._reverse_adjacency[node_id]
        ]
    
    def get_end_nodes(self) -> List[str]:
        """获取结束节点（没有出边的节点）"""
        return [
            node_id for node_id in self._nodes
            if node_id not in self._adjacency or not self._adjacency[node_id]
        ]
    
    def get_next_nodes(self, node_id: str) -> List[str]:
        """获取下一个节点"""
        return self._adjacency.get(node_id, [])
    
    def get_prev_nodes(self, node_id: str) -> List[str]:
        """获取上一个节点"""
        return self._reverse_adjacency.get(node_id, [])
    
    def _topological_sort(self) -> List[str]:
        """拓扑排序"""
        in_degree = {node_id: 0 for node_id in self._nodes}
        
        for node_id in self._nodes:
            for next_id in self._adjacency.get(node_id, []):
                in_degree[next_id] = in_degree.get(next_id, 0) + 1
        
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            
            for next_id in self._adjacency.get(node_id, []):
                in_degree[next_id] -= 1
                if in_degree[next_id] == 0:
                    queue.append(next_id)
        
        return result
    
    def _level_groups(self, execution_order: List[str]) -> List[List[str]]:
        """
        将拓扑排序后的节点按 BFS 层级分组。
        同层级节点之间无依赖关系，可以并行执行。
        
        返回: [[level0_node_ids], [level1_node_ids], ...]
        """
        node_levels: Dict[str, int] = {}
        
        # 起始节点 level=0
        start_nodes = self.get_start_nodes()
        q = deque()
        for nid in start_nodes:
            node_levels[nid] = 0
            q.append(nid)
        
        # BFS 计算层级
        while q:
            nid = q.popleft()
            for next_id in self._adjacency.get(nid, []):
                new_level = node_levels[nid] + 1
                if next_id not in node_levels or node_levels[next_id] < new_level:
                    node_levels[next_id] = new_level
                    q.append(next_id)
        
        # 按层级分组（保持拓扑序内的相对顺序）
        groups: Dict[int, List[str]] = {}
        for nid in execution_order:
            level = node_levels.get(nid, 0)
            if level not in groups:
                groups[level] = []
            groups[level].append(nid)
        
        return [groups[lvl] for lvl in sorted(groups.keys())]
    
    def _execute_single_node(
        self, node_id: str, node: FlowNode,
        node_results: Dict[str, BlockResult]
    ) -> BlockResult:
        """
        执行单个 BLOCK 节点（线程安全）。
        
        Args:
            node_id: 节点ID
            node: 流程节点
            node_results: 共享结果字典（写时加锁）
        """
        prev_nodes = self.get_prev_nodes(node_id)
        node_inputs = {}
        
        # 从上游节点收集输入（读取共享字典需要加锁）
        with self._lock:
            for prev_id in prev_nodes:
                if prev_id in node_results:
                    prev_outputs = node_results[prev_id].outputs
                    for conn in self._connections.values():
                        if conn.source_id == prev_id and conn.target_id == node_id:
                            if conn.output_key in prev_outputs:
                                node_inputs[conn.input_key] = prev_outputs[conn.output_key]
        
        # 注入节点自身配置
        for key, value in node.config.items():
            if key not in node_inputs:
                node_inputs[key] = value
        
        # 执行
        self._event_bus.emit(
            EventType.BLOCK_STARTED,
            {"node_id": node_id, "block_name": node.block_name}
        )
        
        result = node.block_instance.run(node_inputs)
        
        # 写入结果（加锁保护共享字典）
        with self._lock:
            node_results[node_id] = result
        
        self._event_bus.emit(
            EventType.BLOCK_COMPLETED if result.success else EventType.BLOCK_FAILED,
            {"node_id": node_id, "result": result.to_dict() if hasattr(result, 'to_dict') else {}}
        )
        
        return result
    
    def execute(self, initial_data: Dict[str, Any] = None) -> FlowResult:
        """
        执行整个流程
        """
        start_time = time.time()
        self._state = FlowState.RUNNING
        self._data_context = initial_data or {}
        node_results: Dict[str, BlockResult] = {}
        
        self._event_bus.emit(EventType.TASK_STARTED, {"flow": "orchestrator"})
        
        try:
            execution_order = self._topological_sort()
            level_groups = self._level_groups(execution_order)
            total_nodes = len(execution_order)
            executed_count = 0
            
            for group_idx, node_ids in enumerate(level_groups):
                if self._state == FlowState.PAUSED:
                    while self._state == FlowState.PAUSED:
                        time.sleep(0.1)
                
                if self._state != FlowState.RUNNING:
                    break
                
                # ── 分离 BLOCK 节点和非 BLOCK 节点 ──
                block_nodes: List[tuple] = []  # (node_id, FlowNode)
                special_nodes: List[tuple] = []  # (node_id, FlowNode) - START/END
                
                for nid in node_ids:
                    node = self._nodes.get(nid)
                    if not node:
                        continue
                    if node.node_type == NodeType.BLOCK and node.block_instance:
                        block_nodes.append((nid, node))
                    else:
                        special_nodes.append((nid, node))
                
                # ── 处理 START/END 等特殊节点（串行，设置上下文）──
                for nid, node in special_nodes:
                    executed_count += 1
                    self._current_node = nid
                    progress = executed_count / total_nodes if total_nodes > 0 else 1.0
                    self._report_progress(progress, f"执行节点: {node.block_name or nid}")
                    
                    if node.node_type == NodeType.START:
                        node_results[nid] = BlockResult(success=True, outputs=self._data_context)
                    elif node.node_type == NodeType.END:
                        prev_nodes = self.get_prev_nodes(nid)
                        final_outputs = {}
                        for prev_id in prev_nodes:
                            if prev_id in node_results:
                                final_outputs.update(node_results[prev_id].outputs)
                        node_results[nid] = BlockResult(success=True, outputs=final_outputs)
                
                # ── 并行执行同层级 BLOCK 节点 ──
                if block_nodes:
                    parallel_count = len(block_nodes)
                    self._report_progress(
                        executed_count / total_nodes if total_nodes > 0 else 1.0,
                        f"并行执行 {parallel_count} 个节点..."
                    )
                    
                    # 单节点直接执行，避免线程池开销
                    if parallel_count == 1:
                        nid, node = block_nodes[0]
                        self._current_node = nid
                        result = self._execute_single_node(nid, node, node_results)
                        executed_count += 1
                        if not result.success:
                            self._state = FlowState.ERROR
                            return FlowResult(
                                success=False,
                                error=f"节点 {nid} 执行失败: {result.error}",
                                execution_time=time.time() - start_time,
                                node_results=node_results
                            )
                    else:
                        with ThreadPoolExecutor(max_workers=min(parallel_count, 8)) as executor:
                            futures = {
                                executor.submit(self._execute_single_node, nid, node, node_results): nid
                                for nid, node in block_nodes
                            }
                            for future in as_completed(futures):
                                nid = futures[future]
                                executed_count += 1
                                try:
                                    result = future.result()
                                    if not result.success:
                                        self._state = FlowState.ERROR
                                        # 取消尚未完成的 futures
                                        for f in futures:
                                            f.cancel()
                                        return FlowResult(
                                            success=False,
                                            error=f"节点 {nid} 执行失败: {result.error}",
                                            execution_time=time.time() - start_time,
                                            node_results=node_results
                                        )
                                except Exception as exc:
                                    self._state = FlowState.ERROR
                                    for f in futures:
                                        f.cancel()
                                    return FlowResult(
                                        success=False,
                                        error=f"节点 {nid} 执行异常: {exc}",
                                        execution_time=time.time() - start_time,
                                        node_results=node_results
                                    )
                        
                        self._report_progress(
                            executed_count / total_nodes if total_nodes > 0 else 1.0,
                            f"完成并行执行 {parallel_count} 个节点"
                        )
            
            end_nodes = self.get_end_nodes()
            final_outputs = {}
            for end_id in end_nodes:
                if end_id in node_results:
                    final_outputs.update(node_results[end_id].outputs)
            
            self._state = FlowState.COMPLETED
            self._event_bus.emit(EventType.TASK_COMPLETED, {"flow": "orchestrator"})
            
            return FlowResult(
                success=True,
                outputs=final_outputs,
                execution_time=time.time() - start_time,
                node_results=node_results
            )
            
        except Exception as e:
            self._state = FlowState.ERROR
            self._event_bus.emit(EventType.TASK_FAILED, {"flow": "orchestrator", "error": str(e)})
            return FlowResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
                node_results=node_results
            )
    
    def pause(self):
        """暂停执行"""
        self._state = FlowState.PAUSED
    
    def resume(self):
        """恢复执行"""
        if self._state == FlowState.PAUSED:
            self._state = FlowState.RUNNING
    
    def cancel(self):
        """取消执行"""
        self._state = FlowState.IDLE
        self._current_node = None
    
    def reset(self):
        """重置流程"""
        self._state = FlowState.IDLE
        self._current_node = None
        self._data_context = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化流程"""
        return {
            "nodes": [
                {
                    "id": node.id,
                    "node_type": node.node_type.value,
                    "block_name": node.block_name,
                    "config": node.config,
                    "position": node.position
                }
                for node in self._nodes.values()
            ],
            "connections": [
                {
                    "id": conn.id,
                    "source_id": conn.source_id,
                    "target_id": conn.target_id,
                    "output_key": conn.output_key,
                    "input_key": conn.input_key
                }
                for conn in self._connections.values()
            ]
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """反序列化流程"""
        self._nodes.clear()
        self._connections.clear()
        self._adjacency.clear()
        self._reverse_adjacency.clear()
        
        for node_data in data.get("nodes", []):
            node = FlowNode(
                id=node_data["id"],
                node_type=NodeType(node_data["node_type"]),
                block_name=node_data.get("block_name", ""),
                config=node_data.get("config", {}),
                position=tuple(node_data.get("position", (0, 0)))
            )
            self._nodes[node.id] = node
        
        for conn_data in data.get("connections", []):
            self.connect(
                source_id=conn_data["source_id"],
                target_id=conn_data["target_id"],
                output_key=conn_data.get("output_key", "output"),
                input_key=conn_data.get("input_key", "input")
            )
    
    def create_simple_chain(self, blocks: List[LegoBlock]) -> str:
        """
        创建简单的串联流程
        A → B → C → ...
        返回起始节点ID
        """
        prev_id = None
        start_id = None
        
        start_node = FlowNode(id="start", node_type=NodeType.START)
        self.add_node(start_node)
        start_id = start_node.id
        prev_id = start_id
        
        for block in blocks:
            node = FlowNode(
                id="",
                node_type=NodeType.BLOCK,
                block_name=block.info().name,
                block_instance=block
            )
            self.add_node(node)
            self.connect(prev_id, node.id)
            prev_id = node.id
        
        end_node = FlowNode(id="end", node_type=NodeType.END)
        self.add_node(end_node)
        self.connect(prev_id, end_node.id)
        
        return start_id
    
    def create_parallel_flow(self, blocks: List[LegoBlock]) -> str:
        """
        创建并联流程
              → B →
        A →         → D
              → C →
        返回起始节点ID
        """
        start_node = FlowNode(id="start", node_type=NodeType.START)
        self.add_node(start_node)
        
        end_node = FlowNode(id="end", node_type=NodeType.END)
        self.add_node(end_node)
        
        for block in blocks:
            node = FlowNode(
                id="",
                node_type=NodeType.BLOCK,
                block_name=block.info().name,
                block_instance=block
            )
            self.add_node(node)
            self.connect(start_node.id, node.id)
            self.connect(node.id, end_node.id)
        
        return start_node.id
