# 正式回放笔记的版本截图

原始需求#166的截图子范围，承接已合入main的#235/#236/#237；main e71bbf33与原cb20e41c源码树一致。整个#166保持开放。执行边界见../../architecture/REPLAY_NOTE_SCREENSHOTS_20261104_zh.md。

## 当前实现

复用双Manager、现有注释事务、JournalEditor和图表导出/绘图lease。只读导出源receipt复用SingleChartPanes已有paintedSourceRef核对当前store与版本，稳定两帧后固定像素，捕获过程若视图/源变化则拒绝。导出PNG不改变回放时间或账户。

PNG先作为不可变、运行/轨道/epoch所属素材保存，再与文字版本同事务绑定。旧版本不追加新截图；按具体可见笔记版本读取PNG，同毫秒更早事件不能读取后来的图片。schema28→29增加capture及版本关联表，所有旧文字/关联/金融行保持原值。单图2MiB/4096×4096，每版本2图，每运行16MiB/128图。普通文字请求仍64KiB；单独PNG端点3MiB。运行删除沿用既有外键级联。

待提交PNG请求在本地草稿中保留原ID、上下文、像素及图表元数据，响应不确定可精确重试；显式另存创建新请求并保留原素材，捕获市场时间不改成另存时刻。已上传未绑定素材受预算约束保留，避免误删仍属于草稿的数据。图片按需加载，整个笔记面板/历史同时只解码一张大图。

## 当前验证

180项整合后端测试通过，4条既有FastAPI提示；架构输出与main既有10条逐字节一致。5项截图后端用例覆盖真PNG字节版本、同毫秒回退、跨运行拒绝、不可见版本404及坏绑定503、请求及资产预算、迁移保留行和删除运行级联。16项笔记前端测试通过，包括原PNG请求恢复/显式复制不改原始素材、源变化、未绘制的源拒绝及lease释放、严格图片解析、Manager parsed-body取消。

真实Chrome156/生产React/HTTP/SQLite的10项场景通过，使用明确测试canvas和真实导出器而非实际K线截图，范围不能替代原生图表：v1/v2不同PNG字节、同毫秒旧事件无法读未来图、25版20+5分页、已提交PNG响应丢失后remount精确重试、文字不确定提交、显式复制保留原PNG及捕获时间、迟到历史正文均正确。0异常/残留worker/外网尝试。首轮浏览器因按钮附带市场时间、QA只按完整标题匹配而超时，选择器已修正，保留失败原始日志；未放宽产品边界。

正常退出HTTP服务后，同一SQLite目录由两个全新后端进程40370→40383读取：4条可见笔记及2张版本PNG的字节/元数据相同，源/Review游标与金融快照相同，两个退出均关闭Manager、0streams/外网尝试。该证据仍是后端新进程，不代替原生完整退出。

完整npm check正在收尾。最初类型问题为可选captureChart的exactOptionalPropertyTypes及删除草稿字段的Record类型，均已按现有类型契约修正。首次完整前端检查遇到pt-BR的英文token规则；将暂停提示及分辨率改为自然葡语文字，保留原翻译门槛。实际导入BAR原生截图、完整退出/重启及新head远程CI尚未完成，不宣称已交付。

## 复现入口

新增backend/tests/test_replay_note_captures.py；浏览器沿用../replay-time-notes-20261104/http_server.py及frontend/scripts/frontend-script-integration.mjs --replay-notes；独立后端恢复用同目录restart_check.py。都必须用新的私有QA目录及loopback端口，守卫在导入后端前安装。

本目录native-acceptance.mjs针对实际导入BAR图表，沿用../replay-imported-bar-20261104/assemble.py、verify.mjs和已验证Python运行时。先构建当前frontend/dist并提交源码，再用新私有目录生成候选；校验源码/SDK/插件、严格签名及完整正常退出。Windows、广泛多商品/重连/指标及原生图形Review仍独立待验。


首轮8a670f08原生候选已成功提交真实图表PNG，但QA把Playwright HTTPResponse误当Fetch Response调用clone，脚本退出；未作为通过记录。已按既有Playwright接口修正，同时补充截图期间指标计算/呈现引用变化的拒绝条件；源/行情时间未变也不能混入异步更新中的指标画面。后续候选必须重新构建当前源。
