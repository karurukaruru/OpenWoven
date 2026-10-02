# 首次公开发布清单 / First public release

适合筹备 **experimental source release**，不称成熟产品。本文件是待办，
不是“全部通过”证明；2026-10-02 源码仓库
[`karurukaruru/OpenWoven`](https://github.com/karurukaruru/OpenWoven) 已转公开。
源码公开与正式 APK 分发
是两个不同里程碑。所有者已选择 MIT，确认版权署名 `karurukaruru` 与
目标仓库 `karurukaruru/OpenWoven`。

按步骤操作见 [GitHub发布指南](GITHUB_RELEASE.md)，首版文案见
[发布说明草稿](RELEASE_NOTES.md)，版本记录见 [CHANGELOG](CHANGELOG.md)。
本地 `scripts/release_preflight.py` 可生成待上传源码清单及所选附件的SHA-256；
不读取数据库/凭据，不修改Git，不上传。它不是完整秘密或历史扫描。

已补 [三张架构图与模块对应](ARCHITECTURE.md)。架构文档及Android所引用的
`android/app/proguard-rules.pro` 都是发布检查必备项，缺失会阻塞自动检查。
本轮补了 [AUL 设计](AUL_DESIGN.md) 与定时任务同时间排序修复；不启用 R8 或生产签名。
公开产物只考虑 Full，Locked 源码保留，不上传 Locked APK。

## 1. 公开源码前必须完成

- [x] 确定仓库账号/名称，填写 `LICENSE` 的版权署名（所有者确认：karurukaruru）。
  MIT 文本及 Python 包的 SPDX 声明已准备；不要带占位署名直接发布。
  [GitHub 说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
  区分公开可见与授予使用、修改、再分发许可。
- [x] 检查实际待提交文件及已有历史（如导入旧仓库）：不得包含 Key、真实聊天、
  数据库/WAL/SHM、私有地址、签名材料或构建缓存。忽略规则不是秘密扫描。
  不提交工作目录的全部文件；APK 只考虑单独的 Release 附件。
  本次检查初始两次提交的 166 个源码 blob、提交邮箱与当前 160 项源码清单；
  未发现常见密钥特征，未纳入私人数据／构建产物，提交邮箱为 GitHub noreply。
  有限模式检查不等于完备安全审计，后续新增提交仍需复查。
- [x] 建立私下安全报告渠道并更新 `SECURITY.md`。目标仓库已启用
  [private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)。
  已由 API 复核 `enabled=true`；不承诺固定响应时限。
- [x] 在 GitHub 跑通 Core workflow：Windows/Linux、Python 3.11/3.13、发行包安装、
  隔离模式无 Key Demo、全部回归和合成检索记录。不仅凭本地测试挂绿徽章。
  修复提交 `46f2d21` 的 [四组 Core CI](https://github.com/karurukaruru/OpenWoven/actions/runs/37002623203)
  通过；同提交的 [源码候选包检查](https://github.com/karurukaruru/OpenWoven/actions/runs/37002692407)
  通过。此后新提交仍需查看自己的检查结果。
- [x] 完成版权署名后重新构建 wheel，并运行
  `python scripts/package_smoke.py --for-publication`。默认检查允许本地草稿，
  发布模式拒绝未完成的版权占位；这仍不是秘密扫描或许可证法律审查。
  本次当前源码 wheel 已通过临时隔离环境的发布模式检查、无 Key demo 和兼容入口。
- [x] 首页标注原型、单用户、规则语言范围、非语义检索、删除边界；
  不把本地示例说成真实 LLM 效果，不宣传未验证的 60%-token/90%-quality。

已准备：中英文入口、无 Key 演示、贡献/安全说明、Issue/PR 模板、Core CI、
手动 Android CI、[检索成本记录](PERFORMANCE.md)、MIT 文本与包声明。
配置存在不代表托管 CI/安全审查通过。Action 已固定到2026-10-01从官方仓库标签
核实的 commit SHA；需要持续审核更新，固定版本不等于完整供应链审计。
另有手动 Source release candidate 工作流：版权完成后构建/检查wheel，生成
短期候选 artifact；无仓库写权限、不自动公开 Release。执行状态看 Actions，
不要把已配置等同于已运行通过。
本次手动源码候选包已运行通过；手动 Android 托管流程未运行，本地两版各 98 项
单测、Lint 0 问题和 Full Debug 构建通过，不伪写成真机／托管 Android 验收。

## 2. Android 体验版与正式版分开

体验版可以标注 Debug/experimental；正式用户版本至少还需：

- [ ] 真机验证连续发送成一轮、空框20秒等待、拼字/草稿暂停、生成途中继续输入、切后台/进程终止后的恢复；检查分条关闭延迟、重开、通知后仍独立显示。
- [ ] 验证后台完成回复后也能规划下一次低频开场；手动立即执行仍走逐条展示和通知待发箱。设置数字可清空/输入小数，无效草稿不能保存；取消/删除预约及时刷新，删除暂存任务不留下等待状态或未记账缓存。
- [ ] 用合成旧库验证日语/半角索引升级、中断续接、学习失败后的摘要恢复、256条分批与原话来源保留；首次大库升级耗时、真机旋转草稿及删除与初始化并发仍需设备验收。
- [ ] 检查四语Talk不显示计时/后台/生成机制提示，设置仍能查看身份、图片费用、通知权限与详细错误；直接询问真实身份时如实回答。验证第一人称角色表现及长期连续性，不能拿提示词字符串断言当作模型效果验收。
- [ ] 真实接口验收普通文字回复、可选角色元数据、低输出额度截断、坏记录跳过但保留正文、同标签冲突、自由多语标签漏报与近义标签；重启/改昵称/换角色/删除/暂存取消后的连续性。技术回答/文章/故事不误归档，近期原话去重不丢唯一摘录。不宣传全语义时间线一致、统一节省率或真实人类经历。检查v10到v11升级保留预约及通知待发箱。
- [ ] 验证慢学习后的自动滚动整理、q21最短端点、整轮失败/图片模型切换的重试状态，以及长聊天在5400预算内的连续性；前台同时排队消息和刷新历史不得吞掉新消息，关闭系统通知仍显示聊天。虚拟时钟/离线回归不能替代真机耗电和时序检查。
- [ ] 用自己配置且确有图像能力的接口检查图片及文字混合请求、权限最小化、超大/损坏图片、旋转方向、切到文本模型、失败重试和删除副本。离线合成测试不能证明第三方模型看图成功。
- [ ] 检查手机时区变更、午夜与夏令时。可选聊天时区目前只影响模型时钟，预约选择与归档仍使用设备本地时间；未实现任意时间自然语言解析。

- [ ] 目标真机验收：10题/50题、四语、旋转/进程恢复、断网/重试、长聊天、
  删除/清空、取消任务、重复通知、后台静默/省电限制；通知拒绝/再次开启、
  无通知权限时不消耗普通开场请求、滑杆端点、阅读旧历史不被拉回底部。
  验证普通定时页的指定内容/到时生成话题、取消/重启/免打扰顺延、前后台
  气泡一致与反馈/删除身份，以及5400旧默认迁移与模型提炼后再纠正/撤回。
  两版默认常驻及停止/恢复；固定原文配置API后断网恢复；已写聊天未提交通知时
  杀进程后的补发、消息渠道单独关闭/恢复、夜间补发顺延、通知待发箱24小时
  过期与删除级联。通知“提交系统”不当作可见或已读验收。
- [ ] 经用户同意测试一个真实 Provider，确认真实请求、预算、错误与费用；
  包括手动角色生成的严格JSON、候选昵称、确认/失败保留、低输出额度与重试，
  以及普通主动话题的真实效果。离线回归只验证机制，不强制读者提供 Key。
- [ ] 确定正式包名/版本/Release 签名与密钥保存策略，签名材料不提交。
  对 R8/缩减与 Chaquopy 验证兼容，不直接开启未经检查的混淆。
- [ ] 明确 ABI。现有 ARM64＋x86_64 通用 Debug 包兼顾手机/模拟器，也增加包体；
  正式分发再评估按 ABI 构建/AAB，不删除必需的 Python 运行库硬缩包。
- [ ] APK 附版本、构建条件、SHA-256、已知限制、来源链接与第三方声明。
  手动 workflow 的短期 artifact 不是正式 Release；不同机器 Debug 签名可能
  无法互相覆盖安装。卸载会丢本地历史，当前无加密导出。
- [ ] 核对实际打包的许可证/版权声明：Chaquopy/Python 标准库、AndroidX、
  Kotlin/coroutines 与传递依赖。项目的 MIT 不替代这些声明。
  [Chaquopy 官方说明](https://chaquo.com/chaquopy/license/)其12.0.1之后为开源版本，
  无需旧商业授权 Key，但 APK 再分发声明清单仍未完成。
- [ ] 说明公开管理员密码仅为便利锁；数据库未加密、自动备份关闭、
  远程服务商可接收上下文。不以 Locked 版冒充安全隔离。
- [ ] 如计划 Google Play，再审查前台 `specialUse`、权限与商店政策；
  GitHub 发布不代表获得商店审核通过。

## 3. 怎样更有说服力

- [ ] 让另一个人在干净目录按英文 README 跑通，记录独立上手问题。
  这是后续体验验证，不把“另一位真人已跑过”伪写成源码首发的自动检查结果。
  首次安装可能下载构建工具，无 Key 不等于安装过程完全无需互联网。

先展示可复现闭环：偏好反馈 → Evidence/AUL → 后续 Policy 改变 → 来源解释 →
撤回/删除，再展示日期定位原话。录屏只用合成身份；真实模型效果与离线机制
明确分开。建议定位：**Explainable preference learning + calendar memory,
with an Android reference app**。

先找少量真正需要 Core 的开发者试用，记录能否跑通、能否复用和具体缺陷。
Star 无法承诺，也不是长期陪伴质量证明；不购买或互刷。
后续公开评测涵盖纠正、否定/转述、过期事实、旧事召回、删除后遗忘，分别
报告规则准确性、真人盲评、模型费用和端到端延迟。不得把 SQLite 查询减少
比例外推为 LLM 质量或总体费用改善。
