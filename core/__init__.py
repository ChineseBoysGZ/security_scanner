"""
core/__init__.py
"""

# core包初始化文件 - 补全正则相关函数导入，适配regex_page
from .file_scanner import (
    compile_patterns,
    scan_files,
    SCAN_STOPPED,
    SCAN_PAUSED
)
from .models import ScanResult
from .excel_exporter import export_excel
# 关键补充：从regex_manager导入实际存在的正则校验/测试函数
from .regex_manager import validate_regex, test_regex

# 对外暴露的核心接口（补全正则相关函数）
__all__ = [
    # file_scanner 核心函数/全局变量
    "compile_patterns",
    "scan_files",
    "SCAN_STOPPED",
    "SCAN_PAUSED",
    # models 核心模型
    "ScanResult",
    # excel_exporter 导出函数
    "export_excel",
    # regex_manager 正则校验/测试函数（适配regex_page）
    "validate_regex",
    "test_regex"
]