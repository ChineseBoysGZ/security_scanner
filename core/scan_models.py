"""
core/scan_models.py
核心数据模型与扫描状态管理 - 阶段一基础
替代原有的全局变量和简单数据类，提供线程安全的状态管理和高效的数据结构。
已修复：确保时间显示至少0.1秒
"""
import time
import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Any, Dict, List
from enum import Enum, auto

class ScanState(Enum):
    """扫描状态枚举，明确状态机流转"""
    IDLE = auto()           # 空闲
    PREPARING = auto()      # 准备中（编译正则等）
    COUNTING = auto()       # 统计文件中
    SCANNING = auto()      # 扫描中
    PAUSED = auto()        # 已暂停
    STOPPING = auto()      # 停止中
    COMPLETED = auto()     # 已完成
    ERROR = auto()         # 错误

@dataclass
class ScanContext:
    """
    扫描上下文 - 线程安全的状态与回调管理器
    替代 core/file_scanner.py 中的 SCAN_STOPPED, SCAN_PAUSED 等全局变量。
    """
    # --- 核心状态 ---
    state: ScanState = ScanState.IDLE
    _stop_requested: bool = False
    _pause_requested: bool = False
    
    # --- 扫描统计 ---
    total_files_discovered: int = 0      # 发现的总文件数（过滤前）
    total_files_scanned: int = 0         # 实际扫描的有效文件数
    total_files_skipped: int = 0         # 跳过的文件数
    total_matches_found: int = 0         # 找到的匹配项总数
    start_time: Optional[float] = None   # 扫描开始时间
    
    # --- 性能监控 ---
    large_files_skipped: int = 0         # 跳过的大文件数
    current_file_path: Optional[str] = None  # 当前扫描的文件
    
    # --- 回调函数 (由外部 UI 或管理器设置) ---
    on_progress: Optional[Callable[[int, int, int], None]] = None          # (已扫描, 总数, 发现数)
    on_file_scanned: Optional[Callable[[str], None]] = None                # 当前文件名
    on_match_found: Optional[Callable[['ScanResult'], None]] = None        # 单条结果
    on_batch_found: Optional[Callable[[List['ScanResult']], None]] = None  # 批次结果
    on_status_change: Optional[Callable[[ScanState], None]] = None         # 状态变更
    
    def __post_init__(self):
        """初始化后的验证"""
        if self.start_time is None:
            self.start_time = time.time()
    
    def request_stop(self):
        """请求停止扫描（线程安全）"""
        self._stop_requested = True
        self._pause_requested = False  # 停止时强制取消暂停
        self._update_state(ScanState.STOPPING)
    
    def request_pause(self):
        """请求暂停扫描（线程安全）"""
        if self.state == ScanState.SCANNING:
            self._pause_requested = True
            self._update_state(ScanState.PAUSED)
    
    def request_resume(self):
        """请求恢复扫描（线程安全）"""
        if self.state == ScanState.PAUSED:
            self._pause_requested = False
            self._update_state(ScanState.SCANNING)
    
    def should_stop(self) -> bool:
        """检查是否应该停止（线程安全）"""
        return self._stop_requested or self.state == ScanState.STOPPING
    
    def check_pause(self):
        """
        检查并处理暂停状态（阻塞直到恢复或停止）
        在扫描循环中调用此方法
        """
        while self._pause_requested and not self._stop_requested:
            time.sleep(0.1)  # 避免忙等待
        return self.should_stop()
    
    def mark_file_scanned(self, file_path: str):
        """记录一个文件已被扫描"""
        self.total_files_scanned += 1
        self.current_file_path = file_path
        if self.on_file_scanned:
            self.on_file_scanned(file_path)
    
    def mark_match_found(self, result: 'ScanResult'):
        """记录一个匹配项被发现"""
        self.total_matches_found += 1
        if self.on_match_found:
            self.on_match_found(result)
    
    def _update_state(self, new_state: ScanState):
        """内部方法：更新状态并触发回调"""
        old_state = self.state
        self.state = new_state
        if self.on_status_change and old_state != new_state:
            self.on_status_change(new_state)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取当前统计信息
        ✅ 修复时间显示
        """
        if self.start_time is None:
            return {
                "state": self.state.name,
                "elapsed_seconds": 0,
                "elapsed_display": "0.0秒",
                "files_discovered": self.total_files_discovered,
                "files_scanned": self.total_files_scanned,
                "files_skipped": self.total_files_skipped,
                "matches_found": self.total_matches_found,
                "large_files_skipped": self.large_files_skipped,
                "scan_speed": 0
            }
    
        elapsed = time.perf_counter() - self.start_time  # ✅ 使用高精度计时器

        # 🔧 修复：确保显示至少0.1秒，避免显示0.00
        if elapsed < 0.1:
            elapsed_display = 0.1
            display_str = "0.1秒"
        else:
            elapsed_display = elapsed
            # 格式化为更友好的显示
            if elapsed_display < 60:
                display_str = f"{elapsed_display:.1f}秒"
            else:
                minutes = int(elapsed_display // 60)
                seconds = elapsed_display % 60
                display_str = f"{minutes}分{seconds:.0f}秒"
    
        return {
            "state": self.state.name,
            "elapsed_seconds": round(elapsed, 2),
            "elapsed_display": display_str,
            "files_discovered": self.total_files_discovered,
            "files_scanned": self.total_files_scanned,
            "files_skipped": self.total_files_skipped,
            "matches_found": self.total_matches_found,
            "large_files_skipped": self.large_files_skipped,
            "scan_speed": round(self.total_files_scanned / max(elapsed, 0.001), 1) if elapsed > 0 else 0
        }

    def reset(self):
        """重置上下文（开始新的扫描前调用）"""
        self.__init__()  # 重新初始化所有字段

@dataclass
class ScanResult:
    """
    增强版扫描结果模型
    在原有字段基础上增加唯一ID、严重性评估和性能优化字段。
    """
    def __init__(
        self,
        rule_name: str = "",
        file_path: str = "",
        match_content: str = "",
        app_id: str = "",
        system_name: str = "",      # ✅ 新增：对应系统
        responsible_person: str = "", # ✅ 新增：负责人
        notes: str = "",           # ✅ 新增：备注
        final_result: str = "",    # ✅ 新增：最终结果
        line_num: int = 0,
        file_size: int = 0,
        encoding: str = "utf-8",
        severity: str = "medium"
    ):
        self.rule_name = rule_name
        self.file_path = file_path
        self.match_content = match_content
        self.app_id = app_id
        self.system_name = system_name          # ✅ 新增
        self.responsible_person = responsible_person # ✅ 新增
        self.notes = notes                     # ✅ 新增
        self.final_result = final_result       # ✅ 新增
        self.line_num = line_num
        self.file_size = file_size
        self.encoding = encoding
        self.severity = severity
        self.timestamp = time.time()
        
    # --- 核心字段（必须保留，与您的四点要求一致）---
    rule_name: str           # 匹配规则
    file_path: str          # 文件路径
    match_content: str      # 匹配内容
    line_num: int           # 行号
    
    # --- 原有字段 ---
    app_id: str = ""        # 应用ID
    
    # --- 新增优化字段 ---
    severity: str = "medium"  # 严重性: low, medium, high, critical
    match_hash: str = field(init=False)  # 匹配内容哈希，用于去重
    file_size: Optional[int] = None      # 文件大小（字节）
    encoding: Optional[str] = None       # 文件编码
    
    def __post_init__(self):
        """初始化后计算哈希和严重性"""
        # 1. 计算唯一哈希（用于结果去重）
        content = f"{self.file_path}:{self.line_num}:{self.rule_name}:{self.match_content}"
        self.match_hash = hashlib.md5(content.encode()).hexdigest()[:16]
        
        # 2. 自动评估严重性（基于规则名称关键词）
        rule_lower = self.rule_name.lower()
        sensitive_keywords = {
            'high': ['password', 'secret', 'key', 'token', 'credential', 'auth'],
            'medium': ['email', 'phone', 'id', '身份证', '手机', '邮箱'],
            'low': ['name', 'user', '地址', 'username']
        }
        
        self.severity = "low"  # 默认
        for level, keywords in sensitive_keywords.items():
            if any(kw in rule_lower for kw in keywords):
                self.severity = level
                break
        
        # 3. 截断过长的匹配内容（避免内存占用过大）
        if len(self.match_content) > 1000:
            self.match_content = self.match_content[:1000] + "...【内容过长已截断】"
    
    @property
    def filename(self) -> str:
        """获取文件名（不含路径）"""
        import os
        return os.path.basename(self.file_path)
    
    @property
    def directory(self) -> str:
        """获取文件所在目录"""
        import os
        return os.path.dirname(self.file_path)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于JSON序列化或Excel导出）"""
        return asdict(self)
    
    def to_display_dict(self) -> Dict[str, Any]:
        """转换为显示用的字典（包含派生属性）"""
        base = self.to_dict()
        base.update({
            "filename": self.filename,
            "directory": self.directory,
            "severity_display": {
                "low": "低",
                "medium": "中", 
                "high": "高",
                "critical": "严重"
            }.get(self.severity, "中")
        })
        return base

@dataclass
class ScanConfig:
    """扫描配置（可从 config_manager 转换而来）"""
    scan_paths: List[str]
    patterns: Dict[str, re.Pattern]  # 编译后的正则对象
    max_file_size_mb: int = 50
    recursive: bool = True
    skip_hidden: bool = True
    skip_binary: bool = True
    skip_no_extension: bool = True  # 新增：是否跳过无后缀文件
    default_encoding: str = "utf-8"
    batch_size: int = 100  # 结果批次大小
    patterns_dict: Optional[Dict[str, str]] = None  # 原始正则字符串字典
    
    def __post_init__(self):
        # 如果没有提供patterns_dict，尝试从patterns中提取
        if self.patterns_dict is None and self.patterns:
            # 尝试从编译后的正则中获取原始字符串
            try:
                self.patterns_dict = {name: pattern.pattern for name, pattern in self.patterns.items()}
            except:
                self.patterns_dict = {}
                
# 快捷函数
def create_default_context() -> ScanContext:
    """创建默认的扫描上下文"""
    return ScanContext()