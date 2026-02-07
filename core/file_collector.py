"""
core/file_collector.py
文件收集器 - 单次遍历，高效过滤，避免重复IO
"""
import os
from pathlib import Path
from typing import List, Tuple, Set, Iterator
import logging

logger = logging.getLogger(__name__)


class FileCollector:
    """
    高效文件收集器
    特点：
    1. 单次遍历：同时收集文件和统计数量
    2. 快速过滤：尽早应用低成本跳过规则
    3. 内存友好：支持迭代器和分批处理
    """
    
    def __init__(self, skip_extensions: Set[str], skip_no_extension: bool = True):
        """
        初始化文件收集器
        
        :param skip_extensions: 跳过的扩展名集合
        :param skip_no_extension: 是否跳过无后缀文件
        """
        self.skip_extensions = skip_extensions
        self.skip_no_extension = skip_no_extension
        
    def _should_skip_fast(self, file_path: Path) -> Tuple[bool, str]:
        """
        快速跳过检查（仅基于文件名和扩展名）
        成本极低，无需文件系统访问
        """
        # 1. 检查是否有后缀
        suffix = file_path.suffix.lower()
        if not suffix:
            if self.skip_no_extension:
                return True, "无后缀文件"
            return False, ""
        
        # 2. 检查扩展名是否在黑名单中
        if suffix in self.skip_extensions:
            return True, f"跳过后缀: {suffix}"
        
        return False, ""
    
    def collect_files(self, scan_paths: List[str], recursive: bool = True) -> Tuple[List[Path], int]:
        """
        收集所有需要扫描的文件
        
        :param scan_paths: 扫描路径列表
        :param recursive: 是否递归扫描
        :return: (文件列表, 总文件数)
        """
        all_files = []
        total_count = 0
        
        for path_str in scan_paths:
            path = Path(path_str).resolve()
            if not path.exists():
                logger.warning(f"扫描路径不存在: {path}")
                continue
            
            if path.is_file():
                # 单个文件：应用快速跳过检查
                skip, reason = self._should_skip_fast(path)
                if not skip:
                    all_files.append(path)
                    total_count += 1
                else:
                    logger.debug(f"快速跳过文件: {path} - {reason}")
            else:
                # 目录：递归收集
                for file_path in self._walk_directory(path, recursive):
                    all_files.append(file_path)
                    total_count += 1
        
        logger.info(f"文件收集完成，找到 {total_count} 个有效文件")
        return all_files, total_count
    
    def collect_files_iterative(self, scan_paths: List[str], recursive: bool = True) -> Iterator[Path]:
        """
        迭代收集文件（内存更友好）
        
        :param scan_paths: 扫描路径列表
        :param recursive: 是否递归扫描
        :return: 文件路径的迭代器
        """
        for path_str in scan_paths:
            path = Path(path_str).resolve()
            if not path.exists():
                logger.warning(f"扫描路径不存在: {path}")
                continue
            
            if path.is_file():
                # 单个文件：应用快速跳过检查
                skip, reason = self._should_skip_fast(path)
                if not skip:
                    yield path
                else:
                    logger.debug(f"快速跳过文件: {path} - {reason}")
            else:
                # 目录：递归收集
                for file_path in self._walk_directory(path, recursive):
                    yield file_path
    
    def _walk_directory(self, directory: Path, recursive: bool = True) -> Iterator[Path]:
        """
        遍历目录，应用快速跳过规则
        """
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False) and recursive:
                            # 递归遍历子目录
                            yield from self._walk_directory(Path(entry.path), recursive)
                            
                        elif entry.is_file(follow_symlinks=False):
                            file_path = Path(entry.path)
                            
                            # 应用快速跳过检查
                            skip, reason = self._should_skip_fast(file_path)
                            if not skip:
                                yield file_path
                            else:
                                logger.debug(f"快速跳过文件: {file_path} - {reason}")
                                
                    except (PermissionError, OSError) as e:
                        logger.debug(f"跳过无法访问的条目 {entry.path}: {e}")
                        
        except PermissionError:
            logger.warning(f"没有权限访问目录: {directory}")
        except Exception as e:
            logger.warning(f"遍历目录失败 {directory}: {e}")
    
    def estimate_total_files(self, scan_paths: List[str], recursive: bool = True) -> int:
        """
        快速估算总文件数（仅统计，不收集文件）
        用于进度条初始化
        """
        total_count = 0
        
        for path_str in scan_paths:
            path = Path(path_str).resolve()
            if not path.exists():
                continue
            
            if path.is_file():
                # 单个文件：应用快速跳过检查
                skip, _ = self._should_skip_fast(path)
                if not skip:
                    total_count += 1
            else:
                # 目录：递归统计
                total_count += self._count_files_in_directory(path, recursive)
        
        return total_count
    
    def _count_files_in_directory(self, directory: Path, recursive: bool) -> int:
        """
        快速统计目录中的文件数
        """
        count = 0
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False) and recursive:
                            # 递归统计子目录
                            count += self._count_files_in_directory(Path(entry.path), recursive)
                            
                        elif entry.is_file(follow_symlinks=False):
                            file_path = Path(entry.path)
                            
                            # 应用快速跳过检查
                            skip, _ = self._should_skip_fast(file_path)
                            if not skip:
                                count += 1
                                
                    except (PermissionError, OSError):
                        pass  # 跳过无法访问的文件
                        
        except (PermissionError, OSError):
            pass  # 跳过无法访问的目录
        
        return count