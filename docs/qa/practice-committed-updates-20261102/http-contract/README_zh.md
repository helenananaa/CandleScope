真实交易账户FastAPI router/TradingStore/DataManagerCore与未替换的前端API/stream/parser/共享pool，通过独立loopback HTTP进程对接；使用正式GZipMiddleware与已准备CPython依赖，响应未被替换。来源K线明确是受控fixture，不启动LIVE组合，不声明Chrome/native UI或真实市场资格。

首轮Node平台window缺少事件接口，驱动失败，原始日志保留。添加真实Node EventTarget适配后第二轮功能通过；第三轮补齐SIGTERM及服务lifespan完成回执后功能再次通过。不得把浏览器环境适配描述为生产代码修复。

两模拟账户，两个同账户消费者共用1条流；真实HTTP市场单/止盈止损建立、受控下一根K线触发保护单成交、限价挂单/撤单，前端通过提交推送接纳完整状态，另一账户持仓保持独立。独立整数微USDT费用式：3 - .05 - .0206 = 2.9294，账户余额1002.9294，与实际前端模型一致。renderer模型未调用summary/trades/journal旧轮询端点，只有2条events。最后释放后subscriptions/read_jobs均0。

后端和前端模型进程均重新启动，复用原SQLite；账户资金/交易与持久epoch/sequence17一致。两次服务均记录lifespan清理完成后收到SIGTERM退出，0订阅/0读取任务，loopback_only网络尝试0。该证据是实际HTTP和模型生命周期，不是原生应用完全退出验收；原生固定策略验收另有e789独立回执，模拟账户真实LIVE UI仍待完成。
