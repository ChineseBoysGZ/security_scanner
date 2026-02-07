"""
excel_match_page.py - Excel数据匹配页面（字体优化版）
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFileDialog, QComboBox, QGroupBox,
                             QCheckBox, QTextEdit, QMessageBox, QProgressBar,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QGridLayout, QRadioButton, QButtonGroup,
                             QScrollArea, QFrame, QSplitter, QSizePolicy,
                             QSpacerItem, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont
import pandas as pd
import os
import re
import sys
from datetime import datetime, timedelta
import numpy as np
import warnings

# 忽略openpyxl的警告
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# 字体配置
if sys.platform == "win32":
    DEFAULT_FONT = "Microsoft YaHei"
    FONT_SIZE = 9
elif sys.platform == "darwin":  # macOS
    DEFAULT_FONT = "Arial"
    FONT_SIZE = 11
else:  # Linux
    DEFAULT_FONT = "DejaVu Sans"
    FONT_SIZE = 10

class ExcelMatchThread(QThread):
    """Excel匹配线程（日期格式优化版）"""
    progress_signal = pyqtSignal(str, int)  # (消息, 进度)
    result_signal = pyqtSignal(pd.DataFrame)  # 匹配结果
    error_signal = pyqtSignal(str)
    
    def __init__(self, file_a_path, file_b_path, id_column_a, id_columns_b, 
                 column_mapping, match_mode='exact', case_sensitive=False):
        """
        初始化匹配线程
        Args:
            file_a_path: 扫描结果文件A路径
            file_b_path: 数据源文件B路径
            id_column_a: 文件A中的应用ID列
            id_columns_b: 文件B中用于匹配的列（列表）
            column_mapping: 列名映射 {目标列: 源列}
            match_mode: 匹配模式 'exact'/'partial'
            case_sensitive: 是否区分大小写
        """
        super().__init__()
        self.file_a_path = file_a_path
        self.file_b_path = file_b_path
        self.id_column_a = id_column_a
        self.id_columns_b = id_columns_b
        self.column_mapping = column_mapping
        self.match_mode = match_mode
        self.case_sensitive = case_sensitive
        self.result_df = None
        
    def run(self):
        try:
            self.progress_signal.emit("正在读取扫描结果文件A...", 10)
            
            # 读取文件A（扫描结果）
            df_a = self._read_excel_with_date_preserved(self.file_a_path)
            
            # 验证应用ID列
            if self.id_column_a not in df_a.columns:
                self.error_signal.emit(f"扫描结果文件中未找到列: {self.id_column_a}")
                return
            
            self.progress_signal.emit("正在读取数据源文件B...", 20)
            
            # 读取文件B（数据源）
            df_b = self._read_excel_with_date_preserved(self.file_b_path)
            
            # 验证文件B中的匹配列
            missing_id_columns = [col for col in self.id_columns_b if col not in df_b.columns]
            if missing_id_columns:
                self.error_signal.emit(f"数据源文件中未找到匹配列: {', '.join(missing_id_columns)}")
                return
            
            # 验证映射列
            missing_mapping_columns = []
            for source_col in self.column_mapping.values():
                if source_col and source_col not in df_b.columns:
                    missing_mapping_columns.append(source_col)
            
            if missing_mapping_columns:
                self.error_signal.emit(f"数据源文件中未找到映射列: {', '.join(missing_mapping_columns)}")
                return
            
            self.progress_signal.emit("开始匹配数据...", 30)
            
            # 预处理应用ID（清理和标准化）
            df_a['_match_id'] = df_a[self.id_column_a].apply(self._normalize_id)
            
            # 构建文件B的匹配字典
            match_dict = self._build_match_dict(df_b)
            
            # 执行匹配并合并数据
            merged_df = self._merge_data(df_a, df_b, match_dict)
            
            # 清理临时列
            if '_match_id' in merged_df.columns:
                merged_df = merged_df.drop(columns=['_match_id'])
            
            self.result_df = merged_df
            
            # 统计匹配结果
            matched_count = merged_df['_matched'].sum() if '_matched' in merged_df.columns else 0
            total_count = len(merged_df)
            
            self.progress_signal.emit(f"匹配完成！共匹配到{matched_count}/{total_count}条记录", 100)
            self.result_signal.emit(merged_df)
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            self.error_signal.emit(f"匹配过程中出现错误: {str(e)}\n详细: {error_detail}")
    
    def _read_excel_with_date_preserved(self, file_path):
        """
        读取Excel文件，根据列名进行日期格式化
        """
        try:
            # 使用pandas读取，但处理日期列
            df = pd.read_excel(
                file_path, 
                engine='openpyxl',
                dtype=object  # 使用object类型保持原始格式
            )
            
            # 将NaN转换为空字符串
            df = df.fillna("")
            
            # 处理日期列
            date_columns = ["下线时间", "上线日期"]
            for col in df.columns:
                if col in date_columns:
                    df[col] = df[col].apply(lambda x: self._conservative_date_format(x, col))
            
            return df
            
        except Exception as e:
            # 如果失败，使用简单方法
            self.progress_signal.emit(f"注意: 使用简单方法读取文件 {os.path.basename(file_path)}", 0)
            df = pd.read_excel(file_path, dtype=str)
            df = df.fillna("")
            return df
    
    def _conservative_date_format(self, value, column_name):
        """
        根据列名进行不同的日期格式化
        - 下线时间：格式化为YYYYMMDD（如20110210）
        - 上线日期：格式化为YYYY/MM/DD（如2011/02/10）
        """
        if pd.isna(value) or value == "":
            return ""
        
        str_value = str(value).strip()
        # 如果已经是目标格式，直接返回
        if column_name == "下线时间" and self._is_valid_downline_format(str_value):
            return str_value
        elif column_name == "上线日期" and self._is_valid_upline_format(str_value):
            return str_value
        
        # 尝试转换为datetime对象
        date_obj = self._parse_date(str_value)
        if date_obj:
            # 根据列名格式化为不同的格式
            if column_name == "下线时间":
                return date_obj.strftime('%Y%m%d')  # YYYYMMDD
            elif column_name == "上线日期":
                return date_obj.strftime('%Y/%m/%d')  # YYYY/MM/DD
            else:
                return str_value
            
        # 无法解析为日期，返回原始值
        return str_value
    
    def _is_valid_downline_format(self, value):
        """检查是否是有效的下线时间格式（YYYYMMDD）"""
        # 检查是否是8位纯数字
        if len(value) == 8 and value.isdigit():
            try:
                year = int(value[0:4])
                month = int(value[4:6])
                day = int(value[6:8])
                # 简单的日期验证
                if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                    return True
            except:
                pass
        return False
    
    def _is_valid_upline_format(self, value):
        """检查是否是有效的上线日期格式（YYYY/MM/DD）"""
        # 检查是否符合YYYY/MM/DD格式
        import re
        pattern = r'^\d{4}/\d{2}/\d{2}$'
        if re.match(pattern, value):
            try:
                parts = value.split('/')
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
                if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                    return True
            except:
                pass
        return False
    
    def _parse_date(self, value):
        """尝试解析各种格式的日期字符串"""
        from datetime import datetime
        
        if not value or pd.isna(value):
            return None
        
        # 去除空格
        value = str(value).strip()
        
        # 如果为空，返回None
        if not value:
            return None
        
        # 尝试常见的日期格式
        date_formats = [
            '%Y-%m-%d',      # 2020-10-02
            '%Y/%m/%d',      # 2020/10/02
            '%Y.%m.%d',      # 2020.10.02
            '%Y%m%d',        # 20201002
            '%Y年%m月%d日',  # 2020年10月02日
            '%m/%d/%Y',      # 10/02/2020 (美国格式)
            '%d/%m/%Y',      # 02/10/2020 (欧洲格式)
        ]
        
        # 尝试每个格式
        for date_format in date_formats:
            try:
                return datetime.strptime(value, date_format)
            except:
                continue
        
        # 尝试处理Excel日期序列号
        try:
            float_val = float(value)
            # Excel日期序列号通常大于1
            if 1 < float_val < 100000:
                # Excel日期序列号转换
                if float_val > 60:
                    float_val -= 1  # 修正1900年闰年错误
                excel_epoch = datetime(1899, 12, 30)
                date_value = excel_epoch + timedelta(days=float_val)
                return date_value
        except:
            pass
        
        return None

    def _normalize_id(self, id_value):
        """标准化应用ID"""
        if pd.isna(id_value) or id_value == "":
            return ""
        
        id_str = str(id_value).strip()
        if not self.case_sensitive:
            id_str = id_str.lower()
        
        return id_str
    
    def _build_match_dict(self, df_b):
        """构建文件B的匹配字典"""
        match_dict = {}
        
        total_rows = len(df_b)
        
        for idx, row in df_b.iterrows():
            progress = 30 + int(40 * idx / total_rows)
            if (idx + 1) % 100 == 0:
                self.progress_signal.emit(f"处理数据源第{idx+1}行...", progress)
            
            # 从多个列中提取可能的应用ID
            extracted_ids = set()
            
            for id_col in self.id_columns_b:
                if id_col not in df_b.columns:
                    continue
                
                cell_value = str(row[id_col]) if pd.notna(row[id_col]) else ""
                if not cell_value:
                    continue
                
                # 标准化ID
                normalized_value = self._normalize_id(cell_value)
                
                if self.match_mode == 'exact':
                    # 精确匹配：整个单元格作为一个ID
                    if normalized_value:
                        extracted_ids.add(normalized_value)
                else:
                    # 部分匹配：从单元格中提取可能的ID
                    # 这里可以根据实际情况调整提取逻辑
                    # 例如：按逗号、空格等分隔符分割
                    parts = re.split(r'[,，;；\s]+', normalized_value)
                    for part in parts:
                        if part and len(part) >= 2:  # 假设ID长度至少2位
                            extracted_ids.add(part)
            
            # 为提取到的每个ID存储该行的数据
            for app_id in extracted_ids:
                if app_id not in match_dict:
                    match_dict[app_id] = {}
                    for target_col, source_col in self.column_mapping.items():
                        if source_col and source_col in df_b.columns:
                            value = row[source_col] if pd.notna(row[source_col]) else ""
                            match_dict[app_id][target_col] = str(value)
                        else:
                            match_dict[app_id][target_col] = ""
        
        return match_dict
    
    def _merge_data(self, df_a, df_b, match_dict):
        """合并数据到文件A"""
        self.progress_signal.emit("开始合并数据...", 70)
        
        # 在df_a中添加新列
        for target_col in self.column_mapping.keys():
            if target_col not in df_a.columns:
                df_a[target_col] = ""
        
        # 添加匹配状态列
        df_a['_matched'] = False
        
        total_rows = len(df_a)
        matched_count = 0
        
        for idx, row in df_a.iterrows():
            progress = 70 + int(20 * idx / total_rows)
            if (idx + 1) % 100 == 0:
                self.progress_signal.emit(f"合并第{idx+1}行...", progress)
            
            app_id = row['_match_id']
            
            if app_id and app_id in match_dict:
                # 匹配成功，填充数据
                matched_data = match_dict[app_id]
                for target_col, value in matched_data.items():
                    # 处理日期字段
                    if target_col in ["下线时间", "上线日期"]:
                        df_a.at[idx, target_col] = self._conservative_date_format(value, target_col)
                    else:
                        df_a.at[idx, target_col] = str(value) if value else ""
                
                df_a.at[idx, '_matched'] = True
                matched_count += 1
        
        return df_a

    def _ensure_date_format(self, value):
        """
        确保日期值是易读的格式
        """
        if not value:
            return ""
        
        # 如果已经是易读的日期格式，直接返回
        str_value = str(value)
        if any(sep in str_value for sep in ['-', '/', '.', '年', '月', '日']):
            return str_value
        
        # 尝试转换可能的Excel日期序列号
        try:
            # 检查是否是数字
            float_val = float(str_value)
            if 1 < float_val < 100000:
                return self._excel_serial_to_date(float_val)
        except:
            pass
        
        # 其他情况返回原始字符串
        return str_value

class ScrollableCheckboxFrame(QFrame):
    """可滚动的复选框框架"""
    def __init__(self):
        super().__init__()
        self.checkboxes = {}
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 创建一个水平滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 禁用垂直滚动条
        scroll_area.setMinimumHeight(40)  # 设置较小的高度
        scroll_area.setMaximumHeight(45)
        
        # 滚动区域内的容器
        container = QWidget()
        self.container_layout = QHBoxLayout(container)
        self.container_layout.setSpacing(8)
        self.container_layout.setContentsMargins(5, 2, 5, 2)
        
        scroll_area.setWidget(container)
        layout.addWidget(scroll_area)
        
        self.setLayout(layout)
    
    def set_checkboxes(self, columns):
        """设置复选框"""
        # 清除之前的复选框
        self.clear_checkboxes()
        
        # 为每一列创建复选框
        for col in columns:
            cb = QCheckBox(col)
            cb.setFixedHeight(24)  # 固定高度
            
            # 自动选中可能包含应用ID的列
            col_lower = col.lower()
            if any(keyword in col_lower for keyword in ['系统id', '应用id', 'appid', 'id', '开发者', '开发人员', '创建人']):
                cb.setChecked(True)
            
            self.checkboxes[col] = cb
            self.container_layout.addWidget(cb)
        
        self.container_layout.addStretch()
    
    def clear_checkboxes(self):
        """清空复选框"""
        for cb in self.checkboxes.values():
            cb.setParent(None)
            cb.deleteLater()
        self.checkboxes.clear()
    
    def get_checked_columns(self):
        """获取选中的列名"""
        checked = []
        for col, cb in self.checkboxes.items():
            if cb.isChecked():
                checked.append(col)
        return checked

class ColumnMappingWidget(QWidget):
    """列名映射部件（优化版）"""
    def __init__(self, file_b_columns):
        super().__init__()
        self.file_b_columns = file_b_columns
        self.mapping_combos = {}
        self.init_ui()
        
    def init_ui(self):
        # 使用垂直布局，更加紧凑
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 表头
        #layout.addWidget(QLabel("<b>目标字段</b>"), 0, 0)
        #layout.addWidget(QLabel("<b>映射到数据源文件的列</b>"), 0, 1)
        #layout.addWidget(QLabel("<b>自动匹配</b>"), 0, 2)
        
        # 定义必须匹配的字段（按优先级排序）
        self.required_fields = [
            ("应用ID", ["应用ID", "APPID", "应用编号", "ID", "app_id", "AppID"], True),
            ("对应系统", ["对应系统", "系统名称", "所属系统", "系统", "归属系统", "system"], False),
            ("项目经理", ["项目经理", "负责人", "责任人", "负责人姓名", "owner"], False),
            ("子应用名称", ["子应用名称", "应用名称", "应用名", "应用", "app_name"], False),
            ("项目经理工号", ["项目经理工号", "工号", "员工号", "员工编号", "emp_no"], False),
            ("子应用状态", ["子应用状态", "应用状态", "状态", "status"], False),
            ("上线日期", ["上线日期", "上架时间", "启用时间", "上线时间", "create_time"], False),
            ("下线时间", ["下线时间", "下架时间", "停用时间", "下线日期", "offline_time"], False)
        ]
        
        for field_name, keywords, is_id_field in self.required_fields:
            # 每个字段一行
            field_layout = QHBoxLayout()
            
            # 目标字段标签
            field_label = QLabel(field_name)
            field_label.setMinimumWidth(80)
            if is_id_field:
                field_label.setStyleSheet("color: #FF5722; font-weight: bold;")
            field_layout.addWidget(field_label)
            
            # 下拉框选择映射列
            combo = QComboBox()
            combo.setMinimumWidth(180)
            combo.addItem("(不映射)", "")
            combo.addItems(self.file_b_columns)
            self.mapping_combos[field_name] = combo
            field_layout.addWidget(combo)
            
            # 自动匹配按钮
            btn_auto = QPushButton("🔍")
            btn_auto.setMaximumWidth(40)
            btn_auto.setToolTip(f"自动匹配{field_name}")
            btn_auto.clicked.connect(lambda checked, f=field_name, k=keywords: 
                                    self.auto_match(f, k))
            field_layout.addWidget(btn_auto)
            
            layout.addLayout(field_layout)
        
        layout.addStretch()
        self.setLayout(layout)
    
    def auto_match(self, field_name, keywords):
        """自动匹配列名"""
        combo = self.mapping_combos[field_name]
        
        # 首先尝试精确匹配
        for keyword in keywords:
            for col in self.file_b_columns:
                if keyword.lower() == col.lower():
                    index = combo.findText(col)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                        return
        
        # 然后尝试包含匹配
        for keyword in keywords:
            for col in self.file_b_columns:
                if keyword.lower() in col.lower():
                    index = combo.findText(col)
                    if index >= 0:
                        combo.setCurrentIndex(index)
                        return
        
        # 如果还没找到，使用第一个列
        if self.file_b_columns:
            index = combo.findText(self.file_b_columns[0])
            if index >= 0:
                combo.setCurrentIndex(index)
    
    def auto_match_all(self):
        """自动匹配所有字段"""
        for field_name, keywords, _ in self.required_fields:
            self.auto_match(field_name, keywords)
    
    def get_mapping(self):
        """获取映射关系"""
        mapping = {}
        for field_name, combo in self.mapping_combos.items():
            selected_col = combo.currentText()
            if selected_col == "(不映射)":
                mapping[field_name] = ""
            else:
                mapping[field_name] = selected_col
        return mapping
    
    def get_id_mapping(self):
        """获取应用ID的映射列（用于文件B）"""
        mapping = self.get_mapping()
        # 返回"应用ID"字段的映射
        return mapping.get("应用ID", "")

class ExcelMatchPage(QWidget):
    """Excel数据匹配页面（字体优化版）"""
    
    from datetime import timedelta

    def __init__(self):
        super().__init__()
        self.file_a_path = None  # 扫描结果文件
        self.file_b_path = None  # 数据源文件
        self.df_a = None
        self.df_b = None
        self.result_df = None  # 匹配结果
        self.column_mapping_widget = None
        self.init_ui()
        
    def init_ui(self):
        # 主水平布局，左侧配置，右侧操作和预览
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)
        
        # === 左侧：配置区域（固定宽度）===
        left_panel = QWidget()
        left_panel.setMaximumWidth(450)  # 限制左侧宽度
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 5, 0)
        
        # 1. 文件选择和输出方式（水平并排）
        file_output_widget = QWidget()
        file_output_layout = QHBoxLayout(file_output_widget)
        file_output_layout.setContentsMargins(0, 0, 0, 0)
        
        # 文件选择组（更紧凑）
        file_group = QGroupBox("📁 文件选择")
        file_layout = QVBoxLayout()
        file_layout.setSpacing(4)
        
        # 扫描结果文件A
        file_a_layout = QHBoxLayout()
        file_a_layout.addWidget(QLabel("扫描结果(A):"))
        self.btn_select_file_a = QPushButton("选择...")
        self.btn_select_file_a.setMaximumWidth(80)
        self.btn_select_file_a.clicked.connect(self.select_file_a)
        file_a_layout.addWidget(self.btn_select_file_a)
        file_a_layout.addStretch()
        self.label_file_a = QLabel("未选择")
        self.label_file_a.setStyleSheet("color: #666; font-size: 11px;")
        file_a_layout.addWidget(self.label_file_a)
        file_layout.addLayout(file_a_layout)
        
        # 数据源文件B
        file_b_layout = QHBoxLayout()
        file_b_layout.addWidget(QLabel("数据源(B):"))
        self.btn_select_file_b = QPushButton("选择...")
        self.btn_select_file_b.setMaximumWidth(80)
        self.btn_select_file_b.clicked.connect(self.select_file_b)
        file_b_layout.addWidget(self.btn_select_file_b)
        file_b_layout.addStretch()
        self.label_file_b = QLabel("未选择")
        self.label_file_b.setStyleSheet("color: #666; font-size: 11px;")
        file_b_layout.addWidget(self.label_file_b)
        file_layout.addLayout(file_b_layout)
        
        file_group.setLayout(file_layout)
        file_group.setMaximumHeight(100)
        file_output_layout.addWidget(file_group, 1)  # 拉伸因子1
        
        # 输出方式组
        output_group = QGroupBox("💾 输出")
        output_layout = QVBoxLayout()
        output_layout.setSpacing(6)
        self.radio_new_file = QRadioButton("创建新文件")
        self.radio_new_file.setChecked(True)
        self.radio_overwrite = QRadioButton("覆盖原文件")
        output_layout.addWidget(self.radio_new_file)
        output_layout.addWidget(self.radio_overwrite)
        output_group.setLayout(output_layout)
        output_group.setMaximumHeight(100)
        file_output_layout.addWidget(output_group, 1)  # 拉伸因子1
        
        left_layout.addWidget(file_output_widget)
        
        # 2. 匹配设置区域（紧凑）
        settings_group = QGroupBox("匹配设置")
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(6)
        
        # 应用ID列选择
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("应用ID列:"))
        self.combo_id_column_a = QComboBox()
        self.combo_id_column_a.setMinimumWidth(180)
        id_layout.addWidget(self.combo_id_column_a)
        settings_layout.addLayout(id_layout)
        
        # 匹配列选择（单行显示）
        match_layout = QVBoxLayout()
        match_layout.addWidget(QLabel("匹配列（文件B，勾选包含应用ID的列）:"))
        
        # 创建可滚动的复选框框架，设置固定高度
        self.scrollable_checkbox_frame = ScrollableCheckboxFrame()
        self.scrollable_checkbox_frame.setMinimumHeight(40)
        self.scrollable_checkbox_frame.setMaximumHeight(50)
        match_layout.addWidget(self.scrollable_checkbox_frame)
        settings_layout.addLayout(match_layout)
        
        # 匹配选项
        options_layout = QHBoxLayout()
        options_layout.addWidget(QLabel("匹配模式:"))
        self.radio_exact = QRadioButton("精确")
        self.radio_exact.setChecked(True)
        self.radio_partial = QRadioButton("部分")
        options_layout.addWidget(self.radio_exact)
        options_layout.addWidget(self.radio_partial)
        
        self.cb_case_sensitive = QCheckBox("区分大小写")
        self.cb_case_sensitive.setChecked(False)
        options_layout.addWidget(self.cb_case_sensitive)
        options_layout.addStretch()
        settings_layout.addLayout(options_layout)
        
        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)
        
        # 3. 列名映射区域（占比最大）
        self.mapping_group = QGroupBox("🔄 数据字段映射")
        self.mapping_group.setVisible(False)
        self.mapping_layout = QVBoxLayout()
        self.mapping_group.setLayout(self.mapping_layout)
        left_layout.addWidget(self.mapping_group, 1)  # 拉伸因子1，占用剩余空间
        
        # 自动配置按钮（放在左侧底部）
        self.btn_auto_config = QPushButton("🔧 自动配置所有")
        self.btn_auto_config.clicked.connect(self.auto_config_all)
        self.btn_auto_config.setEnabled(False)
        left_layout.addWidget(self.btn_auto_config)
        
        left_layout.addStretch()
        
        # === 右侧：操作和结果区域（可拉伸）===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 0, 0, 0)
        
        # 操作按钮区域
        button_group = QGroupBox("🚀 操作控制")
        button_group.setMaximumHeight(80)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        # 分析文件按钮
        self.btn_analyze = QPushButton("📊 分析文件")
        self.btn_analyze.clicked.connect(self.analyze_files)
        self.btn_analyze.setEnabled(False)
        button_layout.addWidget(self.btn_analyze)
        
        # 预览按钮
        self.btn_preview = QPushButton("👁️ 预览匹配")
        self.btn_preview.clicked.connect(self.preview_match)
        self.btn_preview.setEnabled(False)
        self.btn_preview.setStyleSheet("background-color: #2196F3; color: white;")
        button_layout.addWidget(self.btn_preview)
        
        # 执行匹配按钮
        self.btn_execute = QPushButton("🚀 执行匹配")
        self.btn_execute.clicked.connect(self.execute_match)
        self.btn_execute.setEnabled(False)
        self.btn_execute.setStyleSheet("background-color: #4CAF50; color: white;")
        button_layout.addWidget(self.btn_execute)
        
        # 导出按钮
        self.btn_export = QPushButton("💾 导出结果")
        self.btn_export.clicked.connect(self.export_result)
        self.btn_export.setEnabled(False)
        button_layout.addWidget(self.btn_export)
        
        button_layout.addStretch()
        button_group.setLayout(button_layout)
        right_layout.addWidget(button_group)
        
        # 进度条
        self.progress_bar = QProgressBar()
        right_layout.addWidget(self.progress_bar)
        
        # 使用选项卡组织信息显示
        self.info_tabs = QTabWidget()  # 改为实例变量
        
        # 文件信息标签页
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFont(QFont(DEFAULT_FONT, FONT_SIZE))
        info_layout.addWidget(self.info_text)
        self.info_tabs.addTab(info_tab, "📋 文件分析")
        
        # 状态日志标签页
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)

        # 添加清空日志按钮
        log_button_layout = QHBoxLayout()
        btn_clear_log = QPushButton("🗑️ 清空日志")
        btn_clear_log.clicked.connect(self.clear_log)
        log_button_layout.addWidget(btn_clear_log)
        log_button_layout.addStretch()
        log_layout.addLayout(log_button_layout)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setFont(QFont(DEFAULT_FONT, FONT_SIZE - 1))
        log_layout.addWidget(self.status_text)
        self.info_tabs.addTab(log_tab, "📝 状态日志")
        
        # 预览标签页
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        self.preview_table = QTableWidget()
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview_table.setFont(QFont(DEFAULT_FONT, FONT_SIZE))
        preview_layout.addWidget(self.preview_table)
        self.info_tabs.addTab(preview_tab, "👁️ 预览结果")
        
        # 添加选项卡索引的引用，方便跳转
        self.TAB_FILE_ANALYSIS = 0  # 文件分析标签页索引
        self.TAB_STATUS_LOG = 1     # 状态日志标签页索引
        self.TAB_PREVIEW = 2        # 预览结果标签页索引
    
        right_layout.addWidget(self.info_tabs, 1)  # 拉伸因子1，占用剩余空间
        
        # === 将左右面板添加到主布局 ===
        main_layout.addWidget(left_panel, 1)  # 左侧固定宽度
        main_layout.addWidget(right_panel, 3)  # 右侧占用3倍宽度
        
        # 设置整体布局
        self.setLayout(main_layout)
        
        # 设置字体
        self.setFont(QFont(DEFAULT_FONT, FONT_SIZE))
        
        # 初始化日志
        self.log_message("=== Excel数据匹配工具 ===")
        self.log_message("请按照以下步骤操作:")
        self.log_message("1. 选择扫描结果文件（A）和数据源文件（B）")
        self.log_message("2. 配置匹配设置和字段映射")
        self.log_message("3. 分析文件结构")
        self.log_message("4. 预览匹配结果")
        self.log_message("5. 执行匹配并导出结果")
    
    def clear_log(self):
        """清空状态日志"""
        self.status_text.clear()
        self.log_message("日志已清空")

    def select_file_a(self):
        """选择扫描结果文件A"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择扫描结果Excel文件", "", "Excel文件 (*.xlsx *.xls)"
        )
        if file_path:
            self.file_a_path = file_path
            self.label_file_a.setText(os.path.basename(file_path))
            self.load_file_a_columns(file_path)
            self.check_ready_state()
            self.log_message(f"已选择扫描结果文件: {os.path.basename(file_path)}")
    
    def select_file_b(self):
        """选择数据源文件B"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择数据源Excel文件", "", "Excel文件 (*.xlsx *.xls)"
        )
        if file_path:
            self.file_b_path = file_path
            self.label_file_b.setText(os.path.basename(file_path))
            self.load_file_b_columns(file_path)
            self.check_ready_state()
            self.log_message(f"已选择数据源文件: {os.path.basename(file_path)}")
    
    def load_file_a_columns(self, file_path):
        """加载文件A的列名"""
        try:
            # 使用优化的读取方法
            self.df_a = self.read_excel_safe(file_path, nrows=0)
            self.combo_id_column_a.clear()
            self.combo_id_column_a.addItems(self.df_a.columns.tolist())
            
            # 尝试自动识别应用ID列
            id_keywords = ['应用ID', 'AppID', '应用编号', 'ID', 'app_id', '应用标识']
            for keyword in id_keywords:
                for col in self.df_a.columns:
                    if keyword.lower() in col.lower():
                        index = self.combo_id_column_a.findText(col)
                        if index >= 0:
                            self.combo_id_column_a.setCurrentIndex(index)
                            self.log_message(f"自动选择了应用ID列: {col}")
                            break
                else:
                    continue
                break
                
        except Exception as e:
            self.log_message(f"❌ 读取扫描结果文件失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"读取扫描结果文件失败: {str(e)}")
    
    def load_file_b_columns(self, file_path):
        """加载文件B的列名"""
        try:
            # 使用优化的读取方法
            self.df_b = self.read_excel_safe(file_path, nrows=0)
            columns = self.df_b.columns.tolist()
            
            # 设置可滚动复选框
            self.scrollable_checkbox_frame.set_checkboxes(columns)
            
            self.btn_auto_config.setEnabled(True)
            
        except Exception as e:
            self.log_message(f"❌ 读取数据源文件失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"读取数据源文件失败: {str(e)}")

    def read_excel_safe(self, file_path, nrows=None):
        """安全读取Excel文件，正确处理日期格式"""
        try:
            # 尝试使用openpyxl引擎读取，可以更好地处理日期
            if nrows:
                df = pd.read_excel(
                    file_path, 
                    engine='openpyxl',
                    nrows=nrows,
                    dtype=str  # 先全部读取为字符串
                )
            else:
                df = pd.read_excel(
                    file_path, 
                    engine='openpyxl',
                    dtype=str
                )
            
            # 将所有NaN转换为空字符串
            df = df.fillna("")
            
            return df
            
        except Exception as e:
            # 如果出错，回退到简单读取
            self.log_message(f"注意: 使用简单模式读取文件 {os.path.basename(file_path)}")
            if nrows:
                df = pd.read_excel(file_path, nrows=nrows, dtype=str)
            else:
                df = pd.read_excel(file_path, dtype=str)
            df = df.fillna("")
            return df
    
    def check_ready_state(self):
        """检查是否可以执行匹配"""
        ready = bool(self.file_a_path and self.file_b_path)
        self.btn_analyze.setEnabled(ready)
        self.btn_preview.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.btn_export.setEnabled(False)
    
    def log_message(self, message):
        """记录日志消息到状态文本区域"""
        # 如果是错误消息，自动跳转到状态日志标签页
        if "❌" in message or "⚠️" in message or "错误" in message:
            self.info_tabs.setCurrentIndex(self.TAB_STATUS_LOG)

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.append(f"[{timestamp}] {message}")
        # 滚动到底部
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )
    
    def auto_config_all(self):
        """自动配置所有选项"""
        # 检查复选框是否存在
        if not hasattr(self.scrollable_checkbox_frame, 'checkboxes') or not self.scrollable_checkbox_frame.checkboxes:
            self.log_message("⚠️ 请先选择数据源文件")
            return
        
        # 自动选择匹配列
        id_keywords = ['系统id', '应用id', 'appid', 'id', '开发者', '开发人员', '创建人', 'creator', 'author']
        
        checked_count = 0
        for col, cb in self.scrollable_checkbox_frame.checkboxes.items():
            col_lower = col.lower()
            if any(keyword in col_lower for keyword in id_keywords):
                cb.setChecked(True)
                checked_count += 1
            else:
                cb.setChecked(False)
        
        self.log_message(f"✅ 已自动配置匹配列: {checked_count} 个列被选中")
        
        # 自动配置字段映射
        if self.column_mapping_widget:
            self.column_mapping_widget.auto_match_all()
            self.log_message("✅ 已自动配置字段映射")
    
    def analyze_files(self):
        """分析文件结构"""
        if not self.validate_inputs():
            return
        
        try:
            # 先跳转到文件分析标签页
            self.info_tabs.setCurrentIndex(self.TAB_FILE_ANALYSIS)
        
            # 读取文件A的预览数据
            df_a_sample = self.read_excel_safe(self.file_a_path, nrows=10)
            id_column = self.combo_id_column_a.currentText()
        
            # 读取文件B的预览数据
            df_b_sample = self.read_excel_safe(self.file_b_path, nrows=10)
            
            # 显示文件信息
            info = "=== 文件分析结果 ===\n\n"
            info += f"📄 扫描结果文件（A）: {os.path.basename(self.file_a_path)}\n"
            info += f"   列数: {len(df_a_sample.columns)}\n"
            info += f"   行数（预览）: {len(df_a_sample)}\n"
            info += f"   应用ID列: {id_column}\n"
            
            if id_column in df_a_sample.columns:
                id_samples = df_a_sample[id_column].head(5).tolist()
                info += f"   应用ID示例: {id_samples}\n"
            
            info += f"\n📄 数据源文件（B）: {os.path.basename(self.file_b_path)}\n"
            info += f"   列数: {len(df_b_sample.columns)}\n"
            info += f"   行数（预览）: {len(df_b_sample)}\n"
            info += f"   所有列: {', '.join(df_b_sample.columns.tolist())}\n\n"
            
            # 显示推荐配置
            info += "=== 推荐配置 ===\n"
            info += "1. 在数据源文件中勾选可能包含应用ID的列（已自动勾选系统ID、开发者等）\n"
            info += "2. 在下方字段映射中配置对应关系\n"
            info += "3. 点击'自动配置'可以自动完成配置\n"
            
            self.info_text.setText(info)
            self.info_text.setVisible(True)
            
            # 创建列名映射配置界面
            self.setup_column_mapping(df_b_sample.columns.tolist())
            
            self.btn_preview.setEnabled(True)
            self.preview_table.setVisible(False)
            
            self.log_message("✅ 文件分析完成")
            
        except Exception as e:
            # 出错时跳转到状态日志标签页
            self.info_tabs.setCurrentIndex(self.TAB_STATUS_LOG)
            self.log_message(f"❌ 分析文件失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"分析文件失败: {str(e)}")
    
    def setup_column_mapping(self, file_b_columns):
        """设置列名映射配置"""
        # 清空之前的映射界面
        self.clear_layout(self.mapping_layout)
        
        # 创建新的映射部件
        self.column_mapping_widget = ColumnMappingWidget(file_b_columns)
        self.mapping_layout.addWidget(self.column_mapping_widget)
        
        # 添加自动配置所有按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_auto_all = QPushButton("🔧 自动配置所有字段")
        btn_auto_all.setMaximumWidth(150)
        btn_auto_all.clicked.connect(self.column_mapping_widget.auto_match_all)
        btn_layout.addWidget(btn_auto_all)
        self.mapping_layout.addLayout(btn_layout)
        
        # 显示映射区域
        self.mapping_group.setVisible(True)
    
    def clear_layout(self, layout):
        """清空布局"""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
    
    def get_selected_match_columns(self):
        """获取选中的匹配列"""
        if hasattr(self, 'scrollable_checkbox_frame') and self.scrollable_checkbox_frame:
            return self.scrollable_checkbox_frame.get_checked_columns()
        return []
    
    def get_column_mapping(self):
        """获取列名映射关系"""
        if self.column_mapping_widget:
            return self.column_mapping_widget.get_mapping()
        return {}
    
    def get_match_mode(self):
        """获取匹配模式"""
        if self.radio_exact.isChecked():
            return 'exact'
        else:
            return 'partial'
    
    def preview_match(self):
        """预览匹配结果"""
        if not self.validate_inputs():
            return
        
        id_column = self.combo_id_column_a.currentText()
        match_columns = self.get_selected_match_columns()
        column_mapping = self.get_column_mapping()
        
        if not match_columns:
            QMessageBox.warning(self, "警告", "请至少选择一个匹配列")
            return
        
        # 检查是否有有效的映射
        if not any(column_mapping.values()):
            QMessageBox.warning(self, "警告", "请配置至少一个字段的映射")
            return
        
        try:
            # 跳转到状态日志标签页，让用户看到进度
            self.info_tabs.setCurrentIndex(self.TAB_STATUS_LOG)
            self.log_message("正在预览匹配结果...")
            
            # 创建预览线程（只处理前50行）
            self.preview_thread = ExcelMatchThread(
                self.file_a_path,
                self.file_b_path,
                id_column,
                match_columns,
                column_mapping,
                self.get_match_mode(),
                self.cb_case_sensitive.isChecked()
            )
            
            self.preview_thread.progress_signal.connect(self.update_progress)
            self.preview_thread.result_signal.connect(self.on_preview_complete)
            self.preview_thread.error_signal.connect(self.on_match_error)
            
            self.btn_preview.setEnabled(False)
            self.preview_thread.start()
            
        except Exception as e:
            # 出错时保持状态日志标签页显示
            self.info_tabs.setCurrentIndex(self.TAB_STATUS_LOG)
            self.log_message(f"❌ 预览失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"预览失败: {str(e)}")
    
    def on_preview_complete(self, result_df):
        """预览完成"""
        # 跳转到预览结果标签页
        self.info_tabs.setCurrentIndex(self.TAB_PREVIEW)

        # 只显示前20行作为预览
        preview_df = result_df.head(20)
        
        # 显示预览表格
        self.show_preview_table(preview_df)
        
        self.btn_preview.setEnabled(True)
        self.btn_execute.setEnabled(True)
        
        # 统计预览结果
        matched_count = preview_df['_matched'].sum() if '_matched' in preview_df.columns else 0
        total_count = len(preview_df)
        
        self.log_message(f"✅ 预览完成: {matched_count}/{total_count} 条记录匹配成功")
        
        if matched_count == 0:
            self.log_message("⚠️ 警告: 预览中未找到匹配记录，请检查配置")
    
    def show_preview_table(self, df):
        """显示预览表格"""
        # 确定要显示的列（排除临时列）
        display_columns = []
        for col in df.columns:
            if not col.startswith('_'):
                display_columns.append(col)
        
        # 添加匹配状态列
        if '_matched' in df.columns:
            display_columns.append('匹配状态')
        
        self.preview_table.setColumnCount(len(display_columns))
        self.preview_table.setHorizontalHeaderLabels(display_columns)
        self.preview_table.setRowCount(min(30, len(df)))  # 最多显示30行
        
        for i, (_, row) in enumerate(df.head(30).iterrows()):  # 只处理前30行
            for j, col_name in enumerate(display_columns):
                if col_name == '匹配状态':
                    value = "✅ 已匹配" if row.get('_matched', False) else "❌ 未匹配"
                else:
                    value = str(row[col_name]) if pd.notna(row[col_name]) else ""
                
                item = QTableWidgetItem(str(value))
                
                # 为匹配状态设置颜色
                if col_name == '匹配状态':
                    if value == "✅ 已匹配":
                        item.setBackground(Qt.green)
                        item.setForeground(Qt.white)
                    else:
                        item.setBackground(Qt.lightGray)
                
                self.preview_table.setItem(i, j, item)
        
        self.preview_table.setVisible(True)
        self.info_text.setVisible(False)
    
    def execute_match(self):
        """执行匹配"""
        if not self.validate_inputs():
            return
        
        id_column = self.combo_id_column_a.currentText()
        match_columns = self.get_selected_match_columns()
        column_mapping = self.get_column_mapping()
        
        if not match_columns:
            QMessageBox.warning(self, "警告", "请至少选择一个匹配列")
            return
        
        # 检查是否有有效的映射
        if not any(column_mapping.values()):
            QMessageBox.warning(self, "警告", "请配置至少一个字段的映射")
            return
        
        # 确认执行
        reply = QMessageBox.question(
            self, '确认执行', 
            f'确定要执行匹配吗？\n\n'
            f'• 扫描结果文件: {os.path.basename(self.file_a_path)}\n'
            f'• 数据源文件: {os.path.basename(self.file_b_path)}\n'
            f'• 匹配列: {len(match_columns)}个\n'
            f'• 映射字段: {len([v for v in column_mapping.values() if v])}个',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 跳转到状态日志标签页
        self.info_tabs.setCurrentIndex(self.TAB_STATUS_LOG)

        # 创建并启动匹配线程
        self.match_thread = ExcelMatchThread(
            self.file_a_path,
            self.file_b_path,
            id_column,
            match_columns,
            column_mapping,
            self.get_match_mode(),
            self.cb_case_sensitive.isChecked()
        )
        
        self.match_thread.progress_signal.connect(self.update_progress)
        self.match_thread.result_signal.connect(self.on_match_complete)
        self.match_thread.error_signal.connect(self.on_match_error)
        
        self.btn_execute.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.match_thread.start()
        
        self.log_message("🚀 开始执行匹配...")
    
    def validate_inputs(self):
        """验证输入"""
        if not self.file_a_path or not self.file_b_path:
            QMessageBox.warning(self, "警告", "请先选择两个文件")
            return False
        
        if self.combo_id_column_a.count() == 0:
            QMessageBox.warning(self, "警告", "请先选择扫描结果文件")
            return False
        
        return True
    
    def update_progress(self, message, progress):
        """更新进度"""
        self.progress_bar.setValue(progress)
        self.log_message(message)
    
    def on_match_complete(self, result_df):
        """匹配完成"""
        # 跳转到预览结果标签页
        self.info_tabs.setCurrentIndex(self.TAB_PREVIEW)

        self.result_df = result_df
        self.btn_execute.setEnabled(True)
        self.btn_preview.setEnabled(True)
        self.btn_export.setEnabled(True)
        
        # 统计匹配结果
        matched_count = result_df['_matched'].sum() if '_matched' in result_df.columns else 0
        total_count = len(result_df)
        
        summary = f"\n=== 匹配统计 ===\n"
        summary += f"📊 总记录数: {total_count}\n"
        summary += f"✅ 成功匹配: {matched_count}\n"
        summary += f"❌ 未匹配: {total_count - matched_count}\n"
        if total_count > 0:
            match_rate = matched_count / total_count * 100
            summary += f"📈 匹配率: {match_rate:.1f}%\n"
        
        summary += f"\n📋 新增字段:\n"
        column_mapping = self.get_column_mapping()
        for field, source_col in column_mapping.items():
            if source_col:
                summary += f"  • {field} ← {source_col}\n"
        
        # 添加到状态日志
        self.status_text.append(summary)
        
        # 显示结果预览
        self.show_preview_table(result_df.head(20))
        
        QMessageBox.information(self, "完成", 
            f"匹配完成！\n\n"
            f"总记录数: {total_count}\n"
            f"成功匹配: {matched_count}\n"
            f"匹配率: {(matched_count/total_count*100):.1f}%")
    
    def on_match_error(self, error_msg):
        """匹配错误"""
        # 保持在状态日志标签页显示错误
        self.info_tabs.setCurrentIndex(self.TAB_STATUS_LOG)
        self.log_message(f"❌ 错误: {error_msg}")
        self.btn_execute.setEnabled(True)
        self.btn_preview.setEnabled(True)
        QMessageBox.critical(self, "错误", error_msg)
    
    def export_result(self):
        """导出结果"""
        if self.result_df is None:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        # 移除临时列
        export_df = self.result_df.copy()
        for col in export_df.columns:
            if col.startswith('_'):
                export_df = export_df.drop(columns=[col])

        # 处理日期列
        date_columns = ["下线时间", "上线日期"]
        for col in date_columns:
            if col in export_df.columns:
                export_df[col] = export_df[col].apply(
                    lambda x: self._safe_date_format(x, col) if pd.notna(x) else ""
                )

        # 根据输出选项确定默认文件名
        if self.radio_new_file.isChecked():
            # 创建新文件
            base_name = os.path.splitext(os.path.basename(self.file_a_path))[0]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"{base_name}_匹配结果_{timestamp}.xlsx"
        else:
            # 覆盖原文件
            default_filename = os.path.basename(self.file_a_path)
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "保存匹配结果", 
            default_filename, 
            "Excel文件 (*.xlsx)"
        )
        
        if file_path:
            try:
                # 确保文件扩展名正确
                if not file_path.endswith('.xlsx'):
                    file_path += '.xlsx'
                
                # 保存到Excel，使用openpyxl引擎以保持格式
                with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                    export_df.to_excel(writer, index=False, sheet_name='匹配结果')
                
                # 如果选择覆盖原文件，备份原文件
                if self.radio_overwrite.isChecked() and file_path == self.file_a_path:
                    backup_path = self.file_a_path.replace('.xlsx', f'_备份_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
                    import shutil
                    shutil.copy2(self.file_a_path, backup_path)
                    self.log_message(f"📁 原文件已备份到: {backup_path}")
                
                self.log_message(f"✅ 结果已保存到: {file_path}")
                
                # 显示保存信息
                file_size = os.path.getsize(file_path) / 1024  # KB
                info_msg = f"保存成功！\n\n文件: {os.path.basename(file_path)}\n大小: {file_size:.1f} KB\n行数: {len(export_df)}"
                
                reply = QMessageBox.information(
                    self, "成功", info_msg,
                    QMessageBox.Open | QMessageBox.Ok, QMessageBox.Ok
                )
                
                if reply == QMessageBox.Open:
                    # 打开文件所在目录
                    import subprocess
                    import platform
                    
                    file_dir = os.path.dirname(file_path)
                    
                    if platform.system() == "Windows":
                        os.startfile(file_dir)
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.call(["open", file_dir])
                    else:  # Linux
                        subprocess.call(["xdg-open", file_dir])
                
            except Exception as e:
                self.log_message(f"❌ 保存失败: {str(e)}")
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")
    
    def _safe_date_format(self, value, column_name):
        """
        安全地格式化日期值，避免误转换
        Excel数据匹配页面（添加上线日期）
        """
        if not value or pd.isna(value):
            return ""
        
        str_value = str(value).strip()
        
        # 检查是否已经是目标格式
        if column_name == "下线时间":
            # 检查是否是YYYYMMDD格式
            if len(str_value) == 8 and str_value.isdigit():
                return str_value
        elif column_name == "上线日期":
            # 检查是否是YYYY/MM/DD格式
            import re
            if re.match(r'^\d{4}/\d{2}/\d{2}$', str_value):
                return str_value
            
        # 尝试解析并重新格式化
        date_obj = self._parse_date_for_export(str_value)
        if date_obj:
            if column_name == "下线时间":
                return date_obj.strftime('%Y%m%d')  # YYYYMMDD
            elif column_name == "上线日期":
                return date_obj.strftime('%Y/%m/%d')  # YYYY/MM/DD
        
        # 无法解析，返回原始值
        return str_value
    
    def _parse_date_for_export(self, value):
        """为导出解析日期字符串"""
        from datetime import datetime
        
        if not value:
            return None
        
        # 尝试常见的日期格式
        date_formats = [
            '%Y-%m-%d',      # 2020-10-02
            '%Y/%m/%d',      # 2020/10/02
            '%Y.%m.%d',      # 2020.10.02
            '%Y%m%d',        # 20201002
            '%Y年%m月%d日',  # 2020年10月02日
            '%m/%d/%Y',      # 10/02/2020
            '%d/%m/%Y',      # 02/10/2020
        ]
        
        for date_format in date_formats:
            try:
                return datetime.strptime(value, date_format)
            except:
                continue
        
        # 尝试Excel日期序列号
        try:
            float_val = float(value)
            if 1 < float_val < 100000:
                if float_val > 60:
                    float_val -= 1
                excel_epoch = datetime(1899, 12, 30)
                date_value = excel_epoch + timedelta(days=float_val)
                return date_value
        except:
            pass
        
        return None
    