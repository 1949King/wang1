"""
代码重构工具模块
================
提供代码重构的工具和辅助函数
"""

import ast
import inspect
import logging
from typing import Dict, Any, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re

from app.core.logging_enhanced import monitor_performance
from app.core.exceptions import ConfigurationError, ErrorCode

logger = logging.getLogger(__name__)


class RefactoringType(Enum):
    """重构类型"""
    EXTRACT_METHOD = "extract_method"
    EXTRACT_CLASS = "extract_class"
    RENAME_VARIABLE = "rename_variable"
    RENAME_FUNCTION = "rename_function"
    SIMPLIFY_CONDITION = "simplify_condition"
    REDUCE_COMPLEXITY = "reduce_complexity"
    REMOVE_DUPLICATE = "remove_duplicate"
    IMPROVE_NAMING = "improve_naming"


class CodeQuality(Enum):
    """代码质量等级"""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


@dataclass
class CodeIssue:
    """代码问题"""
    file_path: str
    line_number: int
    issue_type: str
    severity: CodeQuality
    description: str
    suggestion: str
    code_snippet: str


@dataclass
class RefactoringSuggestion:
    """重构建议"""
    file_path: str
    line_number: int
    refactoring_type: RefactoringType
    description: str
    current_code: str
    suggested_code: str
    complexity_reduction: int = 0
    readability_improvement: int = 0


