"""
utils/log_utils.py - 增强版
添加性能监控日志，便于调试卡死问题
"""

import logging
import os
import time
from datetime import datetime
from PyQt5.QtWidgets import QTextEdit
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG

# 初始化目录
from .file_utils import init_dirs
init_dirs()

from config.constants import APP_NAME, LOG_DIR

# 全局日志器
logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.INFO)
logger.handlers.clear()  # 清除默认处理器，避免重复输出
logger.propagate = False  # 🔧 新增：关闭日志传播，防止向根日志器传播导致重复

# -------------------------- 性能监控器 --------------------------
class PerformanceMonitor:
    """性能监控器，记录关键操作的耗时"""
    
    _instance = None
    _records = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def start(cls, operation: str):
        """开始计时一个操作"""
        cls._records[operation] = {
            'start': time.time(),
            'end': None,
            'duration': None
        }
    
    @classmethod
    def end(cls, operation: str):
        """结束计时一个操作"""
        if operation in cls._records:
            cls._records[operation]['end'] = time.time()
            cls._records[operation]['duration'] = (
                cls._records[operation]['end'] - cls._records[operation]['start']
            )
            
            # 如果操作耗时超过1秒，记录警告日志
            if cls._records[operation]['duration'] > 1.0:
                logger.warning(f"性能警告: {operation} 耗时 {cls._records[operation]['duration']:.2f}秒")
            
            return cls._records[operation]['duration']
        return None
    
    @classmethod
    def log_duration(cls, operation: str, duration: float):
        """直接记录耗时"""
        if duration > 1.0:
            logger.warning(f"性能警告: {operation} 耗时 {duration:.2f}秒")
        elif duration > 0.5:
            logger.info(f"性能提示: {operation} 耗时 {duration:.2f}秒")

# -------------------------- 日志格式 --------------------------
LOG_FORMAT = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)

# -------------------------- 文件日志处理器 --------------------------
def _init_file_handler():
    """初始化文件日志处理器-按日期生成日志文件"""
    log_file = os.path.join(LOG_DIR, f"scan_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(LOG_FORMAT)
    file_handler.setLevel(logging.INFO)
    return file_handler

# 添加文件日志处理器
logger.addHandler(_init_file_handler())

# -------------------------- UI日志处理器（绑定PyQt5 QTextEdit） --------------------------
class UiLogHandler(logging.Handler):
    """UI日志处理器-将日志输出到QTextEdit，线程安全"""
    def __init__(self, text_edit: QTextEdit):
        super().__init__()
        self.text_edit = text_edit
        self.setFormatter(LOG_FORMAT)

    def emit(self, record):
        """发射日志到UI-真正的线程安全，通过Qt元对象派发到主线程，解决QTextCursor报错"""
        try:
            msg = self.format(record)
            # 核心修复：用QMetaObject.invokeMethod将UI操作派发到主线程执行
            # 1. 异步追加日志文本（Qt.QueuedConnection确保主线程执行）
            QMetaObject.invokeMethod(
                self.text_edit,
                "append",  # 要调用的QTextEdit方法
                Qt.QueuedConnection,  # 队列连接-跨线程安全的核心
                Q_ARG(str, msg)  # 传递append的参数（日志字符串）
            )
            # 2. 异步滚动到日志底部（同样派发到主线程）
            QMetaObject.invokeMethod(
                self.text_edit.verticalScrollBar(),
                "setValue",
                Qt.QueuedConnection,
                Q_ARG(int, self.text_edit.verticalScrollBar().maximum())
            )
        except Exception as e:
            # 如果UI日志输出失败，回退到标准输出
            print(f"UI日志输出失败：{str(e)}")

def init_ui_log(text_edit: QTextEdit, is_duplicate_protect: bool = False):
    """初始化UI日志处理器-绑定到全局日志器，添加前先移除旧的，避免重复输出"""
    # 核心去重：先移除logger中已有的UiLogHandler，防止多次添加
    for handler in logger.handlers[:]:  # 遍历副本，避免遍历时修改原列表
        if isinstance(handler, UiLogHandler):
            logger.removeHandler(handler)
    # 再添加新的UI处理器
    ui_handler = UiLogHandler(text_edit)
    ui_handler.setLevel(logging.INFO)
    logger.addHandler(ui_handler)
    logger.info("UI日志处理器初始化成功，日志将同时输出到UI和文件")
