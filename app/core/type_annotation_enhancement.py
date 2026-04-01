"""
类型注解增强模块
================
提供类型注解工具和类型检查功能
"""

import ast
import inspect
import logging
from typing import Dict, Any, List, Optional, Type, get_type_hints, get_origin, get_args
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import ConfigurationError, ErrorCode

logger = logging.getLogger(__name__)


class TypeAnnotationQuality(Enum):
    """类型注解质量等级"""
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    INCORRECT = "incorrect"


@dataclass
class TypeIssue:
    """类型问题"""
    file_path: str
    line_number: int
    function_name: str
    issue_type: TypeAnnotationQuality
    expected_type: str
    actual_type: Optional[str] = None
    description: str
    suggestion: str


@dataclass
class TypeCoverage:
    """类型覆盖率统计"""
    file_path: str
    total_functions: int
    annotated_functions: int
    coverage_rate: float
    missing_annotations: List[str]


class TypeChecker:
    """类型检查器"""
    
    def __init__(self):
        self._issues: List[TypeIssue] = []
        self._coverage: List[TypeCoverage] = []
        self._type_hints_cache: Dict[str, Dict[str, Any]] = {}
    
    def check_file(self, file_path: str) -> Dict[str, Any]:
        """检查单个文件的类型注解
        
        Args:
            file_path: 文件路径
        
        Returns:
            检查结果
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析AST
            tree = ast.parse(content)
            
            # 检查类型注解
            issues = self._check_type_annotations(tree, file_path)
            
            # 计算类型覆盖率
            coverage = self._calculate_type_coverage(tree, file_path)
            
            result = {
                'file_path': file_path,
                'issues': issues,
                'coverage': coverage,
                'total_issues': len(issues),
                'coverage_rate': coverage.coverage_rate
            }
            
            self._issues.extend(issues)
            self._coverage.append(coverage)
            
            return result
            
        except Exception as e:
            logger.error(f"类型检查失败: {file_path} - {e}")
            return {
                'file_path': file_path,
                'error': str(e)
            }
    
    def _check_type_annotations(self, tree: ast.AST, 
                           file_path: str) -> List[TypeIssue]:
        """检查类型注解"""
        issues = []
        
        for node in ast.walk(tree):
            # 检查函数类型注解
            if isinstance(node, ast.FunctionDef):
                func_issues = self._check_function_types(node, file_path)
                issues.extend(func_issues)
            
            # 检查类方法类型注解
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        func_issues = self._check_function_types(item, file_path)
                        issues.extend(func_issues)
        
        return issues
    
    def _check_function_types(self, node: ast.FunctionDef, 
                           file_path: str) -> List[TypeIssue]:
        """检查函数类型注解"""
        issues = []
        
        # 检查返回类型
        if node.returns is None:
            issues.append(TypeIssue(
                file_path=file_path,
                line_number=node.lineno,
                function_name=node.name,
                issue_type=TypeAnnotationQuality.MISSING,
                expected_type="Any",
                actual_type=None,
                description=f"函数 {node.name} 缺少返回类型注解",
                suggestion="添加返回类型注解，如: def func() -> int:"
            ))
        
        # 检查参数类型
        for arg in node.args.args:
            if arg.annotation is None:
                issues.append(TypeIssue(
                    file_path=file_path,
                    line_number=node.lineno,
                    function_name=node.name,
                    issue_type=TypeAnnotationQuality.MISSING,
                    expected_type="Any",
                    actual_type=None,
                    description=f"函数 {node.name} 的参数 {arg.arg} 缺少类型注解",
                    suggestion=f"添加参数类型注解，如: def func({arg.arg}: str) -> int:"
                ))
        
        # 检查类型注解是否正确
        if node.returns:
            type_issues = self._validate_type_annotation(node.returns, node.name, file_path, node.lineno)
            issues.extend(type_issues)
        
        return issues
    
    def _validate_type_annotation(self, annotation: ast.AST, 
                              function_name: str,
                              file_path: str,
                              line_number: int) -> List[TypeIssue]:
        """验证类型注解的正确性"""
        issues = []
        
        try:
            # 检查是否为有效类型
            annotation_str = ast.unparse(annotation)
            
            # 检查是否使用了Any类型
            if 'Any' in annotation_str:
                issues.append(TypeIssue(
                    file_path=file_path,
                    line_number=line_number,
                    function_name=function_name,
                    issue_type=TypeAnnotationQuality.PARTIAL,
                    expected_type="具体类型",
                    actual_type=annotation_str,
                    description=f"函数 {function_name} 使用了Any类型",
                    suggestion="使用具体的类型代替Any，提高类型安全性"
                ))
            
            # 检查是否使用了不推荐的类型
            if 'typing.' in annotation_str:
                type_name = annotation_str.split('.')[-1]
                if type_name in ['List', 'Dict', 'Tuple', 'Set']:
                    issues.append(TypeIssue(
                        file_path=file_path,
                        line_number=line_number,
                        function_name=function_name,
                        issue_type=TypeAnnotationQuality.PARTIAL,
                        expected_type="泛型类型",
                        actual_type=annotation_str,
                        description=f"函数 {function_name} 使用了旧式泛型类型",
                        suggestion=f"使用新式泛型类型，如: list[Type] 代替 List[Type]"
                    ))
        
        except Exception as e:
            logger.debug(f"类型注解验证失败: {e}")
        
        return issues
    
    def _calculate_type_coverage(self, tree: ast.AST, 
                              file_path: str) -> TypeCoverage:
        """计算类型覆盖率"""
        total_functions = 0
        annotated_functions = 0
        missing_annotations = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                total_functions += 1
                
                # 检查是否有返回类型注解
                if node.returns is not None:
                    annotated_functions += 1
                else:
                    missing_annotations.append(node.name)
        
        coverage_rate = (annotated_functions / total_functions * 100) if total_functions > 0 else 0
        
        return TypeCoverage(
            file_path=file_path,
            total_functions=total_functions,
            annotated_functions=annotated_functions,
            coverage_rate=coverage_rate,
            missing_annotations=missing_annotations
        )
    
    def check_directory(self, directory: str, 
                     pattern: str = "*.py") -> Dict[str, Any]:
        """检查整个目录的类型注解
        
        Args:
            directory: 目录路径
            pattern: 文件匹配模式
        
        Returns:
            检查结果汇总
        """
        results = {
            'total_files': 0,
            'checked_files': 0,
            'total_functions': 0,
            'total_annotated': 0,
            'average_coverage': 0.0,
            'total_issues': 0,
            'file_results': []
        }
        
        directory_path = Path(directory)
        python_files = list(directory_path.glob(pattern))
        
        for file_path in python_files:
            result = self.check_file(str(file_path))
            
            if 'error' not in result:
                results['checked_files'] += 1
                results['total_functions'] += result['coverage'].total_functions
                results['total_annotated'] += result['coverage'].annotated_functions
                results['total_issues'] += result['total_issues']
                results['file_results'].append(result)
                
                if 'coverage_rate' in result:
                    results['average_coverage'] += result['coverage_rate']
            
            results['total_files'] += 1
        
        # 计算平均覆盖率
        if results['checked_files'] > 0:
            results['average_coverage'] = (
                results['average_coverage'] / results['checked_files']
            )
        
        return results
    
    def get_issues(self, issue_type: Optional[TypeAnnotationQuality] = None,
                  limit: int = 100) -> List[TypeIssue]:
        """获取类型问题列表"""
        if issue_type:
            return [issue for issue in self._issues 
                   if issue.issue_type == issue_type][:limit]
        return self._issues[:limit]
    
    def get_coverage_stats(self) -> List[TypeCoverage]:
        """获取覆盖率统计"""
        return self._coverage.copy()
    
    def clear_results(self):
        """清空检查结果"""
        self._issues.clear()
        self._coverage.clear()
        logger.info("类型检查结果已清空")


class TypeAnnotationGenerator:
    """类型注解生成器"""
    
    def __init__(self):
        self._generated_annotations: Dict[str, List[str]] = {}
    
    @monitor_performance(threshold_warning=1.0, threshold_critical=5.0)
    def generate_annotations_for_file(self, file_path: str) -> Dict[str, Any]:
        """为文件生成类型注解
        
        Args:
            file_path: 文件路径
        
        Returns:
            生成的类型注解
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析AST
            tree = ast.parse(content)
            
            # 生成类型注解
            annotations = self._generate_annotations(tree, file_path)
            
            result = {
                'file_path': file_path,
                'annotations': annotations,
                'total_functions': len(annotations),
                'annotated_functions': sum(1 for ann in annotations.values() if ann)
            }
            
            self._generated_annotations[file_path] = annotations
            
            return result
            
        except Exception as e:
            logger.error(f"类型注解生成失败: {file_path} - {e}")
            return {
                'file_path': file_path,
                'error': str(e)
            }
    
    def _generate_annotations(self, tree: ast.AST, 
                          file_path: str) -> Dict[str, List[str]]:
        """生成类型注解"""
        annotations = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 分析函数签名
                func_annotations = self._analyze_function_signature(node)
                annotations[node.name] = func_annotations
        
        return annotations
    
    def _analyze_function_signature(self, node: ast.FunctionDef) -> List[str]:
        """分析函数签名并生成类型注解建议"""
        annotations = []
        
        # 分析参数
        for arg in node.args.args:
            param_type = self._infer_parameter_type(arg, node)
            if param_type:
                annotations.append(f"{arg.arg}: {param_type}")
        
        # 分析返回类型
        return_type = self._infer_return_type(node)
        if return_type:
            annotations.append(f"-> {return_type}")
        
        return annotations
    
    def _infer_parameter_type(self, arg: ast.arg, 
                             func_node: ast.FunctionDef) -> Optional[str]:
        """推断参数类型"""
        # 检查默认值
        if arg.default:
            return self._infer_type_from_value(arg.default)
        
        # 检查参数名模式
        param_name = arg.arg.lower()
        
        # 常见参数类型推断
        if 'path' in param_name or 'file' in param_name:
            return "str"
        elif 'count' in param_name or 'num' in param_name:
            return "int"
        elif 'name' in param_name or 'text' in param_name:
            return "str"
        elif 'data' in param_name or 'content' in param_name:
            return "Any"
        elif 'enabled' in param_name or 'flag' in param_name:
            return "bool"
        
        return None
    
    def _infer_return_type(self, node: ast.FunctionDef) -> Optional[str]:
        """推断返回类型"""
        if not node.body:
            return "None"
        
        # 检查函数体中的return语句
        return_statements = []
        for stmt in ast.walk(node.body):
            if isinstance(stmt, ast.Return):
                if stmt.value:
                    return_type = self._infer_type_from_value(stmt.value)
                    if return_type:
                        return_statements.append(return_type)
        
        # 如果有多个返回类型，使用Union
        if return_statements:
            unique_types = list(set(return_statements))
            if len(unique_types) == 1:
                return unique_types[0]
            elif len(unique_types) > 1:
                return f"Union[{', '.join(unique_types)}]"
        
        return None
    
    def _infer_type_from_value(self, value: ast.AST) -> Optional[str]:
        """从值推断类型"""
        if isinstance(value, ast.Constant):
            if isinstance(value.value, bool):
                return "bool"
            elif isinstance(value.value, int):
                return "int"
            elif isinstance(value.value, float):
                return "float"
            elif isinstance(value.value, str):
                return "str"
            elif value.value is None:
                return "None"
        
        elif isinstance(value, ast.List):
            return "List[Any]"
        
        elif isinstance(value, ast.Dict):
            return "Dict[str, Any]"
        
        elif isinstance(value, ast.Call):
            # 检查函数调用
            if isinstance(value.func, ast.Name):
                func_name = value.func.id
                
                # 常见函数返回类型
                if func_name in ['len', 'size']:
                    return "int"
                elif func_name in ['str', 'int', 'float', 'bool']:
                    return func_name.capitalize()
                elif func_name in ['list', 'dict', 'set', 'tuple']:
                    return func_name.capitalize() + "[Any]"
        
        return None
    
    def generate_annotations_for_directory(self, directory: str,
                                     pattern: str = "*.py") -> Dict[str, Any]:
        """为目录生成类型注解
        
        Args:
            directory: 目录路径
            pattern: 文件匹配模式
        
        Returns:
            生成结果汇总
        """
        results = {
            'total_files': 0,
            'processed_files': 0,
            'total_functions': 0,
            'total_annotated': 0,
            'file_results': []
        }
        
        directory_path = Path(directory)
        python_files = list(directory_path.glob(pattern))
        
        for file_path in python_files:
            result = self.generate_annotations_for_file(str(file_path))
            
            if 'error' not in result:
                results['processed_files'] += 1
                results['total_functions'] += result['total_functions']
                results['total_annotated'] += result['annotated_functions']
                results['file_results'].append(result)
            
            results['total_files'] += 1
        
        return results
    
    def get_generated_annotations(self, file_path: str) -> Optional[List[str]]:
        """获取生成的类型注解"""
        return self._generated_annotations.get(file_path)
    
    def clear_cache(self):
        """清空缓存"""
        self._generated_annotations.clear()
        logger.info("类型注解生成缓存已清空")


# 全局实例
_global_type_checker: Optional[TypeChecker] = None
_global_type_annotation_generator: Optional[TypeAnnotationGenerator] = None


def get_type_checker() -> TypeChecker:
    """获取全局类型检查器"""
    global _global_type_checker
    
    if _global_type_checker is None:
        _global_type_checker = TypeChecker()
    
    return _global_type_checker


def get_type_annotation_generator() -> TypeAnnotationGenerator:
    """获取全局类型注解生成器"""
    global _global_type_annotation_generator
    
    if _global_type_annotation_generator is None:
        _global_type_annotation_generator = TypeAnnotationGenerator()
    
    return _global_type_annotation_generator


def check_project_types(directory: str = "app/core") -> Dict[str, Any]:
    """检查项目类型注解（便捷函数）"""
    checker = get_type_checker()
    return checker.check_directory(directory)


def generate_type_annotations(directory: str = "app/core") -> Dict[str, Any]:
    """生成项目类型注解（便捷函数）"""
    generator = get_type_annotation_generator()
    return generator.generate_annotations_for_directory(directory)