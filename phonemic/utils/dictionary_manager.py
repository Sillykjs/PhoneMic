"""
词典管理器：维护"语音识别固定错误 → 正确文字"的替换词条。

与 CommandsManager 同构（单例 + Qt 信号 + JSON 原子落盘），
配置文件为用户数据目录下的 dictionary.json。
"""

import json
import os
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Literal, Optional

from PySide6.QtCore import QObject, Signal

from phonemic.utils.paths import get_config_dir


@dataclass
class DictionaryEntry:
    """一条替换规则。

    matchType 的三种取值（都不区分大小写，大小写由手机端语音引擎决定）：
    - literal：把 pattern 按字面量全部替换（最常用，用于固定错别字）
    - whole：仅当整句与 pattern 完全相等时替换（保守，不会误伤正文）
    - regex：把 pattern 当正则，用 replacement 替换（支持 \\1 这类捕获组引用）
    """

    id: str
    name: str
    matchType: Literal["literal", "whole", "regex"]
    pattern: str
    replacement: str
    enabled: bool

    @staticmethod
    def new(name: str, match_type: str, pattern: str, replacement: str) -> "DictionaryEntry":
        return DictionaryEntry(
            id=uuid.uuid4().hex,
            name=name,
            matchType=match_type,  # type: ignore
            pattern=pattern,
            replacement=replacement,
            enabled=True,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "DictionaryEntry":
        # 兼容旧格式缺失字段
        return DictionaryEntry(
            id=data.get("id", uuid.uuid4().hex),
            name=data["name"],
            matchType=data["matchType"],
            pattern=data["pattern"],
            replacement=data.get("replacement", ""),
            enabled=data.get("enabled", True),
        )


class DictionaryManager(QObject):
    entries_changed = Signal()

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def instance(cls) -> "DictionaryManager":
        """获取单例实例（等价于直接调用构造函数）"""
        return cls()

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        super().__init__()
        self._initialized = True
        self._entries: List[DictionaryEntry] = []
        self._load()

    def _get_file_path(self) -> Path:
        return get_config_dir() / "dictionary.json"

    def _load(self):
        file_path = self._get_file_path()
        if not file_path.exists():
            self._entries = []
            self.save()
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("Root element must be a list")
            self._entries = [DictionaryEntry.from_dict(item) for item in data]

            # 重复 ID 修复：GUI 用 id 定位行，重复会让编辑或删除打错目标
            seen = set()
            need_save = False
            for entry in self._entries:
                while entry.id in seen:
                    old_id = entry.id
                    entry.id = uuid.uuid4().hex
                    print(f"[DictionaryManager] 发现重复 ID '{old_id}'，已重新分配为 '{entry.id}'")
                    need_save = True
                seen.add(entry.id)

            if need_save:
                self.save()
        except Exception as e:
            # 与 CommandsManager 一致：损坏文件先备份再重建。
            # 用 os.replace 而非 Path.rename，Windows 上后者在目标已存在时会抛
            # FileExistsError，而这个调用在 except 块里，会直接把构造函数带崩。
            backup = file_path.with_suffix(".json.bak")
            try:
                os.replace(file_path, backup)
                print(f"[DictionaryManager] Failed to load dictionary.json, backup created: {backup}, error: {e}")
            except OSError as be:
                # 备份失败也要能把服务拉起来（杀软扫描期文件可能被短暂锁住）
                print(f"[DictionaryManager] Failed to load dictionary.json and backup failed: {be}, error: {e}")
            self._entries = []
            self.save()

    def save(self):
        try:
            data_to_write = [entry.to_dict() for entry in self._entries]
        except Exception as e:
            print(f"构建词典数据失败: {e}")
            raise

        try:
            json_str = json.dumps(data_to_write, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"词典 JSON 序列化失败: {e}")
            raise

        file_path = self._get_file_path()
        get_config_dir().mkdir(parents=True, exist_ok=True)

        # 先写临时文件再原子替换，避免中途失败留下半个文件
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        temp_path.replace(file_path)

    def _emit_and_save(self):
        self.entries_changed.emit()
        self.save()

    # ---------- Public API ----------
    def get_entries(self) -> List[DictionaryEntry]:
        return self._entries.copy()  # 返回副本防止外部修改

    def add_entry(self, entry: DictionaryEntry) -> None:
        if not isinstance(entry, DictionaryEntry):
            raise TypeError(f"Expected DictionaryEntry, got {type(entry)}")
        self._entries.append(entry)
        self._emit_and_save()

    def update_entry(self, entry_id: str, **updates) -> None:
        for entry in self._entries:
            if entry.id == entry_id:
                allowed = {"name", "matchType", "pattern", "replacement", "enabled"}
                for key, value in updates.items():
                    if key in allowed:
                        setattr(entry, key, value)
                self._emit_and_save()
                return
        raise ValueError(f"Dictionary entry with id {entry_id} not found")

    def delete_entry(self, entry_id: str) -> None:
        self._entries = [e for e in self._entries if e.id != entry_id]
        self._emit_and_save()

    def move_up(self, entry_id: str) -> None:
        idx = self._find_index(entry_id)
        if idx > 0:
            self._entries[idx], self._entries[idx - 1] = self._entries[idx - 1], self._entries[idx]
            self._emit_and_save()

    def move_down(self, entry_id: str) -> None:
        idx = self._find_index(entry_id)
        if idx < len(self._entries) - 1:
            self._entries[idx], self._entries[idx + 1] = self._entries[idx + 1], self._entries[idx]
            self._emit_and_save()

    def set_enabled(self, entry_id: str, enabled: bool) -> None:
        for entry in self._entries:
            if entry.id == entry_id:
                entry.enabled = enabled
                self._emit_and_save()
                return
        raise ValueError(f"Dictionary entry with id {entry_id} not found")

    def _find_index(self, entry_id: str) -> int:
        for i, entry in enumerate(self._entries):
            if entry.id == entry_id:
                return i
        raise ValueError(f"Dictionary entry with id {entry_id} not found")
