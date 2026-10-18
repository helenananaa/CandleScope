# 插件安装与详情同步

2026-10-13，QA-07，第32版生产复验通过。

`usePluginDetail`在平台registryRevision变化时重新加载当前插件详情；响应绑定选择与请求代次，迟到的旧请求或旧组件的reload不能覆盖新选择。保留正在加载时的当前详情，错误与loading按插件隔离。

原资料中的Hello Command 0.1.0用于复验。负向fixture从项目自带包复制，SDK wheel不变、无新增权限，只把manifest入口改为不存在模块，并重新计算包内容摘要。生产安装正确报fresh-process platform Host probe failed，原有效激活没有被替换。随后在同一插件中心选择原有效包安装成功，直接切“我的插件”，概览可用、旧失败消失；停用→启用即时同步，关闭中心后Say hello命令完成。

证据位于`output/acceptance-20261012/evidence/QA07-v32-install-failed.*`、`QA07-v32-install-success.*`、`QA07-v32-overview-enabled.*`、`QA07-v32-command.*`。负向包首次制作遗漏ZIP普通文件模式，被完整性检查正确拒绝；修正fixture属性后才进入上述真实入口探测失败，未放松产品校验。安装前插件页有一次AX树不完整，截图内容正常，不计为白屏缺陷。

现有插件前端54项回归通过（`qa07-plugin-regression.log`）。此项验收不代表签名市场已配置，也不代替有权限插件的拒绝/撤销验收。

2026-10-15 独立 PR 提取：从 `2947ae1d` 基线仅提取当前详情订阅注册表版本的修复，不包含其他插件、运行时或回放改动。提取后插件前端 54 项回归、完整前端类型检查、修改文件 ESLint 和 `git diff --check` 通过。本次未重新打包或操作原生应用；上述第 32 版记录保留为历史验收证据。
