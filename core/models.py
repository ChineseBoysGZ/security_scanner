"""
core/models.py - 增强数据模型
统一的数据模型定义，集成所有优化功能。
"""
import os
import re
import time
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, ClassVar
from datetime import datetime
from enum import Enum, auto


# -------------------------- 枚举定义 --------------------------
class ScanState(Enum):
    """扫描状态枚举"""
    IDLE = auto()
    PREPARING = auto()
    COUNTING = auto()
    SCANNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    COMPLETED = auto()
    ERROR = auto()


class SeverityLevel(Enum):
    """严重性级别枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    
    @classmethod
    def from_rule_name(cls, rule_name: str) -> 'SeverityLevel':
        """根据规则名称推断严重性级别"""
        rule_lower = rule_name.lower()
        
        if any(kw in rule_lower for kw in ['password', 'secret', 'key', 'token', 'credential', 'auth']):
            return cls.HIGH
        elif any(kw in rule_lower for kw in ['email', 'phone', 'id', '身份证', '手机', '邮箱']):
            return cls.MEDIUM
        elif any(kw in rule_lower for kw in ['name', 'user', '地址', 'username']):
            return cls.LOW
        else:
            return cls.MEDIUM  # 默认中等


# -------------------------- 数据模型 --------------------------
@dataclass
class RegexRule:
    """正则规则数据模型"""
    name: str          # 规则名称
    pattern: str       # 正则表达式
    is_valid: bool = True  # 是否有效
    enabled: bool = True   # 是否启用
    description: str = ""  # 规则描述
    category: str = ""     # 规则分类
    
    # 性能统计
    usage_count: int = 0   # 使用次数
    last_used: Optional[float] = None  # 最后使用时间
    
    def mark_used(self):
        """标记使用"""
        self.usage_count += 1
        self.last_used = time.time()


@dataclass
class ScanResult:
    """
    增强版扫描结果模型
    包含所有必要的字段和性能优化功能。
    """
    # ----- 核心字段（必须保留） -----
    rule_name: str           # 匹配规则
    file_path: str          # 文件路径
    match_content: str      # 匹配内容
    line_num: int           # 行号
    app_id: str = ""        # 应用ID
    
    # ----- 增强字段 -----
    severity: str = field(default="medium")  # 严重性级别
    match_hash: str = field(init=False)      # 匹配内容哈希（用于去重）
    file_size: Optional[int] = None          # 文件大小（字节）
    file_encoding: Optional[str] = None      # 文件编码
    timestamp: float = field(default_factory=time.time)  # 时间戳
    
    # ----- 上下文信息 -----
    context_before: str = ""    # 匹配行前的内容
    context_after: str = ""     # 匹配行后的内容
    matched_pattern: str = ""   # 实际匹配到的模式
    
    # ----- 性能优化 -----
    _hash_cache: ClassVar[Dict[str, str]] = {}  # 哈希缓存
    
    def __post_init__(self):
        """初始化后处理"""
        # 1. 自动评估严重性
        if self.severity == "medium":  # 如果未明确设置
            self.severity = SeverityLevel.from_rule_name(self.rule_name).value
        
        # 2. 计算哈希（用于去重）
        self.match_hash = self._calculate_hash()
        
        # 3. 截断过长的匹配内容
        if len(self.match_content) > 1000:
            self.match_content = self.match_content[:1000] + "...【内容过长已截断】"
        
        # 4. 自动获取文件大小（如果可能）
        if self.file_size is None and os.path.exists(self.file_path):
            try:
                self.file_size = os.path.getsize(self.file_path)
            except (OSError, PermissionError):
                self.file_size = 0
    
    def _calculate_hash(self) -> str:
        """计算唯一哈希值（带缓存）"""
        # 使用文件路径、行号和匹配内容作为哈希基础
        key = f"{self.file_path}:{self.line_num}:{self.match_content}"
        
        if key in self._hash_cache:
            return self._hash_cache[key]
        
        # 计算MD5哈希（前16位足够唯一）
        hash_obj = hashlib.md5(key.encode())
        hash_hex = hash_obj.hexdigest()[:16]
        
        self._hash_cache[key] = hash_hex
        return hash_hex
    
    @property
    def filename(self) -> str:
        """获取文件名（不含路径）"""
        return os.path.basename(self.file_path)
    
    @property
    def directory(self) -> str:
        """获取文件所在目录"""
        return os.path.dirname(self.file_path)
    
    @property
    def formatted_time(self) -> str:
        """格式化时间戳"""
        return datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    @property
    def formatted_size(self) -> str:
        """格式化文件大小"""
        if not self.file_size:
            return "0B"
        
        units = ['B', 'KB', 'MB', 'GB']
        size = float(self.file_size)
        unit_index = 0
        
        while size >= 1024 and unit_index < 3:
            size /= 1024
            unit_index += 1
        
        return f"{size:.1f}{units[unit_index]}"
    
    @property
    def severity_display(self) -> str:
        """严重性显示文本"""
        severity_map = {
            "low": "低",
            "medium": "中",
            "high": "高",
            "critical": "严重"
        }
        return severity_map.get(self.severity, "中")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        
        # 添加派生属性
        data.update({
            "filename": self.filename,
            "directory": self.directory,
            "formatted_time": self.formatted_time,
            "formatted_size": self.formatted_size,
            "severity_display": self.severity_display
        })
        
        return data
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    def to_excel_row(self, headers: List[str]) -> List[Any]:
        """转换为Excel行数据"""
        row = []
        
        for header in headers:
            header_lower = header.lower()
            
            if '规则' in header or 'rule' in header_lower:
                row.append(self.rule_name)
            elif '路径' in header or 'path' in header_lower:
                row.append(self.file_path)
            elif '内容' in header or 'content' in header_lower or '匹配' in header:
                row.append(self.match_content)
            elif '应用' in header or 'app' in header_lower:
                row.append(self.app_id)
            elif '行号' in header or 'line' in header_lower:
                row.append(self.line_num)
            elif '严重' in header or 'severity' in header_lower:
                row.append(self.severity_display)
            elif '大小' in header or 'size' in header_lower:
                row.append(self.formatted_size)
            elif '时间' in header or 'time' in header_lower:
                row.append(self.formatted_time)
            elif '目录' in header or 'directory' in header_lower:
                row.append(self.directory)
            elif '文件名' in header or 'filename' in header_lower:
                row.append(self.filename)
            else:
                row.append("")  # 空列
        
        return row
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScanResult':
        """从字典创建实例"""
        # 过滤掉派生字段
        base_fields = {
            'rule_name', 'file_path', 'match_content', 'line_num', 'app_id',
            'severity', 'file_size', 'file_encoding', 'timestamp',
            'context_before', 'context_after', 'matched_pattern'
        }
        
        filtered_data = {k: v for k, v in data.items() if k in base_fields}
        return cls(**filtered_data)


@dataclass
class ScanStats:
    """扫描统计信息"""
    total_files: int = 0          # 总文件数
    scanned_files: int = 0        # 已扫描文件数
    skipped_files: int = 0        # 跳过文件数
    matches_found: int = 0        # 发现匹配数
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    # 性能统计
    large_files_skipped: int = 0  # 跳过大文件数
    memory_usage_mb: float = 0.0  # 内存使用(MB)
    cpu_percent: float = 0.0      # CPU使用率
    
    def complete(self):
        """标记扫描完成"""
        self.end_time = time.time()
    
    @property
    def elapsed_seconds(self) -> float:
        """已用时间（秒）"""
        end = self.end_time or time.time()
        return end - self.start_time
    
    @property
    def files_per_second(self) -> float:
        """扫描速度（文件/秒）"""
        elapsed = self.elapsed_seconds
        if elapsed == 0:
            return 0
        return self.scanned_files / elapsed
    
    @property
    def match_rate(self) -> float:
        """匹配率（匹配数/扫描文件数）"""
        if self.scanned_files == 0:
            return 0
        return self.matches_found / self.scanned_files
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_files": self.total_files,
            "scanned_files": self.scanned_files,
            "skipped_files": self.skipped_files,
            "matches_found": self.matches_found,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "files_per_second": round(self.files_per_second, 2),
            "match_rate": round(self.match_rate, 4),
            "large_files_skipped": self.large_files_skipped,
            "memory_usage_mb": round(self.memory_usage_mb, 2),
            "cpu_percent": round(self.cpu_percent, 1)
        }
    
    def summary(self) -> str:
        """生成统计摘要"""
        elapsed = self.elapsed_seconds
        minutes, seconds = divmod(elapsed, 60)
        
        return (
            f"扫描统计:\n"
            f"总耗时: {int(minutes)}分{seconds:.1f}秒\n"
            f"扫描文件: {self.scanned_files}/{self.total_files}\n"
            f"跳过文件: {self.skipped_files}\n"
            f"发现匹配: {self.matches_found}\n"
            f"扫描速度: {self.files_per_second:.1f} 文件/秒\n"
            f"匹配率: {self.match_rate:.2%}"
        )


# -------------------------- 工具函数 --------------------------
def extract_app_id(file_path: str) -> str:
    """
    从文件路径中提取应用ID
    规则：online/或online\后面、_all_all前面的内容
    """
    pattern = re.compile(r'online[\\/](.*?)_all_all', re.IGNORECASE)
    match = pattern.search(file_path)
    return match.group(1).strip() if match else ""


def create_scan_result(
    rule_name: str,
    file_path: str,
    match_content: str,
    line_num: int,
    app_id: Optional[str] = None
) -> ScanResult:
    """
    创建扫描结果的快捷函数
    """
    if app_id is None:
        app_id = extract_app_id(file_path)
    
    return ScanResult(
        rule_name=rule_name,
        file_path=file_path,
        match_content=match_content,
        line_num=line_num,
        app_id=app_id
    )