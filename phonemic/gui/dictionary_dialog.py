"""
词典配置图形界面
提供替换词条的增删改查、启用/禁用、顺序调整。
所有修改立即通过 DictionaryManager 持久化到 dictionary.json。
"""

import logging
import re
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QComboBox, QLineEdit,
    QCheckBox, QFormLayout, QDialogButtonBox, QWidget, QLabel
)

from phonemic.utils.dictionary_manager import DictionaryManager, DictionaryEntry
from phonemic.utils.i18n import I18n

logger = logging.getLogger(__name__)


class DictionaryEntryEditDialog(QDialog):
    """新增/编辑词条的对话框，带说明文字"""

    def __init__(self, parent=None, entry: Optional[DictionaryEntry] = None):
        super().__init__(parent)
        self.entry = entry
        self.i18n = I18n.instance()
        self.is_new = entry is None

        self.setWindowTitle(self.i18n.tr("dictionary.edit_title_new") if self.is_new
                            else self.i18n.tr("dictionary.edit_title_edit"))
        self.setModal(True)
        self.setMinimumWidth(560)

        self._setup_ui()
        self._load_data()

    def _hint(self, key: str) -> QLabel:
        label = QLabel(self.i18n.tr(key))
        label.setStyleSheet("color: gray; font-size: 11px;")
        label.setWordWrap(True)
        return label

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignRight)

        # 名称
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(self.i18n.tr("dictionary.name_placeholder"))
        form_layout.addRow(self.i18n.tr("dictionary.name") + ":", self.name_edit)
        form_layout.addRow("", self._hint("dictionary.name_help"))

        # 匹配类型
        self.match_type_combo = QComboBox()
        self.match_type_combo.addItem(self.i18n.tr("dictionary.match_literal"), "literal")
        self.match_type_combo.addItem(self.i18n.tr("dictionary.match_whole"), "whole")
        self.match_type_combo.addItem(self.i18n.tr("dictionary.match_regex"), "regex")
        form_layout.addRow(self.i18n.tr("dictionary.match_type") + ":", self.match_type_combo)
        form_layout.addRow("", self._hint("dictionary.match_type_help"))

        # 查找内容
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText(self.i18n.tr("dictionary.pattern_placeholder"))
        form_layout.addRow(self.i18n.tr("dictionary.pattern") + ":", self.pattern_edit)
        form_layout.addRow("", self._hint("dictionary.pattern_help"))

        # 替换为
        self.replacement_edit = QLineEdit()
        self.replacement_edit.setPlaceholderText(self.i18n.tr("dictionary.replacement_placeholder"))
        form_layout.addRow(self.i18n.tr("dictionary.replacement") + ":", self.replacement_edit)
        form_layout.addRow("", self._hint("dictionary.replacement_help"))

        # 启用
        self.enabled_check = QCheckBox(self.i18n.tr("dictionary.enabled"))
        form_layout.addRow("", self.enabled_check)
        form_layout.addRow("", self._hint("dictionary.enabled_help"))

        main_layout.addLayout(form_layout)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _load_data(self):
        if not self.entry:
            self.match_type_combo.setCurrentIndex(0)
            self.enabled_check.setChecked(True)
            return

        self.name_edit.setText(self.entry.name or "")
        idx = self.match_type_combo.findData(self.entry.matchType)
        if idx >= 0:
            self.match_type_combo.setCurrentIndex(idx)
        self.pattern_edit.setText(self.entry.pattern or "")
        self.replacement_edit.setText(self.entry.replacement or "")
        self.enabled_check.setChecked(self.entry.enabled)

    def _validate_and_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, self.i18n.tr("error.title"),
                                self.i18n.tr("dictionary.error_name_empty"))
            self.name_edit.setFocus()
            return

        pattern = self.pattern_edit.text()
        if not pattern.strip():
            QMessageBox.warning(self, self.i18n.tr("error.title"),
                                self.i18n.tr("dictionary.error_pattern_empty"))
            self.pattern_edit.setFocus()
            return

        # 正则类型提前校验，避免保存后静默失效
        if self.match_type_combo.currentData() == "regex":
            try:
                re.compile(pattern)
            except re.error as e:
                QMessageBox.warning(self, self.i18n.tr("error.title"),
                                    self.i18n.tr("dictionary.error_regex_invalid").format(e))
                self.pattern_edit.setFocus()
                return

        self.accept()

    def get_entry_data(self) -> Dict[str, Any]:
        return {
            "name": self.name_edit.text().strip(),
            "matchType": self.match_type_combo.currentData(),
            # 查找内容与替换文本都保留首尾空格：语音识别可能把空格一起带进来
            "pattern": self.pattern_edit.text(),
            "replacement": self.replacement_edit.text(),
            "enabled": self.enabled_check.isChecked(),
        }


class DictionaryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = DictionaryManager.instance()
        self.i18n = I18n.instance()

        self.setWindowTitle(self.i18n.tr("dictionary.title"))
        self.setModal(True)
        self.setMinimumSize(900, 500)

        self._setup_ui()
        self._refresh_table()

        self.manager.entries_changed.connect(self._refresh_table)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            self.i18n.tr("dictionary.column_enabled"),
            self.i18n.tr("dictionary.column_name"),
            self.i18n.tr("dictionary.column_match_type"),
            self.i18n.tr("dictionary.column_pattern"),
            self.i18n.tr("dictionary.column_replacement"),
            self.i18n.tr("dictionary.column_actions"),
        ])

        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(5, 120)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        self.table.cellDoubleClicked.connect(self._edit_entry)
        layout.addWidget(self.table)

        bottom_layout = QHBoxLayout()
        help_label = QLabel(self.i18n.tr("dictionary.footer_hint"))
        help_label.setStyleSheet("color: #666; font-style: italic;")
        bottom_layout.addWidget(help_label)
        bottom_layout.addStretch()

        add_btn = QPushButton(self.i18n.tr("dictionary.add"))
        add_btn.clicked.connect(self._add_entry)
        close_btn = QPushButton(self.i18n.tr("dictionary.close"))
        close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(add_btn)
        bottom_layout.addWidget(close_btn)

        layout.addLayout(bottom_layout)

    def _set_item(self, row, col, text, center=False):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        if center:
            item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, col, item)

    def _refresh_table(self):
        entries = self.manager.get_entries()
        self.table.setRowCount(len(entries))

        for row, entry in enumerate(entries):
            cb = QCheckBox()
            cb.setChecked(entry.enabled)
            # 默认参数捕获当前 id，避免闭包捕获循环变量
            cb.toggled.connect(lambda checked, eid=entry.id: self.manager.set_enabled(eid, checked))
            self.table.setCellWidget(row, 0, cb)

            # 名称列同时存 id，供双击编辑定位
            self._set_item(row, 1, entry.name or "")
            self.table.item(row, 1).setData(Qt.UserRole, entry.id)

            match_type_display = {
                "literal": self.i18n.tr("dictionary.match_literal"),
                "whole": self.i18n.tr("dictionary.match_whole"),
                "regex": self.i18n.tr("dictionary.match_regex"),
            }.get(entry.matchType, entry.matchType)
            self._set_item(row, 2, match_type_display, center=True)

            self._set_item(row, 3, entry.pattern or "")

            # 空替换文本是合法用法（整句删掉），显示成占位提示而不是空白
            replacement = entry.replacement
            self._set_item(row, 4, replacement if replacement else self.i18n.tr("dictionary.empty_replacement"))

            widget = QWidget()
            btn_layout = QHBoxLayout(widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)

            up_btn = QPushButton("▲")
            up_btn.setFixedSize(24, 24)
            up_btn.setToolTip(self.i18n.tr("dictionary.move_up"))
            up_btn.clicked.connect(lambda checked, eid=entry.id: self.manager.move_up(eid))

            down_btn = QPushButton("▼")
            down_btn.setFixedSize(24, 24)
            down_btn.setToolTip(self.i18n.tr("dictionary.move_down"))
            down_btn.clicked.connect(lambda checked, eid=entry.id: self.manager.move_down(eid))

            del_btn = QPushButton("✖")
            del_btn.setFixedSize(24, 24)
            del_btn.setToolTip(self.i18n.tr("dictionary.delete"))
            del_btn.clicked.connect(lambda checked, eid=entry.id: self._delete_entry(eid))

            btn_layout.addWidget(up_btn)
            btn_layout.addWidget(down_btn)
            btn_layout.addWidget(del_btn)
            btn_layout.addStretch()
            self.table.setCellWidget(row, 5, widget)

        self.table.resizeRowsToContents()

    def _delete_entry(self, entry_id: str):
        reply = QMessageBox.question(self, self.i18n.tr("dictionary.confirm_delete_title"),
                                     self.i18n.tr("dictionary.confirm_delete_msg"),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.manager.delete_entry(entry_id)

    def _add_entry(self):
        dlg = DictionaryEntryEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.manager.add_entry(DictionaryEntry.from_dict(dlg.get_entry_data()))

    def _edit_entry(self, row, column):
        item = self.table.item(row, 1)
        if not item:
            return
        entry_id = item.data(Qt.UserRole)
        entry = next((e for e in self.manager.get_entries() if e.id == entry_id), None)
        if not entry:
            return
        dlg = DictionaryEntryEditDialog(self, entry=entry)
        if dlg.exec() == QDialog.Accepted:
            self.manager.update_entry(entry_id, **dlg.get_entry_data())
