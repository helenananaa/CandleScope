# 正式回放笔记：按版本绑定成交和交易

对应原始需求[#166](https://github.com/helenananaa/CandleScope/issues/166)的笔记关联子范围。依赖#235时间笔记/历史和#236用户导入BAR；不关闭整个issue。截图附件另行推进，本记录不包含截图功能交付。

## 所有权与时间

- 双Manager入口和既有JournalEditor不变；两个可选字符串表单字段replayFillIds/replayTradeIds保存选择的ID数组，因此原有草稿/排队保存/不确定提交重试一并保留选择。最多八笔关联；候选按所属运行与轨道查询，每页最多20条，UI只保留当前页及最多八项选择。
- 验证来自既有contract_fill、不可变trade_result及已提交账本FILL引用；不改金融表、不创建第二个账户。Review事件的冻结ledger_count限定账本前缀，同一毫秒后来发生的成交仍不可选；仅按时间比较不足以建立该边界。
- schema27→28只添加note_links并为旧文字版本回填空关联，保留所有既有数据。旧版升级26及更早受支持路径同样补齐新表。引用摘要与笔记版本在同一SQLite注释事务保存，计入既有8MiB/运行预算；历史版本只读自己的摘要，不从当前账户补写。版本摘要缺失/损坏明确503，不能用新版本替代。
- 关联摘要包含类型/ID、成交ID、有效市场时间、源序号、方向、原始精确数量与价格。显示时间仍经过public-time。前端严格解析与Manager的parsed-body lease覆盖候选响应，关闭/换上下文取消旧请求。

## 已有验证与待补

19项笔记和新增关联测试通过：真实交易产生同毫秒成交与平仓交易，v1/v2/v3分别无关联/成交/成交+交易；历史、精确重试与服务重启保留对应选择；另一个运行不能引用本运行成交；两个FULL轨道出现同样的fill ID时保持各自价格与引用；27迁移保留原表行，缺失版本摘要503；候选20+5分页及八项限制有效，笔记不改变账户或游标。11项前端笔记测试通过，覆盖精确Decimal字符串、未来/损坏摘要拒绝、选择草稿及parsed-body取消。

真实Chrome156/生产React/HTTP/SQLite的8项场景通过：UI选择实际模拟成交和已平仓交易，25版20+5历史，回退同毫秒更早事件无未来关联，旧响应迟到、丢失已提交响应、草稿恢复及显式另存均正确。0renderer异常/残留worker/外网尝试。该服务在导入后端前安装loopback-only守卫，使用显式fixture行情，不代替导入原生验收。

整合后端、完整前端CI同命令检查及新原生已安装包保存/完整退出/重启仍在执行，最终结果以qualification.json及后续本节为准。第一次扩展服务重启测试因测试工厂复用ID发生冲突，已将另一个运行的创建放在重启前；未更改产品ID规则。整合检查发现旧obsolete集合没有排除新增可迁移的27，测试分类已跟随迁移更新；27的保留行测试独立保留。

## 复现

沿用../replay-time-notes-20261104/http_server.py和frontend/scripts/frontend-script-integration.mjs --replay-notes，使用新的私有CANDLESCOPE_NOTE_QA_ROOT及loopback端口。原生使用本目录native-acceptance.mjs、../replay-imported-bar-20261104/assemble.py及verify.mjs，必须先构建当前frontend/dist，候选使用当前已提交源和独立新QA目录。LOCAL_OFFLINE、回放WS、源与插件匹配及完整正常退出保持强制检查。
