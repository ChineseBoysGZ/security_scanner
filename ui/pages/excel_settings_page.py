"""
ui/pages/excel_settings_page.py
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QComboBox,
    QLabel, QFrame, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor

# 本地模块导入
from config.constants import FIXED_COL_NUM, DEFAULT_EXCEL_HEADERS, DEFAULT_EXCEL_WIDTHS, DEFAULT_EXCEL_EXT
from ui.components import (
    create_btn, create_col_config_row, show_warn, show_info, show_confirm
)

class ExcelSettingsPage(QWidget):
    """Excel设置页-列配置增删改/格式设置，配置保存后同步扫描页"""
    # 信号：配置保存后通知其他组件
    settings_saved = pyqtSignal()

    def __init__(self, config_manager, scan_page):
        super().__init__()
        self.config_manager = config_manager
        self.scan_page = scan_page  # 扫描页实例，用于同步配置
        self.selected_col = None    # 选中的列配置行
        self.column_widgets = []    # 列配置部件：[(row_widget, header_input, width_spin), ...]
        # 设置窗口属性
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.init_ui()
        # 加载Excel配置
        self.load_settings()

    def init_ui(self):
        """初始化UI-现代化设计，清晰布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(25, 25, 25, 25)

        # 标题区域
        title_label = QLabel("📊 Excel导出设置")
        title_label.setObjectName("page_title")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 主内容区域
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(25)
        
        # 1. 操作面板（按钮组）
        self._create_control_panel(content_layout)
        
        # 2. 列配置区域
        self._create_column_config_area(content_layout)
        
        # 3. 格式设置区域
        self._create_format_settings_area(content_layout)
        
        # 将内容放入可滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidget(content_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        main_layout.addWidget(scroll_area, stretch=1)
        
        # 应用样式
        self._apply_styles()

    def _create_control_panel(self, parent_layout):
        """创建操作面板"""
        control_group = QGroupBox("操作面板")
        control_group.setObjectName("control_group")
        
        control_layout = QHBoxLayout(control_group)
        control_layout.setSpacing(15)
        control_layout.setContentsMargins(20, 20, 20, 20)
        
        # 左侧按钮组
        left_btn_layout = QHBoxLayout()
        left_btn_layout.setSpacing(10)
        
        self.add_col_btn = create_btn("➕ 添加新列", "primary")
        self.add_col_btn.setIconSize(self.add_col_btn.iconSize() * 0.9)
        self.add_col_btn.setMinimumHeight(40)
        
        self.del_col_btn = create_btn("🗑️ 删除选中列", "danger")
        self.del_col_btn.setIconSize(self.del_col_btn.iconSize() * 0.9)
        self.del_col_btn.setMinimumHeight(40)
        
        left_btn_layout.addWidget(self.add_col_btn)
        left_btn_layout.addWidget(self.del_col_btn)
        left_btn_layout.addStretch()
        
        # 右侧保存按钮
        self.save_btn = create_btn("💾 保存设置", "success")
        self.save_btn.setIconSize(self.save_btn.iconSize() * 0.9)
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setMinimumWidth(120)
        
        control_layout.addLayout(left_btn_layout)
        control_layout.addStretch()
        control_layout.addWidget(self.save_btn)
        
        parent_layout.addWidget(control_group)
        
        # 绑定按钮事件
        self.add_col_btn.clicked.connect(self.add_column)
        self.del_col_btn.clicked.connect(self.delete_column)
        self.save_btn.clicked.connect(self.save_settings)
    
    def _create_column_config_area(self, parent_layout):
        """创建列配置区域"""
        config_group = QGroupBox("列配置管理")
        config_group.setObjectName("config_group")
        
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(15)
        config_layout.setContentsMargins(20, 20, 20, 20)
        
        # 说明标签
        info_label = QLabel(
            "• 点击表头输入框可选中该列进行编辑\n"
            "• 前4列为核心列，显示为红色标签，不可删除\n"
            "• 拖动列配置卡片可调整顺序（功能待实现）"
        )
        info_label.setObjectName("info_label")
        info_label.setWordWrap(True)
        config_layout.addWidget(info_label)
        
        # 添加分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setObjectName("separator")
        config_layout.addWidget(separator)
        
        # 列配置容器
        self.col_container = QWidget()
        self.col_layout = QVBoxLayout(self.col_container)
        self.col_layout.setSpacing(12)
        self.col_layout.setContentsMargins(5, 5, 5, 5)
        
        # 将容器放入可滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.col_container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setMinimumHeight(300)
        scroll_area.setMaximumHeight(500)
        
        config_layout.addWidget(scroll_area)
        
        parent_layout.addWidget(config_group)
    
    def _create_format_settings_area(self, parent_layout):
        """创建格式设置区域"""
        format_group = QGroupBox("导出格式设置")
        format_group.setObjectName("format_group")
        
        format_layout = QFormLayout(format_group)
        format_layout.setSpacing(15)
        format_layout.setContentsMargins(20, 20, 20, 20)
        format_layout.setLabelAlignment(Qt.AlignRight)
        
        # 文件格式选择
        self.format_combo = QComboBox()
        self.format_combo.addItems([".xlsx", ".xls"])
        self.format_combo.setFixedWidth(120)
        self.format_combo.setMinimumHeight(35)
        
        format_layout.addRow("默认保存格式：", self.format_combo)
        
        # 添加提示信息
        tip_label = QLabel("💡 提示：推荐使用 .xlsx 格式以获得更好的兼容性和性能")
        tip_label.setObjectName("tip_label")
        format_layout.addRow("", tip_label)
        
        parent_layout.addWidget(format_group)
    
    def _apply_styles(self):
        """应用简化样式表（完全兼容PyQt5）"""
        self.setStyleSheet("""
            /* 页面标题 */
            QLabel#page_title {
                font-size: 22px;
                font-weight: bold;
                color: #2c3e50;
                padding: 10px;
                border-bottom: 2px solid #3498db;
            }
        
            /* 分组框样式 */
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #34495e;
                border: 1px solid #bdc3c7;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 12px;
            }
        
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px 0 8px;
            }
        
            /* 信息标签 */
            QLabel#info_label {
                font-size: 11px;
                color: #7f8c8d;
                background-color: #f8f9fa;
                padding: 10px;
                border-radius: 4px;
            }
        
            QLabel#tip_label {
                font-size: 11px;
                color: #27ae60;
                padding: 6px;
            }
        
            /* 滚动区域样式 */
            QScrollArea {
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        """)

    # -------------------------- 列配置组件创建 --------------------------
    def _add_col_widget(self, header_text: str, width_val: int, is_fixed: bool, col_index: int):
        """添加列配置部件到布局"""
        row_widget, header_input, width_spin = create_col_config_row(
            header_text, width_val, is_fixed, col_index, self
        )
        
        # 设置行小部件的样式
        row_widget.setObjectName("col_row")
        if is_fixed:
            row_widget.setStyleSheet("""
                QWidget#col_row {
                    background-color: #fff9f9;
                    border: 1px solid #ffcdd2;
                    border-radius: 6px;
                    padding: 12px;
                }
            """)
        else:
            row_widget.setStyleSheet("""
                QWidget#col_row {
                    background-color: #ffffff;
                    border: 1px solid #e0e0e0;
                    border-radius: 6px;
                    padding: 12px;
                }
                QWidget#col_row:hover {
                    border-color: #3498db;
                    background-color: #f8fdff;
                }
            """)
        
        self.column_widgets.append((row_widget, header_input, width_spin))
        self.col_layout.addWidget(row_widget)
        return row_widget

    # -------------------------- 列配置增删改 --------------------------
    def add_column(self):
        """添加新列-自动编号，默认配置"""
        col_num = len(self.column_widgets) + 1
        self._add_col_widget(
            header_text=f"自定义列{col_num}",
            width_val=20 + col_num * 3,
            is_fixed=False,
            col_index=col_num
        )
        # 选中新添加的列
        self.selected_col = self.column_widgets[-1][0]
        self._highlight_selected_column(self.selected_col)
        
        # 滚动到新添加的列
        self.col_container.parent().ensureWidgetVisible(self.selected_col)
        
        show_info(self, "添加成功", f"已添加第{col_num}列，请修改表头名称和列宽！")

    def delete_column(self):
        """删除选中列-禁止删除核心列"""
        if not hasattr(self, 'selected_col') or not self.selected_col:
            show_warn(self, "未选择", "请先点击要删除列的表头输入框选中该列！")
            return
        
        # 检查是否为核心列
        col_index = self._get_column_index(self.selected_col)
        if col_index < FIXED_COL_NUM:
            show_warn(self, "禁止删除", "前四列为核心列，包含扫描关键信息，禁止删除！")
            return
        
        # 获取列信息用于提示
        col_info = ""
        for i, (widget, header_input, _) in enumerate(self.column_widgets):
            if widget == self.selected_col:
                col_info = f"列 {i+1}: {header_input.text() or '未命名'}"
                break
        
        # 二次确认
        if not show_confirm(self, "删除确认", f"确定要删除以下列吗？\n\n{col_info}\n\n删除后需要保存配置才会生效"):
            return
        
        # 从布局和列表中删除
        self.col_layout.removeWidget(self.selected_col)
        self.selected_col.deleteLater()
        
        # 从列表中移除
        for i, (widget, _, _) in enumerate(self.column_widgets):
            if widget == self.selected_col:
                del self.column_widgets[i]
                break
        
        # 重新编号列
        self._reindex_columns()
        show_info(self, "删除成功", "选中列已删除，请点击【保存设置】使修改生效！")

    def _get_column_index(self, widget):
        """获取列索引"""
        for i, (w, _, _) in enumerate(self.column_widgets):
            if w == widget:
                return i
        return -1
    
    def _highlight_selected_column(self, row_widget):
        """高亮选中的列"""
        # 清除所有行的高亮
        for widget, _, _ in self.column_widgets:
            current_style = widget.styleSheet()
            if "border: 2px solid #2980b9;" in current_style:
                # 移除选中样式，恢复原有样式
                is_fixed = self._get_column_index(widget) < FIXED_COL_NUM
                if is_fixed:
                    widget.setStyleSheet("""
                        QWidget#col_row {
                            background-color: #fff9f9;
                            border: 1px solid #ffcdd2;
                            border-radius: 6px;
                            padding: 12px;
                        }
                    """)
                else:
                    widget.setStyleSheet("""
                        QWidget#col_row {
                            background-color: #ffffff;
                            border: 1px solid #e0e0e0;
                            border-radius: 6px;
                            padding: 12px;
                        }
                        QWidget#col_row:hover {
                            border-color: #3498db;
                            background-color: #f8fdff;
                        }
                    """)
        
        # 为选中的行添加高亮
        current_style = row_widget.styleSheet()
        if "border: 2px solid #2980b9;" not in current_style:
            is_fixed = self._get_column_index(row_widget) < FIXED_COL_NUM
            border_color = "#e74c3c" if is_fixed else "#2980b9"
            bg_color = "#fff0f0" if is_fixed else "#f0f8ff"
            
            row_widget.setStyleSheet(f"""
                QWidget#col_row {{
                    background-color: {bg_color};
                    border: 2px solid {border_color};
                    border-radius: 6px;
                    padding: 12px;
                }}
            """)

    def _reindex_columns(self):
        """重新编号列配置-删除列后更新标签"""
        for i, (row_widget, header_input, width_spin) in enumerate(self.column_widgets):
            is_fixed = i < FIXED_COL_NUM
            
            # 更新行小部件的样式
            if is_fixed:
                row_widget.setStyleSheet("""
                    QWidget#col_row {
                        background-color: #fff9f9;
                        border: 1px solid #ffcdd2;
                        border-radius: 6px;
                        padding: 12px;
                    }
                """)
            else:
                row_widget.setStyleSheet("""
                    QWidget#col_row {
                        background-color: #ffffff;
                        border: 1px solid #e0e0e0;
                        border-radius: 6px;
                        padding: 12px;
                    }
                    QWidget#col_row:hover {
                        border-color: #3498db;
                        background-color: #f8fdff;
                    }
                """)
        
        # 清除选中状态
        self.selected_col = None

    # -------------------------- 配置加载/保存 --------------------------
    def load_settings(self):
        """加载Excel配置-从配置读取，无则加载默认列"""
        # 清空原有部件
        for row_widget, _, _ in self.column_widgets:
            self.col_layout.removeWidget(row_widget)
            row_widget.deleteLater()
        self.column_widgets.clear()
        
        # 获取配置
        excel_settings = self.config_manager.get_excel_settings()
        headers = excel_settings.get("headers", DEFAULT_EXCEL_HEADERS)
        widths = excel_settings.get("column_widths", DEFAULT_EXCEL_WIDTHS)
        
        # 确保列数至少为默认列数，不足则补充
        default_col_count = 8  # 您需要的8列
        if len(headers) < default_col_count:
            # 使用默认的8列配置进行补充
            headers += DEFAULT_EXCEL_HEADERS[len(headers):default_col_count]
            widths += DEFAULT_EXCEL_WIDTHS[len(widths):default_col_count]
        
        # 加载列配置部件
        for i, (header, width) in enumerate(zip(headers, widths)):
            self._add_col_widget(
                header_text=header,
                width_val=width,
                is_fixed=i < FIXED_COL_NUM,
                col_index=i + 1
            )
        
        # 加载默认保存格式
        self.format_combo.setCurrentText(excel_settings.get("default_ext", DEFAULT_EXCEL_EXT))
        
        # 选中第一列
        if self.column_widgets:
            self.selected_col = self.column_widgets[0][0]
            self._highlight_selected_column(self.selected_col)

    def save_settings(self):
        """保存Excel配置-同步到扫描页表格/导出配置"""
        # 收集列配置
        headers, widths = [], []
        for _, header_input, width_spin in self.column_widgets:
            header = header_input.text().strip() or "未命名列"
            headers.append(header)
            # 列宽限制在10-100之间
            width = max(10, min(width_spin.value(), 100))
            widths.append(width)
        
        # 验证表头是否重复
        duplicates = {}
        for i, header in enumerate(headers):
            if header in duplicates:
                duplicates[header].append(i + 1)
            else:
                duplicates[header] = [i + 1]
        
        duplicate_headers = {k: v for k, v in duplicates.items() if len(v) > 1}
        if duplicate_headers:
            duplicate_msg = "\n".join([f"'{header}' 出现在第{', '.join(map(str, cols))}列" 
                                      for header, cols in duplicate_headers.items()])
            show_warn(self, "表头重复", f"以下表头名称重复，请修改：\n\n{duplicate_msg}")
            return
        
        # 更新配置字典
        excel_settings = {
            "headers": headers,
            "column_widths": widths,
            "default_ext": self.format_combo.currentText()
        }
        
        self.config_manager.config["excel_settings"] = excel_settings
        
        # 保存配置
        if self.config_manager.save_config():
            # 发出配置保存信号
            self.settings_saved.emit()
            
            show_info(self, "保存成功", 
                     f"✅ Excel配置已保存！\n\n"
                     f"• 总列数: {len(headers)}\n"
                     f"• 核心列: {FIXED_COL_NUM}\n"
                     f"• 格式: {self.format_combo.currentText()}\n\n"
                     "配置已应用到导出功能。")
        else:
            show_warn(self, "保存失败", "Excel配置保存失败，请检查日志或文件权限！")
