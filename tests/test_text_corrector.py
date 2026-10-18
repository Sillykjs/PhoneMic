# tests/test_text_corrector.py
"""
TextCorrector / apply_entries 单元测试

覆盖三种匹配类型、链式顺序、禁用词条、无效正则与类型守卫。
"""

import logging
import pytest
from pathlib import Path

from phonemic.utils import paths
from phonemic.utils.dictionary_manager import DictionaryManager, DictionaryEntry
from phonemic.utils.text_corrector import TextCorrector, apply_entries


def _entry(name="n", match_type="literal", pattern="a", replacement="b", enabled=True):
    e = DictionaryEntry.new(name, match_type, pattern, replacement)
    e.enabled = enabled
    return e


# ----------------------------------------------------------------------
# apply_entries：三种匹配类型
# ----------------------------------------------------------------------
class TestLiteral:
    def test_replaces_all_occurrences(self):
        result, changed = apply_entries("杰森 和 杰森", [_entry(pattern="杰森", replacement="JSON")])
        assert result == "JSON 和 JSON"
        assert changed is True

    def test_no_match_leaves_text_alone(self):
        result, changed = apply_entries("无关文字", [_entry(pattern="杰森", replacement="JSON")])
        assert result == "无关文字"
        assert changed is False

    def test_matches_any_casing(self):
        """英文术语的大小写由语音引擎决定，不该参与匹配"""
        for probe in ("console", "Console", "CONSOLE", "cOnSoLe"):
            result, changed = apply_entries(probe, [_entry(pattern="console", replacement="COMSOL")])
            assert result == "COMSOL", probe
            assert changed is True

    def test_replacement_casing_is_used_as_written(self):
        result, _ = apply_entries("Console", [_entry(pattern="console", replacement="COMSOL")])
        assert result == "COMSOL"

    def test_chinese_unaffected_by_case_folding(self):
        result, _ = apply_entries("杰森", [_entry(pattern="杰森", replacement="JSON")])
        assert result == "JSON"

    def test_backslash_is_literal(self):
        """字面量模式不该把 \\1 当成捕获组"""
        result, _ = apply_entries(r"路径 C:\1", [_entry(pattern=r"C:\1", replacement=r"D:\1")])
        assert result == r"路径 D:\1"


class TestWhole:
    def test_replaces_when_whole_text_equals(self):
        result, changed = apply_entries("杰森", [_entry(match_type="whole", pattern="杰森", replacement="JSON")])
        assert result == "JSON"
        assert changed is True

    def test_keeps_text_when_only_part_matches(self):
        """整句匹配是保守选项：正文里出现同样的字不该被改"""
        result, changed = apply_entries("把杰森改一下", [_entry(match_type="whole", pattern="杰森", replacement="JSON")])
        assert result == "把杰森改一下"
        assert changed is False

    def test_empty_replacement_deletes_whole_text(self):
        result, changed = apply_entries("嗯", [_entry(match_type="whole", pattern="嗯", replacement="")])
        assert result == ""
        assert changed is True

    def test_whole_is_case_insensitive(self):
        result, changed = apply_entries(
            "Console", [_entry(match_type="whole", pattern="console", replacement="COMSOL")]
        )
        assert result == "COMSOL"
        assert changed is True


class TestRegex:
    def test_strips_filler_words(self):
        result, _ = apply_entries("嗯嗯呃这个", [_entry(match_type="regex", pattern="[嗯呃]+", replacement="")])
        assert result == "这个"

    def test_supports_capture_group(self):
        result, _ = apply_entries("12元", [_entry(match_type="regex", pattern=r"(\d+)元", replacement=r"¥\1")])
        assert result == "¥12"

    def test_is_case_insensitive(self):
        """与语音命令的匹配口径一致"""
        result, _ = apply_entries("json", [_entry(match_type="regex", pattern="JSON", replacement="杰森")])
        assert result == "杰森"

    def test_invalid_regex_is_skipped(self, caplog):
        with caplog.at_level(logging.WARNING):
            result, changed = apply_entries("abc", [_entry(match_type="regex", pattern="([", replacement="x")])
        assert result == "abc"
        assert changed is False
        assert "正则无效" in caplog.text


