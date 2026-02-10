"""
core/scanner_manager.py
扫描管理器 - 协调扫描、正则、导出，提供高级API
移除对ConfigManager的直接导入，避免循环依赖。
集成优化的扫描引擎，消除重复统计
"""
import threading
import time
from typing import Dict, List, Optional, Callable, Any
from queue import Queue
import logging

from .scanner_engine import ScannerEngine
from .scan_models import ScanContext, ScanResult, ScanState, ScanConfig
from .regex_manager import PatternManager
from .excel_exporter import ExcelExporter
from utils.log_utils import logger

class ScannerManager:
    """
    扫描管理器 - 高级协调器
    负责：
    1. 管理扫描生命周期（启动、暂停、停止）
    2. 协调扫描引擎、正则管理器、导出器
    3. 提供线程安全的回调机制
    4. 实现结果分批处理和内存控制
    优化点：
    1. 移除重复的文件统计
    2. 集成新的ScannerEngine
    3. 优化进度更新逻辑
    """
    
    def __init__(self, config_manager):
        """
        初始化扫描管理器
        :param config_manager: ConfigManager实例
        """
        
        self.config_manager = config_manager
        self.engine: Optional[ScannerEngine] = None
        self.context: Optional[ScanContext] = None
        
        # 线程控制
        self._scan_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None  # 监控线程
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._context_ready_event = threading.Event()  # 上下文就绪事件
        self._lock = threading.RLock()
        
        # 结果管理
        self.results_queue = Queue(maxsize=1000)  # 线程安全的结果队列
        self.batch_size = 100  # 批次大小
        self.current_batch: List[ScanResult] = []
        
        # 性能监控
        self.scan_start_time: Optional[float] = None
        self.last_progress_time: Optional[float] = None
        
        # 回调注册
        self._callbacks = {
            'progress': [],
            'file_scanned': [],
            'match_found': [],
            'batch_found': [],
            'status_changed': [],
            'completed': [],
            'error': []
        }
    
    def register_callback(self, event_type: str, callback: Callable):
        """注册事件回调"""
        with self._lock:
            if event_type in self._callbacks:
                self._callbacks[event_type].append(callback)
    
    def _emit_event(self, event_type: str, *args, **kwargs):
        """触发事件回调 - ✅ 添加安全保护"""
        with self._lock:
            callbacks = list(self._callbacks.get(event_type, []))  # ✅ 复制列表，防止迭代中修改
        
        for callback in callbacks:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"回调函数执行失败 [{event_type}]: {e}")
    
    def start_scan(
        self,
        scan_paths: List[str],
        max_file_size_mb: Optional[int] = None,
        on_progress: Optional[Callable] = None,
        on_match_found: Optional[Callable] = None
    ) -> bool:
        """启动扫描（异步）"""
        with self._lock:
            if self._scan_thread and self._scan_thread.is_alive():
                logger.warning("扫描已在运行中")
                return False
            
            # 重置状态
            self._stop_event.clear()
            self._pause_event.clear()
            self._context_ready_event.clear()
            self.results_queue = Queue(maxsize=1000)
            self.current_batch.clear()

            # ✅ 修复：清除旧回调，防止重复注册导致信号翻倍
            self._callbacks = {k: [] for k in self._callbacks}

            # 注册回调
            if on_progress:
                self.register_callback('progress', on_progress)
            if on_match_found:
                self.register_callback('match_found', on_match_found)
            
            # 创建扫描线程
            self._scan_thread = threading.Thread(
                target=self._scan_worker,
                args=(scan_paths, max_file_size_mb),
                daemon=True,
                name="ScannerThread"
            )
            
            self.scan_start_time = time.time()
            self._scan_thread.start()
            
            logger.info(f"扫描线程已启动，扫描路径: {scan_paths}")
            return True
    
    def _scan_worker(self, scan_paths: List[str], max_file_size_mb: Optional[int]):
        """
        扫描工作线程
        优化:消除重复统计
        集成新的正则管理器
        """
        try:
            # 创建上下文
            self.context = ScanContext()
            
            # 创建引擎 - 不再传入total_files
            self.engine = ScannerEngine(self.context)
            
            # 设置回调
            self.context.on_progress = lambda c, t, f: self._emit_event('progress', c, t, f)
            self.context.on_file_scanned = lambda f: self._emit_event('file_scanned', f)
            self.context.on_match_found = self._handle_match_found
            self.context.on_status_change = lambda s: self._emit_event('status_changed', s)
            self.context.on_batch_found = self._handle_batch_found
            
            # 通知监控线程上下文已就绪
            self._context_ready_event.set()
            
            # 启动监控线程
            self._start_monitor_thread()
            
            # 准备配置
            scan_settings = self.config_manager.get_scan_settings()
            if max_file_size_mb is None:
                max_file_size_mb = scan_settings.get("max_file_size_mb", 50)
            
            # 在创建config之前，确保传递原始正则字符串
            patterns_dict = self.config_manager.get_patterns_dict()
            
            # 获取正则表达式 - 使用新的正则管理器
            from .regex_manager import get_pattern_manager, compile_patterns_dict
            # 获取PatternManager单例
            pattern_manager = get_pattern_manager()
            # 编译正则（带缓存）
            compiled_patterns = compile_patterns_dict(patterns_dict)

            # 验证 patterns 格式
            if not isinstance(patterns_dict, dict):
                logger.error(f"正则表达式格式错误，期望 dict，实际得到 {type(patterns_dict)}")
                patterns_dict = {}

            # 创建合并正则组（性能优化）
            merged_patterns = pattern_manager.create_merged_patterns(patterns_dict)
            
            # 创建配置，传递编译后的正则
            config = ScanConfig(
                scan_paths=scan_paths,
                patterns=compiled_patterns,  # ← 传递编译后的正则对象
                patterns_dict=patterns_dict,  # ← 传递合并的正则组
                max_file_size_mb=max_file_size_mb,
                recursive=True,
                skip_hidden=True,
                skip_binary=True,
                skip_no_extension=True
            )
            
            # 执行扫描（使用优化后的引擎）
            self._emit_event('status_changed', ScanState.SCANNING)
            results = self.engine.scan(config)
            
            # 处理剩余批次
            if self.current_batch:
                self._emit_event('batch_found', self.current_batch.copy())
                self.current_batch.clear()
            
            # 扫描完成
            if self.context.state == ScanState.COMPLETED:
                self._emit_event('completed', results, self.context.get_stats())
            elif self.context.state == ScanState.STOPPING:
                self._emit_event('completed', results[:100], self.context.get_stats())
            else:
                self._emit_event('error', f"扫描异常结束: {self.context.state}")
                
        except Exception as e:
            logger.error(f"扫描工作线程异常: {e}", exc_info=True)
            self._emit_event('error', str(e))
        
        finally:
            # 停止监控线程
            self._stop_monitor_thread()
            
            # 清理资源
            self.engine = None
            self.context = None
            self._context_ready_event.clear()
    
    def _start_monitor_thread(self):
        """启动监控线程"""
        self._monitor_thread = threading.Thread(
            target=self._monitor_events,
            daemon=True,
            name="ScannerMonitor"
        )
        self._monitor_thread.start()
        logger.debug("监控线程已启动")
    
    def _monitor_events(self):
        """监控外部事件（停止、暂停）"""
        try:
            # 等待上下文初始化（最多等待5秒）
            if not self._context_ready_event.wait(timeout=5):
                logger.error("等待上下文初始化超时，监控线程退出")
                return
            
            # 检查上下文是否有效
            if self.context is None:
                logger.error("上下文初始化失败，监控线程退出")
                return
            
            logger.debug("监控线程进入主循环")
            
            # 主监控循环
            while not self._stop_event.is_set() and self.context is not None:
                try:
                    # 检查停止事件
                    if self._stop_event.is_set():
                        self.context.request_stop()
                        logger.debug("收到停止信号，停止上下文")
                        break
                    
                    # 检查暂停事件
                    if self._pause_event.is_set():
                        self.context.request_pause()
                    else:
                        self.context.request_resume()
                    
                    # 检查上下文是否请求停止
                    if self.context and self.context.should_stop():
                        logger.debug("上下文请求停止，监控线程退出")
                        break
                    
                    time.sleep(0.1)
                    
                except AttributeError as e:
                    logger.error(f"监控线程属性错误: {e}")
                    break
                except Exception as e:
                    logger.error(f"监控线程异常: {e}")
                    break
            
            logger.debug("监控线程退出")
            
        except Exception as e:
            logger.error(f"监控线程启动失败: {e}")
    
    def _stop_monitor_thread(self):
        """停止监控线程"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            # 设置停止事件，让线程自然退出
            self._stop_event.set()
            
            # 等待线程结束（最多1秒）
            self._monitor_thread.join(timeout=1)
            if self._monitor_thread.is_alive():
                logger.warning("监控线程未在1秒内结束")
            
            self._monitor_thread = None
            logger.debug("监控线程已停止")
    
    def _handle_match_found(self, result: ScanResult):
        """处理单个匹配结果"""
        # 添加到当前批次
        self.current_batch.append(result)
        self.results_queue.put(result)
        
        # 触发单个匹配回调
        self._emit_event('match_found', result)
        
        # 检查批次是否已满
        if len(self.current_batch) >= self.batch_size:
            self._handle_batch_found(self.current_batch.copy())
            self.current_batch.clear()
    
    def _handle_batch_found(self, batch: List[ScanResult]):
        """处理批次结果"""
        self._emit_event('batch_found', batch)
    
    def pause_scan(self):
        """暂停扫描"""
        with self._lock:
            if self._scan_thread and self._scan_thread.is_alive():
                self._pause_event.set()
                logger.info("扫描已暂停")
    
    def resume_scan(self):
        """恢复扫描"""
        with self._lock:
            if self._scan_thread and self._scan_thread.is_alive():
                self._pause_event.clear()
                logger.info("扫描已恢复")
    
    def stop_scan(self):
        """停止扫描"""
        with self._lock:
            # 设置停止事件
            self._stop_event.set()
            self._pause_event.clear()
            
            # 停止上下文（如果存在）
            if self.context:
                try:
                    self.context.request_stop()
                except Exception as e:
                    logger.error(f"停止上下文时出错: {e}")
            
            # 等待扫描线程结束（最多5秒）
            if self._scan_thread and self._scan_thread.is_alive():
                self._scan_thread.join(timeout=5)
                if self._scan_thread.is_alive():
                    logger.warning("扫描线程未在5秒内结束")
            
            # 停止监控线程
            self._stop_monitor_thread()
            
            logger.info("扫描已停止")
            
            # 重置事件（为下次扫描准备）
            self._stop_event.clear()
            self._context_ready_event.clear()
    
    def get_recent_results(self, limit: int = 100) -> List[ScanResult]:
        """获取最近的结果"""
        results = []
        while not self.results_queue.empty() and len(results) < limit:
            try:
                results.append(self.results_queue.get_nowait())
            except:
                break
        return results
    
    def is_scanning(self) -> bool:
        """检查是否正在扫描"""
        with self._lock:
            return self._scan_thread is not None and self._scan_thread.is_alive()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取当前统计信息"""
        if self.context:
            return self.context.get_stats()
        return {}

    def get_performance_summary(self) -> Dict:
        """获取性能摘要"""
        if self.context and hasattr(self.context, 'get_stats'):
            stats = self.context.get_stats()
            
            # 添加正则性能统计
            from .regex_manager import get_regex_stats
            regex_stats = get_regex_stats()
            
            return {
                'scan_stats': stats,
                'regex_stats': regex_stats,
                'timestamp': time.time()
            }
        return {}
    
    def print_performance_report(self):
        """打印性能报告"""
        from .regex_manager import get_performance_report
        report = get_performance_report()
        print(report)
        
        # 同时记录到日志
        for line in report.split('\n'):
            logger.info(line)
