# 其他项目如何做记忆与发布

查阅日期：2026-09-30。只对照官方仓库/文档，不使用各家的宣传 benchmark 推导本项目效果；未复制或引入竞品代码。

| 项目 | 产品形态 | 与记忆有关的做法 | 本项目的取舍 |
| --- | --- | --- | --- |
| [Mem0](https://github.com/mem0ai/mem0) | 可嵌入的记忆层/SDK，也有托管服务，并非 Android-only | 语义检索、可选词项/实体信号、过滤和排序解释 | 先做本地词项+时间+来源检索，未来有明确收益再接语义召回 |
| [Letta 当前入口](https://github.com/letta-ai/letta) | 当前代码在 letta-code；CLI、App Server、桌面、浏览器和 SDK | 小部分 system 记忆每轮进入上下文，其余按需读取；MemFS 版本化，后台 dreaming 整理 | 采用“小型当前 AUL + 按需历史 + 后台整理”的原则，不引入 Git 记忆仓库或额外后台模型 |
| [AIRI](https://github.com/moeru-ai/airi) | 浏览器、Electron 桌面、实验性 Capacitor Pocket 移动版本 | 官方仍将 Memory Alaya 标作 WIP，并列浏览器数据库能力 | 学习共享 Core/多个参考客户端的发布结构，不假设其已经解决成熟长期记忆 |

Mem0 的检索文档区分 Platform 和 OSS，时间推理及部分日期过滤属于平台能力，不能把云功能直接当成开源默认能力。来源：[搜索文档](https://docs.mem0.ai/core-concepts/memory-operations/search)。

Letta 当前文档已经使用文件/仓库式 MemFS，`system/` 每轮注入、其他记忆按需读取，并提供后台 dreaming。
原 V1 服务端进入 archive 分支，不能沿用早期资料把当前版本描述为单一 Python 服务器。
来源：[当前仓库说明](https://github.com/letta-ai/letta)、[当前记忆文档](https://docs.letta.com/agent-sdk/memory)。

AIRI 的 Pocket 文档有 iOS 开发入口，架构标为 experimental；这不等于已验收的 Android 发布版。
来源：[官方 README 中的 Memory 与 Stage Pocket](https://github.com/moeru-ai/airi)。

## 我建议如何发布（判断，不是来源事实）

做“可解释偏好学习 + 可回溯时间记忆 Core，附可安装 Android 客户端”，不要只公开一个 APK。
同一个仓库包含 Core、无 Key 演示、合成测试、Android 源码和已知限制；APK 作为 Release 的体验入口。

最值得展示的具体场景是：说短点/少追问 → 偏好与下一轮策略改变；三个月后 → 找回某一天原话；说忘掉 → 原话、摘要和索引一起清理。
这比笼统宣传“像真人、有长期记忆”更容易让读者理解价值。它是一种发布定位推断，不保证 Star 数量。

目前仍需所有者确定 GitHub 账号、仓库名、版权/许可证和正式发布范围，再检查将被提交的实际文件。
本轮只准备本地源码与说明，没有创建、提交或推送远程仓库，也没有生成任何虚假 Star。
