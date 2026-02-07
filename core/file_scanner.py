"""
core/file_scanner.py - 兼容层
包装新的ScannerEngine，提供与原有代码完全兼容的接口。
这样UI代码无需任何修改即可使用优化后的引擎。
"""
import os
import re
import time
from typing import List, Dict, Callable, Optional, Tuple
from pathlib import Path

from .scanner_engine import ScannerEngine
from .scan_models import ScanContext, ScanResult, ScanConfig
from .regex_manager import compile_patterns as compile_patterns_orig
from config.constants import SKIP_EXTENSIONS, DEFAULT_MAX_FILE_SIZE_MB
from utils.log_utils import logger

# ---------- 保持与原有代码完全兼容的接口 ----------

# 全局变量（为了兼容，但不建议新代码使用）
SCAN_STOPPED = False
SCAN_PAUSED = False

def _is_stopped(stop_event=None) -> bool:
    """线程安全判断是否应停止扫描（兼容原有代码）"""
    return SCAN_STOPPED

def _is_paused(pause_event=None) -> bool:
    """线程安全判断是否处于暂停（兼容原有代码）"""
    return SCAN_PAUSED

def extract_app_id(file_path: str) -> str:
    """从文件路径中提取应用ID（兼容原有代码）"""
    pattern = re.compile(r'online[\\/](.*?)_all_all', re.IGNORECASE)
    match = pattern.search(file_path)
    return match.group(1).strip() if match else ""

def _filter_file(file_path: str, max_file_size_mb: int, skip_counters: dict) -> bool:
    """过滤文件（兼容原有代码，但使用新的智能判断）"""
    from .file_reader import should_skip_file
    
    max_file_size_bytes = max_file_size_mb * 1024 * 1024
    skip, reason = should_skip_file(Path(file_path), set(SKIP_EXTENSIONS), max_file_size_bytes)
    
    if skip:
        # 更新跳过计数器（为了兼容）
        if "跳过后缀" in reason:
            skip_counters["badsuffix"] += 1
        elif "文件过大" in reason:
            skip_counters["oversize"] += 1
        else:
            skip_counters["other"] += 1
        return False
    
    return True

def _scan_single_file(file_path: str, compiled_patterns: dict) -> List[ScanResult]:
    """扫描单个文件（兼容原有代码，但使用新的引擎）"""
    # 创建临时上下文和引擎
    ctx = ScanContext()
    engine = ScannerEngine(ctx)
    
    # 准备配置
    config = ScanConfig(
        scan_paths=[file_path],
        patterns={name: pattern.pattern for name, pattern in compiled_patterns.items()},
        max_file_size_mb=DEFAULT_MAX_FILE_SIZE_MB
    )
    
    # 扫描文件
    if engine.prepare(config):
        return engine._scan_file_content(Path(file_path))
    
    return []

def compile_patterns(patterns_dict: dict) -> dict:
    """编译正则表达式（直接使用原有函数）"""
    return compile_patterns_orig(patterns_dict)

def count_valid_files(scan_paths: list, max_file_size_mb: int, skip_counters: dict) -> int:
    """统计有效文件数（兼容原有代码，但使用新的智能判断）"""
    from .file_reader import should_skip_file
    
    total_valid = 0
    max_file_size_bytes = max_file_size_mb * 1024 * 1024
    
    for path_str in scan_paths:
        if SCAN_STOPPED:
            break
            
        path = Path(path_str).resolve()
        if not path.exists():
            continue
        
        if path.is_file():
            # 单个文件
            skip, reason = should_skip_file(path, set(SKIP_EXTENSIONS), max_file_size_bytes)
            if not skip:
                total_valid += 1
            else:
                # 更新跳过计数器
                if "跳过后缀" in reason:
                    skip_counters["badsuffix"] += 1
                elif "文件过大" in reason:
                    skip_counters["oversize"] += 1
                else:
                    skip_counters["other"] += 1
            continue
        
        # 目录：递归统计
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if SCAN_STOPPED:
                        break
                    
                    if entry.is_dir(follow_symlinks=False):
                        # 递归统计子目录
                        sub_total = count_valid_files(
                            [entry.path], max_file_size_mb, skip_counters
                        )
                        total_valid += sub_total
                        
                    elif entry.is_file(follow_symlinks=False):
                        file_path = Path(entry.path)
                        skip, reason = should_skip_file(
                            file_path, set(SKIP_EXTENSIONS), max_file_size_bytes
                        )
                        
                        if not skip:
                            total_valid += 1
                        else:
                            if "跳过后缀" in reason:
                                skip_counters["badsuffix"] += 1
                            elif "文件过大" in reason:
                                skip_counters["oversize"] += 1
                            else:
                                skip_counters["other"] += 1
                                
        except PermissionError:
            logger.warning(f"没有权限访问目录: {path}")
        except Exception as e:
            logger.warning(f"遍历目录失败 {path}: {e}")
    
    return total_valid

def scan_files(
    scan_paths: list,
    compiled_patterns: dict,
    max_file_size_mb: int,
    progress_callback: Callable,
    file_name_callback: Callable,
    result_callback: Optional[Callable] = None
) -> Tuple[list, dict]:
    """
    核心扫描函数（兼容原有接口）
    内部使用新的ScannerEngine，但对外提供完全相同的接口
    """
    # 重置全局变量（为了兼容）
    global SCAN_STOPPED, SCAN_PAUSED
    SCAN_STOPPED = False
    SCAN_PAUSED = False
    
    # 创建扫描上下文
    ctx = ScanContext()
    
    # 设置回调函数（将原有回调转换为新的回调接口）
    def _on_progress(current: int, total: int, found: int):
        progress_callback(current, total, found)
    
    def _on_file_scanned(file_name: str):
        file_name_callback(file_name)
    
    def _on_match_found(result: ScanResult):
        if result_callback:
            result_callback(result)
    
    ctx.on_progress = _on_progress
    ctx.on_file_scanned = _on_file_scanned
    ctx.on_match_found = _on_match_found
    
    # 创建扫描引擎
    engine = ScannerEngine(ctx)
    
    # 准备配置
    config = ScanConfig(
        scan_paths=scan_paths,
        patterns={name: pattern.pattern for name, pattern in compiled_patterns.items()},
        max_file_size_mb=max_file_size_mb
    )
    
    # 执行扫描
    results = engine.scan(config)
    
    # 构建跳过计数器（为了兼容返回值）
    stats = ctx.get_stats()
    skip_counters = {
        "oversize": ctx.large_files_skipped,
        "badsuffix": 0,  # 新的引擎没有单独统计这个
        "other": ctx.total_files_skipped - ctx.large_files_skipped
    }
    
    # 更新全局变量（为了兼容）
    if ctx.state.name == "STOPPING":
        SCAN_STOPPED = True
    elif ctx.state.name == "PAUSED":
        SCAN_PAUSED = True
    
    return results, skip_counters