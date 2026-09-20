"""
关键帧动画系统 (v2.0)
参考 OpenShot 关键帧设计，提供贝塞尔/线性插值、缓动函数、属性绑定、曲线编辑器接口
核心改进：多属性通道管理、关键帧组操作、曲线可视化、范围编辑
"""

from typing import Dict, Any, List, Optional, Callable, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import time
import math
import copy
import logging

logger = logging.getLogger("AI短剧编辑器.keyframe_animation")


class InterpolationType(Enum):
    LINEAR = "linear"
    BEZIER = "bezier"
    STEP = "step"
    SMOOTH = "smooth"


class EasingType(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    BOUNCE = "bounce"
    ELASTIC = "elastic"
    BACK = "back"
    CUBIC_EASE_IN = "cubic_ease_in"
    CUBIC_EASE_OUT = "cubic_ease_out"
    CUBIC_EASE_IN_OUT = "cubic_ease_in_out"


@dataclass
class Keyframe:
    time: float
    value: Any
    interpolation: InterpolationType = InterpolationType.LINEAR
    easing: EasingType = EasingType.LINEAR
    bezier_control1: Optional[Tuple[float, float]] = None
    bezier_control2: Optional[Tuple[float, float]] = None
    label: str = ""
    comment: str = ""
    locked: bool = False

    def to_dict(self) -> Dict:
        return {
            'time': round(self.time, 3),
            'value': self.value,
            'interpolation': self.interpolation.value,
            'easing': self.easing.value,
            'bezier_c1': self.bezier_control1,
            'bezier_c2': self.bezier_control2,
            'label': self.label,
            'comment': self.comment,
            'locked': self.locked,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Keyframe':
        return cls(
            time=data.get('time', 0),
            value=data.get('value', 0),
            interpolation=InterpolationType(data.get('interpolation', 'linear')),
            easing=EasingType(data.get('easing', 'linear')),
            bezier_control1=tuple(data['bezier_c1']) if data.get('bezier_c1') else None,
            bezier_control2=tuple(data['bezier_c2']) if data.get('bezier_c2') else None,
            label=data.get('label', ""),
            comment=data.get('comment', ""),
            locked=data.get('locked', False),
        )

    def clone(self) -> 'Keyframe':
        return Keyframe(
            time=self.time,
            value=self.value,
            interpolation=self.interpolation,
            easing=self.easing,
            bezier_control1=self.bezier_control1,
            bezier_control2=self.bezier_control2,
            label=self.label,
            comment=self.comment,
            locked=self.locked,
        )


class KeyframeAnimation:
    """关键帧动画轨道 - 管理一个属性通道的所有关键帧

    参考 OpenShot 设计理念：
    - 帧精确的时间控制
    - 支持多种插值和缓动
    - 贝塞尔曲线自定义
    - 曲线可视化数据导出
    """

    def __init__(self, name: str = "animation", fps: float = 30.0):
        self.name = name
        self.fps = fps
        self._keyframes: List[Keyframe] = []
        self._cache: Dict[float, float] = {}
        self._sorted = True
        self._on_keyframe_changed: Optional[Callable[[Keyframe, str], None]] = None

    @property
    def keyframe_changed_callback(self) -> Optional[Callable[[Keyframe, str], None]]:
        return self._on_keyframe_changed

    @keyframe_changed_callback.setter
    def keyframe_changed_callback(self, callback: Optional[Callable[[Keyframe, str], None]]):
        self._on_keyframe_changed = callback

    def _notify_change(self, keyframe: Keyframe, action: str):
        if self._on_keyframe_changed:
            self._on_keyframe_changed(keyframe, action)

    def add_keyframe(self, time_sec: float, value: float,
                     easing: EasingType = EasingType.LINEAR,
                     interpolation: InterpolationType = InterpolationType.LINEAR,
                     label: str = "", comment: str = "") -> Keyframe:
        kf = Keyframe(
            time=time_sec,
            value=value,
            interpolation=interpolation,
            easing=easing,
            label=label,
            comment=comment,
        )
        self._keyframes.append(kf)
        self._sorted = False
        self._cache.clear()
        self._notify_change(kf, "added")
        return kf

    def insert_keyframe(self, index: int, time_sec: float, value: float,
                        easing: EasingType = EasingType.LINEAR,
                        interpolation: InterpolationType = InterpolationType.LINEAR) -> Keyframe:
        kf = Keyframe(time=time_sec, value=value,
                       interpolation=interpolation, easing=easing)
        self._keyframes.insert(index, kf)
        self._sorted = False
        self._cache.clear()
        self._notify_change(kf, "inserted")
        return kf

    def update_keyframe(self, index: int, **kwargs) -> bool:
        if 0 <= index < len(self._keyframes):
            kf = self._keyframes[index]
            if 'time' in kwargs:
                kf.time = kwargs['time']
                self._sorted = False
            if 'value' in kwargs:
                kf.value = kwargs['value']
            if 'easing' in kwargs:
                kf.easing = kwargs['easing']
            if 'interpolation' in kwargs:
                kf.interpolation = kwargs['interpolation']
            if 'bezier_control1' in kwargs:
                kf.bezier_control1 = kwargs['bezier_control1']
            if 'bezier_control2' in kwargs:
                kf.bezier_control2 = kwargs['bezier_control2']
            if 'label' in kwargs:
                kf.label = kwargs['label']
            if 'comment' in kwargs:
                kf.comment = kwargs['comment']
            self._cache.clear()
            self._notify_change(kf, "updated")
            return True
        return False

    def remove_keyframe(self, index: int) -> bool:
        if 0 <= index < len(self._keyframes):
            kf = self._keyframes.pop(index)
            self._cache.clear()
            self._notify_change(kf, "removed")
            return True
        return False

    def remove_keyframe_at(self, time_sec: float, tolerance: float = 0.05) -> bool:
        for i, kf in enumerate(self._keyframes):
            if abs(kf.time - time_sec) < tolerance:
                self._keyframes.pop(i)
                self._cache.clear()
                self._notify_change(kf, "removed")
                return True
        return False

    def remove_keyframes_in_range(self, start_time: float, end_time: float) -> int:
        removed = 0
        for i in reversed(range(len(self._keyframes))):
            if start_time <= self._keyframes[i].time <= end_time:
                kf = self._keyframes.pop(i)
                removed += 1
                self._notify_change(kf, "removed")
        if removed > 0:
            self._cache.clear()
        return removed

    def clear(self):
        for kf in self._keyframes:
            self._notify_change(kf, "removed")
        self._keyframes.clear()
        self._cache.clear()

    def _sort(self):
        if not self._sorted:
            self._keyframes.sort(key=lambda k: k.time)
            self._sorted = True

    def get_keyframe_at_time(self, time_sec: float, tolerance: float = 0.05) -> Optional[Keyframe]:
        self._sort()
        for kf in self._keyframes:
            if abs(kf.time - time_sec) < tolerance:
                return kf
        return None

    def get_keyframe_index_at_time(self, time_sec: float, tolerance: float = 0.05) -> int:
        self._sort()
        for i, kf in enumerate(self._keyframes):
            if abs(kf.time - time_sec) < tolerance:
                return i
        return -1

    def get_nearest_keyframe(self, time_sec: float) -> Optional[Keyframe]:
        self._sort()
        if not self._keyframes:
            return None
        nearest = self._keyframes[0]
        min_dist = abs(nearest.time - time_sec)
        for kf in self._keyframes[1:]:
            dist = abs(kf.time - time_sec)
            if dist < min_dist:
                min_dist = dist
                nearest = kf
        return nearest

    def get_keyframes_in_range(self, start_time: float, end_time: float) -> List[Keyframe]:
        self._sort()
        result = []
        for kf in self._keyframes:
            if start_time <= kf.time <= end_time:
                result.append(kf)
        return result

    def shift_keyframes(self, start_time: float, end_time: float, delta_time: float):
        self._sort()
        for kf in self._keyframes:
            if start_time <= kf.time <= end_time:
                kf.time += delta_time
                self._notify_change(kf, "shifted")
        self._sorted = False
        self._cache.clear()

    def scale_keyframes(self, start_time: float, end_time: float, scale_factor: float):
        self._sort()
        for kf in self._keyframes:
            if start_time <= kf.time <= end_time:
                kf.time = start_time + (kf.time - start_time) * scale_factor
                self._notify_change(kf, "scaled")
        self._sorted = False
        self._cache.clear()

    def copy_keyframes(self, start_time: float, end_time: float, target_time: float) -> List[Keyframe]:
        source_kfs = self.get_keyframes_in_range(start_time, end_time)
        if not source_kfs:
            return []
        offset = target_time - start_time
        new_kfs = []
        for kf in source_kfs:
            new_kf = kf.clone()
            new_kf.time += offset
            self._keyframes.append(new_kf)
            new_kfs.append(new_kf)
            self._notify_change(new_kf, "copied")
        self._sorted = False
        self._cache.clear()
        return new_kfs

    def _apply_easing(self, t: float, easing: EasingType) -> float:
        t = max(0.0, min(1.0, t))
        if easing == EasingType.LINEAR:
            return t
        elif easing == EasingType.EASE_IN:
            return t * t
        elif easing == EasingType.EASE_OUT:
            return t * (2 - t)
        elif easing == EasingType.EASE_IN_OUT:
            return t * t * (3 - 2 * t)
        elif easing == EasingType.CUBIC_EASE_IN:
            return t * t * t
        elif easing == EasingType.CUBIC_EASE_OUT:
            return 1 - math.pow(1 - t, 3)
        elif easing == EasingType.CUBIC_EASE_IN_OUT:
            if t < 0.5:
                return 4 * t * t * t
            return 1 - math.pow(-2 * t + 2, 3) / 2
        elif easing == EasingType.BOUNCE:
            if t < 1 / 2.75:
                return 7.5625 * t * t
            elif t < 2 / 2.75:
                t -= 1.5 / 2.75
                return 7.5625 * t * t + 0.75
            elif t < 2.5 / 2.75:
                t -= 2.25 / 2.75
                return 7.5625 * t * t + 0.9375
            else:
                t -= 2.625 / 2.75
                return 7.5625 * t * t + 0.984375
        elif easing == EasingType.ELASTIC:
            if t == 0 or t == 1:
                return t
            c4 = (2 * math.pi) / 3
            return math.pow(2, -10 * t) * math.sin((t * 10 - 0.75) * c4) + 1
        elif easing == EasingType.BACK:
            c1 = 1.70158
            c3 = c1 + 1
            return c3 * t * t * t - c1 * t * t
        return t

    def _apply_bezier(self, t: float, p0: float, p1: float, c0: Tuple[float, float], c1: Tuple[float, float]) -> float:
        """贝塞尔曲线插值"""
        t2 = t * t
        t3 = t2 * t
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        return mt3 * p0 + 3 * mt2 * t * c0[1] + 3 * mt * t2 * c1[1] + t3 * p1

    def get_value(self, time_sec: float) -> float:
        """获取指定时间点的插值（增强版，支持贝塞尔曲线）"""
        if not self._keyframes:
            return 0.0
        self._sort()
        cache_key = round(time_sec, 2)
        if cache_key in self._cache:
            return self._cache[cache_key]
        if len(self._keyframes) == 1:
            return float(self._keyframes[0].value)
        if time_sec <= self._keyframes[0].time:
            return float(self._keyframes[0].value)
        if time_sec >= self._keyframes[-1].time:
            return float(self._keyframes[-1].value)
        right_idx = 1
        while right_idx < len(self._keyframes) and self._keyframes[right_idx].time < time_sec:
            right_idx += 1
        kf0 = self._keyframes[right_idx - 1]
        kf1 = self._keyframes[right_idx]
        duration = kf1.time - kf0.time
        if duration <= 0:
            return float(kf1.value)
        t = (time_sec - kf0.time) / duration
        t = self._apply_easing(t, kf0.easing if kf0 != self._keyframes[0] else kf1.easing)
        v0 = float(kf0.value)
        v1 = float(kf1.value)
        if kf0.interpolation == InterpolationType.BEZIER and kf0.bezier_control1 and kf0.bezier_control2:
            result = self._apply_bezier(t, v0, v1, kf0.bezier_control1, kf0.bezier_control2)
        elif kf0.interpolation == InterpolationType.STEP:
            result = v0
        elif kf0.interpolation == InterpolationType.SMOOTH:
            neighbors = []
            if right_idx > 1:
                neighbors.append(self._keyframes[right_idx - 2])
            neighbors.extend([kf0, kf1])
            if right_idx < len(self._keyframes) - 1:
                neighbors.append(self._keyframes[right_idx + 1])
            result = self._smooth_interpolate(neighbors, t, v0, v1, duration)
        else:
            result = v0 + (v1 - v0) * t
        self._cache[cache_key] = result
        return result

    def _smooth_interpolate(self, neighbors: List[Keyframe], t: float, v0: float, v1: float, duration: float) -> float:
        """平滑插值，基于相邻关键帧计算自然曲线"""
        if len(neighbors) >= 4:
            prev_v = float(neighbors[0].value)
            next_v = float(neighbors[-1].value)
            m0 = ((v1 - prev_v) / (neighbors[2].time - neighbors[0].time)) * 0.5
            m1 = ((next_v - v0) / (neighbors[-1].time - neighbors[1].time)) * 0.5
            t2 = t * t
            t3 = t2 * t
            return (2 * t3 - 3 * t2 + 1) * v0 + (t3 - 2 * t2 + t) * m0 * duration + (-2 * t3 + 3 * t2) * v1 + (t3 - t2) * m1 * duration
        return v0 + (v1 - v0) * t

    def get_keyframes(self) -> List[Keyframe]:
        self._sort()
        return list(self._keyframes)

    def get_keyframe_count(self) -> int:
        return len(self._keyframes)

    def to_list(self) -> List[Dict]:
        self._sort()
        return [kf.to_dict() for kf in self._keyframes]

    def from_list(self, data: List[Dict]):
        self._keyframes = [Keyframe.from_dict(d) for d in data]
        self._sorted = False
        self._cache.clear()

    def get_curve_points(self, start_time: float, end_time: float, samples: int = 100) -> List[Tuple[float, float]]:
        """生成曲线可视化数据点（供曲线编辑器使用）"""
        points = []
        if samples <= 1:
            samples = 100
        step = (end_time - start_time) / (samples - 1)
        for i in range(samples):
            t = start_time + i * step
            val = self.get_value(t)
            points.append((t, val))
        return points

    def get_tangent(self, time_sec: float) -> float:
        """计算指定时间点的切线斜率（用于曲线编辑器）"""
        eps = 0.001
        v0 = self.get_value(time_sec - eps)
        v1 = self.get_value(time_sec + eps)
        return (v1 - v0) / (2 * eps)

    def get_animation_range(self) -> Tuple[float, float]:
        """获取动画时间范围"""
        self._sort()
        if not self._keyframes:
            return (0.0, 1.0)
        return (self._keyframes[0].time, self._keyframes[-1].time)

    def clone(self) -> 'KeyframeAnimation':
        """克隆动画轨道"""
        cloned = KeyframeAnimation(name=self.name, fps=self.fps)
        cloned._keyframes = [kf.clone() for kf in self._keyframes]
        cloned._sorted = self._sorted
        return cloned

    def merge(self, other: 'KeyframeAnimation'):
        """合并另一个动画轨道的关键帧"""
        for kf in other._keyframes:
            existing = self.get_keyframe_at_time(kf.time)
            if existing:
                existing.value = kf.value
                existing.easing = kf.easing
                existing.interpolation = kf.interpolation
            else:
                self._keyframes.append(kf.clone())
        self._sorted = False
        self._cache.clear()


class AnimatableProperties:
    """可动画的属性通道集合 (v2.0)

    参考 OpenShot 属性动画设计：
    - 多属性通道统一管理
    - 属性组操作（平移、缩放、复制）
    - 曲线可视化数据导出
    - 属性链接和表达式支持
    """

    VALID_PROPERTIES = {
        'position_x', 'position_y', 'scale_x', 'scale_y', 'rotation',
        'opacity', 'volume', 'speed', 'brightness', 'contrast',
        'saturation', 'hue', 'blur', 'vignette', 'sharpen',
        'crop_top', 'crop_bottom', 'crop_left', 'crop_right',
        'color_r', 'color_g', 'color_b', 'color_a',
        'font_size', 'line_spacing', 'shadow_opacity', 'border_width',
    }

    POSITION_PROPERTIES = {'position_x', 'position_y'}
    SCALE_PROPERTIES = {'scale_x', 'scale_y'}
    COLOR_PROPERTIES = {'brightness', 'contrast', 'saturation', 'hue'}
    TRANSFORM_PROPERTIES = {'position_x', 'position_y', 'scale_x', 'scale_y', 'rotation'}
    VISUAL_PROPERTIES = {'opacity', 'blur', 'vignette', 'sharpen'}

    def __init__(self):
        self._channels: Dict[str, KeyframeAnimation] = {}
        self._link_expressions: Dict[str, Callable[[Dict[str, float]], float]] = {}

    def get_channel(self, prop_name: str, fps: float = 30.0) -> KeyframeAnimation:
        if prop_name not in self._channels:
            self._channels[prop_name] = KeyframeAnimation(name=prop_name, fps=fps)
        return self._channels[prop_name]

    def add_keyframe(self, prop_name: str, time_sec: float, value: float,
                     easing: EasingType = EasingType.LINEAR,
                     interpolation: InterpolationType = InterpolationType.LINEAR):
        if prop_name not in self.VALID_PROPERTIES:
            raise ValueError(f"无效属性: {prop_name}")
        channel = self.get_channel(prop_name)
        channel.add_keyframe(time_sec, value, easing=easing, interpolation=interpolation)

    def add_keyframes_to_multiple(self, prop_names: List[str], time_sec: float,
                                   values: Dict[str, float],
                                   easing: EasingType = EasingType.LINEAR):
        """一次性为多个属性添加关键帧"""
        for prop_name in prop_names:
            if prop_name in values:
                self.add_keyframe(prop_name, time_sec, values[prop_name], easing=easing)

    def get_property_value(self, prop_name: str, time_sec: float) -> float:
        if prop_name in self._link_expressions:
            all_values = self.get_all_values(time_sec)
            try:
                return self._link_expressions[prop_name](all_values)
            except Exception as e:
                logger.debug(f"[KeyframeAnimation] 链接表达式求值失败: {e}")

        channel = self._channels.get(prop_name)
        if channel:
            return channel.get_value(time_sec)
        if prop_name in ('scale_x', 'scale_y', 'opacity', 'volume', 'speed',
                          'contrast', 'saturation'):
            return 1.0
        return 0.0

    def get_all_values(self, time_sec: float) -> Dict[str, float]:
        result = {}
        for name in self.VALID_PROPERTIES:
            result[name] = self.get_property_value(name, time_sec)
        return result

    def get_active_values(self, time_sec: float) -> Dict[str, float]:
        result = {}
        for name, channel in self._channels.items():
            if channel.get_keyframe_count() > 0:
                result[name] = channel.get_value(time_sec)
        return result

    def remove_keyframe(self, prop_name: str, index: int) -> bool:
        channel = self._channels.get(prop_name)
        if channel:
            return channel.remove_keyframe(index)
        return False

    def remove_keyframes_at_time(self, time_sec: float, tolerance: float = 0.05) -> int:
        removed = 0
        for channel in self._channels.values():
            if channel.remove_keyframe_at(time_sec, tolerance):
                removed += 1
        return removed

    def remove_keyframes_in_range(self, start_time: float, end_time: float) -> int:
        removed = 0
        for channel in self._channels.values():
            removed += channel.remove_keyframes_in_range(start_time, end_time)
        return removed

    def shift_all_keyframes(self, start_time: float, end_time: float, delta_time: float):
        """平移所有属性通道中指定时间范围内的关键帧"""
        for channel in self._channels.values():
            channel.shift_keyframes(start_time, end_time, delta_time)

    def scale_all_keyframes(self, start_time: float, end_time: float, scale_factor: float):
        """缩放所有属性通道中指定时间范围内的关键帧"""
        for channel in self._channels.values():
            channel.scale_keyframes(start_time, end_time, scale_factor)

    def copy_all_keyframes(self, start_time: float, end_time: float, target_time: float):
        """复制所有属性通道中指定时间范围内的关键帧到目标位置"""
        for channel in self._channels.values():
            channel.copy_keyframes(start_time, end_time, target_time)

    def link_property(self, prop_name: str, expression: Callable[[Dict[str, float]], float]):
        """为属性添加链接表达式（一个属性的值可以由其他属性计算得出）"""
        self._link_expressions[prop_name] = expression

    def unlink_property(self, prop_name: str):
        """移除属性的链接表达式"""
        self._link_expressions.pop(prop_name, None)

    def is_linked(self, prop_name: str) -> bool:
        """检查属性是否有链接表达式"""
        return prop_name in self._link_expressions

    def get_channel_names(self) -> List[str]:
        return list(self._channels.keys())

    def get_keyframe_count(self) -> int:
        """获取所有属性通道的关键帧总数"""
        total = 0
        for channel in self._channels.values():
            total += channel.get_keyframe_count()
        return total

    def get_keyframes_at_time(self, time_sec: float, tolerance: float = 0.05) -> Dict[str, Keyframe]:
        """获取指定时间点所有属性的关键帧"""
        result = {}
        for name, channel in self._channels.items():
            kf = channel.get_keyframe_at_time(time_sec, tolerance)
            if kf:
                result[name] = kf
        return result

    def get_animation_range(self) -> Tuple[float, float]:
        """获取所有属性通道的动画时间范围"""
        if not self._channels:
            return (0.0, 1.0)
        min_time = float('inf')
        max_time = float('-inf')
        for channel in self._channels.values():
            start, end = channel.get_animation_range()
            min_time = min(min_time, start)
            max_time = max(max_time, end)
        return (min_time, max_time)

    def get_curve_data(self, property_name: str, start_time: float,
                        end_time: float, samples: int = 100) -> List[Tuple[float, float]]:
        """获取指定属性的曲线可视化数据"""
        channel = self._channels.get(property_name)
        if channel:
            return channel.get_curve_points(start_time, end_time, samples)
        return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            'channels': {name: ch.to_list() for name, ch in self._channels.items()},
            'linked_properties': list(self._link_expressions.keys()),
        }

    def from_dict(self, data: Dict[str, Any]):
        self._channels.clear()
        channels_data = data.get('channels', {})
        for name, kfs in channels_data.items():
            channel = KeyframeAnimation(name=name)
            channel.from_list(kfs)
            self._channels[name] = channel

    def clone(self) -> 'AnimatableProperties':
        """克隆属性集合"""
        cloned = AnimatableProperties()
        for name, channel in self._channels.items():
            cloned._channels[name] = channel.clone()
        cloned._link_expressions = dict(self._link_expressions)
        return cloned

    def merge(self, other: 'AnimatableProperties'):
        """合并另一个属性集合的关键帧"""
        for name, channel in other._channels.items():
            if name in self._channels:
                self._channels[name].merge(channel)
            else:
                self._channels[name] = channel.clone()

    def clear(self):
        self._channels.clear()
        self._link_expressions.clear()

    def has_animation(self) -> bool:
        """检查是否有任何动画关键帧"""
        for channel in self._channels.values():
            if channel.get_keyframe_count() > 0:
                return True
        return False

    def get_property_group(self, group_name: str) -> List[str]:
        """获取指定属性组的属性名称列表"""
        group_map = {
            'position': self.POSITION_PROPERTIES,
            'scale': self.SCALE_PROPERTIES,
            'color': self.COLOR_PROPERTIES,
            'transform': self.TRANSFORM_PROPERTIES,
            'visual': self.VISUAL_PROPERTIES,
        }
        return list(group_map.get(group_name, []))
