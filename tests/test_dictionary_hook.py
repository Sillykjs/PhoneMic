# tests/test_dictionary_hook.py
"""
词典纠正挂钩点测试。

验证 phonemic/PhoneMic.py 的 on_backend_event「send」分支确实先过词典、再走命令拦截器。

手法与 tests/test_phone_mic_startup.py 一致：mock 掉全部外部依赖后跑一遍 main()，
再从被 mock 的 QtEventBridge 上取回 on_backend_event 回调，直接按事件类型触发。
"""

import json
import sys
from pathlib import Path

import pytest

import phonemic.PhoneMic as pm
from phonemic.utils import paths
from phonemic.utils.dictionary_manager import DictionaryManager
from phonemic.utils.network import IpCandidate


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _install_startup_mocks(mocker):
    """mock 掉启动所需的一切外部依赖，返回关键 mock。"""
    mocker.patch.object(pm, "get_all_lan_ips",
                        return_value=[IpCandidate("192.168.1.100", "eth0", "Ethernet", 0, mac="AA:BB:CC:DD:EE:01")])
    mocker.patch.object(pm, "find_free_port", return_value=8008)
    mocker.patch.object(pm, "start_server")
    mocker.patch.object(pm, "wait_for_server", return_value=True)

    mocker.patch.object(pm, "Dashboard")
    mocker.patch.object(pm, "HudWindow")
    mocker.patch.object(pm, "SystemTray")
    mocker.patch.object(pm, "TunnelManager")

    mock_flash = mocker.patch.object(pm, "flash_insert")
    mocker.patch.object(pm, "preview_text", return_value=False)
    mock_send_keys = mocker.patch.object(pm, "send_keys")

    # 命令拦截器：默认"没命中命令"，这样 flash_insert 才会被调用
    mock_interceptor_cls = mocker.patch.object(pm, "CommandInterceptor")
    mock_interceptor = mock_interceptor_cls.return_value
    mock_interceptor.process_send_text.return_value = False

    mocker.patch("threading.Thread")
    mocker.patch("multiprocessing.Queue")
    mocker.patch.object(pm.QApplication, "exec", return_value=0)

    mock_bridge_cls = mocker.patch.object(pm, "QtEventBridge")

    mock_sm_cls = mocker.patch.object(pm, "SettingsManager")
    mock_sm = mock_sm_cls.instance.return_value
    mock_sm.get.side_effect = lambda key, default=None: {
        "network_selection_mode": "auto",
        "language": "zh_CN",
    }.get(key, default)

    return {
        "flash_insert": mock_flash,
        "send_keys": mock_send_keys,
        "process_send_text": mock_interceptor.process_send_text,
        "bridge": mock_bridge_cls,
    }


def _run_main_and_capture_callback(mocker, tmp_path, entries=None):
    """跑一遍 main()，返回 (on_backend_event 回调, mocks 字典)。"""
    def fake_local_app_data():
        return Path(tmp_path)

    mocker.patch.object(paths, "_get_local_app_data", fake_local_app_data)
    DictionaryManager._instance = None
    mgr = DictionaryManager()
    for entry in entries or []:
        mgr.add_entry(entry)
    # main() 内部会新建 TextCorrector，让它重新读一次词条缓存
    DictionaryManager._instance = None

    mocks = _install_startup_mocks(mocker)

    sys.argv = ["PhoneMic.py"]
    with pytest.raises(SystemExit) as exc:
        pm.main()
    assert exc.value.code == 0

    connect_call = mocks["bridge"].return_value.event_signal.connect.call_args
    assert connect_call is not None, "main() 没有把事件回调接到 bridge 上"
    return connect_call[0][0], mocks


def _make_entry(pattern, replacement, match_type="literal"):
    from phonemic.utils.dictionary_manager import DictionaryEntry
    return DictionaryEntry.new("测试词条", match_type, pattern, replacement)


# ----------------------------------------------------------------------
# 挂钩行为
# ----------------------------------------------------------------------
class TestSendHook:
    def test_send_text_is_corrected_before_insert(self, qapp, mocker, tmp_path):
        callback, mocks = _run_main_and_capture_callback(
            mocker, tmp_path, [_make_entry("杰森", "JSON")]
        )

        callback("send", "杰森")

        mocks["flash_insert"].assert_called_once_with("JSON")

    def test_uncorrected_text_passes_through_when_no_rule_matches(self, qapp, mocker, tmp_path):
        callback, mocks = _run_main_and_capture_callback(
            mocker, tmp_path, [_make_entry("杰森", "JSON")]
        )

        callback("send", "普通文字")

        mocks["flash_insert"].assert_called_once_with("普通文字")

    def test_empty_dictionary_keeps_original_text(self, qapp, mocker, tmp_path):
        callback, mocks = _run_main_and_capture_callback(mocker, tmp_path, [])

        callback("send", "杰森")

        mocks["flash_insert"].assert_called_once_with("杰森")

    def test_command_interceptor_receives_corrected_text(self, qapp, mocker, tmp_path):
        """先纠正再匹配命令：把听错的词写成正确写法，命令依然能命中"""
        callback, mocks = _run_main_and_capture_callback(
            mocker, tmp_path, [_make_entry("却定", "确定")]
        )

        callback("send", "却定")

        assert mocks["process_send_text"].call_args[0][0] == "确定"

    def test_command_hit_suppresses_insert(self, qapp, mocker, tmp_path):
        callback, mocks = _run_main_and_capture_callback(
            mocker, tmp_path, [_make_entry("却定", "确定")]
        )
        mocks["process_send_text"].return_value = True

        callback("send", "却定")

        mocks["flash_insert"].assert_not_called()

    def test_preview_is_not_corrected(self, qapp, mocker, tmp_path):
        """识别中的半截词不可靠，preview 必须原样走原逻辑"""
        callback, mocks = _run_main_and_capture_callback(
            mocker, tmp_path, [_make_entry("杰森", "JSON")]
        )

        callback("preview", "杰森")

        # preview_text 返回 False（非直接输入模式），因此这里应保持调用原样
        mocks["flash_insert"].assert_not_called()

    def test_key_event_is_untouched(self, qapp, mocker, tmp_path):
        callback, mocks = _run_main_and_capture_callback(
            mocker, tmp_path, [_make_entry("ctrl", "XXX")]
        )

        callback("key", "ctrl+z")

        mocks["send_keys"].assert_called_once_with("ctrl+z")
        mocks["flash_insert"].assert_not_called()

    def test_multiple_rules_chain_on_live_path(self, qapp, mocker, tmp_path):
        callback, mocks = _run_main_and_capture_callback(
            mocker, tmp_path,
            [_make_entry("杰森", "JSON"), _make_entry("JSON", "[json]")],
        )

        callback("send", "杰森")

        mocks["flash_insert"].assert_called_once_with("[json]")

    def test_disabled_rule_does_not_apply(self, qapp, mocker, tmp_path):
        entry = _make_entry("杰森", "JSON")
        entry.enabled = False
        callback, mocks = _run_main_and_capture_callback(mocker, tmp_path, [entry])

        callback("send", "杰森")

        mocks["flash_insert"].assert_called_once_with("杰森")


# ----------------------------------------------------------------------
# 配置文件落盘
# ----------------------------------------------------------------------
class TestPersistence:
    def test_dictionary_file_is_created_next_to_commands(self, qapp, mocker, tmp_path):
        _run_main_and_capture_callback(mocker, tmp_path, [_make_entry("a", "b")])

        config_file = Path(tmp_path) / "PhoneMic/config/dictionary.json"
        assert config_file.exists()
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved[0]["pattern"] == "a"
