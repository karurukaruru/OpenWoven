# OpenWoven GitHub 首次发布操作指南

所有者已授权检查通过后公开发布，确认目标为 `karurukaruru/OpenWoven`，
MIT版权署名为 `karurukaruru`（2026）。以下为可复用操作步骤，不是托管CI
或公开完成证明；当前状态见GitHub实际仓库及本地审查记录。

2026-10-02：仓库已公开，私下漏洞报告已启用；修复提交 `46f2d21` 的四组 Core CI
与源码候选包检查均通过。本次补齐 APK 第三方声明与模型周摘要，准备发布
实验性下载包；最新附件以 [Releases](https://github.com/karurukaruru/OpenWoven/releases) 为准。
下方保留发版操作步骤，不要把“仓库公开”与“正式二进制发行”混为一谈。

建议首版：**OpenWoven — v0.1.0 Experimental**。
先公开可复用 Core＋Android 参考客户端源码；APK 是可选附件，不是开源的前提。
源码开源不需要 API Key、FCM、应用商店账号或生产签名密钥。
只要准确说明限制，不必为源码首版宣称已完成真实模型/真机验收。

## 1. 补齐三个决定

- 版权署名：所有者已明确确认为 `karurukaruru`，`LICENSE` 已更新。
- GitHub 账号和仓库名：所有者已确认 `karurukaruru/OpenWoven`。
- 私下安全报告渠道：确认可公开的联系渠道，或在公开仓库启用私下漏洞报告，
  再更新 `SECURITY.md`。没有启用前不要写“已经提供”。安全问题不要走公开 Issue。

仓库简介建议：

> An AI chat app that gets to know you over time.

建议 Topics：`android`、`llm`、`memory`、`chat`。
首页展示无 Key 可复现的学习/遗忘闭环，不用未验证的真人感或节省率宣传。
博客只提炼项目动机，不上传完整私人经历或把未经验证的效果当作广告。
公开附件以 Full 为主；Locked 源码保留，不上传 Locked APK。

## 2. 本地检查准备上传的内容

从项目根目录运行（Python 3.11+；无需模型接口）：

```powershell
python scripts/release_preflight.py --output release-dist/source-review-01
$env:PYTHONPATH="src"
$env:PYTHONUTF8="1"
python -m unittest discover -s tests -v
python examples/calendar_memory_demo.py
```

`release-dist/source-review-01/` 不提交到仓库，包含：

- `SOURCE_FILES.txt`：待提交源码/文档路径。人工逐项检查，不用 `git add .`。
- `preflight.json`：自动检查、阻塞项和仍需人工确认的事项。
- `SHA256SUMS.txt`：所选附件校验值；未指定附件时为空。

工具只读取白名单源码，排除数据库、`.env`、本机 SDK 配置、构建缓存、签名材料及链接路径。
只检查少数常见 Key/私钥特征，**不能识别所有密钥、私有地址或真实聊天，不扫描 Git 历史**。
“自动检查通过”不等于允许公开：人工隐私核对、安全渠道和 CI 仍需完成。
每次使用新报告目录；脚本不覆盖旧报告、不提交、不上传。

改名后的清单在 `release-dist/openwoven-20261002/`；包括架构文档、兼容入口及
打包检查，记录 OpenWoven wheel 与本次两版 Debug APK 校验值。较早的153/155项
草稿保留为历史快照，不作为最新提交清单。源码数以本次 `SOURCE_FILES.txt` 为准。
这是本地草稿，不是可直接发布的来源证明；版本、署名或内容改变后须重新构建/生成。
本次因应用显示名称变化重打包 Debug APK，仍未启用生产签名或混淆。

版权署名补齐后再检查发布模式：

```powershell
python scripts/release_preflight.py --for-publication
python -m pip --isolated wheel --no-deps --wheel-dir dist .
python scripts/package_smoke.py --for-publication
```

wheel 是 Python 安装包，不是 APK；首次构建可能下载工具依赖。
版权占位仍在时发布模式应失败，不要绕过。`dist/` 有多个 wheel 时，
给 `package_smoke.py` 指定本次 wheel 路径，不混用旧产物。

## 3. 所有者确认后才创建仓库、提交和推送

2026-10-02 已初始化本地仓库并推送 `main` 到 `karurukaruru/OpenWoven`。
下方是新项目可复用步骤，不要在已有仓库重复初始化、改写历史或重复添加 `origin`。
先确认 Git 身份和提交邮箱公开范围；邮箱会进入提交元数据。

1. GitHub 新建空仓库，不额外初始化 README、许可证和忽略规则。
   可先建私有仓库，完成人工复核和 CI 后再明确确认转公开。
2. 首次初始化并按已审核清单暂存源码（PowerShell）：

```powershell
git init -b main
$releaseSourceFiles = Get-Content -LiteralPath release-dist/source-review-01/SOURCE_FILES.txt
foreach ($releaseSourceFile in $releaseSourceFiles) {
    git add -- $releaseSourceFile
    if ($LASTEXITCODE -ne 0) { throw "停止：暂存失败，请检查清单" }
}
git diff --cached --stat
python scripts/release_preflight.py --for-publication --check-index
if ($LASTEXITCODE -ne 0) { throw "停止：提交内容检查未通过" }
```

人工查看实际暂存内容；疑似密钥不截图/复制进公开 Issue。
`--check-index` 拒绝白名单外已跟踪文件、未暂存源码、未解决冲突和工作文件与暂存内容不同。
导入已有仓库须另行检查历史；`.gitignore` 不会清理旧提交。
修改/新增源码后重跑检查并更新清单，不沿用较早快照直接发布。

3. 提交、连接自己的空仓库、推送（已连接 `origin` 时只需正常推送）：

```powershell
git commit -m "Prepare experimental v0.1.0 source release"
git remote add origin https://github.com/karurukaruru/OpenWoven.git
git push -u origin main
```

这些命令会改变本地/远程状态。推送到公开仓库后源码即公开；
**Release 草稿不会隐藏已经公开的提交和标签**。已有远程/分支冲突先检查，不强制覆盖。

## 4. 在 GitHub 生成候选材料，不自动发布

- `Core tests`：推送/PR 后检查 Linux/Windows、Python 3.11/3.13、发行包安装和无 Key 回归。
- `Android offline-model checks (manual)`：Actions 手动运行，两版 JVM 检查、Lint，
  只构建与保留 Full Debug APK，绝不上传 Locked APK。
  短期 artifact 是检查产物，不是正式 Release。
- `Source release candidate (manual, no publication)`：在确认的候选提交手动运行。
  要求版权完成，检查源码清单、构建 wheel、隔离安装、回归及校验值；
  只保留14天候选 artifact，无模型/签名 Key、无仓库写权限、不自动创建 Release。

Actions 已固定到从官方仓库标签核实的 commit SHA（2026-10-01）。
这限制浮动标签变更，不等于完整供应链审计；以后要审核更新。
Core 工作流已开始在 GitHub 执行，当前结果见
[Actions](https://github.com/karurukaruru/OpenWoven/actions)。应检查同一提交的
四组结果，不以旧提交通过或本地静态检查代替；手动工作流须另外触发。
三份工作流已通过本地actionlint 1.7.12静态检查（未启用ShellCheck/Pyflakes）；
静态通过不能替代GitHub运行或Android真机检查。
托管执行按账号可用额度进行，不需要模型 API 额度。

## 5. 首次 Release：先草稿，再确认公开

建议标签 `v0.1.0`，匹配 Python/Android 版本 `0.1.0`；
标题 `OpenWoven v0.1.0 — Experimental source release`，勾选 **pre-release**。
避免另建同版本 alpha 标签，造成包版本与来源对应不清。

1. Core CI 在同一待发布提交上通过。附 APK 时，同一提交的 Android 检查也须通过。
2. 核对候选 artifact 的提交编号、实际校验文件，完善 [发布说明草稿](RELEASE_NOTES.md)。
   不把旧本地产物附到不同的新标签；仅 `HEAD` 编号不能证明已有附件由该提交构建。
3. 仓库 → Releases → Draft a new release，选标签/目标提交，填标题和说明。
4. 先 Save draft。可附 wheel＋`SHA256SUMS.txt`，GitHub 自动提供标签源码下载。
   核对版本、来源和限制后，由所有者点 Publish release。
5. 私有仓库转公开前再次确认源码、提交元数据及可见内容；启用私下漏洞报告，
   更新 `SECURITY.md` 和已完成事项的待定描述。

若附 APK，先完成第三方声明与对应验收，在选定提交重新构建 Full，
再显式指定附件生成新快照。不要复制或上传 Locked APK：

```powershell
Copy-Item -LiteralPath android/app/build/outputs/apk/full/debug/app-full-debug.apk `
  -Destination dist/OpenWoven-0.1.0-full-debug.apk
python scripts/release_preflight.py --for-publication --check-index `
  --asset dist/openwoven-0.1.0-py3-none-any.whl `
  --asset dist/OpenWoven-0.1.0-full-debug.apk `
  --output release-dist/assets-review-01
```

按 `SHA256SUMS.txt` 对照实际附件，可用 `Get-FileHash -Algorithm SHA256`。
校验值只说明文件是否相同，不证明安全、签名可靠或模型效果。
APK 再分发前还需完成组件版权/许可证声明；Debug 必须明写。
不同机器 Debug 签名可能不能覆盖安装，卸载会丢历史。正式签名版另走
[Android 验收清单](RELEASE_CHECKLIST.md)，生产私钥不放进仓库或 artifact。
本轮不配置自动发版、PyPI 或应用商店发布。

## 官方流程依据

- [上传已有本地项目](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)：仓库、提交和推送。
- [管理 Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)：标签、草稿、附件、pre-release；若启用不可变 Release，公开前附齐文件。
- [配置私下漏洞报告](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)：启用后才有私下入口。
- [Push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection)：按可用功能核对配置，不替代人工隐私/历史审查。
