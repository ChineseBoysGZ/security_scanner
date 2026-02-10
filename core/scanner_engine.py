"""
core/scanner_engine.py - 高性能优化版
核心扫描引擎 - 集成正则合并、性能监控、智能匹配策略
"""
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Iterator, Set, Tuple, Any
import logging

from collections import deque
from .scan_models import ScanContext, ScanResult, ScanState, ScanConfig
from .file_reader import SmartFileReader, should_skip_file
from .file_collector import FileCollector
from core.regex_manager import get_pattern_manager, compile_patterns_dict
from config.constants import SKIP_EXTENSIONS, SKIP_NO_EXTENSION_FILES
from utils.log_utils import logger

_APP_ID_PATTERN = re.compile(r'online[\\/](.*?)_all_all', re.IGNORECASE)

class ScannerEngine:
    """
    高性能扫描引擎（正则合并优化版）
    核心优化：
    1. 启用正则合并 - 大幅减少匹配次数
    2. 智能匹配顺序 - 按历史命中率排序
    3. 性能监控集成 - 实时统计匹配效率
    4. 批量处理优化 - 减少回调开销
    """
    
    def __init__(self, context: Optional[ScanContext] = None):
        self.ctx = context or ScanContext()
        self.compiled_patterns: Dict[str, re.Pattern] = {}
        self.merged_pattern_groups: List[Tuple[str, re.Pattern, Dict[str, str]]] = []
        self.single_patterns: Dict[str, re.Pattern] = {}
        self.pattern_manager = get_pattern_manager()
        self.skip_extensions: Set[str] = set()
        self.file_collector: Optional[FileCollector] = None
        
        # 性能监控
        # ✅ 修复：使用 deque 限制大小，防止内存膨胀
        self.match_stats = {
            'total_matches': 0,
            'merged_matches': 0,
            'single_matches': 0,
            'match_times': deque(maxlen=10000),  # ✅ 最多保留10000条
            'pattern_hits': {},
            'start_time': 0
        }
        
        # 匹配顺序缓存
        self.pattern_order = []
        self.use_merged_patterns = True  # 是否启用合并正则
        self._matched_positions: Set[Tuple[str, int, int]] = set()

    def prepare(self, config: ScanConfig) -> bool:
        """准备扫描引擎：启用正则合并和性能优化"""
        try:
            self.ctx._update_state(ScanState.PREPARING)
            
            # 1. 初始化文件收集器
            self.file_collector = FileCollector(
                skip_extensions=set(SKIP_EXTENSIONS),
                skip_no_extension=SKIP_NO_EXTENSION_FILES
            )
            
            # 2. 初始化正则管理器并获取配置
            self.match_stats['start_time'] = time.time()
            
            # 获取原始正则字典
            if hasattr(config, 'patterns_dict'):
                raw_patterns = config.patterns_dict
            else:
                # 兼容模式：假设patterns已经是字典格式
                raw_patterns = config.patterns if isinstance(config.patterns, dict) else {}
            
            logger.info(f"正在准备正则引擎，模式数量: {len(raw_patterns)}")
            
            # 3. 编译正则表达式（使用单例管理器，带缓存）
            self.compiled_patterns = compile_patterns_dict(raw_patterns)
            
            if not self.compiled_patterns:
                logger.error("没有有效的正则表达式，扫描终止")
                return False
            
            # 4. 创建合并正则组（性能优化关键）
            merged_patterns = self.pattern_manager.create_merged_patterns(raw_patterns)
            
            # 转换为便于处理的格式
            for group_name, (merged_pattern, subpattern_map) in merged_patterns.items():
                self.merged_pattern_groups.append((group_name, merged_pattern, subpattern_map))
            
            # 5. 构建单个正则映射（用于未合并的正则）
            self._build_single_patterns(raw_patterns, merged_patterns)
            
            # 6. 优化匹配顺序（按历史命中率排序）
            self._optimize_pattern_order()
            
            # 7. 初始化性能统计
            self.skip_extensions = set(SKIP_EXTENSIONS)
            
            # 8. 更新上下文配置
            self.ctx.total_files_discovered = 0
            self.ctx.total_files_scanned = 0
            self.ctx.total_files_skipped = 0
            self.ctx.total_matches_found = 0
            self.ctx.start_time = time.perf_counter()  # ✅ 修复：与 get_stats 保持一致
            
            # 记录准备信息
            logger.info(f"扫描引擎准备就绪:")
            logger.info(f"  - 原始正则: {len(raw_patterns)}个")
            logger.info(f"  - 编译成功: {len(self.compiled_patterns)}个")
            logger.info(f"  - 合并组数: {len(self.merged_pattern_groups)}组")
            logger.info(f"  - 单模式数: {len(self.single_patterns)}个")
            logger.info(f"  - 启用合并: {self.use_merged_patterns}")
            
            if self.merged_pattern_groups:
                total_merged_patterns = sum(len(m[2]) for m in self.merged_pattern_groups)
                logger.info(f"  - 合并效率: {total_merged_patterns}个正则合并为{len(self.merged_pattern_groups)}组")
            
            return True
            
        except Exception as e:
            logger.error(f"扫描引擎准备失败: {e}", exc_info=True)
            self.ctx._update_state(ScanState.ERROR)
            return False
    
    def _build_single_patterns(self, raw_patterns: Dict[str, str], 
                               merged_patterns: Dict[str, Tuple[re.Pattern, Dict[str, str]]]):
        """构建单个正则映射（用于未合并的正则）"""
        # 收集所有已合并的正则名
        merged_names = set()
        for _, _, subpattern_map in self.merged_pattern_groups:
            merged_names.update(subpattern_map.values())
        
        # 构建未合并的正则映射
        self.single_patterns = {}
        for name, pattern in self.compiled_patterns.items():
            if name not in merged_names:
                self.single_patterns[name] = pattern
        
        logger.debug(f"构建单个正则映射: {len(self.single_patterns)}个未合并正则")
    
    def _optimize_pattern_order(self):
        """优化匹配顺序（基于历史命中率）"""
        # 获取历史统计
        stats = self.pattern_manager.get_pattern_stats()
        
        if 'patterns' in stats:
            pattern_stats = stats['patterns']
            
            # 按平均匹配时间排序（快的优先）
            sorted_patterns = sorted(
                pattern_stats.items(),
                key=lambda x: x[1].get('avg_match_time', 1.0)  # 默认1秒
            )
            
            self.pattern_order = [name for name, _ in sorted_patterns]
            logger.debug(f"优化匹配顺序完成: {len(self.pattern_order)}个正则已排序")
        else:
            # 无历史数据，使用原始顺序
            self.pattern_order = list(self.compiled_patterns.keys())
            logger.debug("使用默认匹配顺序")
    
    def scan(self, config: ScanConfig) -> List[ScanResult]:
        """
        执行扫描 - 使用正则合并优化
        """
        if not self.prepare(config):
            return []
        
        all_results: List[ScanResult] = []
        max_file_size_bytes = config.max_file_size_mb * 1024 * 1024
        
        try:
            self.ctx._update_state(ScanState.SCANNING)
            
            # 使用文件收集器获取所有需要扫描的文件
            logger.info("开始收集需要扫描的文件...")
            collect_start = time.time()
            
            # 迭代收集文件（节省内存）
            files_iter = self.file_collector.collect_files_iterative(
                config.scan_paths, getattr(config, 'recursive', True)
            )
            
            # 估算总文件数用于进度条
            total_files_estimate = self.file_collector.estimate_total_files(
                config.scan_paths, getattr(config, 'recursive', True)
            )
            self.ctx.total_files_estimated = total_files_estimate
            
            collect_time = time.time() - collect_start
            logger.info(f"文件收集完成，耗时: {collect_time:.2f}秒，估计文件数: {total_files_estimate}")
            
            # 扫描收集到的文件
            scanned_count = 0
            for file_path in files_iter:
                if self.ctx.should_stop():
                    break
                
                self.ctx.check_pause()
                scanned_count += 1
                
                # 处理单个文件（使用正则合并优化）
                self._process_single_file_optimized(
                    file_path, max_file_size_bytes, all_results, scanned_count, total_files_estimate
                )
            
            # 扫描完成
            if self.ctx.should_stop():
                self.ctx._update_state(ScanState.STOPPING)
                logger.info("扫描被用户停止")
            else:
                self.ctx._update_state(ScanState.COMPLETED)
                self._print_scan_summary()
        
        except Exception as e:
            logger.error(f"扫描过程中发生错误: {e}", exc_info=True)
            self.ctx._update_state(ScanState.ERROR)
        
        return all_results
    
    def _process_single_file_optimized(
        self,
        file_path: Path,
        max_file_size_bytes: int,
        all_results: List[ScanResult],
        current_index: int,
        total_estimate: int
    ):
        """优化版的单文件处理流程（支持正则合并）"""
        # 跳过检查
        skip, reason = should_skip_file(file_path, self.skip_extensions, max_file_size_bytes)
        
        if skip:
            self.ctx.total_files_skipped += 1
            
            # 记录跳过信息
            if "文件过大" in reason:
                self.ctx.large_files_skipped += 1
            
            # 更新进度
            if self.ctx.on_progress and total_estimate > 0:
                self.ctx.on_progress(
                    current_index,
                    total_estimate,
                    self.ctx.total_matches_found
                )
            return
        
        # 开始扫描文件
        scan_start = time.time()
        try:
            # 使用正则合并优化扫描
            file_results = self._scan_file_content_with_merged_patterns(file_path)
            all_results.extend(file_results)
            
            # 更新统计
            self.ctx.total_files_scanned += 1
            self.ctx.total_matches_found += len(file_results)
            
            # 记录扫描时间
            scan_time = time.time() - scan_start
            self.match_stats['match_times'].append(scan_time)
            
            # 更新进度
            if self.ctx.on_progress and total_estimate > 0:
                self.ctx.on_progress(
                    current_index,
                    total_estimate,
                    self.ctx.total_matches_found
                )
            
            # 触发回调
            if file_results:
                if self.ctx.on_file_scanned:
                    self.ctx.on_file_scanned(str(file_path))
                
                if self.ctx.on_batch_found:
                    self.ctx.on_batch_found(file_results)
                    
        except Exception as e:
            logger.warning(f"扫描文件失败 {file_path}: {e}")
            self.ctx.total_files_skipped += 1
            
            # 即使出错也要更新进度
            if self.ctx.on_progress and total_estimate > 0:
                self.ctx.on_progress(
                    current_index,
                    total_estimate,
                    self.ctx.total_matches_found
                )
    
    def _scan_file_content_with_merged_patterns(self, file_path: Path) -> List[ScanResult]:
        """使用合并正则优化扫描文件内容"""
        results: List[ScanResult] = []
        reader = SmartFileReader(file_path)
        
        # ✅ 修复：重置匹配位置记录（每个文件独立）
        self._matched_positions.clear()

        try:
            # 获取文件信息
            file_size = reader.file_size
            encoding = reader.detect_encoding()
            
            # ✅ 修复：使用行读取而不是分块读取（避免重复处理）
            for line_num, line in reader.read_lines():
                if self.ctx.should_stop():
                    break
                
                line_stripped = line.strip()
                if not line_stripped or len(line_stripped) < 3:
                    continue
                
                # 处理单行
                line_results = self._process_line_with_patterns_fixed(
                    line_stripped, file_path, file_size, encoding, line_num
                )
                results.extend(line_results)
            
            logger.debug(f"文件扫描完成: {file_path}, 发现 {len(results)} 个匹配")
            return results
            
        except Exception as e:
            logger.warning(f"扫描文件内容失败 {file_path}: {e}")
            return []
    
    def _process_line_with_patterns_fixed(self, line: str, file_path: Path,
                                         file_size: int, encoding: str,
                                         line_num: int) -> List[ScanResult]:
        """
        处理单行内容（修复重复匹配）
        核心修复：防止合并正则和单个正则重复匹配同一内容
        """
        """添加调试信息"""
        if logger.isEnabledFor(logging.DEBUG) and "test" in str(file_path).lower():
            logger.debug(f"处理文件: {file_path}, 行 {line_num}: {line[:50]}...")
    
        results = []
        
        # ✅ 修复：记录已匹配的规则-行位置，防止重复
        line_matched_rules = set()
        
        # 第一步：使用合并正则匹配
        if self.use_merged_patterns and self.merged_pattern_groups:
            merged_match_count = 0
            for group_name, merged_pattern, subpattern_map in self.merged_pattern_groups:
                matches = list(merged_pattern.finditer(line))
                if matches and logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"  合并组 '{group_name}' 在行 {line_num} 找到 {len(matches)} 个匹配")

                for match in matches:
                    # 确定是哪个子模式匹配的
                    for group_id, pattern_name in subpattern_map.items():
                        matched_text = match.group(group_id)
                        if matched_text and pattern_name not in line_matched_rules:
                            # ✅ 修复：检查是否为重复匹配
                            match_key = (str(file_path), line_num, pattern_name, matched_text[:100])

                            if match_key in self._matched_positions:
                                logger.debug(f"    跳过重复匹配: {pattern_name} - {matched_text[:30]}")
                                continue
                            
                            line_matched_rules.add(pattern_name)
                            self._matched_positions.add(match_key)
                            merged_match_count += 1
                            
                            # 创建结果对象
                            result = ScanResult(
                                rule_name=pattern_name,
                                file_path=str(file_path),
                                match_content=matched_text[:500] + "..." if len(matched_text) > 500 else matched_text,
                                line_num=line_num,
                                app_id=self._extract_app_id(str(file_path)),
                                file_size=file_size,
                                encoding=encoding
                            )
                            results.append(result)
                            
                            # 更新性能统计
                            self.match_stats['merged_matches'] += 1
                            self.match_stats['pattern_hits'][pattern_name] = \
                                self.match_stats['pattern_hits'].get(pattern_name, 0) + 1
        
        # 第二步：使用单个正则匹配（只匹配未在合并正则中匹配过的规则）
        single_match_count = 0
        for pattern_name in self.pattern_order:
            if pattern_name in line_matched_rules:
                continue  # ✅ 修复：跳过已在合并正则中匹配过的规则
            
            pattern = self.compiled_patterns.get(pattern_name)
            if not pattern:
                continue
            
            match = pattern.search(line)
            if match:
                matched_text = match.group()
                if matched_text:
                    # ✅ 修复：检查是否为重复匹配
                    match_key = (str(file_path), line_num, pattern_name, matched_text[:100])
                    
                    if match_key in self._matched_positions:
                        continue
                    
                    self._matched_positions.add(match_key)
                    single_match_count += 1
                    
                    result = ScanResult(
                        rule_name=pattern_name,
                        file_path=str(file_path),
                        match_content=matched_text[:500] + "..." if len(matched_text) > 500 else matched_text,
                        line_num=line_num,
                        app_id=self._extract_app_id(str(file_path)),
                        file_size=file_size,
                        encoding=encoding
                    )
                    results.append(result)
                    
                    self.match_stats['single_matches'] += 1
                    self.match_stats['pattern_hits'][pattern_name] = \
                        self.match_stats['pattern_hits'].get(pattern_name, 0) + 1
        
        if logger.isEnabledFor(logging.DEBUG) and (merged_match_count > 0 or single_match_count > 0):
            logger.debug(f"  行 {line_num} 总计匹配: {merged_match_count} 合并 + {single_match_count} 单个")
        
        return results
    
    def _process_line_with_patterns(self, line: str, file_path: Path, 
                               file_size: int, encoding: str, 
                               line_num: int) -> List[ScanResult]:
        """
        处理单行内容（支持合并正则和单正则）
        """
        results = []
    
        # 第一步：使用合并正则匹配（如果启用）
        if self.use_merged_patterns and self.merged_pattern_groups:
            line_results = self._process_line_with_merged_patterns(
                line, file_path, file_size, encoding, line_num
            )
            results.extend(line_results)
    
        # 第二步：使用单个正则匹配
        line_results = self._process_line_with_single_patterns(
            line, file_path, file_size, encoding, line_num
        )
        results.extend(line_results)
    
        return results

    def _process_chunk_with_merged_patterns(self, chunk: str, file_path: Path, 
                                          file_size: int, encoding: str, 
                                          position: int) -> List[ScanResult]:
        """使用合并正则处理文件块 - ✅ 修复变量名错误"""
        results = []
        
        if not self.use_merged_patterns or not self.merged_pattern_groups:
            # ✅ 修复：使用正确的参数名（原来错误地使用了 line/line_num）
            return self._process_chunk_with_single_patterns(chunk, file_path, file_size, encoding, position)
    
        matched_patterns = set()  # 记录已匹配的模式，避免重复
        
        # 按行分割 chunk 进行处理
        lines = chunk.split('\n')
        estimated_line_start = max(1, position // 100)  # 估算起始行号
        
        for i, line in enumerate(lines):
            if self.ctx.should_stop():
                break
            
            line_num = estimated_line_start + i
            line_stripped = line.strip()
            if not line_stripped or len(line_stripped) < 3:
                continue
            
            for group_name, merged_pattern, subpattern_map in self.merged_pattern_groups:
                if self.ctx.should_stop():
                    break
            
                matches = merged_pattern.finditer(line_stripped)
                for match in matches:
                    for group_id, pattern_name in subpattern_map.items():
                        matched_text = match.group(group_id)
                        if matched_text and pattern_name not in matched_patterns:
                            matched_patterns.add(pattern_name)
                        
                            result = ScanResult(
                                rule_name=pattern_name,
                                file_path=str(file_path),
                                match_content=matched_text[:500] + "..." if len(matched_text) > 500 else matched_text,
                                line_num=line_num,
                                app_id=self._extract_app_id(str(file_path)),
                                file_size=file_size,
                                encoding=encoding
                            )
                            results.append(result)
                        
                            self.match_stats['merged_matches'] += 1
                            self.match_stats['pattern_hits'][pattern_name] = \
                                self.match_stats['pattern_hits'].get(pattern_name, 0) + 1
        
        # 单个正则匹配
        if self.single_patterns:
            single_results = self._process_chunk_with_single_patterns(
                chunk, file_path, file_size, encoding, position
            )
            results.extend(single_results)
    
        return results
    
    def _process_chunk_with_single_patterns(self, chunk: str, file_path: Path,
                                           file_size: int, encoding: str,
                                           position: int) -> List[ScanResult]:
        """使用单个正则处理文件块"""
        results = []
        
        for pattern_name in self.pattern_order:
            if self.ctx.should_stop():
                break
            
            pattern = self.compiled_patterns.get(pattern_name)
            if not pattern:
                continue
            
            match_start_time = time.perf_counter()
            matches = pattern.finditer(chunk)
            
            for match in matches:
                matched_text = match.group()
                if matched_text:
                    result = ScanResult(
                        rule_name=pattern_name,
                        file_path=str(file_path),
                        match_content=matched_text[:500] + "..." if len(matched_text) > 500 else matched_text,
                        line_num=self._estimate_line_number(position, chunk, match.start()),
                        app_id=self._extract_app_id(str(file_path)),
                        file_size=file_size,
                        encoding=encoding
                    )
                    results.append(result)
                    
                    # 更新性能统计
                    self.match_stats['single_matches'] += 1
                    self.match_stats['pattern_hits'][pattern_name] = \
                        self.match_stats['pattern_hits'].get(pattern_name, 0) + 1
            
            # 记录单个正则匹配时间到性能管理器
            match_time = time.perf_counter() - match_start_time
            if match_time > 0:
                # 通过性能管理器记录（如果支持）
                if hasattr(self.pattern_manager, 'match_with_stats'):
                    self.pattern_manager.match_with_stats(pattern_name, pattern, chunk)
        
        return results
    
    def _process_line_with_merged_patterns(self, line: str, file_path: Path,
                                          file_size: int, encoding: str,
                                          line_num: int) -> List[ScanResult]:
        """使用合并正则处理单行"""
        results = []
        
        if not self.use_merged_patterns or not self.merged_pattern_groups:
            # 回退到单正则匹配
            return self._process_line_with_single_patterns(line, file_path, file_size, encoding, line_num)
        
        matched_patterns = set()
        
        for group_name, merged_pattern, subpattern_map in self.merged_pattern_groups:
            if self.ctx.should_stop():
                break
            
            matches = merged_pattern.finditer(line)
            for match in matches:
                for group_id, pattern_name in subpattern_map.items():
                    matched_text = match.group(group_id)
                    if matched_text and pattern_name not in matched_patterns:
                        matched_patterns.add(pattern_name)
                        
                        result = ScanResult(
                            rule_name=pattern_name,
                            file_path=str(file_path),
                            match_content=matched_text[:500] + "..." if len(matched_text) > 500 else matched_text,
                            line_num=line_num,
                            app_id=self._extract_app_id(str(file_path)),
                            file_size=file_size,
                            encoding=encoding
                        )
                        results.append(result)
                        
                        self.match_stats['merged_matches'] += 1
        
        # 单正则匹配
        if self.single_patterns:
            line_results = self._process_line_with_single_patterns(
                line, file_path, file_size, encoding, line_num
            )
            results.extend(line_results)
        
        return results
    
    def _process_line_with_single_patterns(self, line: str, file_path: Path,
                                          file_size: int, encoding: str,
                                          line_num: int) -> List[ScanResult]:
        """使用单个正则处理单行（每行可匹配多个正则）"""
        results = []
        
        for pattern_name in self.pattern_order:
            if self.ctx.should_stop():
                break
            
            pattern = self.compiled_patterns.get(pattern_name)
            if not pattern:
                continue
            
            match = pattern.search(line)
            if match:
                matched_text = match.group()
                if matched_text:
                    result = ScanResult(
                        rule_name=pattern_name,
                        file_path=str(file_path),
                        match_content=matched_text[:500] + "..." if len(matched_text) > 500 else matched_text,
                        line_num=line_num,
                        app_id=self._extract_app_id(str(file_path)),
                        file_size=file_size,
                        encoding=encoding
                    )
                    results.append(result)
                    
                    self.match_stats['single_matches'] += 1
        
        return results
    
    @staticmethod
    def _estimate_line_number(position: int, chunk: str, match_pos: int) -> int:
        """估算匹配所在的行号"""
        # 简单实现：通过换行符计数
        if position == 0:
            # 计算chunk中match_pos之前的换行符数量
            return chunk[:match_pos].count('\n') + 1
        return position // 1000 + 1  # 简单估算
    
    @staticmethod
    def _extract_app_id(file_path: str) -> str:
        """从文件路径中提取应用ID - ✅ 使用模块级预编译正则"""
        match = _APP_ID_PATTERN.search(file_path)
        return match.group(1).strip() if match else ""
    
    def _print_scan_summary(self):
        """打印扫描摘要"""
        elapsed = time.time() - self.ctx.start_time
        
        logger.info("=" * 60)
        logger.info("扫描完成摘要")
        logger.info("=" * 60)
        logger.info(f"总耗时: {elapsed:.1f}秒")
        logger.info(f"扫描文件: {self.ctx.total_files_scanned}个")
        logger.info(f"发现匹配: {self.ctx.total_matches_found}个")
        logger.info(f"跳过文件: {self.ctx.total_files_skipped}个")
        
        # 正则性能统计
        if self.match_stats['match_times']:
            total_match_time = sum(self.match_stats['match_times'])
            avg_match_time = total_match_time / len(self.match_stats['match_times'])
            logger.info(f"正则匹配总时间: {total_match_time:.2f}秒")
            logger.info(f"平均匹配时间: {avg_match_time*1000:.1f}ms/文件")
        
        # 合并正则效果
        if self.use_merged_patterns and self.merged_pattern_groups:
            total_merged = self.match_stats.get('merged_matches', 0)
            total_single = self.match_stats.get('single_matches', 0)
            total_matches = total_merged + total_single
            
            if total_matches > 0:
                merge_ratio = total_merged / total_matches * 100
                logger.info(f"合并正则匹配: {total_merged}个 ({merge_ratio:.1f}%)")
                logger.info(f"单个正则匹配: {total_single}个 ({100-merge_ratio:.1f}%)")
        
        # 各正则命中率
        if self.match_stats['pattern_hits']:
            logger.info("各正则命中统计:")
            sorted_hits = sorted(
                self.match_stats['pattern_hits'].items(),
                key=lambda x: x[1],
                reverse=True
            )
            for pattern_name, hits in sorted_hits[:10]:  # 显示前10
                logger.info(f"  - {pattern_name}: {hits}次")
        
        logger.info("=" * 60)
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取详细的性能统计信息"""
        if not self.ctx.start_time:
            return {}
        
        elapsed = time.time() - self.ctx.start_time
        stats = self.ctx.get_stats()
        
        # 添加正则性能指标
        if elapsed > 0:
            stats.update({
                "files_per_second": round(self.ctx.total_files_scanned / elapsed, 1),
                "matches_per_second": round(self.ctx.total_matches_found / elapsed, 1),
                "merged_patterns_enabled": self.use_merged_patterns,
                "merged_pattern_groups": len(self.merged_pattern_groups),
                "single_patterns": len(self.single_patterns),
                "merged_matches": self.match_stats.get('merged_matches', 0),
                "single_matches": self.match_stats.get('single_matches', 0),
                "total_match_operations": self.match_stats.get('total_matches', 0)
            })
        
        # 匹配时间统计
        if deque:
            match_times = deque
            stats.update({
                "total_match_time": round(sum(match_times), 3),
                "avg_match_time_per_file": round(sum(match_times) / len(match_times) * 1000, 1),
                "max_match_time": round(max(match_times) * 1000, 1),
                "min_match_time": round(min(match_times) * 1000, 1)
            })
        
        # 命中率统计
        if self.match_stats['pattern_hits']:
            stats["pattern_hits"] = self.match_stats['pattern_hits']
        
        return stats
    
    def get_regex_performance_report(self) -> str:
        """获取正则性能报告"""
        if hasattr(self.pattern_manager, 'get_performance_report'):
            return self.pattern_manager.get_performance_report()
        return "正则性能报告不可用"
    
    def enable_merged_patterns(self, enable: bool = True):
        """启用或禁用合并正则"""
        self.use_merged_patterns = enable
        logger.info(f"合并正则已{'启用' if enable else '禁用'}")
    
    def reset_performance_stats(self):
        """重置性能统计"""
        self.match_stats = {
            'total_matches': 0,
            'merged_matches': 0,
            'single_matches': 0,
            'match_times': [],
            'pattern_hits': {},
            'start_time': time.time()
        }
        logger.info("性能统计已重置")
