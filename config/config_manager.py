"""
config/config_manager.py
"""

import json
import os
import time
from datetime import datetime
from shutil import copy2
from .constants import (
    CONFIG_FILE,  # 🔴 移除无用导入CONFIG_BACKUP_FILE
    DEFAULT_PATTERNS,
    DEFAULT_MAX_FILE_SIZE_MB, DEFAULT_MAX_WORKERS,
    DEFAULT_EXCEL_HEADERS, DEFAULT_EXCEL_WIDTHS, DEFAULT_EXCEL_EXT,
    SKIP_EXTENSIONS, LOG_SHOW_DETAIL, CONFIG_BACKUP_KEEP
)
from utils.log_utils import logger

class ConfigManager:
    """配置管理器-增强：自动备份/配置验证/默认值填充/配置修改回调"""
    def __init__(self):
        # 🔴 修复1：使用常量CONFIG_FILE，替代硬编码；移除无用参数
        self.config_file = CONFIG_FILE
        self.backup_dir = "config_backups"  # 备份目录
        self._config_callbacks = []  # 🔴 修复2：初始化配置回调列表，核心！
        os.makedirs(self.backup_dir, exist_ok=True)  # 自动创建备份目录
        self.config = self.load_config()  # 统一配置加载

    def _get_default_config(self):
        """获取默认完整配置"""
        return {
            "patterns": DEFAULT_PATTERNS,
            "scan_settings": {
                "max_file_size_mb": DEFAULT_MAX_FILE_SIZE_MB,
                "max_workers": DEFAULT_MAX_WORKERS,
                "log_show_detail": LOG_SHOW_DETAIL
            },
            "excel_settings": {
                "headers": DEFAULT_EXCEL_HEADERS,
                "column_widths": DEFAULT_EXCEL_WIDTHS,
                "default_ext": DEFAULT_EXCEL_EXT
            },
            "skip_extensions": SKIP_EXTENSIONS
        }

    def _validate_config(self, config):
        """验证配置有效性-字段类型/取值范围，无效则填充默认值"""
        default = self._get_default_config()
        # 递归验证字典配置
        def _recursive_validate(src, dst):
            for k, v in dst.items():
                if k not in src or type(src[k]) != type(v):
                    src[k] = v
                    logger.warning(f"配置项[{k}]无效/缺失，使用默认值：{v}")
                if isinstance(v, dict):
                    _recursive_validate(src[k], v)
                # 扫描参数取值范围验证
                if k == "max_workers" and not (1 <= src[k] <= 64):
                    src[k] = DEFAULT_MAX_WORKERS
                    logger.warning(f"线程数超出范围(1-64)，使用默认值：{DEFAULT_MAX_WORKERS}")
                if k == "max_file_size_mb" and not (1 <= src[k] <= 100):
                    src[k] = DEFAULT_MAX_FILE_SIZE_MB
                    logger.warning(f"文件大小超出范围(1-100)，使用默认值：{DEFAULT_MAX_FILE_SIZE_MB}")
        _recursive_validate(config, default)
        return config

    def load_config(self):
        """加载配置-兼容旧配置+自动验证+默认值填充+添加日志定位"""
        # 初始化默认配置
        config = self._get_default_config()
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)  # 读取文件配置
                logger.info(f"成功读取配置文件：{self.config_file}，文件中的excel表头：{file_config.get('excel_settings', {}).get('headers', [])}")
                # 完全覆盖默认配置（而非合并，避免默认配置干扰）
                config.update(file_config)
                # 旧配置（列表式正则）转换为新配置（字典式）
                if isinstance(config.get("patterns", []), list):
                    config["patterns"] = DEFAULT_PATTERNS
                    logger.warning("检测到旧版配置，自动转换为字典式正则规则")
                # 验证并填充配置（仅修复类型/取值，不替换已存在的正确字段）
                config = self._validate_config(config)
                logger.info(f"配置验证完成，最终excel表头：{config.get('excel_settings', {}).get('headers', [])}")
            else:
                logger.warning(f"配置文件不存在：{self.config_file}，使用默认配置，默认excel表头：{config.get('excel_settings', {}).get('headers', [])}")
            logger.info(f"配置文件加载成功，最终生效配置路径：{self.config_file}")
        except Exception as e:
            logger.error(f"配置加载失败，使用默认配置：{str(e)}")
            config = self._get_default_config()
        # 🔧 新增：打印最终生效的excel表头，方便定位
        final_headers = config.get("excel_settings", {}).get("headers", [])
        logger.info(f"【最终生效的Excel表头】：{final_headers}")
        self.config = config
        return config

    def save_config(self):
        """保存配置+自动多版本备份+触发配置回调+清理旧备份
        ✅ 新增：保存成功返回True，保存失败返回False
        ✅ 分离：备份异常不影响保存判定，仅打印日志
        """
        # 第一步：先备份原有配置（如果存在），单独捕获备份异常
        if os.path.exists(self.config_file):
            try:
                backup_name = f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                backup_path = os.path.join(self.backup_dir, backup_name)
                copy2(self.config_file, backup_path)  # 直接复制文件，简洁高效
                logger.info(f"配置文件备份成功：{backup_path}")
                # 清理旧备份：保留最近3个（按需修改）
                self._clean_old_backups(keep_count=3)
            except Exception as e:
                # 备份失败仅打印日志，不影响配置保存
                logger.error(f"配置备份失败（不影响保存）：{str(e)}")
        # 第二步：保存新配置，核心捕获保存异常，添加返回值
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            logger.info(f"配置已成功保存到：{self.config_file}")
            # 触发所有注册的配置回调，核心！（配置修改后更新UI）
            self._trigger_config_callbacks()
            # ✅ 保存成功：返回True
            return True
        except Exception as e:
            logger.error(f"配置保存失败：{str(e)}")
            # ✅ 保存失败：返回False
            return False

    def _clean_old_backups(self, keep_count=CONFIG_BACKUP_KEEP):
        """清理旧备份，保留指定数量的最新备份 ✨ 优化3：加异常捕获+文件判断"""
        try:
            if not os.path.exists(self.backup_dir):
                return
            # 获取所有备份文件，过滤子目录，只保留config_开头的json文件
            backup_files = [
                f for f in os.listdir(self.backup_dir)
                if f.startswith("config_") and f.endswith(".json")
                and os.path.isfile(os.path.join(self.backup_dir, f))
            ]
            if not backup_files:
                return
            # 按修改时间排序（最新的在后）
            backup_files.sort(key=lambda x: os.path.getmtime(os.path.join(self.backup_dir, x)))
            # 超过保留数量则删除最旧的
            if len(backup_files) > keep_count:
                for old_file in backup_files[:-keep_count]:
                    old_path = os.path.join(self.backup_dir, old_file)
                    os.remove(old_path)
                    logger.info(f"清理旧配置备份：{old_file}")
        except Exception as e:
            logger.error(f"清理旧备份失败：{str(e)}")

    def _trigger_config_callbacks(self):
        """触发所有注册的配置回调函数"""
        for callback in self._config_callbacks:
            if callable(callback):
                try:
                    callback()
                except Exception as e:
                    logger.error(f"执行配置回调失败：{str(e)}")

    def register_config_callback(self, callback):
        """注册配置修改回调函数-配置保存时执行"""
        if callable(callback) and callback not in self._config_callbacks:
            self._config_callbacks.append(callback)
            logger.info("配置修改回调已注册")

    # -------------------------- 配置快捷获取/设置 --------------------------
    def get_patterns_dict(self):
        """获取正则字典{名称:表达式}"""
        return self.config.get("patterns", self._get_default_config()["patterns"])

    def set_patterns_dict(self, patterns_dict):
        """设置正则字典"""
        if isinstance(patterns_dict, dict):
            self.config["patterns"] = patterns_dict
            self.save_config()  # 设值后自动保存配置

    def get_scan_settings(self):
        """获取扫描设置 ✨ 优化4：默认配置兜底"""
        return self.config.get("scan_settings", self._get_default_config()["scan_settings"])

    def get_excel_settings(self):
        """获取Excel设置 ✨ 优化4：默认配置兜底"""
        return self.config.get("excel_settings", self._get_default_config()["excel_settings"])

    def get_skip_extensions(self):
        """获取跳过后缀 ✨ 优化4：默认配置兜底"""
        return self.config.get("skip_extensions", self._get_default_config()["skip_extensions"])
    