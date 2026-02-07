"""
ui/pages/regex_page.py
"""

import re
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QListWidgetItem
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 本地模块导入
from config.constants import REGEX_PRESETS, DEFAULT_PATTERNS, SYS_FONT
from core import validate_regex, test_regex
from utils.log_utils import logger
from ui.components import (
    create_btn, create_line_edit, create_text_edit, create_list_widget,
    show_warn, show_info, show_confirm
)

class RegexPage(QWidget):
    """正则管理页-增删改查/测试/保存，所有正则逻辑调用core模块"""
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.selected_col = None  # 选中的正则项
        # 跨平台适配-强制不透明
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background-color: #ffffff;")
        
        # ✅ 修复：设置字体编码，解决选项卡显示方块问题
        self._init_fonts()
        
        self.init_ui()
        # 加载正则规则
        self.load_patterns()

    def _init_fonts(self):
        """初始化字体设置"""
        # 确保使用系统字体，避免编码问题
        font = QFont()
        font.setFamily(SYS_FONT.get("familyName", "Arial"))
        font.setPointSize(SYS_FONT.get("pointSize", 10))
        self.setFont(font)

    def init_ui(self):
        """初始化UI-仅组装组件，无业务逻辑"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setAlignment(Qt.AlignTop)

        # 1. 操作按钮
        btn_layout = QHBoxLayout()
        self.add_btn = create_btn("添加正则", "primary")
        self.edit_btn = create_btn("编辑选中", "default")
        self.del_btn = create_btn("删除选中", "danger")
        self.save_btn = create_btn("保存配置", "success")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.del_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 2. 正则列表
        self.pattern_list = create_list_widget()
        self.pattern_list.setMinimumHeight(350)
        self.pattern_list.itemDoubleClicked.connect(self.edit_regex)
        layout.addWidget(self.pattern_list, stretch=1)

        # 3. 编辑+测试区域（新增测试功能）
        edit_group = QGroupBox("正则表达式编辑（*必填）+ 测试")
        edit_layout = QFormLayout(edit_group)
        # 编辑项
        self.name_input = create_line_edit("规则名称（如：银行卡号）*")
        self.pat_input = create_text_edit("正则表达式（忽略大小写）*", max_height=80)
        # 测试项（新增）
        self.test_input = create_text_edit("测试文本（输入后点击测试）", max_height=80)
        self.test_btn = create_btn("测试正则", "primary")
        self.test_btn.clicked.connect(self.test_current_regex)
        self.test_result = create_text_edit("测试结果（匹配到的内容）", max_height=60)
        self.test_result.setReadOnly(True)
        # 布局组装
        edit_layout.addRow("规则名称：", self.name_input)
        edit_layout.addRow("正则表达式：", self.pat_input)
        edit_layout.addRow("测试文本：", self.test_input)
        edit_layout.addRow("", self.test_btn)
        edit_layout.addRow("测试结果：", self.test_result)
        layout.addWidget(edit_group)

        # 4. 预定义模板
        preset_group = QGroupBox("预定义模板（点击快速填充）")
        preset_group.setFont(QFont(SYS_FONT.get("familyName", "Arial"), 10, QFont.Bold))  # ✅ 设置组框字体
        preset_layout = QHBoxLayout(preset_group)
        
        # ✅ 修复：确保预定义模板按钮使用正确编码
        for name, pat in REGEX_PRESETS.items():
            # 确保按钮文本使用正确的编码
            btn = create_btn(name, "small")
            # 设置按钮字体
            btn_font = QFont()
            btn_font.setFamily(SYS_FONT.get("familyName", "Arial"))
            btn_font.setPointSize(9)
            btn.setFont(btn_font)
            
            btn.clicked.connect(lambda _, n=name, p=pat: self.fill_preset(n, p))
            preset_layout.addWidget(btn)
        
        preset_layout.addStretch()
        layout.addWidget(preset_group)

        # 绑定按钮事件
        self.add_btn.clicked.connect(self.add_regex)
        self.edit_btn.clicked.connect(self.edit_regex)
        self.del_btn.clicked.connect(self.delete_regex)
        self.save_btn.clicked.connect(self.save_config)

    # -------------------------- 预定义模板填充 --------------------------
    def fill_preset(self, name: str, pat: str):
        """填充预定义正则模板"""
        self.name_input.setText(name)
        self.pat_input.setPlainText(pat)
        self.test_result.clear()

    # -------------------------- 正则加载/展示 --------------------------
    def load_patterns(self):
        """加载正则规则-从配置读取，无效则加载默认并提示"""
        self.pattern_list.clear()
        patterns = self.config_manager.get_patterns_dict()
        
        # 验证正则字典有效性
        if not isinstance(patterns, dict) or len(patterns) == 0:
            patterns = DEFAULT_PATTERNS
            self.config_manager.set_patterns_dict(patterns)
            show_warn(self, "配置异常", "正则配置无效/为空，已加载默认17类正则规则")
        
        # 展示正则规则
        for name, pat in patterns.items():
            if not name or not pat:
                continue
            
            # 截断超长正则，显示前50字符
            show_pat = pat[:50] + "..." if len(pat) > 50 else pat
            text = f"{name} | {show_pat}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, (name, pat))
            
            # ✅ 设置列表项字体
            item_font = QFont()
            item_font.setFamily(SYS_FONT.get("familyName", "Arial"))
            item_font.setPointSize(9)
            item.setFont(item_font)
            
            item.setForeground(Qt.black)
            self.pattern_list.addItem(item)
        
        logger.info(f"成功加载{len(patterns)}个正则规则")

    # -------------------------- 正则增删改 --------------------------
    def add_regex(self):
        """添加新正则-先验证有效性"""
        name = self.name_input.text().strip()
        pat = self.pat_input.toPlainText().strip()
        
        # 非空验证
        if not name or not pat:
            show_warn(self, "参数缺失", "规则名称和正则表达式为必填项！")
            return
        
        # 有效性验证（调用core模块）
        if not validate_regex(pat):
            show_warn(self, "正则无效", "正则表达式语法错误，请检查后重试！")
            return
        
        # 重复验证
        patterns = self.config_manager.get_patterns_dict()
        if name in patterns:
            if not show_confirm(self, "重复确认", f"规则名称[{name}]已存在，是否覆盖？"):
                return
        
        # 添加到列表
        show_pat = pat[:50] + "..." if len(pat) > 50 else pat
        text = f"{name} | {show_pat}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, (name, pat))
        
        # 设置列表项字体
        item_font = QFont()
        item_font.setFamily(SYS_FONT.get("familyName", "Arial"))
        item_font.setPointSize(9)
        item.setFont(item_font)
        
        item.setForeground(Qt.black)
        self.pattern_list.addItem(item)
        
        # 清空输入框
        self.name_input.clear()
        self.pat_input.clear()
        self.test_input.clear()
        self.test_result.clear()
        
        show_info(self, "添加成功", "正则规则添加成功，点击【保存配置】使修改生效！")

    def edit_regex(self):
        """编辑选中的正则规则"""
        selected = self.pattern_list.selectedItems()
        if not selected:
            show_warn(self, "未选择", "请先选择要编辑的正则规则！")
            return
        
        # 加载选中项到输入框
        name, pat = selected[0].data(Qt.UserRole)
        self.name_input.setText(name)
        self.pat_input.setPlainText(pat)
        self.test_result.clear()

    def delete_regex(self):
        """删除选中的正则规则"""
        selected = self.pattern_list.selectedItems()
        if not selected:
            show_warn(self, "未选择", "请先选择要删除的正则规则！")
            return
        
        if not show_confirm(self, "删除确认", f"确定要删除选中的{len(selected)}个正则规则吗？"):
            return
        
        # 删除选中项
        for item in selected:
            self.pattern_list.takeItem(self.pattern_list.row(item))
        
        show_info(self, "删除成功", "正则规则删除成功，点击【保存配置】使修改生效！")

    # -------------------------- 正则测试（新增核心功能） --------------------------
    def test_current_regex(self):
        """测试当前输入的正则表达式-调用core模块"""
        pat = self.pat_input.toPlainText().strip()
        test_text = self.test_input.toPlainText().strip()
        
        # 非空验证
        if not pat or not test_text:
            show_warn(self, "参数缺失", "请输入正则表达式和测试文本！")
            return
        
        # 测试正则（调用core模块）
        matches = test_regex(pat, test_text)
        if matches:
            result_text = "\n".join([f"{i+1}. {match}" for i, match in enumerate(matches)])
            self.test_result.setPlainText(f"匹配到{len(matches)}条结果：\n{result_text}")
            show_info(self, "测试成功", f"正则匹配成功，共发现{len(matches)}条结果！")
        else:
            self.test_result.setPlainText("未匹配到任何内容")
            show_warn(self, "测试结果", "正则未匹配到任何内容，请检查正则/测试文本！")

    # -------------------------- 配置保存 --------------------------
    def save_config(self):
        """保存正则规则到配置文件"""
        # 收集列表中的正则规则
        patterns = {}
        for i in range(self.pattern_list.count()):
            item = self.pattern_list.item(i)
            try:
                name, pat = item.data(Qt.UserRole)
                if name and pat and validate_regex(pat):
                    patterns[name] = pat
            except Exception as e:
                logger.warning(f"跳过无效正则项：{str(e)}")
                continue
        
        # 保存到配置
        self.config_manager.set_patterns_dict(patterns)
        if self.config_manager.save_config():
            self.load_patterns()
            show_info(self, "保存成功", f"正则配置已保存！共{len(patterns)}个有效正则规则")
        else:
            show_warn(self, "保存失败", "正则配置保存失败，请查看日志排查！")
            