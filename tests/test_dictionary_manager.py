# tests/test_dictionary_manager.py
"""
DictionaryManager 单元测试
使用 pytest + monkeypatch + tmp_path 实现完全隔离的临时配置目录
"""

import json
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from phonemic.utils import paths
from phonemic.utils.dictionary_manager import DictionaryManager, DictionaryEntry


# ----------------------------------------------------------------------
# 辅助函数：直接写入 dictionary.json 到临时目录
# ----------------------------------------------------------------------
def _write_dictionary_file(tmp_path: Path, entries: list) -> Path:
    """将词条列表写入临时目录下的 PhoneMic/config/dictionary.json"""
    config_dir = tmp_path / "PhoneMic/config"
    config_dir.mkdir(parents=True, exist_ok=True)
    file_path = config_dir / "dictionary.json"
    file_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    return file_path


def _write_empty(tmp_path: Path) -> Path:
    return _write_dictionary_file(tmp_path, [])


def _write_two_entries(tmp_path: Path) -> Path:
    data = [
        {
            "id": "e1",
            "name": "JSON 被听错",
            "matchType": "literal",
            "pattern": "杰森",
            "replacement": "JSON",
            "enabled": True,
        },
        {
            "id": "e2",
            "name": "删掉口头叹词",
            "matchType": "regex",
            "pattern": "[嗯呃]+",
            "replacement": "",
            "enabled": False,
        },
    ]
    return _write_dictionary_file(tmp_path, data)


def _write_malformed_json(tmp_path: Path) -> Path:
    config_dir = tmp_path / "PhoneMic/config"
    config_dir.mkdir(parents=True, exist_ok=True)
    file_path = config_dir / "dictionary.json"
    file_path.write_text("{ 这不是合法 JSON ", encoding="utf-8")
    return file_path


@pytest.fixture
def isolated_mgr(tmp_path, monkeypatch):
    """返回 (全新的 DictionaryManager, tmp_path)，配置目录指向临时目录。"""
    def fake_local_app_data():
        return Path(tmp_path)

    monkeypatch.setattr(paths, "_get_local_app_data", fake_local_app_data)

    _write_empty(tmp_path)
    # 重置单例，确保每次 fixture 返回全新实例
    DictionaryManager._instance = None
    mgr = DictionaryManager()
    return mgr, tmp_path


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ----------------------------------------------------------------------
# 加载
# ----------------------------------------------------------------------
class TestLoad:
    def test_missing_file_creates_empty_list(self, isolated_mgr):
        mgr, tmp_path = isolated_mgr
        assert mgr.get_entries() == []
        assert (tmp_path / "PhoneMic/config/dictionary.json").exists()

    def test_loads_two_entries(self, isolated_mgr):
        mgr, tmp_path = isolated_mgr
        _write_two_entries(tmp_path)
        DictionaryManager._instance = None
        mgr = DictionaryManager()

        entries = mgr.get_entries()
        assert len(entries) == 2
        assert entries[0].pattern == "杰森"
        assert entries[0].replacement == "JSON"
        assert entries[1].enabled is False

    def test_unknown_fields_are_ignored(self, isolated_mgr):
        mgr, tmp_path = isolated_mgr
        _write_dictionary_file(tmp_path, [{
            "id": "x", "name": "n", "matchType": "literal",
            "pattern": "a", "replacement": "b", "enabled": True,
            "somethingElse": "未来字段",
        }])
        DictionaryManager._instance = None
        mgr = DictionaryManager()
        assert mgr.get_entries()[0].pattern == "a"

    def test_missing_replacement_defaults_to_empty(self, isolated_mgr):
        """旧格式可能没有 replacement 字段，缺省应为空串而不是崩溃"""
        mgr, tmp_path = isolated_mgr
        _write_dictionary_file(tmp_path, [{
            "id": "x", "name": "n", "matchType": "literal", "pattern": "a",
        }])
        DictionaryManager._instance = None
        mgr = DictionaryManager()
        assert mgr.get_entries()[0].replacement == ""

    def test_malformed_json_backed_up_and_reset(self, isolated_mgr):
        mgr, tmp_path = isolated_mgr
        _write_malformed_json(tmp_path)
        DictionaryManager._instance = None
        mgr = DictionaryManager()

        assert mgr.get_entries() == []
        assert (tmp_path / "PhoneMic/config/dictionary.json.bak").exists()

    def test_duplicate_ids_are_reassigned(self, isolated_mgr):
        """重复 id 会让 GUI 编辑/删除打错目标，加载时必须修好"""
        mgr, tmp_path = isolated_mgr
        _write_dictionary_file(tmp_path, [
            {"id": "dup", "name": "a", "matchType": "literal", "pattern": "1", "replacement": "x", "enabled": True},
            {"id": "dup", "name": "b", "matchType": "literal", "pattern": "2", "replacement": "y", "enabled": True},
        ])
        DictionaryManager._instance = None
        mgr = DictionaryManager()

        ids = [e.id for e in mgr.get_entries()]
        assert len(set(ids)) == 2


