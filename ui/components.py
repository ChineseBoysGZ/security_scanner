"""
ui/components.py
"""

from PyQt5.QtWidgets import (
    QPushButton, QLineEdit, QTextEdit, QListWidget, QTableWidget,
    QProgressBar, QMessageBox, QWidget, QHBoxLayout, QLabel
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from .styles import (
    BUTTON_STYLE, INPUT_STYLE, LIST_STYLE, TABLE_STYLE,
    PROGRESS_STYLE, LABEL_STYLE, GROUP_STYLE
)
from config.constants import SYS_FONT

# -------------------------- 按钮组件 --------------------------
def create_btn(text: str, style_type: str = "default", parent=None) -> QPushButton:
    """创建带样式的按钮-支持primary/success/danger/default/small"""
    btn = QPushButton(text, parent)
    btn.setStyleSheet(BUTTON_STYLE[style_type])
    # 🔴 修复：替换解包为位置参数
    btn.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))
    return btn

# -------------------------- 输入框组件 --------------------------
def create_line_edit(placeholder: str = "", style_type: str = "default", parent=None) -> QLineEdit:
    """创建带样式的单行输入框"""
    le = QLineEdit(parent)
    le.setPlaceholderText(placeholder)
    le.setStyleSheet(INPUT_STYLE[style_type])
    le.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))  # 已正确，无需修改
    return le

def create_text_edit(placeholder: str = "", max_height: int = 0, parent=None) -> QTextEdit:
    """创建带样式的多行文本框-支持最大高度"""
    te = QTextEdit(parent)
    te.setPlaceholderText(placeholder)
    te.setStyleSheet(INPUT_STYLE["default"])
    # 🔴 修复：替换解包为位置参数
    te.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))
    if max_height > 0:
        te.setMaximumHeight(max_height)
    return te

# -------------------------- 列表/表格组件 --------------------------
def create_list_widget(parent=None) -> QListWidget:
    """创建带样式的列表组件"""
    lw = QListWidget(parent)
    lw.setStyleSheet(LIST_STYLE)
    # 🔴 修复：替换解包为位置参数
    lw.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))
    return lw

def create_table_widget(col_num: int, headers: list, parent=None) -> QTableWidget:
    """创建带样式的表格组件-初始化列数/表头"""
    tw = QTableWidget(parent)
    tw.setColumnCount(col_num)
    tw.setHorizontalHeaderLabels(headers)
    tw.setStyleSheet(TABLE_STYLE)
    # 🔴 修复：替换解包为位置参数
    tw.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))
    tw.horizontalHeader().setSectionResizeMode(tw.horizontalHeader().Stretch)
    tw.setAlternatingRowColors(True)
    tw.setEditTriggers(tw.NoEditTriggers)  # 禁止编辑
    return tw

# -------------------------- 进度条组件 --------------------------
def create_progress_bar(parent=None) -> QProgressBar:
    """创建带样式的进度条（显示百分比）"""
    pb = QProgressBar(parent)
    pb.setStyleSheet("""
        QProgressBar {
            border: 1px solid #EEEEEE;
            border-radius: 6px;
            text-align: center;
            font-size: 9pt;
            height: 20px;
        }
        QProgressBar::chunk {
            background-color: #2196F3;
            border-radius: 4px;
        }
    """)
    pb.setValue(0)
    pb.setFormat("%p%")  # 🔴 显示百分比（%p%是PyQt5内置占位符）
    return pb

# -------------------------- 标签组件 --------------------------
def create_label(text: str, is_fixed: bool = False, parent=None) -> QLabel:
    """创建标签-支持核心列标红"""
    lbl = QLabel(text, parent)
    lbl.setStyleSheet(LABEL_STYLE)
    if is_fixed:
        lbl.setObjectName("fixed_label")
        lbl.setToolTip("核心列-禁止删除/修改")
    return lbl

# -------------------------- 消息提示框（统一封装） --------------------------
def show_info(parent, title: str, msg: str):
    """信息提示框"""
    QMessageBox.information(parent, title, msg, QMessageBox.Ok)

def show_warn(parent, title: str, msg: str):
    """警告提示框"""
    QMessageBox.warning(parent, title, msg, QMessageBox.Ok)

def show_error(parent, title: str, msg: str):
    """错误提示框"""
    QMessageBox.critical(parent, title, msg, QMessageBox.Ok)

def show_confirm(parent, title: str, msg: str) -> bool:
    """确认提示框-返回True/False"""
    reply = QMessageBox.question(
        parent, title, msg,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No
    )
    return reply == QMessageBox.Yes

