"""
utils/thread_utils.py - 简化版（解决循环导入）
线程工具模块（兼容层）- 为现有UI代码提供兼容接口。
使用延迟导入解决循环依赖问题。
已修复：
1.进度统计准确性问题 
2.信号节流逻辑优化
"""
import threading
import time
from typing import Optional, Callable
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from utils.log_utils import logger

# -------------------------- 简化的工作线程（兼容原有接口） --------------------------
class ScannerThreadManager(QObject):
    """
    扫描线程管理器（兼容原有接口）
    为现有的 scan_page.py 提供完全兼容的接口。
    使用延迟导入解决循环依赖问题。
    修复进度统计问题
    """
    # 必须保持原有信号名称和签名
    progress_updated = pyqtSignal(int, int, int)      # (current, total, found)
    scan_completed = pyqtSignal(list, dict)           # (results, skip_counters)
    error_occurred = pyqtSignal(str)
    status_updated = pyqtSignal(str)
    file_counting = pyqtSignal()                      # 开始统计文件
    file_count_completed = pyqtSignal(int)            # 统计完成，总文件数
    current_file = pyqtSignal(str)                    # 当前扫描的文件名
    match_found = pyqtSignal(str, str)                # (file_path, match_content)
    
    def __init__(self, scan_path_str: str, config_manager):
        super().__init__()
        self.scan_path_str = scan_path_str
        self.config_manager = config_manager
        self.scanner_manager = None
        self._stop_requested = False
        self._total_files = 0   # 缓存总文件数
        self._scanned_files = 0
        self._found_matches = 0 

        # ✅ 修复：使用QTimer进行节流，避免手动节流导致信号丢失
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._emit_progress)
        self._progress_timer.setInterval(100)  # 100ms
        
        self._file_timer = QTimer()
        self._file_timer.timeout.connect(self._emit_file)
        self._file_timer.setInterval(300)  # 300ms
        
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._emit_status)
        self._status_timer.setInterval(500)  # 500ms

        # 缓存队列
        self._progress_cache = None
        self._file_cache = None
        self._status_cache = None

    def start(self):
        """启动扫描（非阻塞）- 使用延迟导入"""
        try:
            # 延迟导入，避免循环
            from core.scanner_manager import ScannerManager
            
            # 分割扫描路径
            scan_paths = [p.strip() for p in self.scan_path_str.split(";") if p.strip()]
            if not scan_paths:
                self.error_occurred.emit("无有效扫描路径")
                return
            
            # 创建 ScannerManager
            self.scanner_manager = ScannerManager(self.config_manager)
            self._stop_requested = False
            self._scanned_files = 0
            self._found_matches = 0
            
            # 注册回调
            self.scanner_manager.register_callback('progress', self._on_progress)
            self.scanner_manager.register_callback('file_scanned', self._on_file_scanned)
            self.scanner_manager.register_callback('match_found', self._on_match_found)
            self.scanner_manager.register_callback('status_changed', self._on_status_changed)
            self.scanner_manager.register_callback('completed', self._on_completed)
            self.scanner_manager.register_callback('error', self._on_error)
            self.scanner_manager.register_callback('batch_found', self._on_batch_found)
            
            # ✅ 修复：先统计总文件数，确保准确性
            self.file_counting.emit()
            self._total_files = self._count_total_files_optimized(scan_paths)

            # ✅ 关键修复：如果总文件数为0，直接完成
            if self._total_files == 0:
                self.file_count_completed.emit(0)
                self.scan_completed.emit([], {"oversize": 0, "badsuffix": 0, "other": 0})
                return
                
            self.file_count_completed.emit(self._total_files)

            # 启动节流定时器
            self._progress_timer.start()
            self._file_timer.start()
            self._status_timer.start()

            # 获取配置参数
            scan_settings = self.config_manager.get_scan_settings()
            max_file_size_mb = scan_settings.get("max_file_size_mb", 50)

            # 启动扫描
            success = self.scanner_manager.start_scan(
                scan_paths=scan_paths,
                max_file_size_mb=max_file_size_mb
            )

            if not success:
                self.error_occurred.emit("无法启动扫描，可能已有扫描任务在运行")
                
        except Exception as e:
            logger.error(f"启动扫描失败: {e}", exc_info=True)
            self.error_occurred.emit(f"启动扫描失败: {str(e)[:200]}")
    
    def _count_total_files_optimized(self, scan_paths):
        """
        优化版的总文件数统计
        ✅ 修复：与扫描引擎使用完全相同的跳过规则
        """
        import os
        from pathlib import Path
        
        # 获取配置
        skip_extensions = set(self.config_manager.get_skip_extensions())
        
        try:
            from config.constants import SKIP_NO_EXTENSION_FILES
            skip_no_extension = SKIP_NO_EXTENSION_FILES
        except ImportError:
            skip_no_extension = True
        
        total = 0
        skipped_info = []
        
        for path_str in scan_paths:
            path = Path(path_str).resolve()
            if not path.exists():
                continue
            
            if path.is_file():
                # ✅ 修复：使用与扫描引擎完全相同的跳过逻辑
                suffix = path.suffix.lower()
                
                # 检查是否跳过
                should_skip = False
                reason = ""
                
                if skip_no_extension and not suffix:
                    should_skip = True
                    reason = "无后缀文件"
                elif suffix in skip_extensions:
                    should_skip = True
                    reason = f"跳过后缀: {suffix}"
                
                if should_skip:
                    skipped_info.append((str(path), reason))
                else:
                    total += 1
            else:
                # 递归统计目录
                for root, dirs, files in os.walk(str(path)):
                    # 过滤隐藏文件和目录
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    files = [f for f in files if not f.startswith('.')]
                    
                    for file in files:
                        file_path = Path(os.path.join(root, file))
                        suffix = file_path.suffix.lower()
                        
                        # ✅ 修复：使用与扫描引擎完全相同的跳过逻辑
                        should_skip = False
                        reason = ""
                        
                        if skip_no_extension and not suffix:
                            should_skip = True
                            reason = "无后缀文件"
                        elif suffix in skip_extensions:
                            should_skip = True
                            reason = f"跳过后缀: {suffix}"
                        
                        if should_skip:
                            skipped_info.append((str(file_path), reason))
                        else:
                            total += 1
        
        # 记录跳过信息
        if skipped_info:
            logger.info(f"📊 统计阶段根据后缀规则跳过了 {len(skipped_info)} 个文件")
            if len(skipped_info) <= 20:
                for file_path, reason in skipped_info:
                    logger.debug(f"  └ {reason}: {os.path.basename(file_path)}")
        
        logger.info(f"📊 统计完成，有效文件数: {total} (跳过了 {len(skipped_info)} 个后缀不匹配的文件)")
        return total
    
    def _on_progress(self, current: int, total: int, found: int):
        """
        处理进度回调
        使用缓存和定时器节流
        """
        # ✅ 修复：更新内部计数
        self._scanned_files = current
        self._found_matches = found

        # 使用正确的总数（优先使用引擎返回的，否则用统计的）
        actual_total = total if total > 0 else self._total_files
        
        # 缓存最新进度
        self._progress_cache = (self._scanned_files, actual_total, self._found_matches)

    def _emit_progress(self):
        """定时器回调：发射进度信号"""
        if self._progress_cache:
            current, total, found = self._progress_cache
            
            # ✅ 关键修复：确保进度不会超过100%
            if total > 0 and current > total:
                current = total
            
            self.progress_updated.emit(current, total, found)

    def _flush_progress_update(self):
        """刷新缓存的进度更新"""
        if self._pending_progress:
            current, total, found = self._pending_progress
            self.progress_updated.emit(current, total, found)
            self._pending_progress = None

    def _on_file_scanned(self, filename: str):
        """处理文件扫描回调"""
        self._file_cache = filename

    def _emit_file(self):
        """定时器回调：发射文件信号"""
        if self._file_cache:
            self.current_file.emit(self._file_cache)
            self._file_cache = None

    def _flush_file_update(self):
        """刷新缓存的文件更新"""
        if self._pending_file:
            self.current_file.emit(self._pending_file)
            self._pending_file = ""
    
    def _on_match_found(self, result):
        """处理匹配结果回调"""
        from core.scan_models import ScanResult
        
        if isinstance(result, ScanResult):
            # 直接发射，不节流（匹配结果相对较少）
            self.match_found.emit(result.file_path, result.match_content)
    
    def _on_batch_found(self, batch):
        """处理批次结果回调（不发射信号，只用于内部处理）"""
        # 可以在这里添加批量处理逻辑
        pass

    def _on_status_changed(self, status):
        """处理状态变更回调（手动节流）"""
        if hasattr(status, 'name'):
            status_text = status.name
        else:
            status_text = str(status)
        
        status_map = {
            'PREPARING': '正在准备扫描...',
            'COUNTING': '正在统计文件...',
            'SCANNING': '扫描中...',
            'PAUSED': '已暂停',
            'STOPPING': '正在停止...',
            'COMPLETED': '扫描完成',
            'ERROR': '扫描出错'
        }
        
        display_text = status_map.get(status_text, status_text)
        self._status_cache = display_text

    def _emit_status(self):
        """定时器回调：发射状态信号"""
        if self._status_cache:
            self.status_updated.emit(self._status_cache)
            self._status_cache = None

    def _on_completed(self, results, stats):
        """处理扫描完成回调"""
        # 停止所有节流定时器
        self._progress_timer.stop()
        self._file_timer.stop()
        self._status_timer.stop()
        
        # ✅ 修复：确保最终进度显示100%
        actual_total = max(stats.get("files_discovered", 0), self._total_files)
        
        # 发射最终进度信号
        self.progress_updated.emit(actual_total, actual_total, len(results))
        
        # 构建skip_counters
        skip_counters = {
            "oversize": stats.get("large_files_skipped", 0),
            "badsuffix": stats.get("files_skipped", 0) - stats.get("large_files_skipped", 0),
            "other": 0
        }
        
        # 发送完成信号
        self.scan_completed.emit(results, skip_counters)
    
    def _flush_pending_signals(self):
        """刷新所有缓存的信号"""
        if self._pending_progress:
            current, total, found = self._pending_progress
            self.progress_updated.emit(current, total, found)
            self._pending_progress = None
        
        if self._pending_file:
            self.current_file.emit(self._pending_file)
            self._pending_file = None
        
        if self._pending_status:
            self.status_updated.emit(self._pending_status)
            self._pending_status = None
    
    def _on_error(self, error_msg: str):
        """处理错误回调"""
        # 停止定时器
        self._progress_timer.stop()
        self._file_timer.stop()
        self._status_timer.stop()
        
        self.error_occurred.emit(error_msg)
        
    def stop(self):
        """停止扫描"""
        self._stop_requested = True
        if self.scanner_manager:
            self.scanner_manager.stop_scan()
        
        # 停止定时器
        self._progress_timer.stop()
        self._file_timer.stop()
        self._status_timer.stop()
    
    def isRunning(self) -> bool:
        """检查是否正在运行"""
        return self.scanner_manager and self.scanner_manager.is_scanning()

