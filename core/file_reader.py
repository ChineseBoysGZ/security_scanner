"""
core/file_reader.py - 修正版
智能文件读取器 - 解决大文件卡死问题
修正了Python 3.8/3.9兼容性问题。
"""
import os
import mmap
import chardet
import time
from pathlib import Path
from typing import Optional, Iterator, Tuple, List, Union  # 添加 Union 导入
import logging

logger = logging.getLogger(__name__)


class SmartFileReader:
    """
    智能文件读取器
    优化策略：
    1. 小文件 (< 2MB): 一次性读取
    2. 中文件 (2MB - 50MB): 流式按行读取
    3. 大文件 (> 50MB): 流式分块读取（替代原来的内存映射逐行查找）
    4. 超大文件 (> 200MB): 智能采样读取
    5. 所有操作都有超时保护
    """
    
    # 读取策略阈值（单位：字节）
    SMALL_FILE_THRESHOLD = 2 * 1024 * 1024    # 2MB
    LARGE_FILE_THRESHOLD = 50 * 1024 * 1024   # 50MB
    HUGE_FILE_THRESHOLD = 200 * 1024 * 1024   # 200MB
    SAMPLE_SIZE = 5 * 1024 * 1024             # 采样大小 5MB（减少以提高性能）
    READ_TIMEOUT = 30                         # 单文件读取超时时间（秒）
    CHUNK_SIZE = 1024 * 1024                  # 流式读取块大小 1MB
    
    def __init__(self, file_path: Union[str, Path], default_encoding: str = "utf-8"):
        self.file_path = Path(file_path) if isinstance(file_path, str) else file_path
        self.default_encoding = default_encoding
        self._file_size = None
        self._encoding = None
        self._start_time = None
        
    @property
    def file_size(self) -> int:
        """获取文件大小（带缓存）"""
        if self._file_size is None:
            try:
                self._file_size = self.file_path.stat().st_size
            except (OSError, FileNotFoundError) as e:
                logger.warning(f"无法获取文件大小 {self.file_path}: {e}")
                self._file_size = 0
        return self._file_size
    
    def _check_timeout(self):
        """检查是否超时，如果超时则抛出异常"""
        if self._start_time and (time.time() - self._start_time > self.READ_TIMEOUT):
            raise TimeoutError(f"文件读取超时: {self.file_path} (超过{self.READ_TIMEOUT}秒)")

    def detect_encoding(self) -> str:
        """
        智能检测文件编码 - 优化版
        添加超时保护和更安全的检测逻辑
        """
        if self._encoding:
            return self._encoding
            
        self._start_time = time.time()

        # 常见编码尝试顺序
        COMMON_ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'latin-1', 'utf-16', 'ascii']
        
        try:
            # 先检查文件大小，避免读取超大文件
            if self.file_size > 100 * 1024 * 1024:  # 超过100MB
                logger.info(f"大文件跳过详细编码检测: {self.file_path}")
                self._encoding = 'utf-8'  # 默认使用utf-8，即使出错也会忽略错误
                return self._encoding
            
            # 读取文件头部检测编码（限制大小）
            read_size = min(self.file_size, 64 * 1024)  # 最多读64KB，提高速度
            with open(self.file_path, 'rb') as f:
                raw_data = f.read(read_size)
            
            self._check_timeout()

            # 如果文件太小，直接尝试常见编码
            if len(raw_data) < 100:
                for encoding in COMMON_ENCODINGS:
                    try:
                        raw_data.decode(encoding, errors='strict')
                        self._encoding = encoding
                        return self._encoding
                    except UnicodeDecodeError:
                        continue
                self._encoding = self.default_encoding
                return self._encoding
            
            # 使用 chardet 检测（限制最大检测大小）
            try:
                detection = chardet.detect(raw_data[:4096])  # 只检测前4KB
                if detection['confidence'] > 0.8:  # 提高置信度阈值
                    detected_enc = detection['encoding'].lower()
                    # 标准化编码名称
                    if detected_enc.startswith('utf-8'):
                        detected_enc = 'utf-8'
                    elif detected_enc in ['gb2312', 'gb18030']:
                        detected_enc = 'gbk'
                    
                    if detected_enc in COMMON_ENCODINGS:
                        self._encoding = detected_enc
                        logger.debug(f"编码检测成功: {self.file_path} -> {detected_enc}")
                        return self._encoding
            except Exception as e:
                logger.debug(f"chardet检测失败: {e}")
            
            # 尝试常见编码（带更多样本）
            for encoding in COMMON_ENCODINGS:
                try:
                    # 用不同大小的数据测试
                    test_data = raw_data[:min(len(raw_data), 4096)]
                    test_data.decode(encoding, errors='strict')
                    # 再测试更多数据确认
                    if len(raw_data) > 4096:
                        raw_data[4096:8192].decode(encoding, errors='strict')
                    self._encoding = encoding
                    logger.debug(f"通过尝试确定编码: {self.file_path} -> {encoding}")
                    return self._encoding
                except (UnicodeDecodeError, IndexError):
                    continue
            
            # 都失败了，使用默认编码
            self._encoding = self.default_encoding
            return self._encoding
            
        except TimeoutError:
            logger.warning(f"编码检测超时: {self.file_path}")
            self._encoding = self.default_encoding
            return self._encoding
        except Exception as e:
            logger.debug(f"编码检测失败 {self.file_path}: {e}")
            self._encoding = self.default_encoding
            return self._encoding
        finally:
            self._start_time = None
    
    def read_lines(self) -> Iterator[Tuple[int, str]]:
        """
        读取文件的所有行，返回 (行号, 内容) 的迭代器
        根据文件大小自动选择最优策略
        添加超时保护
        """
        if not self.file_path.exists():
            logger.warning(f"文件不存在: {self.file_path}")
            return
        
        self._start_time = time.time()

        try:
            encoding = self.detect_encoding()
            self._check_timeout()

            # 记录文件信息
            file_size_mb = self.file_size / 1024 / 1024
            logger.info(f"开始扫描文件: {self.file_path} ({file_size_mb:.1f}MB, 编码: {encoding})")

            # 策略选择
            if self.file_size < self.SMALL_FILE_THRESHOLD:
                yield from self._read_small_file(encoding)
            elif self.file_size < self.LARGE_FILE_THRESHOLD:
                yield from self._read_medium_file(encoding)
            elif self.file_size < self.HUGE_FILE_THRESHOLD:
                yield from self._read_large_file_streaming(encoding)  # 改用流式读取
            else:
                yield from self._read_huge_file_sampled(encoding)
        
        except TimeoutError as e:
            logger.warning(f"文件扫描超时，跳过: {self.file_path} - {str(e)}")
        except Exception as e:
            logger.error(f"文件扫描异常 {self.file_path}: {e}")
        finally:
            self._start_time = None
    
    def _read_small_file(self, encoding: str) -> Iterator[Tuple[int, str]]:
        """小文件：一次性读取全部内容"""
        try:
            with open(self.file_path, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read()
                lines = content.splitlines()
                for i, line in enumerate(lines, 1):
                    yield i, line
        except Exception as e:
            logger.warning(f"小文件读取失败 {self.file_path}: {e}")
    
    def _read_medium_file(self, encoding: str) -> Iterator[Tuple[int, str]]:
        """中文件：流式按行读取"""
        try:
            with open(self.file_path, 'r', encoding=encoding, errors='ignore') as f:
                line_num = 0
                for line in f:
                    self._check_timeout()
                    line_num += 1
                    yield line_num, line.rstrip('\n')
        except Exception as e:
            logger.warning(f"中文件读取失败 {self.file_path}: {e}")
    
    def _read_large_file_streaming(self, encoding: str) -> Iterator[Tuple[int, str]]:
        """
        大文件：流式分块读取（替代原来的内存映射逐行查找）
        性能更好，内存更安全
        """
        try:
            with open(self.file_path, 'rb') as f:
                buffer = b''
                line_num = 0

                while True:
                    self._check_timeout()
                    
                    # 读取一块数据
                    chunk = f.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    # 添加到缓冲区
                    buffer += chunk

                    # 处理缓冲区中的完整行
                    while b'\n' in buffer:
                        line_end = buffer.find(b'\n')
                        line_bytes = buffer[:line_end]
                        buffer = buffer[line_end + 1:]

                        # 解码当前行
                        try:
                            line = line_bytes.decode(encoding, errors='ignore')
                        except (UnicodeDecodeError, LookupError):
                            try:
                                line = line_bytes.decode(self.default_encoding, errors='ignore')
                            except:
                                line = ""
                        
                        line_num += 1
                        yield line_num, line

                # 处理最后一行（如果没有换行符）
                if buffer:
                    try:
                        line = buffer.decode(encoding, errors='ignore')
                        line_num += 1
                        yield line_num, line
                    except:
                        pass  
                    
        except TimeoutError:
            raise
        except Exception as e:
            logger.warning(f"大文件流式读取失败 {self.file_path}: {e}")
            # 降级到采样读取
            yield from self._read_huge_file_sampled(encoding)

    def _read_huge_file_sampled(self, encoding: str) -> Iterator[Tuple[int, str]]:
        """
        超大文件：智能采样读取
        只读开头、中间和结尾部分，避免完全卡死
        """
        file_size_mb = self.file_size / 1024 / 1024
        logger.info(f"超大文件采样扫描: {self.file_path} ({file_size_mb:.1f}MB)")
        
        try:
            # 采样大小（动态调整）
            sample_size = min(self.SAMPLE_SIZE, max(1024 * 1024, self.file_size // 100))
            
            # 采样位置：开头、1/3处、2/3处、结尾
            sample_positions = [
                0,  # 开头
                self.file_size // 3,
                self.file_size * 2 // 3,
                max(0, self.file_size - sample_size)  # 结尾
            ]
            
            seen_lines = set()  # 避免重复行
            total_yielded = 0

            for i, position in enumerate(sample_positions):
                self._check_timeout()
                
                try:
                    with open(self.file_path, 'rb') as f:
                        f.seek(position)
                        sample_data = f.read(sample_size)
                        
                        # 解码采样数据
                        try:
                            sample_text = sample_data.decode(encoding, errors='ignore')
                        except:
                            sample_text = sample_data.decode(self.default_encoding, errors='ignore')
                        
                        # 按行分割
                        lines = sample_text.splitlines()
                        
                        # 估算行号
                        avg_line_length = 100  # 假设平均每行100字符
                        start_line = max(1, position // avg_line_length)
                        
                        for j, line in enumerate(lines):
                            if total_yielded > 1000:  # 最多返回1000行
                                logger.info(f"采样已达到1000行上限，停止扫描")
                                return
                            
                            line_hash = hash(line)
                            if line_hash not in seen_lines:
                                seen_lines.add(line_hash)
                                line_num = start_line + j
                                yield line_num, line
                                total_yielded += 1

                except Exception as e:
                    logger.debug(f"采样位置 {position} 读取失败: {e}")
                    continue
                
            logger.info(f"超大文件采样完成: {self.file_path}, 共扫描{total_yielded}行")

        except TimeoutError:
            raise
        except Exception as e:
            logger.warning(f"超大文件采样失败 {self.file_path}: {e}")
    
    def read_chunks(self, chunk_size: int = 1024 * 1024) -> Iterator[str]:
        """
        按块读取文件内容
        :param chunk_size: 块大小（字节），默认1MB
        :return: 文件块的迭代器
        """
        if not self.file_path.exists():
            logger.warning(f"文件不存在: {self.file_path}")
            return
        
        self._start_time = time.time()
        
        try:
            encoding = self.detect_encoding()
            self._check_timeout()
            
            file_size_mb = self.file_size / 1024 / 1024
            logger.debug(f"开始分块读取文件: {self.file_path} ({file_size_mb:.1f}MB, 编码: {encoding})")
            
            # 根据文件大小选择读取策略
            if self.file_size < self.SMALL_FILE_THRESHOLD:
                # 小文件：一次性读取作为一个块
                yield from self._read_small_file_as_chunk(encoding)
            elif self.file_size < self.LARGE_FILE_THRESHOLD:
                # 中文件：按行读取后合并成块
                yield from self._read_medium_file_as_chunks(encoding, chunk_size)
            else:
                # 大文件：直接分块读取
                yield from self._read_large_file_as_chunks(encoding, chunk_size)
        
        except TimeoutError as e:
            logger.warning(f"文件分块读取超时，跳过: {self.file_path} - {str(e)}")
        except Exception as e:
            logger.error(f"文件分块读取异常 {self.file_path}: {e}")
        finally:
            self._start_time = None

    def _read_small_file_as_chunk(self, encoding: str) -> Iterator[str]:
        """小文件：一次性读取作为一个块"""
        try:
            with open(self.file_path, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read()
                yield content
        except Exception as e:
            logger.warning(f"小文件读取失败 {self.file_path}: {e}")
    
    def _read_medium_file_as_chunks(self, encoding: str, chunk_size: int) -> Iterator[str]:
        """中文件：按行读取后合并成块"""
        try:
            buffer = []
            buffer_size = 0
            
            with open(self.file_path, 'r', encoding=encoding, errors='ignore') as f:
                for line in f:
                    self._check_timeout()
                    
                    buffer.append(line)
                    buffer_size += len(line)
                    
                    # 当缓冲区大小超过块大小时，返回一个块
                    if buffer_size >= chunk_size:
                        chunk = ''.join(buffer)
                        yield chunk
                        buffer = []
                        buffer_size = 0
                
                # 返回剩余的缓冲区内容
                if buffer:
                    chunk = ''.join(buffer)
                    yield chunk
                    
        except Exception as e:
            logger.warning(f"中文件分块读取失败 {self.file_path}: {e}")

    def _read_large_file_as_chunks(self, encoding: str, chunk_size: int) -> Iterator[str]:
        """大文件：直接分块读取（二进制读取后解码）"""
        try:
            with open(self.file_path, 'rb') as f:
                position = 0
                
                while True:
                    self._check_timeout()
                    
                    # 读取二进制块
                    binary_chunk = f.read(chunk_size)
                    if not binary_chunk:
                        break
                    
                    # 解码块
                    try:
                        chunk = binary_chunk.decode(encoding, errors='ignore')
                    except (UnicodeDecodeError, LookupError):
                        # 如果默认编码失败，尝试其他编码
                        try:
                            chunk = binary_chunk.decode(self.default_encoding, errors='ignore')
                        except:
                            # 如果都失败，使用替换错误处理
                            chunk = binary_chunk.decode('utf-8', errors='replace')
                    
                    yield chunk
                    position += len(binary_chunk)
                    
        except TimeoutError:
            raise
        except Exception as e:
            logger.warning(f"大文件分块读取失败 {self.file_path}: {e}")
    
    def read_first_lines(self, num_lines: int = 100) -> List[str]:
        """读取文件的前N行（用于快速预览）"""
        try:
            encoding = self.detect_encoding()
            lines = []
            with open(self.file_path, 'r', encoding=encoding, errors='ignore') as f:
                for i, line in enumerate(f):
                    if i >= num_lines:
                        break
                    lines.append(line.rstrip('\n'))
            return lines
        except Exception as e:
            logger.debug(f"读取前N行失败 {self.file_path}: {e}")
            return []
    
    def is_likely_binary(self) -> bool:
        """粗略判断是否为二进制文件"""
        if self.file_size == 0:
            return False
            
        try:
            with open(self.file_path, 'rb') as f:
                # 只检查前8KB，提高速度
                sample = f.read(8192)
                if not sample:
                    return False
                
                # 检查NULL字节比例
                null_count = sample.count(b'\x00')
                # 如果NULL字节超过1%并且文件大于10KB，可能是二进制文件
                if null_count > 0 and null_count / len(sample) > 0.01 and self.file_size > 10240:
                    return True
                
                # 检查可打印字符比例
                printable = sum(1 for b in sample if 32 <= b <= 126 or b in b'\t\n\r')
                printable_ratio = printable / len(sample)
                
                # 如果可打印字符比例低于70%，可能是二进制文件
                return printable_ratio < 0.7
        except:
            return False


# 工具函数
def should_skip_file(file_path: Path, skip_extensions: set, max_size_bytes: int, skip_no_extension: bool = True) -> Tuple[bool, str]:
    """
    判断是否应该跳过文件
    返回: (是否跳过, 跳过原因)
    检查顺序：
    1. 检查文件是否有后缀（新增规则）
    2. 检查扩展名是否在黑名单中
    3. 检查文件大小是否超过限制
    4. 快速二进制检测
    判断是否应该跳过文件
    返回: (是否跳过, 跳过原因)
    
    参数:
        file_path: 文件路径
        skip_extensions: 需要跳过的扩展名集合
        max_size_bytes: 最大文件大小（字节）
        skip_no_extension: 是否跳过无后缀文件，默认为True
    """
    # 0. 检查是否有后缀（如果配置为跳过无后缀文件）
    suffix = file_path.suffix.lower()
    if skip_no_extension and not suffix:  # 空字符串表示无后缀
        return True, "无后缀文件（跳过）"
    
    # 1. 检查扩展名是否在黑名单中
    if suffix in skip_extensions:
        return True, f"跳过后缀: {suffix}"
    
    # 2. 检查文件大小
    try:
        file_size = file_path.stat().st_size
        if file_size > max_size_bytes:
            return True, f"文件过大: {file_size // 1024 // 1024}MB"
    except OSError:
        return True, "无法访问文件大小"
    
    # 3. 快速二进制检测（添加大小检查，避免大文件检测过慢）
    if file_size > 100 * 1024 * 1024:  # 超过100MB，假设为文本文件继续扫描
        return False, ""
    
    # 4. 二进制文件检测
    if SmartFileReader(file_path).is_likely_binary():
        return True, "疑似二进制文件"
    
    return False, ""
