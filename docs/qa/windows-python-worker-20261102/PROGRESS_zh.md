# Windows Python worker 独立校验

基于main #224/437eba53。既有macOS相关组合回归中的两个Windows原生用例被跳过，不能据此推导AppContainer路径通过。私人Windows隧道两次仅返回MCP SSE 429，没有远端命令执行证据。

增加独立windows-latest任务，使用正式后端依赖、Python3.12和当前worker/SDK源码，执行完整test_python_strategy_runtime.py。测试只使用本地受控策略、临时文件和回环listener，不启动桌面应用、行情DataManager或请求交易所。独立于macOS任务运行，不将Windows作为本地macOS开发前置。

Windows原生用例包括SDK可用但不能读host-private.txt/连接真实回环listener，以及两次一次性profile启停后共享SDK/worker文件ACL恢复基线。新增正对照先证明普通宿主进程能读取该合成文件并连接listener，避免把目标本身不可达误判为沙箱隔离。

JUnit核验器要求真实Windows解释器、完整用例无skip/failure/error，并明确要求冷SDK字节保存、原生文件/回环拒绝及ACL回收三个用例实际通过。回执绑定Git提交和worker/SDK源码SHA；源字节变化使资格失败。失败时仍上传原JUnit和解释原因，不把无报告或跳过当成功。

此任务的通过范围仅限worker/控制策略、字节保存和AppContainer生命周期；不代表Windows安装包、桌面UI、长期资源或完整产品验收。原生worker当前结果见下；完整Windows产品验收仍未完成。


## Windows 当前源提交回执

848644af的Windows任务在2026-11-02 13:36 UTC通过，平台Windows Server2025/AMD64、Python3.12.10。原始JUnit共10个case，零skip/failure/error；逐项核对三个要求用例均实际通过：冷SDK字节不变0.071s、文件/回环隔离8.010s、ACL回收5.113s。这是所选test_python_strategy_runtime.py的全部10项，不能与之前macOS多文件组合29通过混称同一组数量。

[真实运行](https://github.com/helenananaa/CandleScope/actions/runs/41454219240)及原始资格JSON/JUnit/日志在evidence中。资格提交848644af与PR当时head一致，SDK/worker源SHA逐一和本地同源字节核对，保留比较方式。此回执不证明私人Windows电脑、桌面安装包或UI。后续最终文档head仍需对应CI。