# ----------------------------------------------------------------------
# 增删改查
# ----------------------------------------------------------------------
class TestCrud:
    def test_add_entry_persists(self, isolated_mgr):
        mgr, tmp_path = isolated_mgr
        mgr.add_entry(DictionaryEntry.new("测试", "literal", "杰森", "JSON"))

        on_disk = json.loads((tmp_path / "PhoneMic/config/dictionary.json").read_text(encoding="utf-8"))
        assert len(on_disk) == 1
        assert on_disk[0]["pattern"] == "杰森"
        assert on_disk[0]["replacement"] == "JSON"

    def test_add_entry_rejects_wrong_type(self, isolated_mgr):
        mgr, _ = isolated_mgr
        with pytest.raises(TypeError):
            mgr.add_entry({"name": "不是词条对象"})

    def test_update_entry(self, isolated_mgr):
        mgr, _ = isolated_mgr
        entry = DictionaryEntry.new("旧名", "literal", "a", "b")
        mgr.add_entry(entry)

        mgr.update_entry(entry.id, name="新名", replacement="c")

        updated = mgr.get_entries()[0]
        assert updated.name == "新名"
        assert updated.replacement == "c"

    def test_update_entry_ignores_unknown_field(self, isolated_mgr):
        mgr, _ = isolated_mgr
        entry = DictionaryEntry.new("n", "literal", "a", "b")
        mgr.add_entry(entry)

        mgr.update_entry(entry.id, notAField="x")

        assert not hasattr(mgr.get_entries()[0], "notAField")

    def test_update_missing_entry_raises(self, isolated_mgr):
        mgr, _ = isolated_mgr
        with pytest.raises(ValueError):
            mgr.update_entry("不存在", name="x")

    def test_delete_entry(self, isolated_mgr):
        mgr, _ = isolated_mgr
        entry = DictionaryEntry.new("n", "literal", "a", "b")
        mgr.add_entry(entry)

        mgr.delete_entry(entry.id)

        assert mgr.get_entries() == []

    def test_set_enabled(self, isolated_mgr):
        mgr, _ = isolated_mgr
        entry = DictionaryEntry.new("n", "literal", "a", "b")
        mgr.add_entry(entry)

        mgr.set_enabled(entry.id, False)

        assert mgr.get_entries()[0].enabled is False

    def test_set_enabled_missing_entry_raises(self, isolated_mgr):
        mgr, _ = isolated_mgr
        with pytest.raises(ValueError):
            mgr.set_enabled("不存在", True)


# ----------------------------------------------------------------------
# 顺序
# ----------------------------------------------------------------------
class TestOrder:
    def _three(self, mgr):
        for name in ("a", "b", "c"):
            mgr.add_entry(DictionaryEntry.new(name, "literal", name, name.upper()))
        return [e.id for e in mgr.get_entries()]

    def test_move_up(self, isolated_mgr):
        mgr, _ = isolated_mgr
        ids = self._three(mgr)

        mgr.move_up(ids[2])

        assert [e.name for e in mgr.get_entries()] == ["a", "c", "b"]

    def test_move_down(self, isolated_mgr):
        mgr, _ = isolated_mgr
        ids = self._three(mgr)

        mgr.move_down(ids[0])

        assert [e.name for e in mgr.get_entries()] == ["b", "a", "c"]

    def test_move_up_at_top_is_noop(self, isolated_mgr):
        mgr, _ = isolated_mgr
        ids = self._three(mgr)

        mgr.move_up(ids[0])

        assert [e.name for e in mgr.get_entries()] == ["a", "b", "c"]

    def test_move_down_at_bottom_is_noop(self, isolated_mgr):
        mgr, _ = isolated_mgr
        ids = self._three(mgr)

        mgr.move_down(ids[2])

        assert [e.name for e in mgr.get_entries()] == ["a", "b", "c"]


# ----------------------------------------------------------------------
# 信号
# ----------------------------------------------------------------------
class TestSignal:
    def test_entries_changed_emitted_on_write(self, qapp, isolated_mgr):
        mgr, _ = isolated_mgr
        hits = []
        mgr.entries_changed.connect(lambda: hits.append(1))

        mgr.add_entry(DictionaryEntry.new("n", "literal", "a", "b"))

        assert hits == [1]

    def test_get_entries_returns_copy(self, isolated_mgr):
        mgr, _ = isolated_mgr
        mgr.add_entry(DictionaryEntry.new("n", "literal", "a", "b"))

        mgr.get_entries().clear()

        assert len(mgr.get_entries()) == 1
