# OpenWoven

一个会记住聊过什么、逐步学习你喜欢怎么聊，并能主动找你聊两句的开源 Android 聊天项目。

[English](README.en.md) · [AUL 原理](AUL_DESIGN.md) · [架构](ARCHITECTURE.md) · [角色与冷启动](PERSONA_DESIGN.md) · [记忆设计](MEMORY_DESIGN.md) · [使用与后台](RUNTIME_GUIDE.md) · [发布清单](RELEASE_CHECKLIST.md)

核心想法叫 **AUL（AI User Learning）**：不是训练一个新模型，而是在聊天和反馈中积累可纠正的用户偏好，再把它变成下一轮 LLM 的交流策略。Python Core 可单独复用，Android 是目前的参考客户端。

当前是 **experimental／单用户原型**。数据和调度机制有离线回归；长期效果、真实模型质量和各品牌手机的后台可靠性尚未验证。配置远程接口后，选中的对话和记忆上下文会发送给该服务商；“本地优先”不等于模型也在本地运行。

## 为什么做这个

起点很简单：一个聊天对象如果永远只会在你发问后回一大段话，既不记得之前聊过什么，也不适应你的表达习惯，那换个聊天界面并没有解决多少问题。

此前 ASM（Agent Software Map）的想法是让 Agent 记住如何使用软件。这里把“学软件”换成“学用户的交流偏好”：回复长短、主动程度、能否互相打趣、心情不好时需要怎样的回应。问卷只提供初始线索，后面的明确反馈与纠正继续改变这些判断，不把人定义死。

这是一项可运行、可检查的探索，不是有研究依据的心理测试，也没有“越聊越像真人”或“省 40% token 保留 90% 效果”的实测结论。

## 和普通聊天壳有什么不同

- **学习怎么聊**：10 题起步、50 题可选补充；未回答的不当成事实。具体反馈（例如“太长了”）可以调整后续策略，并追溯到来源。
- **记住聊过什么**：保留原文，按日／周／月整理；需要时按日期和关键词找回摘录，不把全部历史塞进每轮请求。
- **短消息有节奏**：日常中文拆成独立气泡，逐条展示；观察本应用输入框，等用户停下后再回复，不读其他应用键盘。
- **不只等你开口**：可以指定时间发送原文或到时生成话题，也有带频率上限、免打扰和通知门控的低频主动开场。生成的主动开场最多 3 条，不把长文一口气推过来。
- **角色和用户分开记**：角色设定／虚构经历有独立的连续性记录，不混成用户事实；每轮只取需要的部分。
- **机制可检查**：偏好证据、更新审计、原话来源和 token／延迟估算都能查看。系统不修改模型权重。

### AUL 具体存什么

| 层 | 回答的问题 | 不负责什么 |
| --- | --- | --- |
| Persona／角色档案 | 当前扮演怎样的虚构人物，已有设定如何保持连续 | 不能拿虚构经历冒充用户经历 |
| AUL／用户学习层 | 用户偏好、当前状态，以及这些判断来自哪里 | 不是一份不可修改的人格诊断 |
| Memory／聊天记忆 | 之前何时聊过什么，哪里能找到原话 | 摘要不是原始记录的替代品 |
| Policy／本轮策略 | 这轮应该短一点、少追问，还是先认真回答问题 | 不保证模型每次都遵守 |

“回答短点” → 有来源的证据 → AUL 的回复长度下调 → 下一轮提示更简短。
泛泛的赞／踩目前只记录评价，不自动知道用户究竟喜欢哪项风格；实现细节和边界见 [AUL 设计](AUL_DESIGN.md)。

## 无需 API Key 先看闭环

Python 3.11+，Core 无第三方运行时依赖：

```sh
python -m pip install -e .
python -m openwoven --db ":memory:" demo
```

这个演示使用合成对话和确定性 Provider，展示数据与策略变化，不代表真实 LLM 质量。

无 Key 的“三个月后找回某一天原话，并删除后遗忘”演示：

```sh
python examples/calendar_memory_demo.py
```

项目目前包含两条完整链路：

- 对话闭环：消息 → 场景策略 → 记忆检索 → LLM → 分段/延迟展示 → 持久化。
- 学习闭环：原始对话或显式反馈 → Evidence → AUL 聚合 → 下一轮 Interaction Policy 生效。

