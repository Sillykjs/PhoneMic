# AGENTS.md

> 给 AI 编码代理与贡献者的工作指南。**先读完本文件再动手。**
> 用户文档见 [README.md](README.md)、[USER_GUIDE.md](USER_GUIDE.md)；设计细节见 [docs/](docs/)。
> 基线：上游 `main` HEAD `9cecf5e`（2026-10，v0.6.1 之后的 9 个提交）。命令均已在本机实测；与代码冲突时以代码为准。

## 0. 项目是什么

PhoneMic 让**手机浏览器**成为电脑的麦克风 / 键盘 / 鼠标 / 文件通道：手机端页面把语音识别出的文字、按键、鼠标帧、文件通过 WebSocket 发给电脑，电脑端自动填入当前光标位置。

电脑端两部分运行在同一个进程里：

| 部分 | 位置 | 技术 |
|---|---|---|
| 电脑桌面端 | `phonemic/gui/` + `phonemic/PhoneMic.py` | PySide6 (Qt 6.11) 主窗口、悬浮窗、托盘、对话框 |
| 电脑后端 | `phonemic/server/` + `phonemic/tunnel/` | Starlette + uvicorn（后台线程），WebSocket + 端到端加密 |
| 手机网页端 | `phonemic/resources/mobile.html`（约 5100 行单文件） | 原生 JS + libsodium.js + msgpack；由后端页面直接下发 |

- **平台：Windows 10/11 x64**。运行时深度依赖 Win32（pywin32、pyautogui、winreg、SendInput、Qt 剪贴板）。
- Python `>=3.13,<3.14`；依赖由 **uv** 管理（`pyproject.toml` + `uv.lock`），不要用 pip。
- 许可证 Apache-2.0，第三方 LGPL 声明见 `NOTICE.txt` / `NOTICE.LGPL.txt`。

## 1. 环境：WSL 里写代码，Windows 里跑代码 ⚠️

本仓库的开发环境是 **WSL2 + Windows 双环境**：编辑、git、读文件在 WSL；**运行、测试、构建必须用 Windows 的 Python**。

### 三条红线

1. **不要用 WSL 的 `python` / `pytest` 跑这个项目**（缺 pywin32 / Qt / Win32 依赖）。
2. **不要用 WSL 的 `uv` 操作 `.venv`**——`.venv` 是 uv 创建的 **Windows venv**（`Scripts/` 布局，本机基于 `D:\Anaconda` 的 Python 3.13.5，被 `.gitignore` 忽略、约 826 MB）。WSL 版 uv 会按 `bin/` 布局重建，毁掉现有环境。
3. **Windows Python 不认 `/mnt/d/...` 形式的参数**。给它传仓库相对路径（`tests/...`）或 `D:/...`；它的 cwd 会显示为 `D:\PhoneMic-dev`。

依赖变更（升级/新增包）：在 Windows 终端 `uv add` / `uv sync`，或用 Windows 侧 `uv.exe` 全路径调用；提交 `uv.lock`。**不要手工 pip install，也不要改 `.venv` 里的文件。**

> 注意 README 里给最终用户的 `uv sync --no-dev` 会**删除** pytest / nuitka 等 dev 依赖。开发环境用不带 `--no-dev` 的 `uv sync`。

### 常用命令

在仓库根目录（WSL bash）执行，VS Code 终端 / `bash -c` 均可：

| 目的 | 命令 |
|---|---|
| 看解释器是否可用 | `.venv/Scripts/python.exe --version` |
| 同步依赖（Windows 终端） | `uv sync` |
| 运行程序（Windows 终端/桌面） | `uv run app` |
| 运行程序（无控制台，推荐日常） | `.venv\Scripts\pythonw.exe launch.pyw` |
| 从 WSL 启动（窗口仍开在 Windows 桌面） | `.venv/Scripts/python.exe -m phonemic.PhoneMic` |
| 静默启动 / 指定选网策略 | 追加 `--silent` 或 `--select-mode auto\|last\|ask` |
| 生成桌面快捷方式（Windows） | `powershell -ExecutionPolicy Bypass -File .\make_windows_lnk.ps1` |
| 跑全部测试 | `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` |
| 跑单个文件 | `.venv/Scripts/python.exe -m pytest tests/test_text_corrector.py -q -p no:cacheprovider` |
| 只收集用例（快） | `.venv/Scripts/python.exe -m pytest --collect-only -q -p no:cacheprovider` |
| 覆盖率 | 追加 `--cov=phonemic --cov-report=term-missing` |
| 打包 | `.venv/Scripts/python.exe build_nuitka.py --mode standalone [--action compile\|package] [--vendor]` |

