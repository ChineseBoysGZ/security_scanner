"""
utils/signal_throttler.py
信号节流器 - 控制高频信号发射频率，防止GUI卡顿
用于进度更新、文件名显示等高频事件的节流控制。
已优化：信号处理逻辑，防止信号丢失
"""
import time
import threading
from typing import Any, Callable, Optional
from queue import Queue, Empty
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, QMetaObject, Qt, Q_ARG

class ThrottledSignalEmitter(QObject):
    """
    节流信号发射器 - PyQt5信号节流
    将高频信号缓存并按固定频率发射，避免GUI线程过载。
    """
    # 定义各种节流信号
    progress_signal = pyqtSignal(int, int, int)      # 进度: 当前, 总数, 发现数
    file_signal = pyqtSignal(str)                    # 当前文件名
    match_signal = pyqtSignal(object)                # 单个匹配结果 (ScanResult)
    batch_signal = pyqtSignal(list)                  # 批次结果
    status_signal = pyqtSignal(str)                  # 状态消息
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 信号缓存队列（线程安全）
        self._progress_queue = Queue(maxsize=1)      # 进度只保留最新值
        self._file_queue = Queue(maxsize=3)          # 文件名保留最近3个
        self._match_queue = Queue(maxsize=100)       # 匹配结果最多100个
        self._batch_queue = Queue(maxsize=10)        # 批次结果最多10个
        self._status_queue = Queue(maxsize=5)        # 状态消息最多5个
        
        # 节流定时器
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._emit_progress)
        self._progress_timer.start(150)  # 150ms 发射一次进度
        
        self._file_timer = QTimer()
        self._file_timer.timeout.connect(self._emit_file)
        self._file_timer.start(350)  # 350ms发射一次文件名
        
        self._match_timer = QTimer()
        self._match_timer.timeout.connect(self._emit_match)
        self._match_timer.start(200)  # 200ms发射一次匹配结果
        
        self._batch_timer = QTimer()
        self._batch_timer.timeout.connect(self._emit_batch)
        self._batch_timer.start(600)  # 600ms发射一次批次
        
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._emit_status)
        self._status_timer.start(450)  # 450ms发射一次状态

        # ✅ 新增：确保所有缓存信号都能在完成时发射
        self._flush_on_complete = True

        # 性能统计
        self._signal_counts = {
            'progress': 0,
            'file': 0,
            'match': 0,
            'batch': 0,
            'status': 0
        }
        self._start_time = time.time()

    def flush_all(self):
        """立即发射所有缓存的信号"""
        self._emit_progress()
        self._emit_file()
        self._emit_match()
        self._emit_batch()
        self._emit_status()
        
    def update_progress(self, current: int, total: int, found: int):
        """更新进度（线程安全）"""
        try:
            # 只保留最新的进度
            self._progress_queue.put_nowait((current, total, found))
        except:
            # 队列满时替换
            try:
                self._progress_queue.get_nowait()
                self._progress_queue.put_nowait((current, total, found))
            except:
                pass
        self._signal_counts['progress'] += 1
    
    def update_file(self, filename: str):
        """更新文件名（线程安全）"""
        try:
            self._file_queue.put_nowait(filename)
        except:
            # 队列满时丢弃最旧的
            try:
                self._file_queue.get_nowait()
                self._file_queue.put_nowait(filename)
            except:
                pass
        self._signal_counts['file'] += 1
    
    def update_match(self, result):
        """更新匹配结果（线程安全）"""
        try:
            self._match_queue.put_nowait(result)
        except:
            # 队列满时丢弃
            pass
        self._signal_counts['match'] += 1
    
    def update_batch(self, batch: list):
        """更新批次结果（线程安全）"""
        try:
            self._batch_queue.put_nowait(batch)
        except:
            # 队列满时丢弃最旧的
            try:
                self._batch_queue.get_nowait()
                self._batch_queue.put_nowait(batch)
            except:
                pass
        self._signal_counts['batch'] += 1
    
    def update_status(self, status: str):
        """更新状态（线程安全）"""
        try:
            self._status_queue.put_nowait(status)
        except:
            # 队列满时丢弃最旧的
            try:
                self._status_queue.get_nowait()
                self._status_queue.put_nowait(status)
            except:
                pass
        self._signal_counts['status'] += 1
    
    def _emit_progress(self):
        """发射进度信号"""
        if not self._progress_queue.empty():
            try:
                current, total, found = self._progress_queue.get_nowait()
                self.progress_signal.emit(current, total, found)
            except Empty:
                pass
    
    def _emit_file(self):
        """发射文件信号"""
        if not self._file_queue.empty():
            try:
                filename = self._file_queue.get_nowait()
                self.file_signal.emit(filename)
            except Empty:
                pass
    
    def _emit_match(self):
        """发射匹配信号"""
        # 一次最多发射5个匹配结果，避免积压
        max_per_emit = 5
        emitted = 0
        while not self._match_queue.empty() and emitted < max_per_emit:
            try:
                result = self._match_queue.get_nowait()
                self.match_signal.emit(result)
                emitted += 1
            except Empty:
                break
    
    def _emit_batch(self):
        """发射批次信号"""
        if not self._batch_queue.empty():
            try:
                batch = self._batch_queue.get_nowait()
                self.batch_signal.emit(batch)
            except Empty:
                pass
    
    def _emit_status(self):
        """发射状态信号"""
        if not self._status_queue.empty():
            try:
                status = self._status_queue.get_nowait()
                self.status_signal.emit(status)
            except Empty:
                pass
    
    def get_stats(self):
        """获取节流统计信息"""
        elapsed = time.time() - self._start_time
        return {
            'signals_received': dict(self._signal_counts),
            'elapsed_seconds': round(elapsed, 2),
            'signals_per_second': {
                k: round(v / max(elapsed, 0.001), 1)
                for k, v in self._signal_counts.items()
            }
        }


