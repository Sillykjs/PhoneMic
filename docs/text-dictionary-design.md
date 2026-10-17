# PhoneMic 词典纠正设计文档

> 状态：**已实现**（分支 `feature/text-dictionary`）
> 关联模块：`phonemic/utils/dictionary_manager.py`、`phonemic/utils/text_corrector.py`、`phonemic/gui/dictionary_dialog.py`
> 关联文档：`commands` 相关实现见 `feature-plans.md`，协议层无改动（见 §7）

---

## 1. 背景与目标

手机输入法的语音识别有固定错法：同一个词每次都听成同样的错字（例如 `JSON` 稳定听成「杰森」）。
用户每次都要手动改一遍，这是纯重复劳动。

目标：**让用户维护一张"错 → 对"的替换表，电脑上屏前自动套用。**

非目标：
- 不做自动学习（不猜用户想改什么）。错法是固定的，那就由用户显式声明。
- 不做手机端改动。纠正发生在电脑侧，协议与页面都不动。

---

## 2. 关键设计决策

### 2.1 只纠正 `send`，不纠正 `preview`

PC 端收到两类文本事件：`preview`（识别过程中的中间结果）与 `send`（识别结束的最终文本）。

只处理 `send` 有两个理由：

1. **半截词匹配不上。** "杰森"在识别途中可能是"杰"、"杰森 "、"杰森森"，拿它去匹配词典只会命中错的东西。
2. **`preview` 在直接输入模式下会真的往目标窗口打字。** `direct_input` 有一套增量状态机（公共前缀比对 + 回退删除），动它的输入就是在动这台机器。少碰一处，少一处难查的 bug。

代价：悬浮窗的实时预览显示的是未纠正的文本，上屏时才是纠正后的。可以接受。

### 2.2 先纠正，再匹配语音命令

顺序不能反。用户如果已经把「确定」写成命令（比方说触发回车），而识别固定听成「却定」，
先纠正再匹配能让那条已有命令继续生效；先匹配则命令永远命不中。

```
send 文本 → 词典纠正 → 命令拦截器 → 命中则执行 / 未命中则上屏
```

命令的 `{all_text}` / `{content}` 占位符看到的是**纠正后**的文本，与用户实际意图一致。

### 2.3 复用 `CommandInterceptor` 的既有形态

`TextCorrector` 与 `CommandInterceptor` 同构：单例 manager + Qt 信号 + 本地缓存 + 变更即重载。
词典改动无需重启，`entries_changed` 一发就重载缓存。

### 2.4 不加全局开关

每条词条自带 `enabled`，要停用整个功能就把表清空或全部取消勾选。
再加一层总开关只会多一个要维护的状态和一处界面。

### 2.5 匹配类型给三种，默认最常用那种

| 类型 | 语义 | 适用场景 |
|---|---|---|
| `literal`（默认） | 按字面量替换**全部**出现处 | 固定错别字，绝大多数情况 |
| `whole` | 仅当**整句**与查找内容完全相等时替换 | 保守：正文里出现同样的字也不想被改 |
| `regex` | 当作正则替换，替换文本可用 `\1` | 删口头叹词、批量改格式 |

**三种类型一律不区分大小写。** 理由是匹配的输入来自手机端语音引擎，拉丁字母的大小写不由用户控制：
同一个 `COMSOL` 这次给 `console`、下次给 `Console`、`CONSOLE` 都可能出现。把大小写算进匹配只会漏改，
而没有任何一种"想要区分大小写"的真实场景能补偿这个损失。输出统一用词条里 `replacement` 写的样子。

实现上：

- `literal` 走 `re.sub(re.escape(pattern), lambda _m: replacement, text, flags=re.IGNORECASE)`。
  用 `re.escape` 保证 `pattern` 里的反斜杠、点号等保持字面含义；
  替换值用**函数形式**，避免 `replacement` 里的 `\1` 被当成捕获组引用——
  只有 `regex` 模式才解释捕获组。
- `whole` 用 `casefold()` 比较整句（比 `lower()` 更正确处理 Unicode 大小写）。
- `regex` 用 `re.IGNORECASE`，与语音命令的匹配口径一致。

### 2.6 词条按列表顺序串行套用

前一条的输出是后一条的输入，顺序即优先级。每条规则只套用一次，不存在反复替换导致的死循环。

---

## 3. 数据模型

配置文件：`%LOCALAPPDATA%\PhoneMic\config\dictionary.json`（与 `commands.json` 同目录）

```json
[
  {
    "id": "a1b2c3d4",
    "name": "JSON 被听错",
    "matchType": "literal",
    "pattern": "杰森",
    "replacement": "JSON",
    "enabled": true
  },
  {
    "id": "e5f6a7b8",
    "name": "删掉口头叹词",
    "matchType": "regex",
    "pattern": "[嗯呃]+",
    "replacement": "",
    "enabled": true
  }
]
```

字段说明：

| 字段 | 说明 |
|---|---|
| `id` | 唯一标识，GUI 用它定位行 |
| `name` | 便于识别的名称 |
| `matchType` | `literal` / `whole` / `regex` |
| `pattern` | 查找内容（错误的文字） |
| `replacement` | 替换为（正确的文字）。**允许为空**，表示删掉 |
| `enabled` | 是否启用 |