设计目标不是让每轮请求携带全部历史，而是让数据库保留来源记录，让 prompt 只携带本轮需要的摘要和摘录。实际节省多少 token、是否保持回复质量，尚无真实模型对照评测；审计、回放和删除后重建是已实现的机制。

适合先作为开发者可复用的 Core＋Android 参考客户端发布，而不是宣传成成熟的“真人模拟”产品。无 Key 演示验证机制；角色匹配效果、长期满意度和实际后台可靠性仍需验证。正式签名、FCM、流式输出和加密导出未完成；图片发送已接通代码路径，但未做真实接口或真机验证。

## Android 应用

Android 工程位于 `android/`，使用 Kotlin、Jetpack Compose、WorkManager、DataStore 和 Chaquopy。最低系统版本为 Android 8.0（API 26）。

已实现：

- IM 风格聊天页、消息状态、失败重试、复制、删除、重新生成。
- 日/周/月自动归档和“记忆日历”；支持关键词/日期查找，以及分页查看来源原话。摘要不替代聊天记录。
- 快捷反馈和周期反馈；反馈会转成 Evidence，真实改变 AUL 和后续回复策略。
- 首次10题：5题了解用户、5题建立角色偏好，不再要求先选预设人物。未配接口先保留临时称呼或手填昵称；配置后点击生成，由当前模型提出人物简介与8个昵称，预览确认后才保存。Persona与用户画像分离，角色背景可虚构，不伪造用户事实。
- 完整版50题，两边各25题；前置题可明确答“暂不确定”，补充题可按需填写或撤回。空答案、未知和未确认滑块不冒充用户证据；10项滑杆标明0/1两端含义与当前值，补填用户资料不自动重写已确认的模型人物。
- 简中、繁中、日语、美式英语切换；应用自有界面、说明与通知栏目跟随选择，模型收到默认回复语言。原话及原始调试数据不做伪翻译。
- 数值参数有默认值/作用/调整说明；模型可记住、切换并保存独立的看图能力声明。配置接口且勾选看图后，聊天栏“＋图片”打开系统选图器，预览/移除/发送；只访问所选图片，不请求相册全量权限。原图限20MB，缩至最长边1536并重编码为JPEG（去掉EXIF），发送副本限2MB，一轮最多4图。只上传当前轮图片，不把base64塞进AUL或文本历史；删消息/清空时移除关联本地副本。第三方接口需支持Chat Completions的image_url内容块，手动勾选不是能力验证，图片可能额外计费。
- 连续发送的用户气泡各自保存，合并成一轮理解。输入框文字/拼字未完成时暂停；空框触摸、聚焦或继续输入会重置等待，默认停下20秒后生成（可调10–60秒）。只观察本应用输入状态，不读取其他应用键盘。待回复任务落盘，后台仍由常驻/系统任务尽力调度；未发送草稿门控是进程内状态，不是跨进程键盘监听。
- 生成途中继续输入时暂存回复，停下后复用，避免重复请求；真正发出新内容会取消旧任务并合并重新理解。取消/删除/重试按整轮来源处理；没有尚未发送的草稿正文进入模型。
- 普通设置可调整回复长短（左0简短，右1详细，初始0.30）、等待秒数和聊天时区；留空跟随设备，支持标准时区ID。每次模型请求前加入实际本地时间、偏移和时区，计入文本预算；不改变原始消息时间与记忆归档。模型仍可能误读时间，不是一个通用日历代理。
- DeliveryPlan：按偏好和场景决定是否拆分回复、拆成几段以及段间延迟；延迟始终受上限约束。
- 日常中文按自然句界/转折及中文短句之间的空白稳定拆成独立气泡；关闭自然延迟也不会合回一条。默认提示1–3条简短口语，不强制粤语或刻板表达；英文词组、代码、引用、数字和明确要求的通知/邮件/长文不硬拆，不截断正文。分段计划与回复一起落盘，重开应用和后台消息也能恢复。
- 两版普通设置都有“定时消息”：选手机本地日期/时间，指定原文（无需接口）或指定话题（到时用当前模型生成），查看/取消待办。显式预约与每天自动关心额度分开，仍遵守免打扰及24小时有效窗口；目标时间不是秒级准点保证，只发到本应用聊天与系统通知。
- 角色设置的一次模型请求也可把已回答的长用户答案提炼成AUL关键词；确认后更新对应证据，保留原始答案和来源时间，后来聊天纠正仍优先。空白/未知题不发送，50题原文不进入每轮热提示。
- 默认输入预算与本地摘要token阈值改为5400；旧默认值升级时迁移，其他自定义预算保留。较早内容本地归纳、保留原文，每轮优先最新连续对话，不额外调用摘要模型；估算不是服务商精确硬限。
- 独立开场白可选择延后60–180秒生成，新安装默认关闭此额外延迟；已有明确开关设置保留。连续发出实际内容会合并并恢复普通等待。
- 考试事件先记待确认日期/结束时间，补充明确时间后安排结束45分钟后的关心；改期/取消有来源地处理。不再把“明天考试”直接猜成18:30考完。
- 主动消息保存意图，用WorkManager及可选前台服务调度；除事件跟进外，至少3次用户消息后可从近期话题或兴趣低频开场。默认每天最多1次、间隔8小时、22–8点免打扰；每个最新用户回合最多一次，不反复催没有回复的人。生成前后均复核条件；后台没有可用通知时，普通开场不消耗模型请求。
- 省电/常驻模式可手动切换；Full和Locked现在均默认带持续通知的常驻，已手动选择省电模式的设置保留。常驻可停止、不强行保活、不保证准点；没有配置FCM服务端或自动探测Google服务。固定原文任务即使配置接口，恢复后仍不要求网络。
- 前台只写入聊天记录，后台才发系统通知；点击通知返回聊天页。Android 13+在角色设置完成后请求通知权限一次，拒绝后不循环弹窗，可从聊天提示或设置主动开启。无通知权限时暂用省电调度，保留常驻模式选择。
- 定时消息与待通知记录原子保存。常驻循环、系统任务重试和重开应用会独立处理待通知记录，不为补通知再次生成回复；检查实际消息渠道和免打扰，超过24小时不补旧通知。定时列表区分“已写入聊天”和通知状态，系统提交不代表可见或已读。删除原消息/清空数据会级联删除通知记录。
- Provider、对话模型和 Observer 模型配置；API Key 使用 Android Keystore 加密保存。
- 明暗主题、通知声音/振动、主动消息、周期反馈等普通设置。
- AUL、Evidence、Memory、Policy、Audit 和主动任务调试页。
- SQLite schema 已演进到 v11；保留旧数据，包含本地日期、月归档、目录链接、待整理队列、倒排索引、随消息级联删除的分段计划/通知待发箱及轻量角色记录。升级不会为旧的已发送消息补通知。
- 网络失败保留失败气泡，可手动重试；Core 本身可使用离线本地 Provider。
- 每次生成在本地记录 token、延迟、成功/失败状态；Memory and audit 页的 `metrics` 标签可查看。

