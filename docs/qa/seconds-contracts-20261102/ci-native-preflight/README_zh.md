# 当前 CI 原包预检：尚未启动原生应用

PR200 当前 head150bb85c、run41442721624、artifact13145235521的实际arm64产物，下载归档SHA256为1fc3e66be46f3791d9a2d07349d5cf648ab37c14b327e870488bf1faa80de54d；GitHub摘要、内部ZIP/DMG摘要、build-manifest提交及run均一致。仅解包原始ZIP，不重打前端、替换运行时或重签名。官方架构/依赖导入/符号链接/严格签名检查通过。

1045源码/SDK文件对应提交checkout字节逐项一致，161前端资产冻结自原始CI ASAR；9插件资产和76插件源码匹配。SDK原有92个pyc在内的完整212文件集合已冻结用于运行后复核。Pine bundle为d3cc1854…，不冒称此前本地候选f9a075…同一归档。

候选位于output/seconds-contracts-20261102/ci-native-arm64-150bb85c，无profile且应用未启动；qualification.json明确nativeQualified=false。PUBLIC_COOLDOWN在Electron启动前拒绝，原生脚本每次启动均重新检查，包括保存后重启。当前期限2026-11-02T16:14:01.202Z，不能提前启动或清空限流器/profile绕过。

后续优先以该候选的绝对路径设置CANDLESCOPE_BATCH1_QA_ROOT，运行seconds-integration-20261101/native-acceptance.mjs。运行前和所有自有进程正常退出后都运行本目录上级verify.mjs，分别保留回执，包括失败退出。实际四图MA数值、自然收线、保存/完全退出/重启仍未通过，保持Draft；本预检不证明源时钟修复已解决旧共享指标恢复阻塞。

本轮QA准备暂不提交，待真实验收回执集中提交，避免重置当前已通过的三个CI。原始旧候选、profile、失败日志与postmortem-main211时间线全部保留。
