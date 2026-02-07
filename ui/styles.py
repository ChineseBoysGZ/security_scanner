"""
ui/styles.py
"""

from config.constants import SYS_FONT

# -------------------------- 全局应用字体 --------------------------
APP_FONT = SYS_FONT

# -------------------------- 按钮样式（按功能分类） --------------------------
BUTTON_STYLE = {
    "primary": """
        QPushButton {
            background: #2196F3;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 9pt;
        }
        QPushButton:hover {background: #1976D2;}  /* 悬浮加深 */
        QPushButton:disabled {background: #BBDEFB; color: #757575;}  /* 禁用灰化 */
    """,
    "success": """
        QPushButton {
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 9pt;
        }
        QPushButton:hover {background: #388E3C;}
        QPushButton:disabled {background: #C8E6C9; color: #757575;}
    """,
    "danger": """
        QPushButton {
            background: #F44336;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 9pt;
        }
        QPushButton:hover {background: #D32F2F;}
        QPushButton:disabled {background: #FFCDD2; color: #757575;}
    """,
    "default": """
        QPushButton {
            background: #E0E0E0;
            color: #333;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 9pt;
        }
        QPushButton:hover {background: #BDBDBD;}
        QPushButton:disabled {background: #F5F5F5; color: #9E9E9E;}
    """,
    "small": """
        QPushButton {
            background-color: #FFFFFF;
            color: #333333;
            padding: 4px 8px;
            border: 1px solid #E0E0E0;
            border-radius: 4px;
            font-size: 8pt;
        }
        QPushButton:hover {background-color: #F5F5F5;}
    """
}

# -------------------------- 输入框/文本框样式 --------------------------
INPUT_STYLE = {
    "default": """
        QLineEdit {
            border: 1px solid #CCCCCC;
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 9pt;
            background: white;
        }
        QLineEdit:focus {border: 2px solid #2196F3; outline: none;}  /* 聚焦高亮边框 */
        QLineEdit:hover {border: 1px solid #999999;}
    """,
    "search": """
        QLineEdit {
            border: 1px solid #CCCCCC;
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 9pt;
            background: #F5F5F5;
        }
        QLineEdit:focus {border: 2px solid #2196F3; outline: none;}
        QLineEdit:hover {border: 1px solid #999999;}
    """,
    "fixed": """
        QLineEdit {
            border: 1px solid #4CAF50;
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 9pt;
            background: #F9FBE7;
        }
        QLineEdit:focus {border: 2px solid #388E3C; outline: none;}
    """
}

# -------------------------- 列表/表格样式 --------------------------
TABLE_STYLE = """
    QTableWidget {
        border: 1px solid #EEEEEE;
        border-radius: 6px;
        font-size: 9pt;
        alternate-background-color: #F9F9F9;
    }
    QTableWidget::item {padding: 4px 8px;}
    QTableWidget::item:selected {background: #E3F2FD; color: #333;}
    QTableWidget::item:hover {background: #F5F5F5;}  /* 行悬浮 */
    QHeaderView::section {
        background: #F5F5F5;
        border: none;
        padding: 6px;
        font-weight: bold;
    }
"""
LIST_STYLE = """
    QListWidget {
        border: 1px solid #EEEEEE;
        border-radius: 6px;
        font-size: 9pt;
        background: white;
    }
    QListWidget::item {padding: 6px 8px;}
    QListWidget::item:selected {background: #E3F2FD; color: #333;}
    QListWidget::item:hover {background: #F5F5F5;}
"""

# -------------------------- 分组框/标签样式 --------------------------
GROUP_STYLE = """
    QGroupBox {
        font-size: 10pt;
        font-weight: bold;
        color: #333333;
        border: 1px solid #E0E0E0;
        border-radius: 4px;
        margin-top: 10px;
        padding-top: 8px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 8px 0 8px;
    }
"""

LABEL_STYLE = """
    QLabel {
        color: #333333;
        font-size: 9pt;
    }
    QLabel#fixed_label {
        color: #FF5722;
        font-weight: bold;
    }
"""

# -------------------------- 进度条样式 --------------------------
PROGRESS_STYLE = """
    QProgressBar {
        background-color: #F5F5F5;
        border: 1px solid #E0E0E0;
        border-radius: 4px;
        text-align: center;
        font-size: 9pt;
        height: 20px;
    }
    QProgressBar::chunk {
        background-color: #4CAF50;
        border-radius: 4px;
    }
"""