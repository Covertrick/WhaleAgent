# 插件与技能

## 1. 定位

插件是 QQ 运行时可索引的额外技能。仓库里的 `skills/*/SKILL.md` 是 Coding CLI 的说明文本，由 `load_skill` 读取。两套东西不要合成一个注册表。

## 2. 代码位置

- 静态契约类型：`agent/harness/skill_contract.py` 的 `SkillManifest`
- 内置 QQ 表：`agent/harness/qq_skills.py`
- 插件索引与加载：`agent/harness/registry.py`
- 旧门面：`plugins/loader.py` 的 `PluginRegistry`，读的就是 `SkillRegistry`
- 示例：`plugins/echo/manifest.yaml` 与 `plugin.py`
- Coding 技能正文：`agent/skill_load/loader.py` 扫描 `skills/`

## 3. 对外接口

`get_skill_registry().scan()` 只读 manifest，不 import。`load` / `handler` / `unload` / `reload` 按需执行插件代码。`plugins.loader.load_all` 只是 `scan`。

插件 `register(api)` 通过 `ToolAPI.register_tool` 交出 handler。Run 创建时 `acquire_snapshot`，结束时 `release_snapshot`。引用计数大于 0 时拒绝卸载和升级。

## 4. 运行流程

启动扫描 `plugins/*/manifest.yaml`（或 json）。`start_run` 把索引进 `skill_snapshot`，`source` 为 `plugin`。`execute_tool` 若 handlers 里没有这个名字且快照说来自插件，就按冻结的版本向注册表要 handler，再 `dispatch`。

echo 插件的 manifest 声明工具名 `plugin_echo`，效果类 `idempotent`，沙箱 `none`。它不在内置 QQ 名单里。

## 5. 数据与副作用

索引在内存。钉住的模块对象在 `_pinned`。插件自己的副作用由它的 handler 产生，仍然经过当前 Run 的账本（QQ 路径 `require_contract` 时，没有契约且没有快照会被拒绝；插件因为在快照里，可以过这一关）。

## 6. 并发与恢复

注册表用 `RLock`。Run 引用计数避免热更新拆掉正在用的版本。进程重启后内存里的引用清空，磁盘上的 Run 由 `recover_open_runs` 收口，不会自动 reload 插件来重做 UNKNOWN。

## 7. 配置

插件没有环境变量开关。manifest 字段包括 `version`、`description`、`effect_class`、`sandbox_policy`、`permissions`、`tools`。缺省效果类在注册表里写成 `idempotent`，缺省沙箱 `none`。这是索引时的默认，不是 QQ 内置表的默认。QQ 内置表每一项都显式写了效果类。

## 8. 测试

冒烟测试会索引 echo、经账本调用 `plugin_echo`。架构测试不加载插件代码，只比较内置 QQ 名字。

## 9. 已知限制

- 内置 QQ 契约和插件 manifest 是两份来源。插件不从 `QQ_SKILL_MANIFESTS` 派生，内置工具也不读 yaml。合并它们会把「产品自带」和「目录里多出来的包」写成同一种发布物，当前代码不是这样。
- `plugins/loader.py` 不定义第二套 schema。它是注册表的薄封装。
- Coding 的 `SKILL.md` 没有 `effect_class`。不要用它进入 QQ 生产路径。

## 10. 维护规则

- 新插件提供 manifest 和 `register` / `unregister`。加载、引用计数、版本快照留在 `registry.py`。
- 不要在插件里绕过 `execute_tool` 去发不可逆 QQ 动作。
- 自修改白名单不包括插件协议。