class CodeAnalyzer:
    """代码分析器"""
    
    def __init__(self):
        self._issues: List[CodeIssue] = []
        self._suggestions: List[RefactoringSuggestion] = []
        self._metrics: Dict[str, Any] = {}
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """分析单个文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            分析结果字典
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 分析代码质量
            issues = self._analyze_code_quality(content, file_path)
            
            # 分析复杂度
            complexity_metrics = self._analyze_complexity(content, file_path)
            
            # 分析命名规范
            naming_issues = self._analyze_naming(content, file_path)
            
            # 生成重构建议
            suggestions = self._generate_refactoring_suggestions(content, file_path)
            
            result = {
                'file_path': file_path,
                'issues': issues,
                'complexity_metrics': complexity_metrics,
                'naming_issues': naming_issues,
                'suggestions': suggestions,
                'overall_score': self._calculate_overall_score(
                    issues, complexity_metrics, naming_issues
                )
            }
            
            self._issues.extend(issues)
            self._suggestions.extend(suggestions)
            self._metrics[file_path] = result
            
            return result
            
        except Exception as e:
            logger.error(f"文件分析失败: {file_path} - {e}")
            return {
                'file_path': file_path,
                'error': str(e)
            }
    
    def _analyze_code_quality(self, content: str, file_path: str) -> List[CodeIssue]:
        """分析代码质量"""
        issues = []
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, start=1):
            # 检查行长度
            if len(line) > 120:
                issues.append(CodeIssue(
                    file_path=file_path,
                    line_number=line_num,
                    issue_type="line_too_long",
                    severity=CodeQuality.FAIR,
                    description=f"行长度超过120字符: {len(line)}",
                    suggestion="将长行拆分为多行",
                    code_snippet=line.strip()[:100]
                ))
            
            # 检查复杂表达式
            if len(line) > 200 and ';' in line:
                issues.append(CodeIssue(
                    file_path=file_path,
                    line_number=line_num,
                    issue_type="complex_expression",
                    severity=CodeQuality.POOR,
                    description="复杂表达式，建议拆分",
                    suggestion="将复杂表达式拆分为多个简单表达式",
                    code_snippet=line.strip()[:100]
                ))
            
            # 检查魔法数字
            magic_numbers = re.findall(r'\b\d{3,}\b', line)
            if magic_numbers:
                issues.append(CodeIssue(
                    file_path=file_path,
                    line_number=line_num,
                    issue_type="magic_number",
                    severity=CodeQuality.FAIR,
                    description=f"发现魔法数字: {magic_numbers}",
                    suggestion="将魔法数字定义为常量",
                    code_snippet=line.strip()[:100]
                ))
        
        return issues
    
    def _analyze_complexity(self, content: str, file_path: str) -> Dict[str, Any]:
        """分析代码复杂度"""
        try:
            tree = ast.parse(content)
            
            complexity_metrics = {
                'total_functions': 0,
                'total_classes': 0,
                'avg_function_length': 0,
                'max_function_length': 0,
                'complex_functions': [],
                'total_complexity': 0
            }
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    complexity_metrics['total_functions'] += 1
                    
                    # 计算函数长度
                    func_length = node.end_lineno - node.lineno
                    complexity_metrics['avg_function_length'] += func_length
                    complexity_metrics['max_function_length'] = max(
                        complexity_metrics['max_function_length'],
                        func_length
                    )
                    
                    # 计算圈复杂度
                    complexity = self._calculate_cyclomatic_complexity(node)
                    complexity_metrics['total_complexity'] += complexity
                    
                    if complexity > 10:
                        complexity_metrics['complex_functions'].append({
                            'name': node.name,
                            'line': node.lineno,
                            'complexity': complexity
                        })
                
                elif isinstance(node, ast.ClassDef):
                    complexity_metrics['total_classes'] += 1
            
            # 计算平均函数长度
            if complexity_metrics['total_functions'] > 0:
                complexity_metrics['avg_function_length'] = (
                    complexity_metrics['avg_function_length'] / 
                    complexity_metrics['total_functions']
                )
            
            return complexity_metrics
            
        except SyntaxError:
            logger.warning(f"文件语法错误，无法分析复杂度: {file_path}")
            return {
                'error': 'syntax_error'
            }
    
    def _calculate_cyclomatic_complexity(self, node: ast.FunctionDef) -> int:
        """计算圈复杂度"""
        complexity = 1
        
        for child in ast.walk(node.body):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        
        return complexity
    
    def _analyze_naming(self, content: str, file_path: str) -> List[CodeIssue]:
        """分析命名规范"""
        issues = []
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                # 检查函数命名
                if isinstance(node, ast.FunctionDef):
                    if not self._is_snake_case(node.name):
                        issues.append(CodeIssue(
                            file_path=file_path,
                            line_number=node.lineno,
                            issue_type="naming_convention",
                            severity=CodeQuality.FAIR,
                            description=f"函数名不符合蛇形命名法: {node.name}",
                            suggestion="使用蛇形命名法，如: my_function",
                            code_snippet=f"def {node.name}(...)"
                        ))
                
                # 检查变量命名
                elif isinstance(node, ast.Name):
                    if not self._is_snake_case(node.id):
                        issues.append(CodeIssue(
                            file_path=file_path,
                            line_number=node.lineno,
                            issue_type="naming_convention",
                            severity=CodeQuality.FAIR,
                            description=f"变量名不符合蛇形命名法: {node.id}",
                            suggestion="使用蛇形命名法，如: my_variable",
                            code_snippet=node.id
                        ))
                
                # 检查类命名
                elif isinstance(node, ast.ClassDef):
                    if not self._is_pascal_case(node.name):
                        issues.append(CodeIssue(
                            file_path=file_path,
                            line_number=node.lineno,
                            issue_type="naming_convention",
                            severity=CodeQuality.FAIR,
                            description=f"类名不符合帕斯卡命名法: {node.name}",
                            suggestion="使用帕斯卡命名法，如: MyClass",
                            code_snippet=f"class {node.name}:"
                        ))
        
        except SyntaxError:
            logger.warning(f"文件语法错误，无法分析命名: {file_path}")
        
        return issues
    
    def _is_snake_case(self, name: str) -> bool:
        """检查是否为蛇形命名法"""
        return re.match(r'^[a-z_][a-z0-9_]*$', name) is not None
    
    def _is_pascal_case(self, name: str) -> bool:
        """检查是否为帕斯卡命名法"""
        return re.match(r'^[A-Z][a-zA-Z0-9]*$', name) is not None
    
    def _generate_refactoring_suggestions(self, content: str, 
                                    file_path: str) -> List[RefactoringSuggestion]:
        """生成重构建议"""
        suggestions = []
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                # 检查长函数
                if isinstance(node, ast.FunctionDef):
                    func_length = node.end_lineno - node.lineno
                    if func_length > 50:
                        suggestions.append(RefactoringSuggestion(
                            file_path=file_path,
                            line_number=node.lineno,
                            refactoring_type=RefactoringType.EXTRACT_METHOD,
                            description=f"函数过长 ({func_length} 行)，建议拆分",
                            current_code=f"def {node.name}(...):",
                            suggested_code="# 将函数拆分为多个小函数",
                            complexity_reduction=func_length // 10,
                            readability_improvement=3
                        ))
                
                # 检查复杂条件
                elif isinstance(node, ast.If):
                    if self._is_complex_condition(node.test):
                        suggestions.append(RefactoringSuggestion(
                            file_path=file_path,
                            line_number=node.lineno,
                            refactoring_type=RefactoringType.SIMPLIFY_CONDITION,
                            description="条件过于复杂，建议简化",
                            current_code=ast.unparse(node.test).strip(),
                            suggested_code="# 将复杂条件拆分为多个简单条件",
                            complexity_reduction=2,
                            readability_improvement=2
                        ))
                
                # 检查重复代码
                elif isinstance(node, ast.For):
                    if self._has_duplicate_logic(node):
                        suggestions.append(RefactoringSuggestion(
                            file_path=file_path,
                            line_number=node.lineno,
                            refactoring_type=RefactoringType.REMOVE_DUPLICATE,
                            description="发现重复逻辑，建议提取为函数",
                            current_code=ast.unparse(node).strip(),
                            suggested_code="# 将重复逻辑提取为独立函数",
                            complexity_reduction=5,
                            readability_improvement=2
                        ))
        
        except SyntaxError:
            logger.warning(f"文件语法错误，无法生成建议: {file_path}")
        
        return suggestions
    
    def _is_complex_condition(self, node: ast.AST) -> bool:
        """检查是否为复杂条件"""
        if isinstance(node, ast.BoolOp):
            return len(node.values) > 3
        return False
    
    def _has_duplicate_logic(self, node: ast.For) -> bool:
        """检查是否有重复逻辑"""
        return len(node.body) > 10
    
    def _calculate_overall_score(self, issues: List[CodeIssue],
                              complexity_metrics: Dict[str, Any],
                              naming_issues: List[CodeIssue]) -> float:
        """计算总体得分"""
        score = 100.0
        
        # 根据问题严重程度扣分
        severity_weights = {
            CodeQuality.EXCELLENT: 0,
            CodeQuality.GOOD: -2,
            CodeQuality.FAIR: -5,
            CodeQuality.POOR: -10,
            CodeQuality.CRITICAL: -20
        }
        
        for issue in issues:
            score += severity_weights.get(issue.severity, -5)
        
        # 根据复杂度扣分
        if 'total_complexity' in complexity_metrics:
            avg_complexity = (
                complexity_metrics['total_complexity'] / 
                max(complexity_metrics['total_functions'], 1)
            )
            if avg_complexity > 10:
                score -= 10
            elif avg_complexity > 5:
                score -= 5
        
        # 根据命名问题扣分
        score -= len(naming_issues) * 2
        
        return max(0, min(100, score))
    
    def analyze_directory(self, directory: str, 
                     pattern: str = "*.py") -> Dict[str, Any]:
        """分析整个目录
        
        Args:
            directory: 目录路径
            pattern: 文件匹配模式
        
        Returns:
            分析结果汇总
        """
        results = {
            'total_files': 0,
            'analyzed_files': 0,
            'total_issues': 0,
            'total_suggestions': 0,
            'average_score': 0.0,
            'file_results': []
        }
        
        directory_path = Path(directory)
        python_files = list(directory_path.glob(pattern))
        
        for file_path in python_files:
            result = self.analyze_file(str(file_path))
            
            if 'error' not in result:
                results['analyzed_files'] += 1
                results['total_issues'] += len(result['issues'])
                results['total_suggestions'] += len(result['suggestions'])
                results['file_results'].append(result)
                
                if 'overall_score' in result:
                    results['average_score'] += result['overall_score']
            
            results['total_files'] += 1
        
        # 计算平均得分
        if results['analyzed_files'] > 0:
            results['average_score'] = (
                results['average_score'] / results['analyzed_files']
            )
        
        return results
    
    def get_issues(self, severity: Optional[CodeQuality] = None,
                  limit: int = 100) -> List[CodeIssue]:
        """获取代码问题列表"""
        if severity:
            return [issue for issue in self._issues 
                   if issue.severity == severity][:limit]
        return self._issues[:limit]
    
    def get_suggestions(self, refactoring_type: Optional[RefactoringType] = None,
                       limit: int = 100) -> List[RefactoringSuggestion]:
        """获取重构建议列表"""
        if refactoring_type:
            return [suggestion for suggestion in self._suggestions 
                   if suggestion.refactoring_type == refactoring_type][:limit]
        return self._suggestions[:limit]
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取分析指标"""
        return self._metrics.copy()
    
    def clear_results(self):
        """清空分析结果"""
        self._issues.clear()
        self._suggestions.clear()
        self._metrics.clear()
        logger.info("代码分析结果已清空")


