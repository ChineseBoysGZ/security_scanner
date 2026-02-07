"""
core/regex_manager.py - 增强优化版
正则表达式管理器 - 修复缓存问题，添加线程安全，优化性能监控
"""
import re
import time
import hashlib
import threading
import json
from typing import Dict, List, Tuple, Optional, Set, Any
from functools import lru_cache
from dataclasses import dataclass, field
from collections import defaultdict

from utils.log_utils import logger
from core.scan_models import ScanResult

@dataclass
class PatternStats:
    """正则表达式性能统计"""
    compile_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    match_count: int = 0
    total_match_time: float = 0.0
    avg_match_time: float = 0.0
    last_used: float = 0.0
    
    def add_match_time(self, match_time: float):
        """添加匹配时间统计"""
        self.match_count += 1
        self.total_match_time += match_time
        self.avg_match_time = self.total_match_time / self.match_count
        self.last_used = time.time()

@dataclass
class CompiledPattern:
    """编译后的正则模式（带元数据和线程安全）"""
    name: str
    pattern: re.Pattern
    pattern_str: str
    compile_time: float
    usage_count: int = 0
    last_used: float = 0
    _lock: threading.RLock = field(default_factory=threading.RLock)
    
    def mark_used(self):
        """标记使用（线程安全）"""
        with self._lock:
            self.usage_count += 1
            self.last_used = time.time()


