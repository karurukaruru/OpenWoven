# Role packages / 角色包

Android 设置中的“角色管理”和本地 Web 客户端使用同一个 v1 格式。

## 包含什么

ZIP 只包含三份 UTF-8 JSON：

- `manifest.json`：`format: openwoven-role`、`version: 1` 和另外两份文件的 SHA256。
- `role.json`：`name`（40 字符）、`description`（600）、`boundaries`（300）、`preset`。
- `facts.json`：最多 512 条虚构角色经历，每条为 `path` / `value`（160 字符）。

不包含用户画像、问卷原始答案、交流偏好、聊天、预约消息、图片或接口配置。
角色描述也可能由你写入私人内容，分享前请自行检查。哈希用于发现损坏，不是签名或身份认证。

导入创建新的本地角色 ID，不覆盖现有角色。默认不切换，确认后可在角色管理中选择。
每个角色使用独立聊天数据库，未选中的角色暂停发送。切换取消旧角色未完成的回复，保留原消息和预约；返回时由 Core 检查过期与免打扰规则。
旧版默认角色仍使用原数据库和图片目录，不搬迁或清空历史。用户资料不在角色之间自动复制。

## 外部卡兼容范围

支持转换 Character Card V1/V2/V3 JSON 的 `name`、`description`、`personality`、`scenario`；PNG 的 `chara` 或 `ccv3` 文本块也可读取。ZIP 中只有一份角色卡 JSON 时也可转换。
超长文本按当前角色字段上限截短，导入预览会提醒；这是基础设定转换，**不是完整角色卡编辑器或无损转换**。
开场白、知识库、额外系统提示词、脚本、扩展、头像与其他资源不导入，不自动访问卡里的 URL。
带资源的 CHARX、聊天备份、数据库和任意其他应用 ZIP 暂不支持。

参考：[V2 规范](https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md)、[V3 规范](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md)。

文件上限 8 MiB。ZIP 在内存解析，不解压到磁盘；拒绝路径、重复成员、符号链接、加密成员和超限 JSON。
角色经历作为数据按需检索，不作为可执行指令，不将整本档案每轮放入上下文。

## English summary

Both clients exchange an OpenWoven v1 ZIP containing `manifest.json`, `role.json` and `facts.json` only. It excludes user information, questionnaires, chats, schedules, images and provider credentials. Review character text before sharing; checksums detect corruption, not authenticity.

Imports create a new local ID and require confirmation before saving. Switching isolates chats and memory, pauses inactive delivery and cancels unfinished old replies. Legacy Android data stays in its original database and image directory.

Basic V1/V2/V3 JSON and PNG character-card text can be converted; a ZIP with one JSON card is also accepted. Long text may be truncated with a warning. Lorebooks, prompt overrides, scripts, greetings, extensions and assets are not imported. This is not a lossless or fully spec-compliant card editor. Resource-bearing CHARX and arbitrary backups are unsupported.
