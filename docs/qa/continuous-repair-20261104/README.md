# 授权修复基础层（进行中）

基于 Draft #254。当前仅实现来源前缀分叉和账户归属明确的稳定来源 epoch，尚无修复任务、财务替换或公开修复入口；现有 API 仍声明 repair_available=false。

PrefixWatchStore.fork_unchanged 在同一来源 SQLite 事务内，验证原 receipt 身份、观察的 source version 与最早修订范围，仅允许从修订前的已知未变前缀建立新来源记录。拒绝预览后再次修订、覆盖已有 owner 或超过 watch 预算。原记录不回退、不改名、不清除待修订标记。新 epoch 在后续财务发布前已独立持久化；沿用现有提交围栏时，财务提交后来源确认失败仍可恢复该来源记录，避免跨两个数据库改名造成的恢复空洞。

新增内部来源 owner 以账户编号的 SHA256 和随机 epoch 组成，使用区别于旧 strategy: 名称的独立命名空间，防止含冒号的账户编号别名碰撞。旧账户名称保持原有规则。Host 与 Source 注册验证同一账户的新 epoch，执行暂停/恢复改变 generation 时不会改变来源 epoch。

repair-prefix.log.gz：48 passed，5 个既有 warnings。repair-identity.log.gz：50 passed，5 个既有 warnings，包含以上前缀测试及真实 Host/Provider/来源/SQLite 场景：同一账户编号在独立暂存 Store 中使用新来源 epoch 计算并恢复，原财务 Store 完全不变；错误账户和错误来源命名均拒绝。这并非已经完成真实修复或财务原子替换。

下一阶段方案：保持 runs.definition_json 和原创建检查点不可变，保全创建幂等；预先写入独立 epoch 的完整结果行与未来恢复检查点，旧活动指针继续读取旧结果。最终来源围栏只执行财务 identity CAS 和常数大小的活动 epoch/游标切换，不在来源写锁内复制整段历史或插入大检查点。暂存和已采用历史一起纳入有限预算；修复日志、失败回收、旧 watch 退休和应用关闭排空仍需实现与验证。

本轮未启动公开行情、浏览器交互或原生包。完整修复流程、UI 确认与最终原生退出/重启验收均未完成。