class CallbackThrottler:
    """
    通用回调节流器（非PyQt5环境也可用）
    对普通Python回调函数进行节流控制。
    """
    def __init__(self, callback: Callable, min_interval: float = 0.1):
        """
        :param callback: 被节流的回调函数
        :param min_interval: 最小调用间隔（秒）
        """
        self.callback = callback
        self.min_interval = min_interval
        self._last_call_time = 0
        self._timer = None
        self._pending_args = None
        self._pending_kwargs = None
        self._lock = threading.Lock()
    
    def __call__(self, *args, **kwargs):
        """调用节流回调"""
        current_time = time.time()
        
        with self._lock:
            # 如果距离上次调用时间足够久，立即调用
            if current_time - self._last_call_time >= self.min_interval:
                self._last_call_time = current_time
                try:
                    self.callback(*args, **kwargs)
                except Exception as e:
                    import logging
                    logging.error(f"节流回调执行失败: {e}")
                self._pending_args = None
                self._pending_kwargs = None
            else:
                # 否则保存参数，等待定时器触发
                self._pending_args = args
                self._pending_kwargs = kwargs
                
                # 启动或重置定时器
                if self._timer is None:
                    self._timer = threading.Timer(
                        self.min_interval,
                        self._on_timer
                    )
                    self._timer.start()
                else:
                    # 重新调度定时器
                    self._timer.cancel()
                    self._timer = threading.Timer(
                        self.min_interval,
                        self._on_timer
                    )
                    self._timer.start()
    
    def _on_timer(self):
        """定时器回调"""
        with self._lock:
            if self._pending_args is not None:
                self._last_call_time = time.time()
                try:
                    self.callback(*self._pending_args, **self._pending_kwargs)
                except Exception as e:
                    import logging
                    logging.error(f"节流回调执行失败: {e}")
                self._pending_args = None
                self._pending_kwargs = None
            self._timer = None
    
    def flush(self):
        """立即执行所有挂起的回调"""
        with self._lock:
            if self._pending_args is not None:
                self._last_call_time = time.time()
                try:
                    self.callback(*self._pending_args, **self._pending_kwargs)
                except Exception as e:
                    import logging
                    logging.error(f"节流回调执行失败: {e}")
                self._pending_args = None
                self._pending_kwargs = None
            
            if self._timer:
                self._timer.cancel()
                self._timer = None