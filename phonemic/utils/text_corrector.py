"""
文本纠正器：按用户词典把语音固定识别错的文字替换掉。

与 CommandInterceptor 同构（缓存启用的词条 + 词典变更时重载）。

**三种匹配类型一律不区分大小写**：英文术语的大小写由手机端语音引擎决定，
同一个词这次给 "console"、下次给 "Console"，把大小写算进匹配只会漏改。
替换结果统一用词条里写的样子，所以 "Console" 也会被改成 "CONSOLE"（如果写成全大写）。

只处理最终上屏文本（send 事件），不碰 preview：识别中的半截词无法可靠匹配，
而直接输入模式的 preview 会真的往目标窗口打字，动它会干扰那套增量状态机。
"""

import logging
import re
from typing import List, Tuple

from phonemic.utils.dictionary_manager import DictionaryEntry, DictionaryManager

logger = logging.getLogger(__name__)

MATCH_LITERAL = "literal"
MATCH_WHOLE = "whole"
MATCH_REGEX = "regex"


def _replace_literal(text: str, pattern: str, replacement: str) -> str:
    """字面量替换，不区分大小写。

    用 re.escape 让 pattern 里的特殊字符（反斜杠、点号等）保持字面含义；
    替换值走函数形式，避免 replacement 里的 \\1 被当成捕获组引用——
    字面量模式就该是字面量，只有 regex 模式才解释捕获组。
    """
    return re.sub(re.escape(pattern), lambda _m: replacement, text, flags=re.IGNORECASE)


def apply_entries(text: str, entries: List[DictionaryEntry]) -> Tuple[str, bool]:
    """按顺序套用词条，返回 (纠正后文本, 是否发生改动)。

    逐条串行套用：前一条的输出是后一条的输入，因此规则可以链式叠加。
    每条规则只套用一次，不存在反复替换导致的死循环。
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    result = text
    changed = False
    for entry in entries:
        if not entry.enabled or not entry.pattern:
            continue
        try:
            if entry.matchType == MATCH_REGEX:
                # 与语音命令的匹配口径一致：不区分大小写
                new_result = re.sub(entry.pattern, entry.replacement, result, flags=re.IGNORECASE)
            elif entry.matchType == MATCH_WHOLE:
                new_result = entry.replacement if result.casefold() == entry.pattern.casefold() else result
            else:
                new_result = _replace_literal(result, entry.pattern, entry.replacement)
        except re.error as e:
            logger.warning("词典正则无效，跳过词条 %s: %s", entry.name, e)
            continue

        if new_result != result:
            changed = True
            result = new_result
    return result, changed


class TextCorrector:
    """词典纠正器，维护词条缓存并提供纠正入口。"""

    def __init__(self):
        self._cached_entries: List[DictionaryEntry] = []
        self._manager = DictionaryManager.instance()
        self._reload_cache()
        self._manager.entries_changed.connect(self._on_entries_changed)

    def _reload_cache(self):
        """从 manager 加载启用的词条，保持存储顺序（顺序即优先级）"""
        all_entries = self._manager.get_entries()
        self._cached_entries = [e for e in all_entries if e.enabled]
        logger.info("[TextCorrector] Cache reloaded, %d entries", len(self._cached_entries))

    def _on_entries_changed(self):
        self._reload_cache()

    def correct(self, text: str) -> Tuple[str, bool]:
        """返回 (纠正后文本, 是否发生改动)。无词条或类型不对时原样返回。"""
        if not isinstance(text, str) or not self._cached_entries:
            return text, False
        return apply_entries(text, self._cached_entries)