### 两个发行版本

**当前公开分发以 Full 为主，不上传 Locked APK。** Locked 源码保留用于开发与回归，不把它宣传成安全加锁版本。仓库公开源码不等于已发布正式签名 APK；体验包和正式版的剩余条件见 [发布清单](RELEASE_CHECKLIST.md)。

| 版本 | applicationId | 行为 |
|---|---|---|
| Full | `com.adaptive.companion.full` | 高级设置始终可见；默认可停止的常驻模式 |
| Locked | `com.adaptive.companion.locked` | 默认常驻、隐藏高级入口；关于页版本区域点击7次后输入管理员密码解锁 |

表中为基础包名；当前 Debug APK 另加 `.debug` 后缀。两版数据隔离，不自动互相迁移。

Locked 版预置管理员密码为 `MIOKIRISHIMA`。验证成功后，本次界面生命周期中的设置能力与 Full 版相同；Activity 重建（例如旋转或进程恢复）后重新上锁，高级路由也会复核。APK 仅保存固定 salt 和 PBKDF2 派生值，不包含密码明文；但预置共享密码只能作为功能入口，不能替代真正的设备级安全边界。

应用与 Python 包统一叫 OpenWoven。新入口为 `openwoven`；旧 `adaptive_companion` 导入、`companion` 命令及 `COMPANION_*` 环境变量兼容。Android 保留原应用 ID、数据库与通知渠道以保持数据兼容；Full 显示为 OpenWoven Developer。角色昵称不受改名影响。

### 首次使用

