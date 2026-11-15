# Copy guidelines

How CandleScope talks to people, in Chinese and English. The interface defaults to `zh-CN`; `zh-CN` and `en` are the two source catalogs, written together, and the other 28 catalogs in `src/i18n/catalogs` translate them. Design rules live in [`DESIGN.md`](../DESIGN.md); i18n mechanics in [`src/i18n/README.md`](src/i18n/README.md).

## Voice

- **Say what the person can do or what happened**, in the words of their task: prices, candles, orders, runs, notes. Not how the system does it.
- **Short.** A label is a few words; a hint is one sentence. A paragraph in a default view is a sign the control is unclear, or the detail belongs behind 技术详情 / Technical details.
- **One term per thing.** Use the glossary below; the same object never has two names on one screen.
- **No internal vocabulary in default views:** status codes, class and service names, storage or runtime internals, project phases. Engineers still get them, in a technical-details disclosure or in support logs.
- **Calm about failures.** Say what failed and what to do next ("Try again shortly"), not who is at fault.

## Chinese

- Full-width punctuation (`，。：；（）`), with a space between Chinese and Latin letters or numbers: `K 线`, `{n} 个周期`, `Pine v5/v6`.
- No English words, except names (Binance, OKX, Pine, Python, CandleScope, Webhook), file types (CSV, PNG), units and tickers (USDT, ATR, MFE). Everything else gets a Chinese term from the glossary.
- Verbs on buttons (`保存`, `添加账户`); statements in hints, without `请` unless asking for an action.

## English

- Sentence case for labels, buttons and titles ("Add account", not "Add Account").
- Contractions are fine ("Couldn't", "doesn't"). Short messages and labels have no final period; full-sentence hints do.
- Plain verbs: "turn on", "copy", "try again"; not "enable the flag", "fork", "retry the request".

## Codes, identifiers and data

- **Codes never reach a default view.** Map run states, fidelity tiers, kinds and reasons through a label function (`trainingMarketTypeLabel`, `translateMarketType`, …). An unknown value gets a neutral label ("Other"); the raw code goes in technical details.
- **Errors** go through `describeError` (`src/i18n/serverErrors.ts`): a translated summary chosen by code, HTTP status or known message, with the backend's own words as detail. Frequent codes get a message of their own (`CODE_KEYS`).
- **Exchanges and markets** use `translateExchangeName` and `translateMarketType`, never the wire value (`binance spot`).
- **Times** use the locale formatters (`formatDateTime`, `getDateTimeLocale()`); mark UTC when it is UTC. Never epoch milliseconds or ISO strings, in a value or in a field: a time a person enters uses `DateTimeInput`.
- **Numbers** use the locale's grouping; prices keep the exchange's precision.
- Not translated: symbols, intervals, indicator tickers, plugin and exchange ids (see `src/i18n/README.md`).
- **Identifiers a person must type** (an environment variable to set, a file format's field names and values) stay exact: pass them into the message as placeholders, so the sentence is translated and the identifier is not.

## Glossary

Internal term → what users see. "Technical details only" terms may appear inside a technical-details disclosure, never in a default view.

| Internal term | 中文 | English | Notes |
|---|---|---|---|
| status codes (`ONE_WAY`, `COMPLETED`, `BAR_APPROX`, …) | the state's name (单向持仓, 已完成, 按 K 线估算) | the state's name (One-way, Completed, Bar estimate) | via a label function |
| backend (后端) | 本地服务, or CandleScope | local service, or CandleScope | the app runs it for you |
| Run (replay) | 训练 | run | |
| Run, BacktestRun (research) | 运行 | run | |
| Study, BacktestStudy | 参数研究 | parameter study | |
| Host, 宿主 (matching, accounts) | CandleScope, 撮合 | CandleScope, matching | |
| authority, authoritative (权威) | 服务端 | server | "reset from authority" → 恢复为服务端设置 / Reset to server settings |
| frozen, immutable (冻结, 不可变) | 固定, 保存 | saved, fixed; lock (a version) | |
| bridge (replay review) | 复盘连接 | review link | |
| blinded / reveal | 隐藏结果 / 公开 | results hidden / show | |
| holdout | 留出数据 | held-out data | |
| trace | 记录 | log | |
| projection (投影) | — | — | drop it: "report and chart" |
| warmup | 预热 | warm-up | |
| BAR (execution mode) | K 线 | bar | |
| V1 / V2 account model | 标准账户 / 历史永续账户 | standard account / historical perpetual account | |
| profile (offline) | 模式 | mode | |
| provider (evidence source) | 数据源 | source | |
| clone | 复制 | copy | |
| fork | 分叉 | fork | |
| revision | 版本 | version | |
| smoke run | 快速试运行 | quick test run | |
| Study V2 | 参数研究 | parameter study | |
| sandboxed / trusted local (Python) | 沙箱运行 / 本机直接运行 | sandboxed / directly on this computer | |
| epoch, dataEpoch | 数据版本 | data version | |
| receipt | 记录 | record | |
| bundle | 策略包 | package | |
| payload | 内容 | content | |
| hash, checksum | 校验值 | fingerprint | technical details only |
| dry-run | 预演 | preview | |
| GC | 清理 | cleanup | |
| VACUUM | 压缩数据库 | compact the database | |
| SQLite, WAL | 本地数据库 | local database | |
| fidelity | 撮合精度 / 数据精度 | fill accuracy / data accuracy | |
| exact (tier) | 精确 | exact | |
| fail-closed | 无法确认时停止 | stops when it can't confirm | |
| pinned | 固定的 | fixed | |
| overlay (leverage) | 你设的上限 | your limit | |
| ledger | 账本 / 流水 | ledger | |
| lane, slot | 名额 | slot | |
| evaluator | 判断逻辑 | logic | |
| blob, canvas | 图片 | image | |
| Top-N | 前 N 档 | top levels | |
| feature flag | 本地服务的设置 | setting of the local service | say where to turn it on |
| ticker | 价格 | price | |
| native / custom intervals | 交易所周期 / 自定义周期 | exchange intervals / custom intervals | |
| closed bars | 已收盘 K 线 | closed bars | |
| queue exact, raw trade | 排队位置, 逐笔成交 | queue position, individual trades | |
| keep alive (保活) | 持续更新 | keep updated | |
| dead letter (死信) | 发送失败 | failed | |
| rehydrate (水化) | 重新载入 | reload | |
| class and service names (`IndicatorEngine`, `TradeFlow`, `DataManager`, `WorkspaceBus`) | CandleScope, or the feature's name (实时成交, 本地服务) | CandleScope, or the feature's name (live trades, local service) | |
| project phases, versions of internal contracts (Phase 11, Study V2) | — | — | drop them |

## Checks

`npm run check:i18n` (part of `npm run check`) enforces the catalogs: every key in every locale, matching placeholders, no Chinese in English, Traditional Chinese without Simplified remnants, and **no internal terms** in `zh-CN` and `en` (`scripts/i18nInternalTerms.mts` holds the term list above).

While Phase 6 rewrites the remaining surfaces, the messages that still use internal terms are listed in `scripts/i18n-internal-terms-baseline.json`. A new internal term fails the check; so does a listed message that no longer needs its entry. After rewriting a surface, run `npx tsx scripts/check-i18n.mts --write-internal-terms-baseline` and check that the diff only removes lines.

When a message's meaning changes in `zh-CN` and `en`, update the same key in every catalog in the same change, so all languages say the same thing. When only a term changes (an English word inside Chinese, a code dropped from a label), fix every catalog that shows that term; languages that already use their own word can stay as they are.