# ----------------------------------------------------------------------
# apply_entries：通用行为
# ----------------------------------------------------------------------
class TestApplyEntries:
    def test_skip_disabled_entry(self):
        result, changed = apply_entries("a", [_entry(pattern="a", replacement="b", enabled=False)])
        assert result == "a"
        assert changed is False

    def test_skip_empty_pattern(self):
        """空 pattern 会让 str.replace 在字符间插入内容，必须挡住"""
        result, changed = apply_entries("abc", [_entry(pattern="", replacement="X")])
        assert result == "abc"
        assert changed is False

    def test_entries_apply_in_order(self):
        """前一条的输出是后一条的输入，顺序即优先级"""
        entries = [_entry(pattern="A", replacement="B"), _entry(pattern="B", replacement="C")]
        result, _ = apply_entries("A", entries)
        assert result == "C"

    def test_reversed_order_gives_different_result(self):
        entries = [_entry(pattern="B", replacement="C"), _entry(pattern="A", replacement="B")]
        result, _ = apply_entries("A", entries)
        assert result == "B"

    def test_empty_entry_list(self):
        result, changed = apply_entries("原样", [])
        assert result == "原样"
        assert changed is False

    def test_unknown_match_type_falls_back_to_literal(self):
        result, _ = apply_entries("杰森", [_entry(match_type="未来类型", pattern="杰森", replacement="JSON")])
        assert result == "JSON"

    def test_non_string_raises(self):
        with pytest.raises(TypeError):
            apply_entries(None, [_entry()])


# ----------------------------------------------------------------------
# TextCorrector：缓存与热重载
# ----------------------------------------------------------------------
@pytest.fixture
def isolated_dictionary(tmp_path, monkeypatch):
    def fake_local_app_data():
        return Path(tmp_path)

    monkeypatch.setattr(paths, "_get_local_app_data", fake_local_app_data)
    DictionaryManager._instance = None
    mgr = DictionaryManager()
    return mgr


class TestTextCorrector:
    def test_corrects_with_cached_entries(self, isolated_dictionary):
        mgr = isolated_dictionary
        mgr.add_entry(DictionaryEntry.new("n", "literal", "杰森", "JSON"))
        corrector = TextCorrector()

        text, changed = corrector.correct("杰森")

        assert (text, changed) == ("JSON", True)

    def test_cache_refreshes_after_entry_added(self, isolated_dictionary):
        """词典变更后无需重启，纠正立即生效"""
        mgr = isolated_dictionary
        corrector = TextCorrector()
        assert corrector.correct("杰森") == ("杰森", False)

        mgr.add_entry(DictionaryEntry.new("n", "literal", "杰森", "JSON"))

        assert corrector.correct("杰森") == ("JSON", True)

    def test_cache_refreshes_after_entry_disabled(self, isolated_dictionary):
        mgr = isolated_dictionary
        entry = DictionaryEntry.new("n", "literal", "杰森", "JSON")
        mgr.add_entry(entry)
        corrector = TextCorrector()
        assert corrector.correct("杰森")[1] is True

        mgr.set_enabled(entry.id, False)

        assert corrector.correct("杰森") == ("杰森", False)

    def test_disabled_entries_are_not_cached(self, isolated_dictionary):
        mgr = isolated_dictionary
        entry = DictionaryEntry.new("n", "literal", "杰森", "JSON")
        entry.enabled = False
        mgr.add_entry(entry)
        corrector = TextCorrector()

        assert corrector._cached_entries == []
        assert corrector.correct("杰森") == ("杰森", False)

    def test_empty_dictionary_is_a_noop(self, isolated_dictionary):
        corrector = TextCorrector()
        assert corrector.correct("任何文字") == ("任何文字", False)

    def test_non_string_passes_through(self, isolated_dictionary):
        """payload 类型不对时不抛异常，原样返回"""
        mgr = isolated_dictionary
        mgr.add_entry(DictionaryEntry.new("n", "literal", "杰森", "JSON"))
        corrector = TextCorrector()

        assert corrector.correct(None) == (None, False)
