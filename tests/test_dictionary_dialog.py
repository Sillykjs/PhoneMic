# tests/test_dictionary_dialog.py
"""
词典界面与语言包测试。

两件事：
1. 对话框能正常构建，表格内容随词典变化（离屏运行，不弹窗）。
2. 代码里用到的每个 dictionary.* 翻译键，在四个语言包里都存在且非空——
   漏加键时 I18n.tr() 会把键名本身显示到界面上，这种返工最不值得。
"""

import json
import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from phonemic.gui.dictionary_dialog import DictionaryDialog, DictionaryEntryEditDialog
from phonemic.utils import paths
from phonemic.utils.dictionary_manager import DictionaryManager, DictionaryEntry
from phonemic.utils.paths import get_res_path

LOCALES = ["en_US", "zh_CN", "zh_HK", "zh_TW"]
REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILES = [
    REPO_ROOT / "phonemic/gui/dictionary_dialog.py",
    REPO_ROOT / "phonemic/gui/dashboard.py",
    REPO_ROOT / "phonemic/gui/tray.py",
]


def _load_locale(code: str) -> dict:
    with open(get_res_path(f"locales/{code}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def isolated_dictionary(tmp_path, monkeypatch):
    def fake_local_app_data():
        return Path(tmp_path)

    monkeypatch.setattr(paths, "_get_local_app_data", fake_local_app_data)
    DictionaryManager._instance = None
    mgr = DictionaryManager()
    return mgr


@pytest.fixture(autouse=True)
def _reset_i18n_language(monkeypatch):
    """固定界面语言，避免跟随开发者本机配置飘走。"""
    from phonemic.utils import i18n as i18n_module
    i18n_module.I18n._instance = None
    yield
    i18n_module.I18n._instance = None


# ----------------------------------------------------------------------
# 语言包一致性
# ----------------------------------------------------------------------
class TestLocaleParity:
    def test_all_locales_share_the_same_dictionary_keys(self):
        key_sets = {code: set(_load_locale(code)["dictionary"].keys()) for code in LOCALES}
        base = key_sets["en_US"]
        for code, keys in key_sets.items():
            assert keys == base, f"{code} 与 en_US 的 dictionary 键不一致：{keys ^ base}"

    def test_no_empty_translation_values(self):
        for code in LOCALES:
            for key, value in _load_locale(code)["dictionary"].items():
                assert isinstance(value, str) and value.strip(), f"{code}.dictionary.{key} 为空"

    def test_every_key_used_in_source_exists(self):
        """扫描源码里的 dictionary.xxx 引用，逐个到语言包里核对"""
        used = set()
        for path in SOURCE_FILES:
            text = path.read_text(encoding="utf-8")
            used |= set(re.findall(r"[\"']dictionary\.([A-Za-z0-9_]+)[\"']", text))
        assert used, "没有扫描到任何 dictionary.* 引用，正则可能已失效"

        for code in LOCALES:
            available = set(_load_locale(code)["dictionary"].keys())
            missing = used - available
            assert not missing, f"{code} 缺少翻译键：{sorted(missing)}"

    def test_menu_dictionary_key_exists_in_all_locales(self):
        for code in LOCALES:
            assert _load_locale(code)["dashboard"].get("menu_dictionary")


# ----------------------------------------------------------------------
# 对话框
# ----------------------------------------------------------------------
class TestDictionaryDialog:
    def test_empty_dictionary_renders_zero_rows(self, qapp, isolated_dictionary):
        dlg = DictionaryDialog()
        assert dlg.table.rowCount() == 0
        dlg.close()

    def test_rows_follow_entries(self, qapp, isolated_dictionary):
        mgr = isolated_dictionary
        mgr.add_entry(DictionaryEntry.new("一", "literal", "杰森", "JSON"))
        mgr.add_entry(DictionaryEntry.new("二", "regex", "[嗯呃]+", ""))

        dlg = DictionaryDialog()

        assert dlg.table.rowCount() == 2
        assert dlg.table.item(0, 1).text() == "一"
        assert dlg.table.item(0, 3).text() == "杰森"
        assert dlg.table.item(0, 4).text() == "JSON"
        dlg.close()

    def test_table_refreshes_when_entry_added(self, qapp, isolated_dictionary):
        dlg = DictionaryDialog()
        assert dlg.table.rowCount() == 0

        isolated_dictionary.add_entry(DictionaryEntry.new("新", "literal", "a", "b"))

        assert dlg.table.rowCount() == 1
        dlg.close()

    def test_row_stores_entry_id_for_editing(self, qapp, isolated_dictionary):
        from PySide6.QtCore import Qt
        entry = DictionaryEntry.new("一", "literal", "a", "b")
        isolated_dictionary.add_entry(entry)

        dlg = DictionaryDialog()

        assert dlg.table.item(0, 1).data(Qt.UserRole) == entry.id
        dlg.close()

    def test_headers_are_resolved_not_raw_keys(self, qapp, isolated_dictionary):
        """漏翻译键时界面会显示 'dictionary.column_name' 这种字样，必须挡住"""
        dlg = DictionaryDialog()
        for col in range(dlg.table.columnCount()):
            text = dlg.table.horizontalHeaderItem(col).text()
            assert text and not text.startswith("dictionary."), f"第 {col} 列表头未翻译：{text}"
        dlg.close()

    def test_empty_replacement_shows_placeholder(self, qapp, isolated_dictionary):
        """空替换是合法用法（整句删掉），显示成提示而不是空白"""
        isolated_dictionary.add_entry(DictionaryEntry.new("删", "whole", "嗯", ""))

        dlg = DictionaryDialog()

        assert dlg.table.item(0, 4).text().strip() != ""
        dlg.close()


class TestEditDialog:
    def test_regex_type_rejects_invalid_pattern(self, qapp, isolated_dictionary, mocker):
        warned = mocker.patch.object(QMessageBox, "warning")
        dlg = DictionaryEntryEditDialog()
        dlg.name_edit.setText("测试")
        dlg.match_type_combo.setCurrentIndex(dlg.match_type_combo.findData("regex"))
        dlg.pattern_edit.setText("([")

        dlg._validate_and_accept()

        assert warned.called
        assert dlg.result() == 0  # 未 accept

    def test_valid_regex_accepted(self, qapp, isolated_dictionary, mocker):
        mocker.patch.object(QMessageBox, "warning")
        dlg = DictionaryEntryEditDialog()
        dlg.name_edit.setText("测试")
        dlg.match_type_combo.setCurrentIndex(dlg.match_type_combo.findData("regex"))
        dlg.pattern_edit.setText("[嗯呃]+")
        dlg.replacement_edit.setText("")

        dlg._validate_and_accept()

        assert dlg.result() == 1  # QDialog.Accepted
        data = dlg.get_entry_data()
        assert data["matchType"] == "regex"
        assert data["replacement"] == ""

    def test_empty_name_rejected(self, qapp, isolated_dictionary, mocker):
        warned = mocker.patch.object(QMessageBox, "warning")
        dlg = DictionaryEntryEditDialog()
        dlg.pattern_edit.setText("a")

        dlg._validate_and_accept()

        assert warned.called

    def test_empty_pattern_rejected(self, qapp, isolated_dictionary, mocker):
        warned = mocker.patch.object(QMessageBox, "warning")
        dlg = DictionaryEntryEditDialog()
        dlg.name_edit.setText("有名字")

        dlg._validate_and_accept()

        assert warned.called

    def test_edit_mode_prefills_existing_values(self, qapp, isolated_dictionary):
        entry = DictionaryEntry.new("名字", "whole", "杰森", "JSON")
        entry.enabled = False

        dlg = DictionaryEntryEditDialog(entry=entry)

        assert dlg.name_edit.text() == "名字"
        assert dlg.match_type_combo.currentData() == "whole"
        assert dlg.pattern_edit.text() == "杰森"
        assert dlg.replacement_edit.text() == "JSON"
        assert dlg.enabled_check.isChecked() is False