1. 安装 APK 并打开应用。
2. 选择语言，回答前置10题（用户5＋角色5），先保存角色偏好，以临时称呼或自选昵称开始；也可继续50题完整版，以后仍能补充修改。
3. 真实模型使用时才进入设置 → Provider（Locked版先解锁），填写接口地址、模型和自己的API Key；没有Key也可离线检查设置和示例闭环。
4. 保存模型配置；到角色设置点击“用当前模型生成角色和昵称”，预览后确认。连接测试和角色生成均为主动触发、可能计费的动作，失败重试遵循接口设置；保存配置不会自动生成角色。恢复默认只重置生成参数，不擦除接口/密钥/角色。
5. 返回聊天页开始对话；Android 13 及以上系统需要允许通知，主动消息才能显示系统通知。

如果不配置远程 Provider，Core 回退到本地确定性示例回复，便于离线验证整个学习闭环，不是真正的LLM对话。更多机制与边界见 [角色设计](PERSONA_DESIGN.md)。

### 构建与验证

需要 Android SDK platform 36、Build Tools 36.0.0、JDK 17 和 Python 3.13。工程固定 Gradle 9.3.1／AGP 9.1.1／Chaquopy 17.0.0，见 [AGP 官方兼容表](https://developer.android.com/build/releases/agp-9-1-0-release-notes)。可在 PowerShell 中运行：

```powershell
cd android
$env:JAVA_HOME="你的 JDK 安装目录"
$env:ANDROID_SDK_ROOT="你的 Android SDK 安装目录"
# 默认自动发现 Python 3.13；有需要时指定：
# $env:COMPANION_BUILD_PYTHON="你的 Python 3.13 可执行文件路径"
.\gradlew.bat :app:testFullDebugUnitTest :app:testLockedDebugUnitTest
.\gradlew.bat :app:lintFullDebug :app:lintLockedDebug
.\gradlew.bat :app:assembleFullDebug :app:assembleLockedDebug
```

调试 APK 输出：

```text
android/app/build/outputs/apk/full/debug/app-full-debug.apk
android/app/build/outputs/apk/locked/debug/app-locked-debug.apk
```

Lint 报告输出：

```text
android/app/build/reports/lint-results-fullDebug.html
android/app/build/reports/lint-results-lockedDebug.html
```

## Core 架构

[三张架构图与源码对应关系](ARCHITECTURE.md)：系统总览、记忆与学习闭环、后台消息投递。
图示包含已有调用边界及限制；不是把未来FCM/语义搜索画成已经完成。

```text
Dialogue
  snapshot AUL → scene policy → retrieval → budgeted context → provider
           → DeliveryPlan → persisted assistant message

Learning
  rule/semantic observer or explicit feedback → Evidence
           → deterministic aggregation → atomic AUL + Audit

Proactive
  future-event intent → persisted schedule → WorkManager
           → execution-time revalidation → provider → message/notification
```

核心模块位于 `src/adaptive_companion/`：

- `core.py`：对话、学习、投递和主动消息的统一入口。
- `storage.py`：SQLite schema、迁移、Message、Evidence、AUL、Memory、Audit、Feedback、ScheduledMessage。
- `observer.py` / `semantic_observer.py`：零调用规则提取和按需语义 Observer。
- `aggregator.py`：可配置学习率、冲突重放、原子 AUL 提交。
- `policy.py`：根据场景与 AUL 生成本轮 Interaction Policy。
- `retrieval.py` / `context.py`：索引词项、明确日期筛选、排序和有预算的上下文；不要求向量或额外模型调用。
- `memory.py` / `archives.py`：Rolling 和自动 Daily/Weekly/Monthly 归档，保留原话来源；`long_term` 类型仍预留。
- `delivery.py`：确定性的回复拆分和延迟计划。
- `feedback.py`：将显式反馈映射成可审计 Evidence。
- `proactive.py`：主动意图识别、约束检查、取消和执行前复核。
- `llm.py`：本地 Provider 与 OpenAI-compatible Provider、超时和重试。
- `android_bridge.py`：供 Kotlin/Chaquopy 调用的 JSON 边界。

快速闲聊可增加不超过 900ms 的轻微等待，并扣除模型已耗时；技术和情绪场景立即展示，不拆代码块。开关可关闭自然节奏。

### 节省 token 的原则

- 稳定 Persona 放在 prompt 前部，便于服务端复用稳定前缀。
- AUL 进入 prompt 前先投影成简短、可执行的用户上下文，不发送 Evidence ID、审计记录和内部浮点状态。
- 十项交互偏好先编译成少量自然语言约束。
- 当前消息只发送一次；最近对话和长期记忆按场景动态分配预算。
- 默认只取少量高相关记忆，并在装载时去重。
- `reply_length` 同时控制回答风格和输出 token 上限。
- 规则明确理解的消息不额外调用语义 Observer；Rolling 和自动日/周/月摘要都本地生成，不新增模型调用。

“60% token、90% 效果”目前只是希望达到的目标，不是已验证结果。`usage_source` 为 `provider` 才是供应商报告的 token；`estimated` / `mixed` / `unknown` 分别表示估算、混合来源和旧指标来源未标记。现有指标还不是完整计费账单，尤其是 Observer、失败请求和重试。

原始对话、Evidence 和 Audit 不会为了省 prompt token 而删除，因此仍可解释、纠错和重建。

## Python CLI

要求 Python 3.11+，无需第三方运行时依赖。

```powershell
$env:PYTHONPATH="src"
python -m openwoven chat
```

使用 OpenAI-compatible Provider：

```powershell
$env:COMPANION_API_KEY="..."
$env:COMPANION_BASE_URL="https://api.example.com/v1"
$env:COMPANION_MODEL="your-model"
python -m openwoven --provider openai chat
```

启用独立语义 Observer：

```powershell
$env:COMPANION_OBSERVER_API_KEY="..."
$env:COMPANION_OBSERVER_BASE_URL="https://api.example.com/v1"
$env:COMPANION_OBSERVER_MODEL="your-small-model"
python -m openwoven --provider openai --observer hybrid chat
```

## 自动化测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

测试覆盖渐进偏好学习、显式纠正、冲突 Evidence、Stable/Current 分离、记忆压缩、检索与上下文预算、并发学习、重启持久化、语义 Observer 门控与降级、反馈到 AUL、主动任务执行/取消/重启恢复、DeliveryPlan 上限以及模拟 API 失败重试；不调用真实 Provider。

可运行 `python examples/retrieval_benchmark.py` 检查合成历史检索成本，见 [性能记录](PERFORMANCE.md)。通知／声音／振动／周期反馈开关不再重建 Core，后台单条消息更新不再加载整页历史。

Core CI 安装非 editable 的发行包，在 Windows/Linux 与 Python 3.11/3.13 上做隔离冒烟和回归；当前结果见 [GitHub Actions](https://github.com/karurukaruru/OpenWoven/actions)。手动 Android CI 检查两版单测/Lint，只构建并保留 Full Debug 产物，不上传 Locked APK。首次安装/构建可能联网下载依赖；不需要模型 Key。见 [发布清单](RELEASE_CHECKLIST.md)。

## 隐私与限制

- 数据默认保存在应用私有目录；API Key 由 Android Keystore 保护。
- 应用禁用自动云备份，并显式排除设备迁移中的聊天/配置；换机或卸载可能丢失历史，目前没有加密导出。数据库本身尚未应用层加密。
- 删除聊天会同步撤销来源关联的摘要和受影响字段的审计历史；旧摘要没有完整来源时会保守失效。属于逻辑删除，不承诺物理安全擦除或撤回供应商已收到的数据。
- “清除全部数据”会先二次确认，然后删除本地对话、记忆、学习状态和主动任务。
- 主动消息属于尽力而为：WorkManager 会受系统省电策略影响，不承诺精确到秒。
- 当前交付的是 debug APK。正式分发前仍应配置 release 签名、混淆规则、崩溃监控和真机兼容性测试。
- 当前是一人一数据库；conversation ID 不等于用户隔离。检索覆盖已索引历史但仍是词项检索，含糊表达/同义词可能漏召回。详见 [安全边界](SECURITY.md)。
- 所有者已选择 [MIT](LICENSE)，版权署名为 `karurukaruru`；目标仓库为 `karurukaruru/OpenWoven`。托管 CI 和公开状态以 GitHub 实际结果为准。第三方组件各自的许可证仍需保留。

## 许可证与发布

按所有者选择采用 [MIT](LICENSE)，Copyright (c) 2026 karurukaruru。
源码发布与正式APK验收分别列在 [发布清单](RELEASE_CHECKLIST.md)；源码公开不代表正式签名APK已经验收。

按步骤操作见 [GitHub发布指南](GITHUB_RELEASE.md)，首版文案见 [发布说明草稿](RELEASE_NOTES.md)，版本记录见 [CHANGELOG](CHANGELOG.md)。可运行 `python scripts/release_preflight.py` 做本地源码清单/常见密钥特征检查；发布模式拒绝未完成署名，不能替代人工隐私或历史审查。