健壮性处理（与 `CommandsManager` 一致）：

- 加载失败时先备份为 `dictionary.json.bak` 再重建，用 `os.replace` 而非 `Path.rename`（Windows 上后者在目标已存在时会抛 `FileExistsError`，而这个调用在 `except` 块里，会把构造函数带崩）。
- 重复 `id` 在加载时重新分配，否则 GUI 编辑/删除会打错目标。
- 保存先写 `.tmp` 再原子替换。
- 缺字段的旧文件按默认值补齐，不炸。

---

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `phonemic/utils/dictionary_manager.py` | 新增。单例、JSON 持久化、变更信号 |
| `phonemic/utils/text_corrector.py` | 新增。缓存词条、执行替换 |
| `phonemic/gui/dictionary_dialog.py` | 新增。词条编辑界面 |
| `phonemic/PhoneMic.py` | `on_backend_event` 的 `send` 分支插入纠正（约 3 行） |
| `phonemic/gui/dashboard.py` | 「程序」菜单加「词典配置」入口 |
| `phonemic/gui/tray.py` | 托盘菜单加同一入口 |
| `phonemic/resources/locales/*.json` | 4 个语言包各加 `dashboard.menu_dictionary` 与 37 个 `dictionary.*` 键 |
| `tests/test_dictionary_manager.py` | 新增。持久化、CRUD、顺序、重复 ID、损坏文件 |
| `tests/test_text_corrector.py` | 新增。三种匹配类型、链式顺序、无效正则、类型守卫 |
| `tests/test_dictionary_dialog.py` | 新增。界面构建 + 语言包键一致性 |
| `tests/test_dictionary_hook.py` | 新增。`send` 路径端到端挂钩验证 |

`phonemic/PhoneMic.py` 的实际改动：

```python
elif event_type == "send":
    # 先按用户词典纠正，再交给命令拦截器
    corrected, corrected_changed = text_corrector.correct(payload)
    if corrected_changed:
        logger.info(f"词典纠正: {payload!r} -> {corrected!r}")
    if not command_interceptor.process_send_text(
        corrected, before_execute=discard_preview
    ):
        flash_insert(corrected)
    hud.on_preview_text("")
```

---

## 5. 与语音命令的交互

- **纠正先于匹配**，见 §2.2。
- **冲突风险**：如果词典把某段文字改成另一段，而后者正好是一条命令的匹配模式，那条命令就会被触发。这是顺序设计的必然结果，属于预期行为，写文档而不是加特例。
- **`whole` 类型防误伤**：想把「确定」当命令用、又不想正文里的"确定"被改掉时，用 `whole`。

---

## 6. 测试覆盖

| 层次 | 文件 | 覆盖点 |
|---|---|---|
| 单元 | `test_text_corrector.py` | 三种匹配类型、大小写口径、反斜杠字面量、捕获组、链式顺序、禁用与空 pattern、无效正则、非字符串入参 |
| 单元 | `test_dictionary_manager.py` | 空/正常/缺字段/损坏 JSON、重复 ID 修复、CRUD、上下移动边界、信号、返回副本 |
| 界面 | `test_dictionary_dialog.py` | 表格行数随词典变化、表头不是原始键名、空替换显示占位、正则校验拦截 |
| 一致性 | `test_dictionary_dialog.py` | 源码里引用的每个 `dictionary.*` 键在 4 个语言包里都存在且非空 |
| 集成 | `test_dictionary_hook.py` | 跑一遍 `main()` 后取回 `on_backend_event`，验证 `send` 被纠正、命令收到纠正后文本、命中命令则不上屏、`preview` 与 `key` 不受影响 |

关键手法：`test_dictionary_hook.py` 不断言内部函数，而是从被 mock 的 `QtEventBridge` 上取回真正的回调来触发，
这样挂钩点被改坏（例如有人调换了纠正与命令的先后）时测试会失败。

---

## 7. 未改动的东西

- **`wire-protocol.md`**：协议零改动。纠正全在 PC 端应用层。
- **`mobile.html`**：手机端零改动，不需要刷新页面之外的任何配合。
- **加密层**：零改动。
- **`build_nuitka.py`**：无需新增 hidden import（未引入新依赖）。

---

## 8. 后续可做

按价值排序，都**未实现**：

1. **预览也纠正**（仅非直接输入模式）：悬浮窗提前显示纠正结果。直接输入模式仍需保持原样。
2. **导入 / 导出**：把词典搬去另一台电脑时可以整个文件拷贝，目前手写 JSON 即可。
3. **重复 pattern 提醒**：新增词条时提示已有同 pattern 词条，避免两条规则打同一个位置。
4. **手机端面板**：在手机上查看/切换词条。需要新增协议帧，成本明显高于收益。
5. **词条分组**：按项目或场景切换整套词典。等词条数到几十条再考虑。
6. **单词条「区分大小写」开关**：目前三种类型一律不区分（见 §2.5）。
   真出现"只改小写、放过大写"的需求时，再给词条加一个 `caseSensitive` 字段，
   默认仍是 `false`。现在不加，是因为加一个只有极少数人才用的复选框，
   换来的是界面上多一列要解释的东西。
