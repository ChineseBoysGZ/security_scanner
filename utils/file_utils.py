"""
utils/file_utils.py
"""

import os
import chardet
from config.constants import DEFAULT_ENCODINGS, HIDDEN_DIRS, HIDDEN_PREFIX, LOG_DIR

def init_dirs():
    """初始化日志/配置目录-不存在则创建"""
    for dir_name in [LOG_DIR]:
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)

# -------------------------- 文件编码检测 --------------------------
def detect_file_encoding(file_path: str, fallback_encodings: list = DEFAULT_ENCODINGS) -> str:
    """
    检测文件编码-失败则返回默认编码
    :param file_path: 文件路径
    :param fallback_encodings: 默认编码列表
    :return: 检测到的编码
    """
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read(1024 * 1024)  # 读取1MB数据检测编码
        result = chardet.detect(raw_data)
        encoding = result.get('encoding', fallback_encodings[0])
        # 验证编码有效性
        if encoding not in fallback_encodings:
            encoding = fallback_encodings[0]
        return encoding
    except Exception as e:
        from utils.log_utils import logger
        logger.warning(f"文件编码检测失败，使用默认编码：{fallback_encodings[0]}，错误：{str(e)}")
        return fallback_encodings[0]

def read_file_content(file_path: str) -> str:
    """
    读取文件内容-自动检测编码，多编码重试
    :param file_path: 文件路径
    :return: 文件内容字符串，失败返回空
    """
    encoding = detect_file_encoding(file_path)
    for enc in [encoding] + DEFAULT_ENCODINGS:
        try:
            with open(file_path, 'r', encoding=enc, errors='strict') as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
        except Exception as e:
            from utils.log_utils import logger
            logger.error(f"读取文件失败：{file_path}，编码{enc}，错误：{str(e)}")
            return ""
    return ""

# -------------------------- 文件大小处理 --------------------------
def get_file_size_bytes(file_path: str) -> int:
    """获取文件大小（字节）-处理文件不存在/权限问题"""
    try:
        return os.path.getsize(file_path)
    except Exception as e:
        from utils.log_utils import logger
        logger.warning(f"获取文件大小失败：{file_path}，错误：{str(e)}")
        return 0

def get_file_size_formatted(file_path: str) -> str:
    """格式化文件大小-GB/MB/KB/B"""
    size = get_file_size_bytes(file_path)
    units = ['B', 'KB', 'MB', 'GB']
    unit_index = 0
    while size >= 1024 and unit_index < 3:
        size /= 1024
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"

def check_file_size(file_path: str, max_size_mb: int) -> bool:
    """检查文件大小是否超出限制"""
    size_bytes = get_file_size_bytes(file_path)
    return size_bytes <= max_size_mb * 1024 * 1024

# -------------------------- 隐藏文件/目录过滤 --------------------------
def filter_hidden(path: str) -> bool:
    """
    过滤隐藏文件/目录-跨平台
    :param path: 文件/目录路径
    :return: 非隐藏返回True，隐藏返回False
    """
    try:
        # 获取基名
        basename = os.path.basename(path)
        # 过滤隐藏前缀/隐藏目录
        if basename.startswith(HIDDEN_PREFIX) or basename in HIDDEN_DIRS:
            return False
        # Windows隐藏属性检测
        if os.name == 'nt':
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
            if attrs == -1:
                return False
            return not (attrs & 2)
        return True
    except Exception as e:
        from utils.log_utils import logger
        logger.warning(f"过滤隐藏文件失败：{path}，错误：{str(e)}")
        return True