class CodeRefactor:
    """代码重构器"""
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._refactoring_log: List[Dict[str, Any]] = []
        self._analyzer = CodeAnalyzer()
    
    @monitor_performance(threshold_warning=2.0, threshold_critical=10.0)
    def refactor_file(self, file_path: str, 
                   suggestions: List[RefactoringSuggestion]) -> bool:
        """重构文件
        
        Args:
            file_path: 文件路径
            suggestions: 重构建议列表
        
        Returns:
            是否重构成功
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 应用重构
            modified_content = self._apply_refactoring(content, suggestions)
            
            # 记录重构操作
            refactoring_log = {
                'file_path': file_path,
                'suggestions_applied': len(suggestions),
                'dry_run': self.dry_run,
                'timestamp': time.time()
            }
            self._refactoring_log.append(refactoring_log)
            
            if not self.dry_run:
                # 备份原文件
                self._backup_file(file_path)
                
                # 写入重构后的内容
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                
                logger.info(f"文件重构完成: {file_path}")
            else:
                logger.info(f"文件重构预览（dry run）: {file_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"文件重构失败: {file_path} - {e}")
            raise ConfigurationError(
                ErrorCode.INVALID_PARAMETER,
                f"文件重构失败: {str(e)}",
                details={'file_path': file_path}
            )
    
    def _apply_refactoring(self, content: str, 
                       suggestions: List[RefactoringSuggestion]) -> str:
        """应用重构建议"""
        lines = content.split('\n')
        modified_lines = lines.copy()
        
        for suggestion in suggestions:
            # 这里可以实现具体的重构逻辑
            # 简化版本：记录建议但不实际修改
            pass
        
        return '\n'.join(modified_lines)
    
    def _backup_file(self, file_path: str):
        """备份文件"""
        import shutil
        from datetime import datetime
        
        backup_path = f"{file_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(file_path, backup_path)
        
        logger.info(f"文件已备份: {backup_path}")
    
    def refactor_directory(self, directory: str, 
                      pattern: str = "*.py") -> Dict[str, Any]:
        """重构目录
        
        Args:
            directory: 目录路径
            pattern: 文件匹配模式
        
        Returns:
            重构结果汇总
        """
        results = {
            'total_files': 0,
            'refactored_files': 0,
            'failed_files': 0,
            'total_suggestions_applied': 0,
            'file_results': []
        }
        
        # 分析目录
        analysis_results = self._analyzer.analyze_directory(directory, pattern)
        
        # 对每个文件应用重构
        for file_result in analysis_results['file_results']:
            file_path = file_result['file_path']
            
            if 'suggestions' in file_result:
                try:
                    success = self.refactor_file(file_path, file_result['suggestions'])
                    
                    if success:
                        results['refactored_files'] += 1
                        results['total_suggestions_applied'] += len(file_result['suggestions'])
                    else:
                        results['failed_files'] += 1
                    
                    results['file_results'].append({
                        'file_path': file_path,
                        'success': success,
                        'suggestions_count': len(file_result.get('suggestions', []))
                    })
                    
                except Exception as e:
                    logger.error(f"文件重构异常: {file_path} - {e}")
                    results['failed_files'] += 1
            
            results['total_files'] += 1
        
        return results
    
    def get_refactoring_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取重构日志"""
        return self._refactoring_log[-limit:]
    
    def clear_log(self):
        """清空重构日志"""
        self._refactoring_log.clear()
        logger.info("重构日志已清空")


# 全局实例
_global_code_analyzer: Optional[CodeAnalyzer] = None
_global_code_refactor: Optional[CodeRefactor] = None


def get_code_analyzer() -> CodeAnalyzer:
    """获取全局代码分析器"""
    global _global_code_analyzer
    
    if _global_code_analyzer is None:
        _global_code_analyzer = CodeAnalyzer()
    
    return _global_code_analyzer


def get_code_refactor(dry_run: bool = True) -> CodeRefactor:
    """获取全局代码重构器"""
    global _global_code_refactor
    
    if _global_code_refactor is None:
        _global_code_refactor = CodeRefactor(dry_run)
    
    return _global_code_refactor


def analyze_project_code(directory: str = "app/core") -> Dict[str, Any]:
    """分析项目代码（便捷函数）"""
    analyzer = get_code_analyzer()
    return analyzer.analyze_directory(directory)


import time