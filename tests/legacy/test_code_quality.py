#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
代码质量检查脚本
检查代码规范性、复杂度、注释覆盖率等
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

class CodeQualityChecker:
    def __init__(self):
        self.results = {
            'files_checked': 0,
            'total_lines': 0,
            'comment_lines': 0,
            'docstring_functions': 0,
            'total_functions': 0,
            'docstring_classes': 0,
            'total_classes': 0,
            'issues': [],
            'warnings': []
        }
    
    def check_file(self, file_path: str) -> Dict:
        """检查单个文件的质量"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 统计代码行数
            lines = content.split('\n')
            self.results['total_lines'] += len(lines)
            self.results['files_checked'] += 1
            
            # 统计注释行数
            comment_lines = 0
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                    comment_lines += 1
            self.results['comment_lines'] += comment_lines
            
            # 解析AST
            tree = ast.parse(content)
            
            # 统计函数和类
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self.results['total_functions'] += 1
                    if ast.get_docstring(node):
                        self.results['docstring_functions'] += 1
                elif isinstance(node, ast.ClassDef):
                    self.results['total_classes'] += 1
                    if ast.get_docstring(node):
                        self.results['docstring_classes'] += 1
            
            # 检查代码问题
            self._check_code_issues(tree, file_path)
            
            return {
                'file': file_path,
                'lines': len(lines),
                'comment_lines': comment_lines,
                'comment_ratio': comment_lines / len(lines) if len(lines) > 0 else 0
            }
        except Exception as e:
            self.results['issues'].append({
                'file': file_path,
                'type': 'error',
                'message': f"无法解析文件: {str(e)}"
            })
            return None
    
    def _check_code_issues(self, tree: ast.AST, file_path: str):
        """检查代码问题"""
        for node in ast.walk(tree):
            # 检查函数复杂度
            if isinstance(node, ast.FunctionDef):
                complexity = self._calculate_complexity(node)
                if complexity > 10:
                    self.results['warnings'].append({
                        'file': file_path,
                        'type': 'complexity',
                        'function': node.name,
                        'complexity': complexity,
                        'message': f"函数 '{node.name}' 复杂度过高 ({complexity})"
                    })
                
                # 检查函数长度
                if hasattr(node, 'end_lineno') and node.end_lineno:
                    func_length = node.end_lineno - node.lineno
                    if func_length > 50:
                        self.results['warnings'].append({
                            'file': file_path,
                            'type': 'length',
                            'function': node.name,
                            'length': func_length,
                            'message': f"函数 '{node.name}' 过长 ({func_length} 行)"
                        })
            
            # 检查类的方法数量
            if isinstance(node, ast.ClassDef):
                methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                if len(methods) > 20:
                    self.results['warnings'].append({
                        'file': file_path,
                        'type': 'class_size',
                        'class': node.name,
                        'methods': len(methods),
                        'message': f"类 '{node.name}' 方法过多 ({len(methods)} 个)"
                    })
    
    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """计算圈复杂度"""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity
    
    def check_directory(self, directory: str, pattern: str = "*.py") -> List[Dict]:
        """检查目录中的所有Python文件"""
        file_results = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    result = self.check_file(file_path)
                    if result:
                        file_results.append(result)
        return file_results
    
    def generate_report(self) -> str:
        """生成质量报告"""
        report = []
        report.append("=" * 60)
        report.append("代码质量检查报告")
        report.append("=" * 60)
        
        # 基本统计
        report.append(f"\n基本统计:")
        report.append(f"  检查文件数: {self.results['files_checked']}")
        report.append(f"  总代码行数: {self.results['total_lines']}")
        report.append(f"  注释行数: {self.results['comment_lines']}")
        
        if self.results['total_lines'] > 0:
            comment_ratio = (self.results['comment_lines'] / self.results['total_lines']) * 100
            report.append(f"  注释覆盖率: {comment_ratio:.2f}%")
        
        # 函数统计
        if self.results['total_functions'] > 0:
            func_doc_ratio = (self.results['docstring_functions'] / self.results['total_functions']) * 100
            report.append(f"\n函数统计:")
            report.append(f"  总函数数: {self.results['total_functions']}")
            report.append(f"  有文档字符串的函数: {self.results['docstring_functions']}")
            report.append(f"  文档覆盖率: {func_doc_ratio:.2f}%")
        
        # 类统计
        if self.results['total_classes'] > 0:
            class_doc_ratio = (self.results['docstring_classes'] / self.results['total_classes']) * 100
            report.append(f"\n类统计:")
            report.append(f"  总类数: {self.results['total_classes']}")
            report.append(f"  有文档字符串的类: {self.results['docstring_classes']}")
            report.append(f"  文档覆盖率: {class_doc_ratio:.2f}%")
        
        # 问题统计
        if self.results['issues']:
            report.append(f"\n严重问题 ({len(self.results['issues'])}):")
            for issue in self.results['issues'][:10]:  # 只显示前10个
                report.append(f"  - {Path(issue['file']).name}: {issue['message']}")
        
        # 警告统计
        if self.results['warnings']:
            report.append(f"\n警告 ({len(self.results['warnings'])}):")
            for warning in self.results['warnings'][:10]:  # 只显示前10个
                report.append(f"  - {Path(warning['file']).name}: {warning['message']}")
        
        # 评分
        report.append(f"\n质量评分:")
        score = self._calculate_score()
        report.append(f"  总体评分: {score}/100")
        
        if score >= 90:
            report.append(f"  评级: 优秀")
        elif score >= 80:
            report.append(f"  评级: 良好")
        elif score >= 70:
            report.append(f"  评级: 中等")
        elif score >= 60:
            report.append(f"  评级: 及格")
        else:
            report.append(f"  评级: 需要改进")
        
        return '\n'.join(report)
    
    def _calculate_score(self) -> int:
        """计算质量评分"""
        score = 100
        
        # 注释覆盖率扣分
        if self.results['total_lines'] > 0:
            comment_ratio = (self.results['comment_lines'] / self.results['total_lines']) * 100
            if comment_ratio < 10:
                score -= 20
            elif comment_ratio < 20:
                score -= 10
        
        # 文档覆盖率扣分
        if self.results['total_functions'] > 0:
            func_doc_ratio = (self.results['docstring_functions'] / self.results['total_functions']) * 100
            if func_doc_ratio < 50:
                score -= 15
            elif func_doc_ratio < 70:
                score -= 5
        
        # 严重问题扣分
        score -= len(self.results['issues']) * 5
        
        # 警告扣分
        score -= min(len(self.results['warnings']) * 2, 20)
        
        return max(0, score)

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='代码质量检查工具')
    parser.add_argument('directory', help='要检查的目录路径')
    args = parser.parse_args()
    
    checker = CodeQualityChecker()
    
    print(f"正在检查目录: {args.directory}")
    print("-" * 60)
    
    # 检查核心模块
    core_dir = os.path.join(args.directory, 'app', 'core')
    if os.path.exists(core_dir):
        print("\n检查核心模块...")
        checker.check_directory(core_dir)
    
    # 检查视频编辑模块
    lego_dir = os.path.join(args.directory, 'app', 'modules', 'lego')
    if os.path.exists(lego_dir):
        print("检查视频编辑模块...")
        checker.check_directory(lego_dir)
    
    # 生成报告
    print("\n" + checker.generate_report())
    
    return 0

if __name__ == "__main__":
    sys.exit(main())