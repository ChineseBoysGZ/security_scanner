"""
main.py
"""

import sys
import os

# ✅ 消除macOS PyQt5相关的各种警告
os.environ['QT_MAC_WANTS_LAYER'] = '1'  # 解决键盘警告
os.environ['QT_MAC_NO_NATIVE_MENUBAR'] = '1'  # 不使用原生菜单栏（如果不需要）
os.environ['QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM'] = '1'  # 禁用前景应用转换

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

# 本地模块导入
from config.config_manager import ConfigManager
from ui.pages.scan_page import ScanPage
from utils.log_utils import logger
from ui.pages.regex_page import RegexPage
from ui.pages.excel_settings_page import ExcelSettingsPage
from ui.styles import APP_FONT
from ui.pages.excel_match_page import ExcelMatchPage

# 屏蔽Mac输入法框架无关警告（可选，不加也完全不影响）
os.environ['QT_IM_MODULE'] = 'qtvirtualkeyboard'
os.environ['PYTHONWARNINGS'] = 'ignore::UserWarning'

class SecurityScannerTool(QMainWindow):
    """主窗口-仅负责UI框架组装，无业务逻辑"""
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.init_ui()

    def init_ui(self):
        """初始化主窗口布局/选项卡/菜单栏"""
        # 窗口基础设置
        self.setWindowTitle("敏感信息高覆盖度扫描工具 V1.0（专用版）")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1200, 800)
        
        # 🔴 修改1：先调用窗口居中方法
        self.center_window()
        
        # 中心部件
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # 选项卡
        # 🔴 修改2：统一使用 self.tabs 变量名，删除重复的 tab_widget
        self.tabs = QTabWidget()
        self.scan_page = ScanPage(self.config_manager)
        self.regex_page = RegexPage(self.config_manager)
        self.excel_page = ExcelSettingsPage(self.config_manager, self.scan_page)
        # 创建页面实例（在创建其他页面后）
        self.excel_match_page = ExcelMatchPage()  # 新增
        self.tabs.addTab(self.scan_page, "🔍 安全扫描")
        self.tabs.addTab(self.regex_page, "正则管理")
        self.tabs.addTab(self.excel_page, "📊 Excel设置")
        self.tabs.addTab(self.excel_match_page, "🔗 Excel匹配")  # 修改：统一使用 self.tabs
        main_layout.addWidget(self.tabs)

        # 状态栏
        self.statusBar().showMessage(f"就绪 - 配置文件：{self.config_manager.config_file} | 日志目录：logs/")

        # 菜单栏
        self._create_menu_bar()

    def center_window(self):
        # 新增窗口居中方法
        """窗口居中显示（跨平台适配）"""
        qr = self.frameGeometry()
        cp = self.screen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def _create_menu_bar(self):
        """创建菜单栏-仅绑定UI跳转/基础操作"""
        menubar = self.menuBar()
        # 文件菜单
        file_menu = menubar.addMenu("📁 文件")
        file_menu.addAction("🆕 新建扫描", self._new_scan)
        file_menu.addAction("📤 导出结果", self._export_results)
        file_menu.addSeparator()
        file_menu.addAction("🚪 退出", self.close)
        # 工具菜单
        tool_menu = menubar.addMenu("🛠️ 工具")
        tool_menu.addAction("⚙️ 扫描设置", lambda: self.tabs.setCurrentIndex(0))
        tool_menu.addAction("📝 正则管理", lambda: self.tabs.setCurrentIndex(1))
        tool_menu.addAction("📊 Excel设置", lambda: self.tabs.setCurrentIndex(2))
        tool_menu.addAction("🔗 Excel匹配", lambda: self.tabs.setCurrentIndex(3))  # 🔴 新增：添加Excel匹配菜单项
        # 帮助菜单
        help_menu = menubar.addMenu("❓ 帮助")
        help_menu.addAction("ℹ️ 关于", self._show_about)

    def _new_scan(self):
        """新建扫描-调用扫描页重置方法"""
        self.scan_page.reset_scan_state()

    def _export_results(self):
        """导出结果-调用扫描页导出方法"""
        self.scan_page.export_results()

    def _show_about(self):
        """关于弹窗"""
        from ui.components import show_info
        show_info(
            self, "关于",
            "敏感信息高覆盖度扫描工具 V1.0（专用版）\n\n"
            "核心优化：\n"
            "✅ 修复17类正则语法错误，新增正则测试功能\n"
            "✅ 自动检测文件编码（UTF-8/GBK/GB2312），解决中文乱码\n"
            "✅ 过滤隐藏文件/目录，提升扫描效率\n"
            "✅ 日志UI+文件双输出，方便问题排查\n"
            "✅ 线程安全设计，支持立即停止/暂停扫描\n"
            "✅ Excel列配置完全同步，支持覆盖确认\n"
            "✅ 跨平台兼容（Windows/macOS/Linux），中文正常显示\n\n"
            "配置文件：config.json（自动备份）\n"
            "日志目录：logs/（按日期生成）\n\n"
            "Author： w09659 "
        )

    def closeEvent(self, event):
        """关闭事件-确认正在运行的扫描任务✅ 加安全检查+异常捕获，解决RuntimeError"""
        # 初始化退出标志
        need_confirm = False
        try:
            # 安全检查1：判断scan_page是否已初始化，避免属性不存在报错
            if hasattr(self, 'scan_page') and self.scan_page.scanner_thread:
                # 安全检查2：捕获底层QThread已销毁的RuntimeError
                if self.scan_page.scanner_thread.isRunning():
                    need_confirm = True
        except RuntimeError:
            # 底层QThread对象已销毁，视为扫描未运行，直接退出
            need_confirm = False
        except Exception as e:
            # 其他未知异常，打印日志但视为扫描未运行
            logger.warning(f"检查扫描状态异常：{str(e)}")
            need_confirm = False
        # 原有核心业务逻辑：扫描中则弹确认提示
        if need_confirm:
            from ui.components import show_confirm
            if show_confirm(self, "确认退出", "扫描正在进行中，确定要退出吗？"):
                self.scan_page.stop_scan()  # 点确认则停止扫描并退出
                event.accept()
            else:
                event.ignore()  # 点取消则不退出
        else:
            event.accept()  # 非扫描中，直接退出

if __name__ == "__main__":
    """程序主入口-统一跨平台样式/字体（修复属性顺序+字体解包）"""
    # 🔴 第一步：先设置所有Qt全局应用属性（必须在QApplication创建前）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)  # 高分屏适配
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)     # 可选，适配高分屏图片，建议加
    # 🔴 第二步：再创建QApplication实例（Qt硬性要求）
    app = QApplication(sys.argv)
    # 🔴 第三步：最后设置样式、全局字体
    app.setStyle('Fusion')  # 统一跨平台样式
    app.setFont(QFont(APP_FONT["familyName"], APP_FONT["pointSize"]))  # 之前修复的全局字体

    # 启动程序
    scanner = SecurityScannerTool()
    scanner.show()
    sys.exit(app.exec_())