class PatternManager:
    """
    正则模式管理器（单例模式）
    提供正则的编译、缓存、合并、测试和性能监控。
    """
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        """实现单例模式"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        """初始化（确保只执行一次）"""
        if getattr(self, '_initialized', False):
            return
            
        with self._lock:
            self._compiled_cache: Dict[str, CompiledPattern] = {}
            self._pattern_groups: Dict[str, List[Tuple[str, str]]] = {}
            self._merged_patterns: Dict[str, Tuple[re.Pattern, Dict[str, str]]] = {}
            self._stats: Dict[str, PatternStats] = defaultdict(PatternStats)
            self._global_stats = {
                'total_compile_count': 0,
                'total_cache_hits': 0,
                'total_cache_misses': 0,
                'total_match_count': 0,
                'total_match_time': 0.0,
                'start_time': time.time()
            }
            self._manager_lock = threading.RLock()
            self._initialized = True
            
            logger.info("PatternManager 初始化完成（单例模式）")
    
    def get_compiled_pattern(self, name: str, pattern_str: str) -> Optional[re.Pattern]:
        """
        获取编译后的正则模式（带缓存和性能统计）
        
        :param name: 规则名称
        :param pattern_str: 正则表达式字符串
        :return: 编译后的正则对象，如果编译失败返回None
        """
        cache_key = self._get_pattern_key(name, pattern_str)
        
        with self._manager_lock:
            # 检查缓存
            if cache_key in self._compiled_cache:
                cp = self._compiled_cache[cache_key]
                cp.mark_used()
                self._stats[name].cache_hits += 1
                self._global_stats['total_cache_hits'] += 1
                return cp.pattern
            
            # 缓存未命中，编译新正则
            try:
                start_compile = time.perf_counter()
                pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
                compile_time = time.perf_counter() - start_compile
                
                cp = CompiledPattern(
                    name=name,
                    pattern=pattern,
                    pattern_str=pattern_str,
                    compile_time=compile_time
                )
                cp.mark_used()
                
                self._compiled_cache[cache_key] = cp
                self._stats[name].compile_count += 1
                self._global_stats['total_compile_count'] += 1
                self._global_stats['total_cache_misses'] += 1
                
                logger.debug(f"编译正则模式 [{name}]: 耗时 {compile_time:.4f}s")
                return pattern
                
            except re.error as e:
                logger.error(f"正则编译失败 [{name}]: {e}")
                return None
    
    def compile_patterns(self, patterns_dict: Dict[str, str]) -> Dict[str, re.Pattern]:
        """
        批量编译正则模式（带缓存）
        
        :param patterns_dict: {规则名: 正则表达式}
        :return: {规则名: 编译后的正则对象}
        """
        compiled = {}
        
        for name, pattern_str in patterns_dict.items():
            pattern = self.get_compiled_pattern(name, pattern_str)
            if pattern:
                compiled[name] = pattern
        
        logger.info(f"正则批量编译完成: 总数={len(patterns_dict)}, "
                   f"成功={len(compiled)}, 缓存命中={self._global_stats['total_cache_hits']}")
        
        return compiled
    
    def match_with_stats(self, pattern_name: str, pattern: re.Pattern, text: str) -> List[Any]:
        """
        执行正则匹配并记录性能统计
        
        :param pattern_name: 规则名称
        :param pattern: 编译后的正则对象
        :param text: 要匹配的文本
        :return: 匹配结果列表
        """
        start_time = time.perf_counter()
        try:
            matches = pattern.findall(text)
        except Exception as e:
            logger.error(f"正则匹配异常 [{pattern_name}]: {e}")
            return []
        
        match_time = time.perf_counter() - start_time
        
        # 记录性能统计
        with self._manager_lock:
            self._stats[pattern_name].add_match_time(match_time)
            self._global_stats['total_match_count'] += 1
            self._global_stats['total_match_time'] += match_time
        
        # 处理匹配结果
        results = []
        for match in matches:
            if isinstance(match, tuple):
                # 合并元组中的非空元素
                combined = ' | '.join(str(item) for item in match if item)
                if combined.strip():
                    results.append(combined)
            else:
                if str(match).strip():
                    results.append(str(match))
        
        return results
    
    def create_merged_patterns(self, patterns_dict: Dict[str, str]) -> Dict[str, Tuple[re.Pattern, Dict[str, str]]]:
        """
        创建合并的正则模式（性能优化）
        将相似的正则合并为一个，减少匹配次数。
        
        :return: {组名: (合并后的正则, {捕获组ID: 原始模式名})}
        """
        # 按类型分组
        self._group_patterns(patterns_dict)
        merged_results = {}
        
        for group_name, pattern_list in self._pattern_groups.items():
            if len(pattern_list) <= 1:
                continue  # 不需要合并
            
            logger.debug(f"开始合并正则组 [{group_name}]: {len(pattern_list)}个模式")
            
            # 构建合并的正则表达式
            merged_parts = []
            subpattern_map = {}
            
            for i, (name, pattern_str) in enumerate(pattern_list):
                # 清理正则表达式
                clean_pattern = self._clean_pattern(pattern_str)
                # 添加命名捕获组
                group_id = f"{name}_{i}"
                merged_parts.append(f'(?P<{group_id}>{clean_pattern})')
                subpattern_map[group_id] = name
            
            # 用 | 连接所有子模式
            merged_regex = '|'.join(merged_parts)
            
            try:
                start_compile = time.perf_counter()
                merged_pattern = re.compile(merged_regex, re.IGNORECASE | re.MULTILINE)
                compile_time = time.perf_counter() - start_compile
                
                merged_results[group_name] = (merged_pattern, subpattern_map)
                
                logger.debug(f"合并正则组成功 [{group_name}]: "
                           f"{len(pattern_list)}合1, 编译耗时 {compile_time:.4f}s")
                
            except re.error as e:
                logger.error(f"合并正则编译失败 [{group_name}]: {e}")
        
        # 缓存合并结果
        self._merged_patterns = merged_results
        
        return merged_results
    
    def get_merged_pattern_for_matching(self) -> List[Tuple[str, re.Pattern, Dict[str, str]]]:
        """
        获取用于匹配的合并正则列表
        """
        result = []
        for group_name, (pattern, subpattern_map) in self._merged_patterns.items():
            result.append((group_name, pattern, subpattern_map))
        return result
    
    def _group_patterns(self, patterns_dict: Dict[str, str]):
        """将正则模式按类型分组（增强版）"""
        groups = {
            'email': [],
            'phone': [],
            'id_card': [],
            'ip': [],
            'password': [],
            'username': [],
            'number': [],
            'other': []
        }
        
        # 明确的规则映射，避免模糊匹配
        pattern_mapping = {
            # 邮箱相关
            '邮箱地址': 'email',
            # 手机电话相关
            '手机号码': 'phone',
            '座机号码': 'phone',
            # 身份证相关
            '身份证号码': 'id_card',
            '工号用户ID': 'id_card',
            '卡号信息': 'id_card',
            # IP地址相关
            '内网IP地址': 'ip',
            'IPv6地址': 'ip',
            '物理路径地址': 'ip',
            # 密码相关
            '密码泄露': 'password',
            '日志密码': 'password',
            'J密码': 'password',
            # 用户名相关
            '用户名姓名': 'username',
            '日志名称': 'username',
            'J用户名': 'username',
            # 金额相关
            '金额': 'number',
            # 其他
            '机房地址': 'other',
        }
    
        for name, pattern in patterns_dict.items():
            if name in pattern_mapping:
                group_name = pattern_mapping[name]
                groups[group_name].append((name, pattern))
            else:
                # 如果没有明确映射，使用模糊匹配
                name_lower = name.lower()
                if any(kw in name_lower for kw in ['mail', '邮箱']):
                    groups['email'].append((name, pattern))
                elif any(kw in name_lower for kw in ['phone', '手机', '电话', '座机']):
                    groups['phone'].append((name, pattern))
                elif any(kw in name_lower for kw in ['id', '身份证', '证号', '工号', '卡号']):
                    groups['id_card'].append((name, pattern))
                elif any(kw in name_lower for kw in ['ip', '地址', '内网', 'ipv6', '物理路径']):
                    groups['ip'].append((name, pattern))
                elif any(kw in name_lower for kw in ['password', '密码', 'pwd', 'pass', '日志密码']):
                    groups['password'].append((name, pattern))
                elif any(kw in name_lower for kw in ['username', '姓名', '用户', 'j_username', '日志名称']):
                    groups['username'].append((name, pattern))
                elif any(kw in name_lower for kw in ['金额', '金额']):
                    groups['number'].append((name, pattern))
                else:
                    groups['other'].append((name, pattern))
        
        # 移除空分组
        self._pattern_groups = {k: v for k, v in groups.items() if v}
        
        # 输出分组统计
        for group_name, patterns in self._pattern_groups.items():
            logger.debug(f"正则分组 [{group_name}]: {len(patterns)}个模式")
    
    def _clean_pattern(self, pattern: str) -> str:
        """
        安全清理正则表达式
        原则：不改变正则的语义，只做最必要的清理
        """
        # 保存原始模式用于调试
        original = pattern

        # 1. 移除外部的 ^ 和 $（安全操作）
        if pattern.startswith('^'):
            pattern = pattern[1:]
        if pattern.endswith('$'):
            pattern = pattern[:-1]
    
        # 2. 修复常见的非捕获组语法错误（如果有的话）
        # 例如：将 (?:? 修复为 (?:（但这种情况很少见）
        pattern = pattern.replace('(?:?', '(?:')
    
        # 3. 移除首尾多余的空格
        pattern = pattern.strip()
    
        # 记录清理结果（用于调试）
        if pattern != original:
            logger.debug(f"正则清理: {original[:50]}... -> {pattern[:50]}...")
    
        return pattern
    
    def _get_pattern_key(self, name: str, pattern: str) -> str:
        """生成缓存键"""
        content = f"{name}:{pattern}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def test_pattern(self, pattern_str: str, test_text: str) -> Tuple[bool, List[str]]:
        """
        测试正则表达式
        
        :return: (是否有效, 匹配结果列表)
        """
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
            matches = pattern.findall(test_text)
            
            # 处理匹配结果
            results = []
            for match in matches:
                if isinstance(match, tuple):
                    # 合并元组中的非空元素
                    combined = ' | '.join(str(item) for item in match if item)
                    if combined.strip():
                        results.append(combined)
                else:
                    if str(match).strip():
                        results.append(str(match))
            
            return True, results
            
        except re.error as e:
            return False, [str(e)]
    
    def get_pattern_stats(self, pattern_name: str = None) -> Dict:
        """获取正则统计信息"""
        with self._manager_lock:
            if pattern_name:
                if pattern_name in self._stats:
                    stats = self._stats[pattern_name]
                    return {
                        'name': pattern_name,
                        'compile_count': stats.compile_count,
                        'cache_hits': stats.cache_hits,
                        'cache_misses': stats.cache_misses,
                        'match_count': stats.match_count,
                        'total_match_time': stats.total_match_time,
                        'avg_match_time': stats.avg_match_time,
                        'last_used': stats.last_used
                    }
                return {}
            
            # 全局统计
            result = {
                'global': {
                    **self._global_stats,
                    'cache_size': len(self._compiled_cache),
                    'pattern_groups': {k: len(v) for k, v in self._pattern_groups.items()},
                    'merged_patterns': len(self._merged_patterns),
                    'uptime': time.time() - self._global_stats['start_time']
                },
                'patterns': {}
            }
            
            # 各正则详细统计
            for name, stats in self._stats.items():
                result['patterns'][name] = {
                    'compile_count': stats.compile_count,
                    'cache_hits': stats.cache_hits,
                    'cache_misses': stats.cache_misses,
                    'match_count': stats.match_count,
                    'total_match_time': stats.total_match_time,
                    'avg_match_time': stats.avg_match_time,
                    'last_used': stats.last_used
                }
            
            return result
    
    def get_performance_report(self) -> str:
        """生成性能报告"""
        stats = self.get_pattern_stats()
        
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("正则表达式性能报告")
        report_lines.append("=" * 60)
        
        # 全局统计
        global_stats = stats['global']
        report_lines.append(f"\n全局统计:")
        report_lines.append(f"  - 运行时间: {global_stats['uptime']:.2f}秒")
        report_lines.append(f"  - 总编译次数: {global_stats['total_compile_count']}")
        report_lines.append(f"  - 缓存命中率: {global_stats['total_cache_hits']/(global_stats['total_cache_hits']+global_stats['total_cache_misses'])*100:.1f}%")
        report_lines.append(f"  - 总匹配次数: {global_stats['total_match_count']}")
        report_lines.append(f"  - 总匹配时间: {global_stats['total_match_time']:.4f}秒")
        report_lines.append(f"  - 缓存正则数: {global_stats['cache_size']}")
        report_lines.append(f"  - 合并正则组: {global_stats['merged_patterns']}")
        
        # 各正则性能排序（按匹配时间）
        pattern_stats = stats['patterns']
        if pattern_stats:
            report_lines.append(f"\n正则性能排名（按总匹配时间）:")
            sorted_patterns = sorted(
                pattern_stats.items(),
                key=lambda x: x[1]['total_match_time'],
                reverse=True
            )
            
            for i, (name, stats) in enumerate(sorted_patterns[:10], 1):
                report_lines.append(f"  {i:2d}. {name:15s}: "
                                   f"匹配{stats['match_count']:6d}次, "
                                   f"总耗时{stats['total_match_time']:.4f}s, "
                                   f"平均{stats['avg_match_time']*1000:.2f}ms/次")
        
        # 合并正则信息
        if self._pattern_groups:
            report_lines.append(f"\n正则分组统计:")
            for group_name, patterns in self._pattern_groups.items():
                report_lines.append(f"  - {group_name:12s}: {len(patterns):2d}个正则")
        
        report_lines.append("=" * 60)
        
        return "\n".join(report_lines)
    
    def clear_cache(self):
        """清空缓存（保留统计信息）"""
        with self._manager_lock:
            self._compiled_cache.clear()
            self._merged_patterns.clear()
            self._global_stats['total_cache_hits'] = 0
            self._global_stats['total_cache_misses'] = 0
            logger.info("正则缓存已清空")


# ---------- 保持向后兼容的函数 ----------

# 单例实例
_pattern_manager_instance = None
_pattern_manager_lock = threading.RLock()

def get_pattern_manager() -> PatternManager:
    """获取PatternManager单例实例"""
    global _pattern_manager_instance
    with _pattern_manager_lock:
        if _pattern_manager_instance is None:
            _pattern_manager_instance = PatternManager()
        return _pattern_manager_instance

# 保持原有接口兼容性
@lru_cache(maxsize=128)
def compile_patterns(patterns_dict_str: str) -> Dict[str, re.Pattern]:
    """编译正则表达式（带字符串键的缓存）- 兼容原有代码"""
    patterns_dict = json.loads(patterns_dict_str)
    manager = get_pattern_manager()
    return manager.compile_patterns(patterns_dict)

def compile_patterns_dict(patterns_dict: Dict[str, str]) -> Dict[str, re.Pattern]:
    """编译正则表达式（直接使用字典）- 推荐新代码使用"""
    manager = get_pattern_manager()
    return manager.compile_patterns(patterns_dict)

def validate_regex(pattern: str) -> bool:
    """验证正则表达式有效性"""
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False

def test_regex(pattern: str, test_text: str) -> List[str]:
    """测试正则表达式"""
    manager = get_pattern_manager()
    valid, results = manager.test_pattern(pattern, test_text)
    return results if valid else []

def get_regex_stats() -> Dict:
    """获取正则统计信息"""
    manager = get_pattern_manager()
    return manager.get_pattern_stats()

def get_performance_report() -> str:
    """获取性能报告"""
    manager = get_pattern_manager()
    return manager.get_performance_report()