# -------------------------- 其他线程工具函数 --------------------------
def run_in_background(func: Callable, callback: Optional[Callable] = None):
    """
    在后台线程中运行函数（通用工具）
    
    :param func: 要在后台运行的函数
    :param callback: 完成后在主线程调用的回调
    """
    def worker():
        try:
            result = func()
            if callback:
                # 使用Qt的机制在主线程执行回调
                from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    callback.__self__ if hasattr(callback, '__self__') else callback,
                    callback.__name__ if hasattr(callback, '__name__') else '',
                    Qt.QueuedConnection,
                    Q_ARG(object, result) if result is not None else ()
                )
        except Exception as e:
            logger.error(f"后台任务执行失败: {e}")
    
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


class ThreadSafeCounter:
    """线程安全的计数器"""
    def __init__(self, initial_value: int = 0):
        self._value = initial_value
        self._lock = threading.Lock()
    
    def increment(self, amount: int = 1) -> int:
        """增加计数值并返回新值"""
        with self._lock:
            self._value += amount
            return self._value
    
    def decrement(self, amount: int = 1) -> int:
        """减少计数值并返回新值"""
        with self._lock:
            self._value -= amount
            return self._value
    
    def get(self) -> int:
        """获取当前值"""
        with self._lock:
            return self._value
    
    def reset(self, new_value: int = 0):
        """重置计数器"""
        with self._lock:
            self._value = new_value

