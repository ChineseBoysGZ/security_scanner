"""
ui/pages/scan_page.py
修复：
1.扫描时间显示为0秒 
2.进度条卡在86% 
3.UI响应性优化
4.✅ 新增：修改路径选择功能，文件夹单选，文件多选

"""

import os
import time
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QTextEdit, QFileDialog, QSpinBox, QHeaderView
)
from PyQt5.QtCore import Qt, pyqtSlot, QMetaObject, Q_ARG, QTimer, QThread
from PyQt5.QtGui import QFont

# 本地模块导入
from config.constants import DEFAULT_EXCEL_EXT, SYS_FONT
from core import export_excel
from core.models import ScanResult
from utils.thread_utils import ScannerThreadManager
from utils.log_utils import logger, init_ui_log
from ui.components import (
    create_btn, create_line_edit, create_progress_bar,
    show_warn, show_info, show_confirm
)

class ScanPage(QWidget):
    """安全扫描页-性能版｜无预览/过滤｜精准匹配日志｜无重复日志｜防卡死保护"""
    # ✅ 新增：匹配日志计数器
    _match_log_count = 0
    _MATCH_LOG_LIMIT = 200  # 日志框最多显示200条匹配

    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.scanner_thread = None
        self.all_results = []
        self._default_headers = ["规则名称", "文件路径", "匹配内容", "应用ID"]
        self._scan_start_time = None  # ✅ 新增：修复时间显示的关键

        # ✅ 修复：正确初始化定时器属性
        self._update_timer = QTimer(self)  # 传入parent确保在主线程
        self._update_timer.setInterval(500)  # 500ms更新一次
        self._update_timer.timeout.connect(self._update_time_display)

        self.init_ui()
        # ✅ 核心修复1：注册配置回调（必须有！否则配置无法同步到UI）
        self.config_manager.register_config_callback(self._update_ui_from_config)
        # ✅ 核心修复2：初始化时立即加载配置（设置默认值+UI初始值）
        self._update_ui_from_config()
        # ✅ 日志去重核心：init_ui_log仅绑定UI日志框，不添加重复日志处理器
        init_ui_log(self.log_text, is_duplicate_protect=True)  # 传参开启去重保护

    def init_ui(self):
        """初始化UI-保留所有核心功能，仅日志区域优化"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # 1. 扫描配置区域
        config_group = QGroupBox("扫描配置")
        config_group.setStyleSheet("QGroupBox {font-weight: bold; font-size: 10pt; margin-top: 8px;}")
        config_layout = QGridLayout(config_group)
        config_layout.setSpacing(8)
        config_layout.setColumnStretch(1, 2)
        
        # ✅ 修改：更新提示文字，明确新的选择规则
        self.path_input = create_line_edit("请选择扫描文件夹（单选）或文件（多选，多文件用;分隔）")
        self.browse_dir_btn = create_btn("选择文件夹", "primary")  # ✅ 修改按钮文字
        self.browse_dir_btn.clicked.connect(self.browse_directory)
        self.browse_file_btn = create_btn("选择文件", "primary")   # ✅ 修改按钮文字
        self.browse_file_btn.clicked.connect(self.browse_file)
        
        config_layout.addWidget(QLabel("扫描路径："), 0, 0)
        config_layout.addWidget(self.path_input, 0, 1, 1, 3)
        config_layout.addWidget(self.browse_dir_btn, 0, 4)
        config_layout.addWidget(self.browse_file_btn, 0, 5)
        
        config_layout.addWidget(QLabel("扫描线程数："), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.worker_spin = self._create_spin_box(1, 64)
        self.worker_spin.valueChanged.connect(self._save_worker_count)
        config_layout.addWidget(self.worker_spin, 1, 1)
        
        config_layout.addWidget(QLabel("最大文件大小："), 1, 2, Qt.AlignRight | Qt.AlignVCenter)
        self.file_size_spin = self._create_spin_box(1, 100, " MB")
        self.file_size_spin.valueChanged.connect(self._save_file_size)
        config_layout.addWidget(self.file_size_spin, 1, 3)
        
        layout.addWidget(config_group)

        # 2. 控制按钮区域
        control_layout = QHBoxLayout()
        self.start_btn = create_btn("开始扫描", "success")
        self.start_btn.clicked.connect(self.start_scan)
        self.stop_btn = create_btn("停止扫描", "danger")
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setEnabled(False)
        self.export_btn = create_btn("导出结果", "primary")
        self.export_btn.clicked.connect(self.export_results)
        self.export_btn.setEnabled(False)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.export_btn)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # 3. 进度显示区域（✅ 优化：恢复简洁布局）
        progress_layout = QHBoxLayout()
        self.total_file_label = QLabel("总文件数：--")
        self.current_file_label = QLabel("当前扫描：--")
        self.current_file_label.setMinimumWidth(300)
        self.progress_label = QLabel("就绪")
        self.progress_bar = create_progress_bar()
        progress_layout.addWidget(self.total_file_label)
        progress_layout.addWidget(self.current_file_label)
        progress_layout.addWidget(self.progress_label)
        progress_layout.addStretch()
        progress_layout.addWidget(self.progress_bar)
        progress_layout.setSpacing(12)
        layout.addLayout(progress_layout)

        # 4. 扫描日志区域
        log_group = QGroupBox("📌 实时扫描日志")
        log_group.setStyleSheet("QGroupBox {font-weight: bold; font-size: 10pt; margin-top: 8px;}")
        log_layout = QHBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {font-size: 9pt; background-color: #f8f9fa; border: 1px solid #dee2e6; line-height: 1.4;}
        """)
        self.log_text.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))
        
        self.clear_log_btn = create_btn("清空日志", "default")
        self.clear_log_btn.setMaximumWidth(100)
        self.clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        
        log_layout.addWidget(self.log_text, stretch=1)
        log_layout.addWidget(self.clear_log_btn, Qt.AlignTop)
        layout.addWidget(log_group, stretch=1)

        # ✅ 防卡死保护：初始化状态
        self.reset_scan_state()

    def _create_spin_box(self, min_val, max_val, suffix=""):
        """创建SpinBox——范围正确（线程数1-64，文件大小1-100）"""
        spin = QSpinBox()
        spin.setRange(min_val, max_val)  # 线程数1-64，文件大小1-100，符合你的UI设置
        spin.setSuffix(suffix)
        spin.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))
        return spin

    def _deduplicate_paths(self, path_string: str) -> str:
        """
        去除路径字符串中的重复项
        :param path_string: 用分号分隔的路径字符串
        :return: 去重后的路径字符串
        """
        if not path_string or not path_string.strip():
            return ""
    
        # 分割路径并去除首尾空格
        paths = [p.strip() for p in path_string.split(';') if p.strip()]
    
        # 去重，同时保持顺序
        seen = set()
        unique_paths = []
    
        for path in paths:
            # 标准化路径（解决大小写、斜杠差异等问题）
            norm_path = os.path.normcase(os.path.normpath(path))
            if norm_path not in seen:
                seen.add(norm_path)
                unique_paths.append(path)  # 保留原始路径格式
    
        # 重新组合
        return ';'.join(unique_paths)

    def _add_path_to_input(self, new_path: str, replace: bool = False):
        """
        将新路径添加到输入框（自动去重）
        :param new_path: 新路径（单个路径或用分号分隔的多个路径）
        :param replace: 是否替换当前内容（True=替换，False=追加）
        """
        current = self.path_input.text().strip()
    
        if replace or not current:
            # 直接设置新路径（替换或初始设置）
            result = self._deduplicate_paths(new_path)
            self.path_input.setText(result)
        else:
            # 追加新路径
            combined = f"{current};{new_path}"
            result = self._deduplicate_paths(combined)
            self.path_input.setText(result)
    
        # 返回实际添加的路径数量
        return len([p for p in result.split(';') if p.strip()])

    # ✅ 【新增核心】防卡死保护：批量启用/禁用所有操作控件（一键控制，减少重复代码）
    def _set_ui_enabled(self, enabled: bool):
        """
        批量设置所有用户操作控件的启用/禁用状态
        :param enabled: True=启用（就绪/完成），False=禁用（扫描/统计中）
        """
        # 路径选择控件
        self.path_input.setEnabled(enabled)
        self.browse_dir_btn.setEnabled(enabled)
        self.browse_file_btn.setEnabled(enabled)
        # 配置修改控件
        self.worker_spin.setEnabled(enabled)
        self.file_size_spin.setEnabled(enabled)
        # 核心控制按钮（开始/停止单独控制，避免冲突）
        self.start_btn.setEnabled(enabled)
        # 日志相关（清空日志始终启用，不影响）
        self.clear_log_btn.setEnabled(True)
        # 导出按钮仅在有结果时启用，此处不控制

    def _update_ui_from_config(self):
        """从配置更新UI——修复信号重连+配置兜底+防止循环"""
        if not hasattr(self, 'worker_spin') or not hasattr(self, 'file_size_spin'):
            return  # 控件未初始化，直接返回
        # ✅ 修复：断开信号前先判断是否已连接（避免重复断开报错）
        try:
            self.worker_spin.valueChanged.disconnect(self._save_worker_count)
        except TypeError:
            pass  # 未连接时忽略报错
        try:
            self.file_size_spin.valueChanged.disconnect(self._save_file_size)
        except TypeError:
            pass  # 未连接时忽略报错

        # ✅ 核心：读取配置+兜底默认值（避免配置文件无值时显示1）
        scan_settings = self.config_manager.get_scan_settings() or {}  # 兜底空字典
        # 线程数默认32，文件大小默认15（可根据你的需求修改）
        default_worker = 32
        default_file_size = 15
        worker_count = scan_settings.get("max_workers", default_worker)
        file_size_mb = scan_settings.get("max_file_size_mb", default_file_size)

        # 设置UI控件值（这一步会覆盖控件的默认值1）
        self.worker_spin.setValue(worker_count)
        self.file_size_spin.setValue(file_size_mb)

        # ✅ 重新连接信号（修改UI值时触发保存）
        self.worker_spin.valueChanged.connect(self._save_worker_count)
        self.file_size_spin.valueChanged.connect(self._save_file_size)
    
    def _save_worker_count(self):
        """保存线程数配置——确保键名正确"""
        if not hasattr(self, 'config_manager'):
            return
        # 确保scan_settings节点存在，无则创建
        if "scan_settings" not in self.config_manager.config:
            self.config_manager.config["scan_settings"] = {}
        # ✅ 键名：max_workers（和读取时一致）
        self.config_manager.config["scan_settings"]["max_workers"] = self.worker_spin.value()
        self.config_manager.save_config()  # 立即保存到配置文件

    def _save_file_size(self):
        """保存最大文件大小配置——确保键名正确"""
        if not hasattr(self, 'config_manager'):
            return
        if "scan_settings" not in self.config_manager.config:
            self.config_manager.config["scan_settings"] = {}
        # ✅ 键名：max_file_size_mb（和读取时一致）
        self.config_manager.config["scan_settings"]["max_file_size_mb"] = self.file_size_spin.value()
        self.config_manager.save_config()  # 立即保存到配置文件

    # ✅ 修改：路径选择功能 - 文件夹单选，文件多选
    def browse_directory(self):
        """选择扫描文件夹（单选）"""
        # 使用QFileDialog.getExistingDirectory只能选择单个文件夹
        path = QFileDialog.getExistingDirectory(self, "选择扫描目录", os.path.expanduser("~"))
        if path:
            # ✅ 优化：使用路径去重方法
            count = self._add_path_to_input(path, replace=True)  # 文件夹单选，直接替换
        
            if count > 0:
                self.ui_log(f"📁 已选择扫描文件夹：{path}")
            else:
                self.ui_log(f"⚠️ 文件夹已存在：{path}")
    
    def browse_file(self):
        """选择扫描文件（多选）"""
        # 使用QFileDialog.getOpenFileNames可以多选文件
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择扫描文件", os.path.expanduser("~"), "所有文件 (*.*)")
    
        if not file_paths:
            return
    
        # 将多个文件路径用分号连接
        new_files = ";".join(file_paths)
        current_path = self.path_input.text().strip()
    
        # ✅ 优化：智能处理混合情况和去重
        if not current_path:
            # 如果输入框为空，直接设置新文件
            count = self._add_path_to_input(new_files, replace=True)
            self.ui_log(f"📄 已选择 {len(file_paths)} 个文件（{count}个不重复）")
            return
    
        # 检查当前路径类型
        first_path = current_path.split(';')[0].strip()
        is_current_dir = os.path.isdir(first_path) if os.path.exists(first_path) else False
    
        if is_current_dir:
            # 当前是文件夹，不能和文件混合，提示用户
            response = show_confirm(
                self, 
                "混合扫描类型", 
                f"当前已选择文件夹：{first_path}\n是否要替换为选择的 {len(file_paths)} 个文件？\n\n注意：文件夹和文件不能同时扫描。"
            )
            if response:
                # 用户确认替换
                count = self._add_path_to_input(new_files, replace=True)
                self.ui_log(f"📄 已替换为 {len(file_paths)} 个文件（{count}个不重复）")
        else:
            # 当前是文件，追加新文件（自动去重）
            count = self._add_path_to_input(new_files, replace=False)
            new_unique_count = count - len([p for p in current_path.split(';') if p.strip()])
        
            if new_unique_count > 0:
                self.ui_log(f"📄 已添加 {new_unique_count} 个新文件（共 {count} 个不重复文件）")
            else:
                self.ui_log(f" 没有新文件添加，所有文件都已存在")

    # -------------------------- 扫描控制（✅ 新增绑定匹配信号，强化线程判断） --------------------------
    def start_scan(self):
        """
        开始扫描-✅ 绑定match_found匹配信号，强化线程健壮性，防重复点击
        ✅ 修复：记录开始时间
        """
        scan_path_str = self.path_input.text().strip()
        if not scan_path_str:
            show_warn(self, "参数错误", "请选择扫描文件夹或文件")
            return
        
        # ✅ 修改：增强路径验证逻辑
        all_paths = []
        invalid_paths = []
        
        for path in scan_path_str.split(";"):
            path = path.strip()
            if not path:
                continue
                
            if not os.path.exists(path):
                invalid_paths.append(path)
            else:
                all_paths.append(path)
        
        if invalid_paths:
            show_warn(self, "路径错误", f"以下路径不存在：\n{', '.join(invalid_paths[:3])}" + 
                     ("..." if len(invalid_paths) > 3 else ""))
            return
        
        if not all_paths:
            show_warn(self, "参数错误", "没有有效的扫描路径")
            return
        
        # ✅ 新增：检查是否同时包含文件夹和文件（不允许混合扫描）
        has_dir = False
        has_file = False
        mixed_paths = []
        
        for path in all_paths:
            if os.path.isdir(path):
                has_dir = True
                if has_file:
                    mixed_paths.append(path)
            elif os.path.isfile(path):
                has_file = True
                if has_dir:
                    mixed_paths.append(path)
        
        if has_dir and has_file:
            show_warn(self, "扫描类型冲突", "不能同时扫描文件夹和文件。\n请选择：\n1. 仅扫描单个文件夹\n2. 仅扫描多个文件")
            return
        
        # ✅ 新增：检查是否选择了多个文件夹
        if has_dir and len(all_paths) > 1:
            show_warn(self, "文件夹数量限制", "每次只能扫描一个文件夹。\n当前选择了多个文件夹路径。")
            return

        # ✅ 防卡死：避免重复创建线程
        # ✅ 防重复点击
        if self.scanner_thread and self.scanner_thread.isRunning():
            show_warn(self, "扫描中", "当前已有扫描任务在运行，请勿重复点击！")
            return

        self.reset_scan_state()

        # ✅ 核心修复：记录扫描开始时间
        # 使用高精度计时器
        # ✅ 简化：不使用定时器更新时间，只在扫描完成时更新时间
        self._scan_start_time = time.perf_counter() 

        # 启动定时器（500ms更新一次）
        if self._update_timer and not self._update_timer.isActive():
            self._update_timer.start(500)

        # 初始化线程
        self.scanner_thread = ScannerThreadManager(scan_path_str, self.config_manager)
        # ✅ 原有信号保留 + 新增绑定【匹配发现信号】
        self.scanner_thread.progress_updated.connect(self.update_progress)
        self.scanner_thread.scan_completed.connect(self.scan_completed)
        self.scanner_thread.error_occurred.connect(self.log_error)
        self.scanner_thread.status_updated.connect(self.update_status)
        self.scanner_thread.file_counting.connect(self._on_file_counting)
        self.scanner_thread.file_count_completed.connect(self._on_file_count_completed)
        self.scanner_thread.current_file.connect(self._on_current_file)
        self.scanner_thread.match_found.connect(self.on_match_found)  # ✅ 绑定匹配信号
        
        self.scanner_thread.start()

        self.stop_btn.setEnabled(True)
        
        # ✅ 修改：根据扫描类型显示不同的日志信息
        if has_dir:
            scan_type = "文件夹"
            target_info = f"文件夹：{all_paths[0]}"
        else:
            scan_type = "文件"
            if len(all_paths) == 1:
                target_info = f"文件：{all_paths[0]}"
            else:
                target_info = f"{len(all_paths)} 个文件"
        
        # ✅ 日志去重：仅UI打印，控制台/文件由logger单独负责
        self.ui_log(f"🚀 开始扫描{scan_type}：{target_info} | 线程数：{self.worker_spin.value()} | 最大文件：{self.file_size_spin.value()}MB")
        logger.info(f"开始扫描{scan_type}：{target_info} | 线程数：{self.worker_spin.value()} | 最大文件：{self.file_size_spin.value()}MB")

    def _update_time_display(self):
        """更新时间显示（定时器回调）"""
        try:
            if self._scan_start_time and hasattr(self, 'scanner_thread') and self.scanner_thread and self.scanner_thread.isRunning():
                elapsed = time.perf_counter() - self._scan_start_time
            
                # 格式化时间
                if elapsed < 60:
                    time_str = f"{max(elapsed, 0.1):.1f}秒"
                else:
                    minutes = int(elapsed // 60)
                    seconds = elapsed % 60
                    time_str = f"{minutes}分{seconds:.1f}秒"
            
                # 更新UI（如果存在相关控件）
                # 注意：这里可以添加更新时间显示的逻辑
                self.progress_label.setText(f"已用时间: {time_str}")

        except Exception as e:
            logger.warning(f"更新时间显示失败: {e}")

    def _format_time(self, seconds: float) -> str:
        """格式化时间显示"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}分{secs:.0f}秒"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}小时{minutes}分"

    def stop_scan(self):
        """停止扫描（✅ 强化健壮性，统一恢复控件状态）"""
        if not self.scanner_thread or not self.scanner_thread.isRunning():
            show_warn(self, "无任务", "当前无扫描任务在运行，无需停止！")
            return
        try:
            self.scanner_thread.stop()
            self.ui_log("🛑 正在停止扫描，请稍候...")
            logger.info("用户手动停止扫描")
            # ✅ 防卡死：停止后恢复控件状态
            self._set_ui_enabled(True)
            self.stop_btn.setEnabled(False)
        except RuntimeError as e:
            self.ui_log(f"❌ 停止扫描失败：{str(e)[:50]}", is_error=True)
            logger.error(f"停止扫描异常：{str(e)}")
        self.scanner_thread = None

    def reset_scan_state(self):
        """重置状态（✅ 防卡死：初始化控件状态+清空数据）"""
        self.all_results.clear()
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        self.progress_label.setText("就绪")
        self.export_btn.setEnabled(False)
        self.total_file_label.setText("总文件数：--")
        self.current_file_label.setText("当前扫描：--")
        self.stop_btn.setEnabled(False)
        self._set_ui_enabled(True)
        self._scan_start_time = None
        self._match_log_count = 0  # ✅ 重置匹配日志计数器

        # ✅ 修复：确保定时器存在（之前可能被设为 None）
        if not hasattr(self, '_update_timer') or self._update_timer is None:
            self._update_timer = QTimer(self)
            self._update_timer.setInterval(500)
            self._update_timer.timeout.connect(self._update_time_display)

    # -------------------------- 线程信号槽（✅ 统计开始时禁用控件，核心防卡死） --------------------------
    @pyqtSlot()
    def _on_file_counting(self):
        """✅ 防卡死核心：统计文件开始时，禁用所有操作控件（统计也是耗时操作）"""
        self.progress_bar.setMaximum(0)
        self.progress_label.setText("📊 正在统计有效文件数...")
        self.stop_btn.setEnabled(True)
        # ✅ 关键：禁用所有用户操作，让主线程专注统计
        self._set_ui_enabled(False)
        self.ui_log("📊 开始统计扫描范围内的有效文件数...")
        logger.info("开始统计有效文件数")

    @pyqtSlot(int)
    def _on_file_count_completed(self, total_valid: int):
        """
        统计完成，更新总文件数 + ✅ 恢复 UI 控件
        """
        self.total_file_label.setText(f"总文件数：{total_valid}")
    
        # 只有在总数大于0时才设置进度条最大值
        if total_valid > 0:
            # 设置进度条为确定模式，最大值为总文件数
            self.progress_bar.setMaximum(100)  # 百分比模式
            self.progress_bar.setValue(0)
            self.ui_log(f"📊 文件统计完成！本次共扫描 {total_valid} 个有效文件")
        else:
            # 没有文件，设为不确定模式
            self.progress_bar.setMaximum(0)
            self.ui_log("📊 文件统计完成！未找到有效文件")
        
        logger.info(f"文件统计完成，共{total_valid}个有效文件")

    @pyqtSlot(str)
    def _on_current_file(self, file_name: str):
        """更新当前扫描文件（仅UI展示，不重复日志）"""
        show_name = f"{file_name[:40]}..." if len(file_name) > 40 else file_name
        self.current_file_label.setText(f"当前文件：{show_name}")

    @pyqtSlot(int, int, int)
    def update_progress(self, current, total, found):
        """
        更新扫描进度
        ✅ 修复进度显示逻辑
        """
        if total > 0:
            # 确保进度条有正确的最大值
            if self.progress_bar.maximum() != total:
                self.progress_bar.setMaximum(total)
            
            # 设置当前值
            self.progress_bar.setValue(current)
            
            # 计算百分比
            percent = int((current / total) * 100) if total > 0 else 0
            
            # 更新标签
            self.progress_label.setText(f"进度：{current}/{total} ({percent}%) | 匹配：{found} 条")
            
            # ✅ 关键修复：当current >= total时，确保进度条显示100%
            if current >= total and total > 0:
                self.progress_bar.setValue(total)
                self.progress_label.setText(f"扫描完成 ({current}/{total} 文件)")
        else:
            # 如果总数未知，使用不确定模式
            self.progress_bar.setMaximum(0)
            self.progress_label.setText(f"进度：{current}个文件 | 匹配：{found} 条")
        
        # 强制UI更新
        self.progress_bar.update()

    @pyqtSlot(str)
    def log_error(self, error_msg: str):
        """错误日志（✅ 仅UI打印，logger由线程负责 + 恢复控件状态）"""
        self.ui_log(f"❌ [错误] {error_msg}", is_error=True)
        # ✅ 防卡死：出错后立即恢复控件状态
        self._set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        # ✅ 修复：使用安全的定时器停止方法
        self._stop_update_timer()
        # 清空线程引用
        self.scanner_thread = None

    @pyqtSlot(str)
    def update_status(self, status: str):
        """状态更新（✅ 仅UI打印）"""
        self.progress_label.setText(status)
        self.ui_log(f"📢 [状态] {status}")

    # ✅ 新增核心：匹配发现槽函数 - 打印【哪个路径匹配到什么内容】的精准日志
    @pyqtSlot(str, str)
    def on_match_found(self, file_path: str, match_content: str):
        """
        匹配发现槽函数
        ✅ 修复：限制日志条数，防止 QTextEdit 渲染导致 UI 卡死
        """
        self._match_log_count += 1
        if self._match_log_count > self._MATCH_LOG_LIMIT:
            if self._match_log_count == self._MATCH_LOG_LIMIT + 1:
                self.ui_log(f"⚠️ 匹配日志已达 {self._MATCH_LOG_LIMIT} 条上限，后续匹配不再显示（结果仍会导出到Excel）")
            return
        if len(match_content) > 150:
            match_content = match_content[:150] + "......【内容过长，已截断】"
        self.ui_log(f"🔍 [匹配发现] 文件路径：{file_path} | 匹配内容：{match_content}")

    # -------------------------- 扫描完成（✅ 日志去重，统一恢复控件状态） --------------------------
    @pyqtSlot(list, dict)
    def scan_completed(self, results: list, skip_counters: dict):
        """✅ 防卡死：扫描完成后统一恢复控件状态，清空线程对象"""
        """扫描完成处理 - 修复时间显示和进度条"""
        # 停止定时器
        self._stop_update_timer()

        self.scanner_thread = None
        self.all_results = results
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(len(results) > 0)
        self._set_ui_enabled(True)

        # ✅ 修复时间显示：确保至少显示0.1秒
        if self._scan_start_time:
            duration = time.perf_counter() - self._scan_start_time
            # 确保最小显示0.1秒
            if duration < 0.1:
                duration_display = 0.1
            else:
                duration_display = duration
        else:
            duration_display = 0
            duration = 0
        
        minutes, seconds = divmod(duration_display, 60)
        
        # 获取实际扫描的文件数
        total_scanned = self.progress_bar.maximum() if self.progress_bar.maximum() > 0 else 0
        total_skip = sum(skip_counters.values())

        # ✅ 扫描总结日志
        summary = (
            f"✅ [扫描完成] 总耗时：{int(minutes)}分{seconds:.2f}秒 | "
            f"匹配发现 {len(results)} 条内容 | "
            f"跳过文件 {total_skip} 个"
        )
        self.ui_log(summary)
        logger.info(summary)
        
        # ✅ 关键修复：确保进度条显示100%
        if total_scanned > 0:
            self.progress_bar.setValue(total_scanned)
            self.progress_label.setText(f"扫描完成（{len(results)}条匹配，共跳过{total_skip}个文件）")
        else:
            self.progress_label.setText(f"扫描完成（{len(results)}条匹配）")
        
        self.current_file_label.setText("当前扫描：--")
        
        # 自动导出Excel
        if len(results) > 0:
            self._auto_export_results(results)
        else:
            self.ui_log(" [扫描结果] 本次扫描未发现任何正则匹配内容")
            logger.info("本次扫描无匹配结果")

    @pyqtSlot()
    def _stop_update_timer(self):
        """停止更新时间显示的定时器"""
        # ✅ 修复：先检查属性是否存在
        # ✅ 修复：只停止，不设为 None（否则下次扫描无法启动）
        if hasattr(self, '_update_timer') and self._update_timer:
            if self._update_timer.isActive():
                self._update_timer.stop()

    def _auto_export_results(self, results):
        """自动导出结果（在主线程执行）"""
        try:
            result_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
            os.makedirs(result_dir, exist_ok=True)
            excel_name = f"扫描结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            excel_path = os.path.join(result_dir, excel_name)
            excel_settings = self.config_manager.get_excel_settings()
            export_excel(
                results=results,
                save_path=excel_path,
                headers=excel_settings.get("headers", self._default_headers),
                column_widths=excel_settings.get("column_widths", [18,40,50,15,20,20,30,20])
            )
            self.ui_log(f"📌 [自动导出] 扫描结果已导出至：{excel_path}")
            logger.info(f"Excel自动导出成功：{excel_path}")
            show_info(self, "自动导出成功", f"扫描结果已自动保存到：\n{excel_path}")
        except Exception as e:
            err_msg = f"自动导出Excel失败：{str(e)[:200]}"
            self.ui_log(f"❌ [导出错误] {err_msg}", is_error=True)
            logger.error(f"自动导出Excel失败：{str(e)}")
            show_warn(self, "自动导出失败", err_msg)

    # 手动导出（保留）
    def export_results(self):
        """手动导出结果"""
        if not self.all_results:
            show_warn(self, "导出失败", "无扫描结果可导出")
            return
        default_name = f"敏感信息扫描结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        excel_settings = self.config_manager.get_excel_settings()
        default_ext = excel_settings.get("default_ext", DEFAULT_EXCEL_EXT)
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存扫描结果",
            f"{default_name}{default_ext}",
            f"Excel文件 (*{default_ext})"
        )
        if not file_path:
            return
        if not file_path.endswith(default_ext):
            file_path += default_ext
        if os.path.exists(file_path):
            if not show_confirm(self, "文件已存在", f"文件{os.path.basename(file_path)}已存在，是否覆盖？"):
                return
        try:
            excel_settings = self.config_manager.get_excel_settings()
            export_excel(
                results=self.all_results,
                save_path=file_path,
                headers=excel_settings.get("headers", self._default_headers),
                column_widths=excel_settings.get("column_widths", [18,40,50,15,20,20,30,20])
            )
            self.ui_log(f"📌 [手动导出] 扫描结果已导出至：{file_path}")
            logger.info(f"Excel手动导出成功：{file_path}")
            show_info(self, "导出成功", f"扫描结果已成功导出到：\n{file_path}")
        except Exception as e:
            err_msg = f"手动导出Excel失败：{str(e)[:200]}"
            self.ui_log(f"❌ [导出错误] {err_msg}", is_error=True)
            logger.error(f"手动导出Excel失败：{str(e)}")
            show_warn(self, "导出失败", err_msg)

    # -------------------------- 核心工具：✅ 重构ui_log方法（线程安全+彻底去重） --------------------------
    def ui_log(self, msg: str, is_error: bool = False, is_warning: bool = False):
        """
        UI专用日志方法 - ✅ 简化版，修复invokeMethod问题
        使用直接在主线程调用的方式，避免复杂的线程安全问题
        """
        # ✅ 修复：在主线程直接执行，使用QMetaObject.invokeMethod调用一个真实存在的方法
        def append_log():
            time_str = datetime.now().strftime('%H:%M:%S')
            
            if is_error:
                html = f"<font color='red'>[{time_str}] ❌ {msg}</font>"
            elif is_warning:
                html = f"<font color='orange'>[{time_str}] ⚠️ {msg}</font>"
            else:
                if "匹配发现" in msg:
                    html = f"<font color='green'>[{time_str}] 🔍 {msg}</font>"
                elif "扫描完成" in msg:
                    html = f"<font color='blue'>[{time_str}] ✅ {msg}</font>"
                elif "扫描" in msg and "开始" in msg:
                    html = f"<font color='purple'>[{time_str}] 🚀 {msg}</font>"
                else:
                    html = f"[{time_str}] {msg}"
            
            self.log_text.append(html)
            # 自动滚动
            self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
        
        # 如果当前是主线程，直接执行
        if QThread.currentThread() == self.thread():
            append_log()
        else:
            # 否则使用lambda包装，通过invokeMethod在主线程执行
            QMetaObject.invokeMethod(self, "append_log_wrapper", Qt.QueuedConnection,
                                   Q_ARG(object, append_log))
    @pyqtSlot(object)
    def append_log_wrapper(self, func):
        """包装函数，用于invokeMethod调用"""
        if callable(func):
            func()
