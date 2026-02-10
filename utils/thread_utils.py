"""
utils/thread_utils.py - 修复版 v3
修复：
1. 文件统计在后台线程执行
2. match_found 信号节流
3. _on_completed 中所有 UI 操作通过信号转发到主线程（不直接操作 QTimer）
4. 删除死代码
"""
import threading
import time
from collections import deque
from typing import Optional, Callable
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from utils.log_utils import logger


class ScannerThreadManager(QObject):
    """扫描线程管理器（兼容原有接口）"""

    # ── 信号定义 ──
    progress_updated = pyqtSignal(int, int, int)
    scan_completed = pyqtSignal(list, dict)
    error_occurred = pyqtSignal(str)
    status_updated = pyqtSignal(str)
    file_counting = pyqtSignal()
    file_count_completed = pyqtSignal(int)
    current_file = pyqtSignal(str)
    match_found = pyqtSignal(str, str)

    # ✅ 新增：内部信号，用于后台线程安全地通知主线程做清理
    _internal_completed = pyqtSignal(list, dict)
    _internal_error = pyqtSignal(str)

    def __init__(self, scan_path_str: str, config_manager):
        super().__init__()
        self.scan_path_str = scan_path_str
        self.config_manager = config_manager
        self.scanner_manager = None
        self._stop_requested = False
        self._total_files = 0
        self._scanned_files = 0
        self._found_matches = 0
        self._counting_thread: Optional[threading.Thread] = None

        # ── 节流定时器（只在主线程操作！） ──
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._emit_progress)
        self._progress_timer.setInterval(100)

        self._file_timer = QTimer(self)
        self._file_timer.timeout.connect(self._emit_file)
        self._file_timer.setInterval(300)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._emit_status)
        self._status_timer.setInterval(500)

        self._match_timer = QTimer(self)
        self._match_timer.timeout.connect(self._emit_matches)
        self._match_timer.setInterval(200)

        # ── 缓存 ──
        self._progress_cache = None
        self._file_cache = None
        self._status_cache = None
        self._match_cache = deque(maxlen=500)
        self._match_lock = threading.Lock()

        # ✅ 连接内部信号 → 主线程处理完成/错误
        self._internal_completed.connect(self._handle_completed_in_main_thread)
        self._internal_error.connect(self._handle_error_in_main_thread)

    # ================================================================
    #  启动
    # ================================================================
    def start(self):
        """启动扫描（非阻塞）"""
        try:
            from core.scanner_manager import ScannerManager

            scan_paths = [p.strip() for p in self.scan_path_str.split(";") if p.strip()]
            if not scan_paths:
                self.error_occurred.emit("无有效扫描路径")
                return

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

            # 通知 UI 进入统计状态
            self.file_counting.emit()

            # 后台线程做统计 + 启动扫描
            self._counting_thread = threading.Thread(
                target=self._count_and_start_scan,
                args=(scan_paths,),
                daemon=True,
                name="FileCountingThread"
            )
            self._counting_thread.start()

        except Exception as e:
            logger.error(f"启动扫描失败: {e}", exc_info=True)
            self.error_occurred.emit(f"启动扫描失败: {str(e)[:200]}")

    def _count_and_start_scan(self, scan_paths):
        """后台线程：统计文件 + 启动扫描"""
        try:
            self._total_files = self._count_total_files_optimized(scan_paths)

            if self._total_files == 0:
                self.file_count_completed.emit(0)
                self.scan_completed.emit([], {"oversize": 0, "badsuffix": 0, "other": 0})
                return

            self.file_count_completed.emit(self._total_files)

            # ✅ 通过信号在主线程启动定时器
            from PyQt5.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(self, "_start_all_timers", Qt.QueuedConnection)

            # 启动扫描
            scan_settings = self.config_manager.get_scan_settings()
            max_file_size_mb = scan_settings.get("max_file_size_mb", 50)

            success = self.scanner_manager.start_scan(
                scan_paths=scan_paths,
                max_file_size_mb=max_file_size_mb
            )
            if not success:
                self._internal_error.emit("无法启动扫描，可能已有扫描任务在运行")

        except Exception as e:
            logger.error(f"文件统计/启动扫描失败: {e}", exc_info=True)
            self._internal_error.emit(f"启动扫描失败: {str(e)[:200]}")

    def _start_all_timers(self):
        """✅ 在主线程中启动所有定时器（通过 invokeMethod 调用）"""
        self._progress_timer.start()
        self._file_timer.start()
        self._status_timer.start()
        self._match_timer.start()

    def _count_total_files_optimized(self, scan_paths):
        """统计有效文件数"""
        import os
        from pathlib import Path

        skip_extensions = set(self.config_manager.get_skip_extensions())
        try:
            from config.constants import SKIP_NO_EXTENSION_FILES
            skip_no_extension = SKIP_NO_EXTENSION_FILES
        except ImportError:
            skip_no_extension = True

        total = 0
        skipped_count = 0

        for path_str in scan_paths:
            path = Path(path_str).resolve()
            if not path.exists():
                continue

            if path.is_file():
                suffix = path.suffix.lower()
                if skip_no_extension and not suffix:
                    skipped_count += 1
                elif suffix in skip_extensions:
                    skipped_count += 1
                else:
                    total += 1
            else:
                for root, dirs, files in os.walk(str(path)):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for file_name in files:
                        if file_name.startswith('.'):
                            continue
                        suffix = os.path.splitext(file_name)[1].lower()
                        if skip_no_extension and not suffix:
                            skipped_count += 1
                        elif suffix in skip_extensions:
                            skipped_count += 1
                        else:
                            total += 1

        logger.info(f"📊 统计完成，有效文件数: {total} (跳过了 {skipped_count} 个后缀不匹配的文件)")
        return total

    # ================================================================
    #  后台线程回调（只写缓存，不操作 Qt 对象！）
    # ================================================================
    def _on_progress(self, current, total, found):
        self._scanned_files = current
        self._found_matches = found
        actual_total = total if total > 0 else self._total_files
        self._progress_cache = (self._scanned_files, actual_total, self._found_matches)

    def _on_file_scanned(self, filename):
        self._file_cache = filename

    def _on_match_found(self, result):
        """✅ 只写缓存，不直接 emit"""
        from core.scan_models import ScanResult
        if isinstance(result, ScanResult):
            with self._match_lock:
                self._match_cache.append((result.file_path, result.match_content))

    def _on_batch_found(self, batch):
        pass

    def _on_status_changed(self, status):
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
        self._status_cache = status_map.get(status_text, status_text)

    def _on_completed(self, results, stats):
        """
        ✅ 核心修复：此方法在后台线程中被调用
        不直接操作 QTimer，通过信号转发到主线程
        """
        skip_counters = {
            "oversize": stats.get("large_files_skipped", 0),
            "badsuffix": max(0, stats.get("files_skipped", 0) - stats.get("large_files_skipped", 0)),
            "other": 0
        }
        # ✅ 通过 pyqtSignal 转发到主线程处理
        self._internal_completed.emit(results, skip_counters)

    def _on_error(self, error_msg):
        """✅ 通过信号转发到主线程"""
        self._internal_error.emit(error_msg)

    # ================================================================
    #  主线程槽函数（处理完成/错误）
    # ================================================================
    def _handle_completed_in_main_thread(self, results, skip_counters):
        """
        ✅ 在主线程中执行！安全操作 QTimer 和 emit 信号
        """
        # 1. 停止所有定时器（在主线程，安全！）
        self._stop_all_timers()

        # 2. flush 剩余的匹配缓存（限制数量，防止卡顿）
        max_flush = 50
        flushed = 0
        with self._match_lock:
            while self._match_cache and flushed < max_flush:
                fp, mc = self._match_cache.popleft()
                self.match_found.emit(fp, mc)
                flushed += 1
            remaining = len(self._match_cache)
            self._match_cache.clear()

        if remaining > 0:
            logger.info(f"完成时丢弃了 {remaining} 条未显示的匹配（已记录到结果中）")

        # 3. 发射最终进度
        total = max(self._total_files, self._scanned_files)
        self.progress_updated.emit(total, total, len(results))

        # 4. 发射完成信号
        self.scan_completed.emit(results, skip_counters)

    def _handle_error_in_main_thread(self, error_msg):
        """✅ 在主线程中处理错误"""
        self._stop_all_timers()
        self.error_occurred.emit(error_msg)

    # ================================================================
    #  定时器回调（在主线程执行）
    # ================================================================
    def _emit_progress(self):
        if self._progress_cache:
            current, total, found = self._progress_cache
            if total > 0 and current > total:
                current = total
            self.progress_updated.emit(current, total, found)

    def _emit_file(self):
        if self._file_cache:
            self.current_file.emit(self._file_cache)
            self._file_cache = None

    def _emit_status(self):
        if self._status_cache:
            self.status_updated.emit(self._status_cache)
            self._status_cache = None

    def _emit_matches(self):
        """每 200ms 最多发射 5 条匹配"""
        max_per_tick = 5
        emitted = 0
        with self._match_lock:
            while self._match_cache and emitted < max_per_tick:
                fp, mc = self._match_cache.popleft()
                self.match_found.emit(fp, mc)
                emitted += 1

    # ================================================================
    #  控制
    # ================================================================
    def _stop_all_timers(self):
        """✅ 只能在主线程调用！"""
        for timer in [self._progress_timer, self._file_timer,
                      self._status_timer, self._match_timer]:
            if timer.isActive():
                timer.stop()

    def stop(self):
        self._stop_requested = True
        if self.scanner_manager:
            self.scanner_manager.stop_scan()
        # ✅ stop() 是用户在 UI 点击触发的，一定在主线程
        self._stop_all_timers()

    def isRunning(self):
        counting = self._counting_thread is not None and self._counting_thread.is_alive()
        scanning = self.scanner_manager is not None and self.scanner_manager.is_scanning()
        return counting or scanning


# ─── 其他工具 ───
def run_in_background(func: Callable, callback: Optional[Callable] = None):
    def worker():
        try:
            result = func()
            if callback:
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
    def __init__(self, initial_value: int = 0):
        self._value = initial_value
        self._lock = threading.Lock()

    def increment(self, amount=1):
        with self._lock:
            self._value += amount
            return self._value

    def decrement(self, amount=1):
        with self._lock:
            self._value -= amount
            return self._value

    def get(self):
        with self._lock:
            return self._value

    def reset(self, new_value=0):
        with self._lock:
            self._value = new_value