说明：

- `launch.pyw` 在导入 PySide6 **之前**显式加载 `System32\icuuc.dll`，规避 Anaconda 的 ICU 73 缺 `UCNV_TO_CALLBACK_SUBSTITUTE` 导出导致的「无法定位程序输入点」弹窗。**任何新启动入口都要保持这个顺序**（或复制该做法），否则打包/双击场景会踩坑。
- 程序数据在 `%LOCALAPPDATA%\PhoneMic\`：`config\{settings,commands,dictionary}.json`、`bin\cloudflared.exe`、`exec_workdir\`；启动失败日志在 `%LOCALAPPDATA%\PhoneMic\launch_error.log`。**不要把这些写进仓库。**
- 日志：设 `PHONEMIC_LOG=debug`（或 `trace`）可打开 `phonemic.*` 的调试日志；默认 `info`。
- 源码运行时 Cloudflare 模式需要系统 PATH 里有 `cloudflared`，缺失会自动回退局域网模式。

## 2. 测试

- 规模：**40 个测试文件、1080 条用例**；全量单次约 **2 分 45 秒**（单进程、无 xdist）。改动后跑相关子集，收尾跑全量。
- 当前基线：**1079 passed / 1 failed**。唯一稳定失败是 `tests/test_command_processor.py::test_execute_command_with_cwd_custom_cwd`：它断言 `D:\temp`，而 `Path.resolve()` 在存在 `D:\Temp` 目录的机器上返回 `D:\Temp`。这是**环境相关**的既有失败，不要为它改生产代码，也不要用它判断自己的改动。机器繁忙时 `tests/test_transfer.py::test_full_file_transfer_roundtrip`（依赖 0.05 秒 sleep）可能偶发失败，单跑通过即视为负载问题。
- Qt 测试一律跑 **offscreen**：`tests/conftest.py` 在导入 Qt 前 `setdefault("QT_QPA_PLATFORM", "offscreen")`。**不要改成 `windows`**（会真的弹窗）。
- 端口：测试用 `conftest.get_test_port()`，从 **20000** 起逐个 bind 探测；应用本身从 **12000** 起找空闲端口。禁止硬编码固定端口（Windows 动态端口池是 1024–14999，全量跑会撞 `WinError 10048`）。
- 协议/加密测试用 `conftest.PhoneSimulator`（PyNaCl 模拟手机端握手），不要自己糊一套。
- `test_mobile.py`、`test_js_crypto.py`、`test_integration.py` 依赖 Playwright（Windows 侧浏览器已安装），合计约 80 秒，最慢；`test_mobile.py` 单独约 53 秒。
- `tests/my_test_hud.py`、`my_test_dashboard.py`、`my_test_ip_selector.py` 是**手动 GUI 探针**，不带 `test_` 前缀、不被 pytest 收集，别删。
- 测试依赖 Windows（`winreg`/`pyautogui`/Qt）；无 CI、无 pytest 配置节、无 xdist/超时插件。跑全量时给 600 秒超时，且不要在机器繁忙时用单次全量结果下结论（端口压力会导致「单跑过、全量挂」）。

## 3. 代码地图

| 路径 | 职责 |
|---|---|
| `phonemic/PhoneMic.py` | 组合根：QApplication、选 IP/端口、起服务、SecureChannel、事件分发（`on_backend_event`）、退出清理 |
| `phonemic/bridge_interface.py` / `bridge_qt.py` / `bridge_queue.py` | `EventBridge` 抽象；默认 Qt 信号桥（跨线程自动排队），multiprocessing 队列桥为备用（当前 `use_queue=False`） |
| `phonemic/server/api.py` | Starlette 应用：HTTP 路由 + `secret_path` 前缀、WS 握手/鉴权/消息循环、TOFU 审批队列、传输队列接线、应用层保活、uvicorn 线程启停（约 1600 行，改动最需谨慎） |
| `phonemic/server/transfer.py` | `file`/`photo` 分块接收队列（字节上限 + 退避），单 worker 落盘/解包，ack/背压 |
| `phonemic/tunnel/{base,cloudflare,manager,mode}.py` | 隧道提供者抽象、cloudflared 生命周期与 URL 解析、模式编排/回退、`TunnelMode` 与 `effective_auth_method` |
| `phonemic/tunnel/keepalive.py` | 周期性 HTTP 探测公网入口是否失效（带 nonce 回显校验），状态翻转通知界面 |
| `phonemic/tunnel/frame.py` | 唯一的 MessagePack 编解码层（`use_bin_type=True`、`raw=False`，只接受 map） |
| `phonemic/tunnel/e2ee.py` | `SecureChannel`（PC 长期密钥、secret_path、自动生成二维码 URL）与每连接 `SecureSession` 状态机（TOFU / sealed / challenge / proof、wrap/unwrap） |
| `phonemic/tunnel/crypto/*` | `KeyExchange`（X25519 SealedBox → ECDH → BLAKE2b）、`CryptoProvider` 抽象、XChaCha20 / XSalsa20（seq 在 AAD / 帧前缀）、错误类型 |
| `phonemic/gui/dashboard.py` | 主窗口：二维码/地址、模式与认证/上屏菜单、TOFU 审批面板、连接状态、隧道状态、打开各对话框 |
| `phonemic/gui/hud.py` | 无焦点置顶文字预览悬浮窗（超时/字号/ESC 关闭可热改） |
| `phonemic/gui/keyboard.py` | 三种上屏方式（剪贴板粘贴 / 模拟键盘 / 模拟键盘实时）、`flash_insert`、`preview_text`、`discard_preview`、`send_keys` |
| `phonemic/gui/text_input.py` | Win32 SendInput 批量注入 Unicode/VK（含部分注入失败处理） |
| `phonemic/gui/direct_input.py` | 「实时输入」会话状态机（IDLE/TYPING/ABANDONED）+ 焦点锚点 + 公共前缀 diff；**模块级单例** |
| `phonemic/gui/{mouse,mouse_debug}.py` | 鼠标帧校验与 pyautogui 执行、帧统计钩子 / 开发用曲线窗口 |
| `phonemic/gui/{file,photo,clipboard}.py` | 文件落盘状态机（`~/Downloads/PhoneMic`）、图片内存重组、QImage → Qt 剪贴板 |
| `phonemic/gui/{tray,settings_dialog,commands_dialog,dictionary_dialog,ip_selector}.py` | 托盘与通知；设置分组对话框；命令 CRUD；词典 CRUD；首次选网 |
| `phonemic/utils/command_processor.py` | `CommandInterceptor`：匹配（完全/前缀/正则）与执行（按键序列 / 启动程序） |
| `phonemic/utils/{commands_manager,dictionary_manager}.py` | JSON 持久化单例 + `commands_changed` / `entries_changed` 信号 |
| `phonemic/utils/text_corrector.py` | 启用词条缓存 + 字面量/整句/正则替换（不区分大小写、按顺序链式） |
| `phonemic/utils/input_parser.py` | 「按键段 + 引号文本段」解析、Windows 友好命令行分词、占位符替换 |
| `phonemic/utils/i18n.py` | 点分 key 翻译单例；zh 变体 → zh_CN → en_US 回退；`get_section("mobile")` 供手机端 |
| `phonemic/utils/{paths,settings_manager,network,startup,system_lang,signals}.py` | 路径与 build_info、配置单例、网卡枚举、开机自启、系统语言、全局信号 |
| `phonemic/resources/` | `mobile.html`、`sodium.js`、`crypto_providers.js`、`msgpack.min.js`、4 份 locale、图标 |
| `docs/` | 设计与协议文档（见 §10） |
| `tests/` | pytest（含 Playwright 手机页测试） |

**启动顺序**（`PhoneMic.py`）：QApplication → `SettingsManager`/`I18n` → 按 `network_selection_mode` 选网卡 → 12000 起找端口 → 后台线程起 Starlette → 建 `SecureChannel` → 轮询 `/{secret}/` 就绪 → Dashboard/HUD/Tray → `TunnelManager` → 连接事件桥 → `app.exec()`。

**线程模型（最重要的一条边界）**：

- 后端运行在自己的线程 + asyncio 事件循环；**所有 Qt 控件、剪贴板、pyautogui 注入都在 Qt 主线程**。
- 后端 → 界面：只能 `bridge.emit(event, payload)`（Qt 信号自动排队到主线程）。
- 界面 → 后端：`send_to_phone()`、`request_client_rescan()`、`resolve_approval()`（内部 `run_coroutine_threadsafe`）。
- 传输 worker / asyncio 回调里**不要**碰 Qt；图片剪贴板必须经 bridge 回主线程（现有实现可参考 `photo` 事件链路）。

## 4. 数据流（以文字上屏为例）

```
手机页面输入/语音
  → WSClient.sendFrame({type:'send', text})                     mobile.html
  → SecureClient.encrypt: msgpack.encode → Provider.encrypt      （seq 在加密层，无外层信封）
  → ws.send(binary)
        │  ws:// 局域网  或  wss:// Cloudflare 隧道
        ▼
uvicorn/Starlette（后台线程）
  → _normalize_path(secret 前缀) → /ws
  → _handle_auth: auth → [TOFU: sealed+人工审批] → auth_challenge → auth_proof
  → _serve_messages: session.unwrap → frame_decode → _handle_client_message
  → bridge.emit('send', text)        （Qt 信号跨线程）
        ▼
Qt 主线程 on_backend_event
  → TextCorrector.correct(text)           词典纠正（只纠正 send，不碰 preview）
  → CommandInterceptor.process_send_text  先撤销 preview 字面文字，再执行命令
  → 未命中 → flash_insert(text)           粘贴（pyperclip + Ctrl+V）或 SendInput 逐字输入
  → hud.on_preview_text("")               清空悬浮窗
```

**协议分层**：WS 二进制帧 = AEAD(msgpack(map))。`type` 字段本身也在密文内（认证阶段除外）；所有二进制字段用 msgpack `bin`，**不做 base64**。协议全文见 `docs/wire-protocol.md`，加密细节见 `docs/crypto-design.md`。

## 5. 不能破坏的不变量

改动前先读 `docs/e2ee-always-on-design.md`、`docs/crypto-design.md`、`docs/wire-protocol.md` 对应章节。

1. **加密永远开启，没有明文/关闭分支**。`SecureSession.is_encrypted`/`needs_auth` 恒为真；没有 `SecureChannel` 时 `/ws` 直接拒绝。不要为了调试加明文模式。所有业务消息统一走加密帧，只有握手阶段的 `auth` / `sealed` 是明文信封 + SealedBox 密文。
2. **握手顺序固定**。URL fragment / TOFU 重连：`auth`(SealedBox) → `auth_challenge`(Provider 加密) → `auth_proof`。TOFU 首次：`auth`(明文 pk) → `sealed`（PC 指派 4 位识别码，SealedBox）→ **人工审批** → `auth_challenge`(SealedBox) → `auth_proof`。`sealed` 先于审批，用户核对之前手机上必须已有本连接专属识别码。握手帧必须是 binary（text 帧按旧客户端拒绝）。
3. **seq 是每连接、每方向、从 0 严格 +1**，完全由 Provider 在加密层承载，不进 msgpack。手机端每次握手前 `provider.reset()`。握手会合法消耗 seq 0，别「修正」两端的不对称；握手中间插入额外的 Provider 帧会让两端失步。
4. **TOFU 审批是每连接一个实例**，由 `ApprovalRegistry` 统一排队/结算：界面只显示队首快照，按 `request id` 结算；批准会作废其余待审批；同 IP 新连接取代旧请求。审批超时 30 秒，单次鉴权等待 10 秒（审批通过后重新计时）。**未经鉴权的连接不能顶掉当前活动连接**。
5. **`secret_path` 前缀贯穿一切**：HTTP 路径、二维码 URL、`wait_for_server`、保活探测都要带 `/{secret}/`；新增静态资源必须加入 `_PUBLIC_PATHS` 并加分发分支，否则手机端 404。改认证方式/隧道模式必须重建 `SecureChannel` 并 `request_client_rescan()`（二维码/密钥已变）。
6. **保活是应用层的**：原生 WS ping 已关闭（大文件上传会误杀），45 秒无消息发 `ping`、60 秒无 `pong` 以 1011 关闭。阈值必须低于 Cloudflare 约 100 秒空闲回收。
7. **单帧上限 16 MB**（`WS_MAX_FRAME_SIZE`），通过 `config` 下发；超限关闭整条连接（1009）。手机端要容忍字段缺失/非法。
8. **上屏模式的状态机**：`direct_input` 是模块级单例，`disconnect` 和「切到实时输入」时必须 `reset()`；停在 ABANDONED 会让下一轮静默退化成「预览 + 悬浮窗」。命中命令前必须 `discard_preview()`。
9. **词典先于命令匹配**（先纠正再匹配命令）；**只纠正 `send`，不纠正 `preview`**（实时输入模式下 preview 会真的打字）。
10. **pyautogui 调用**保持 `_pause=False`（连发/长按）且全局 `FAILSAFE=False`（远程鼠标可能停在 (0,0)）。
11. **配置写入只发生在 `%LOCALAPPDATA%`**；`SettingsManager.set()` 会同步重写整个 JSON。新增键要进默认值、类型校验，重命名要写迁移。

## 6. 常见改动怎么做

**(a) 新增手机→PC 消息类型**

1. `mobile.html`：用 `wsClient.sendFrame({type, ...})` 发送；下行监听加在 `wsClient.on(...)` 的分发处。
2. `phonemic/server/api.py::_handle_client_message`：加分支——只通知界面用 `bridge.emit(type, payload)`；需要回包用 `_send_frame`。未知类型会回 `error/malformed`。
3. `PhoneMic.py::on_backend_event`：加事件分支，**GUI 操作只能在这里做**。
4. 补 `docs/wire-protocol.md` §6/§7 的 type 表与字段定义。
5. 测试：协议层用 `conftest.PhoneSimulator`（参考 `test_dispatcher.py` / `test_ws_keepalive.py`）；界面层可加 `test_mobile.py` 的 Playwright 用例。

**(b) 新增设置项**

1. `utils/settings_manager.py`：默认值 + 类型校验（改键名要写迁移）。
2. 消费方用 `connect_changed(key, cb)` 热生效（参考 `hud.py`、`api.py` 的 `_on_max_records_changed`）。
3. UI：`gui/settings_dialog.py` 分组；若是顶层开关，再改 `dashboard.py` 菜单/勾选同步和/或 `tray.py`。
4. 4 份 locale 的 `settings.*` 文案 + `USER_GUIDE.md`。

**(c) 新增电脑端对话框**

照 `commands_dialog.py` 克隆（QDialog + manager 单例 + `I18n.tr`），从 `dashboard.py` 菜单和 `tray.py` 菜单打开；文案进 4 份 locale；加 `tests/test_*_dialog.py`。

**(d) 新增手机端面板/按钮**

面板目前是 `mobile.html` 里硬编码的（`docs/panel-plugin-design.md` 的声明式插件**只是设计，尚未实现**——不要照它找 `api/panels.json`）。控制类面板优先复用现有 `key` / `mouse` 帧，这样服务端无需改动。

**(e) 新增语音命令动作 / 词典匹配类型**

- 命令：`utils/commands_manager.py` 的 `actionType` → `utils/command_processor.py::execute_command` 新分支 → `gui/commands_dialog.py` 下拉项 → locale `commands.*` → `tests/test_command_processor.py` + `USER_GUIDE.md`。
- 词典：`utils/dictionary_manager.py` 的 `matchType` → `utils/text_corrector.py::apply_entries` 分支 → `gui/dictionary_dialog.py` → locale `dictionary.match_*` → `tests/test_text_corrector.py` + `docs/text-dictionary-design.md`。

**(f) 改 UI 文案 / i18n**

- PC 端：`I18n.tr("点分.key")`，文案写进 `phonemic/resources/locales/{en_US,zh_CN,zh_HK,zh_TW}.json`。缺 key 时返回 key 本身，不会崩但会露英文点分串。
- 手机端：同一 JSON 的 `mobile` 段（约 75 个扁平 key），由 `/api/lang.json` 下发；页面每次请求重读，**手机刷新即生效**。手机端请求要用相对 URL 以兼容 secret 前缀。
- 手机端页面/脚本有 no-store 头，改完刷新即可，不需要重启服务。

## 7. 代码与协作约定

- **注释与 docstring 用中文，重点写「为什么」**：非显然的决策、时序、跨线程/加密约束必须解释原因（现有代码普遍如此，参考 `api.py::_handle_auth`、`conftest.py` 顶部说明）。不要写逐行复述代码的废话注释。
- 模块顶部用一段 docstring 说明职责与关键约束；类/函数 docstring 可带 Args/Returns。
- 类型标注跟现有风格：简单可选值用 `Optional[...]` / `Literal`，新代码可用 `str | None`；不要引入 mypy/ruff 配置。
- **格式：没有 black/ruff/flake8 配置，isort 也未对齐（全仓未通过 `isort --check`）**。不要顺手做全量格式化/导入排序；保持局部最小 diff。README 的「PEP8 + 测试」是约定不是 CI。
- **行尾是 CRLF**（Windows checkout，无 `.gitattributes`）。避免全文件重写导致整篇 diff。
- 日志用 `logging.getLogger(__name__)`，异常不要静默吞掉（除了明确的清理路径）。
- 测试风格：按行为分 `class TestXxx`，docstring 用中文描述断言意图；网络/端口相关用 `conftest` 的辅助函数；文件系统写操作一律 `tmp_path` 或 monkeypatch `get_config_dir`。
- **提交信息：中文 Conventional Commits**，如 `feat: 新增词典纠正，上屏前替换语音识别错字`、`fix(审批): ...`、`docs(release-notes): ...`、`chore: bump version to x.y.z`；一个逻辑一个提交。
- **分支/PR**：`main` 为发布线，功能走 `feature/<kebab>` 分支，经 PR 合并（仓库历史是 GitHub merge commit）。`origin` 是上游 `franj/PhoneMic`；个人 fork 是 `fork` remote。不要直接推 `main`。
- 不要提交：`.venv/`、`build/`、`dist/`、`.pytest_cache/`、`%LOCALAPPDATA%` 下的任何东西。`AGENTS.md` 本身应入库。

## 8. 构建与发布

```bash
# 只编译 standalone（build/phonemic_nuitka/PhoneMic.dist/）
.venv/Scripts/python.exe build_nuitka.py --mode standalone --action compile
# 编译 + NSIS 打包（需要 Windows PATH 里有 makensis）
.venv/Scripts/python.exe build_nuitka.py --mode standalone
# 内嵌 cloudflared 的安装包（下载 + SHA256 校验）
.venv/Scripts/python.exe build_nuitka.py --mode standalone --vendor
# 单文件
.venv/Scripts/python.exe build_nuitka.py --mode onefile
```

- 版本唯一来源是 `pyproject.toml` 的 `version`；构建脚本用 stdlib `tomllib` 读取，并生成 `build_info.json {version,commit,date}`。发布时同步改：`pyproject.toml`、`uv.lock`、`docs/release-notes-vX.Y.Z.md`、如涉及则 `build_nuitka.py` 里的 cloudflared pin，然后打 lightweight tag `vX.Y.Z`。
- NSIS 脚本 `makesetup.nsi` 按用户安装（无需管理员），输出 `dist/PhoneMic_Setup_<suffix>.exe`。
- **本机未安装 NSIS（`makensis` 不在 PATH），打包步骤无法在此验证**；Nuitka 4.1.3 已安装，编译需要 Windows C 工具链。

## 9. 排障速查

| 现象 | 原因 / 处理 |
|---|---|
| 双击启动弹「无法定位程序输入点 UCNV_TO_CALLBACK_SUBSTITUTE」 | Qt 绑到了 Anaconda 的 ICU 73；用 `launch.pyw` 启动（先钉 System32 icuuc.dll），或检查快捷方式是否指向它 |
| 手机页面连不上 / 一直重连 | 看后端日志与本机 firewall；确认扫码地址含 secret 路径；核对认证方式（TOFU 需在电脑上点「允许」） |
| 手机端 `non-binary frame (stale client?)` | 手机还开着旧版页面；刷新页面（后端对页面/脚本发 no-store） |
| 连接被关闭 | 4001=握手/算法拒绝，4032=审批被拒/超时/被取代，1011=应用层保活超时，1009=帧超限；对照 `docs/wire-protocol.md` 关闭码 |
| Cloudflare 模式没反应 | 未装 cloudflared 或启动失败会自动回退 LAN；国内网络可能不稳定，优先 LAN |
| 多网卡选错地址 | 菜单「网络 → 切换网络地址」，或用 `--select-mode ask` 启动 |
| 测试单独过、全量挂 | 端口压力（Windows 动态端口池），重跑或减少并发；不要改成固定端口 |
| Qt 测试报窗口/托盘异常 | 确认没有覆盖 `QT_QPA_PLATFORM=offscreen`；无头环境必须 offscreen |
| 改完文案手机没变 | 手机页面刷新（`/api/lang.json` 每次重读）；PC 端文字改 locale JSON 后需重载或重启 |

## 10. 文档地图

| 文档 | 内容 | 状态 |
|---|---|---|
| `docs/wire-protocol.md` | v1 协议：msgpack、type 表、握手、seq、心跳、分块传输、关闭码 | 与实现同步，优先读 |
| `docs/crypto-design.md` | 加密分层、KeyExchange 与 Provider、seq/防重放、TOFU 密钥流 | 与实现同步 |
| `docs/e2ee-always-on-design.md` | 加密与认证解耦、三种模式、TOFU 首次五步、PC 指派识别码 | 与实现同步 |
| `docs/text-dictionary-design.md` | 词典纠正：只纠正 send、先纠正再命令、匹配类型 | 已实现 |
| `docs/mouse-joystick-design.md` | 触控板/摇杆速度模型、帧格式、节流 | 已实现 |
| `docs/mobile_i18n.md` | 手机端 `/api/lang.json` 国际化 | 已实现 |
| `docs/direct-input-mode-research.md` | 实时输入模式调研、状态机、diff、已知限制 | 已实现（部分历史内容） |
| `docs/panel-plugin-design.md` | 手机端声明式面板插件契约 | **仅设计，未实现** |
| `docs/feature-plans.md` | 历史功能/界面规划 | 部分已实现，别当规范 |
| `docs/release-notes-v*.md` | 版本发布说明（中文、面向用户） | 每版新增 |

## 11. 基线快照（2026-10，写本文件时）

- 上游 `main` HEAD `9cecf5e`；本地开发分支 `personal/local-tweaks` 在它之上叠了几个本地提交：手机端短按气泡直发、`launch.pyw` ICU 启动修复、本基线的更新。**这条分支不推上游**（个人的本地改动，PR 已合并的部分不需要再提）。
- `launch.pyw` 与 `make_windows_lnk.ps1`（快捷方式改指 `launch.pyw`、名字 `PhoneMic.lnk`）已入库；README / `USER_GUIDE.md` 尚未同步这两处。
- 手机端确认框已是**自绘** `showConfirm()`（`#dialog-host`，非原生 `confirm`）。微信浏览器会反复改写原生框的「取消」按钮，所以新增交互不要再用原生 `confirm`/`alert`；文字气泡重发干脆不弹框，只给 `showToast` 回执。
- 测试基线：见 §2（1080 collected / 1079 passed / 1 已知环境相关失败）。