# -------------------------- 列配置行组件（Excel设置页专用） --------------------------
def create_col_config_row(
    header_text: str,
    width_val: int,
    is_fixed: bool,
    col_index: int,
    parent=None
) -> QWidget:
    """创建Excel列配置行组件-现代化设计"""
    from PyQt5.QtWidgets import QSpinBox, QFrame, QVBoxLayout  # ✅ 添加导入

    row_widget = QWidget(parent)
    row_widget.setObjectName("col_row")
    row_layout = QHBoxLayout(row_widget)
    row_layout.setContentsMargins(15, 10, 15, 10)
    row_layout.setSpacing(15)

    # 列序号标签
    index_frame = QFrame()
    index_frame.setObjectName("index_frame")
    index_frame.setFixedSize(40, 40)
    index_layout = QVBoxLayout(index_frame)
    index_layout.setContentsMargins(0, 0, 0, 0)
    
    index_label = QLabel(str(col_index))
    index_label.setObjectName("index_label")
    index_label.setAlignment(Qt.AlignCenter)

    if is_fixed:
        index_frame.setStyleSheet("""
            QFrame#index_frame {
                background-color: #ffebee;
                border: 2px solid #f44336;
                border-radius: 8px;
            }
            QLabel#index_label {
                color: #d32f2f;
                font-weight: bold;
                font-size: 14px;
            }
        """)
    else:
        index_frame.setStyleSheet("""
            QFrame#index_frame {
                background-color: #e3f2fd;
                border: 2px solid #2196f3;
                border-radius: 8px;
            }
            QLabel#index_label {
                color: #1565c0;
                font-weight: bold;
                font-size: 14px;
            }
        """)
    
    index_layout.addWidget(index_label)
    row_layout.addWidget(index_frame)
    
    # 表头配置区域
    header_widget = QWidget()
    header_layout = QVBoxLayout(header_widget)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(5)
    
    header_label = QLabel("表头名称")
    header_label.setObjectName("config_label")
    header_label.setStyleSheet("""
        QLabel#config_label {
            color: #546e7a;
            font-size: 10px;
            font-weight: bold;
        }
    """)
    
    header_input = create_line_edit("", "fixed" if is_fixed else "default")
    header_input.setText(header_text)
    header_input.setMinimumWidth(200)
    header_input.setMinimumHeight(35)
    
    # 设置占位符文本
    if is_fixed:
        header_input.setPlaceholderText("核心列表头（必填）")
    else:
        header_input.setPlaceholderText("输入列名称")
    
    # 选中高亮回调
    header_input.focusInEvent = lambda e, w=row_widget: _on_col_selected(w, parent)
    
    header_layout.addWidget(header_label)
    header_layout.addWidget(header_input)
    row_layout.addWidget(header_widget)
    
    # 列宽配置区域
    width_widget = QWidget()
    width_layout = QVBoxLayout(width_widget)
    width_layout.setContentsMargins(0, 0, 0, 0)
    width_layout.setSpacing(5)
    
    width_label = QLabel("列宽")
    width_label.setObjectName("config_label")
    width_label.setStyleSheet("""
        QLabel#config_label {
            color: #546e7a;
            font-size: 10px;
            font-weight: bold;
        }
    """)
    
    width_spin = QSpinBox(parent)
    width_spin.setRange(5, 200)
    width_spin.setValue(width_val)
    width_spin.setMinimumWidth(120)
    width_spin.setMinimumHeight(35)
    
    # 优化SpinBox样式
    width_spin.setStyleSheet("""
        QSpinBox {
            border: 1px solid #bdc3c7;
            border-radius: 4px;
            padding: 8px;
            font-size: 11pt;
            background: white;
        }
        QSpinBox:focus {
            border: 2px solid #2196f3;
        }
        QSpinBox::up-button, QSpinBox::down-button {
            width: 20px;
            border: 1px solid #bdc3c7;
            border-radius: 2px;
            background-color: #f5f5f5;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background-color: #e0e0e0;
        }
        QSpinBox::up-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-bottom: 7px solid #34495e;
        }
        QSpinBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 7px solid #34495e;
        }
    """)
    
    # 🔴 修复：替换解包为位置参数
    width_spin.setFont(QFont(SYS_FONT["familyName"], SYS_FONT["pointSize"]))
    
    width_layout.addWidget(width_label)
    width_layout.addWidget(width_spin)
    row_layout.addWidget(width_widget)
    
    # 添加类型标签
    type_label = QLabel("🔒 核心" if is_fixed else "📝 自定义")
    type_label.setObjectName("type_label")
    if is_fixed:
        type_label.setStyleSheet("""
            QLabel#type_label {
                color: #d32f2f;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 8px;
                background-color: #ffebee;
                border-radius: 4px;
                border: 1px solid #ffcdd2;
            }
        """)
    else:
        type_label.setStyleSheet("""
            QLabel#type_label {
                color: #1565c0;
                font-weight: bold;
                font-size: 10px;
                padding: 4px 8px;
                background-color: #e3f2fd;
                border-radius: 4px;
                border: 1px solid #bbdefb;
            }
        """)
    
    row_layout.addWidget(type_label)
    row_layout.addStretch()
    
    return row_widget, header_input, width_spin

def _on_col_selected(row_widget: QWidget, parent):
    """列配置行选中回调"""
    if hasattr(parent, '_highlight_selected_column'):
        parent._highlight_selected_column(row_widget)
    else:
        # 回退到原有逻辑
        if hasattr(parent, 'col_layout'):
            for i in range(parent.col_layout.count()):
                w = parent.col_layout.itemAt(i).widget()
                if w and w != row_widget:
                    w.setStyleSheet("background:transparent;border-radius:6px;")
        row_widget.setStyleSheet("background:#E3F2FD;border:2px solid #2980b9;border-radius:6px;padding:12px;")
        parent.selected_col = row_widget
