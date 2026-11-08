export const researchReturnEnglish = {
  "researchReturn.select": "Return this selected version to a chart",
  "researchReturn.loading": "Reading selected version…",
  "researchReturn.title": "Apply selected research version",
  "researchReturn.help": "Create an independent chart draft with the selected code, parameters, market, range and execution settings. The target chart is unlinked from its group. Existing runs continue unchanged. Choose History → Live and initialize a new run after reviewing Python permissions; research balances, positions and trades are not copied.",
  "researchReturn.workspace": "Target workspace", "researchReturn.target": "Target chart", "researchReturn.origin": "Original chart",
  "researchReturn.version": "Selected run: {run} · Strategy version: {revision}",
  "researchReturn.apply": "Create independent chart draft",
  "researchReturn.unsupported": "This version cannot be applied to the current chart continuation profile ({field}). Supported: editor Python, native crypto 1m BAR, V1 account at leverage 1, equity-percent sizing, equal maker/taker fees and standard execution settings. The research version is retained.",
  "researchReturn.changed": "The target chart or workspace changed while saving. Select the target again and retry. Existing runs and drafts are retained.",
} as const;
export const researchReturnChinese: Record<keyof typeof researchReturnEnglish, string> = {
  "researchReturn.select": "将当前选定版本挂回图表", "researchReturn.loading": "正在读取选定版本…",
  "researchReturn.title": "应用选定研究版本",
  "researchReturn.help": "以选定源码、参数、品种周期、区间和执行设置创建独立图表草稿，并解除目标图表的分组联动。已有运行继续保持原版本。请查看 Python 权限后，选择“历史接实时”并初始化新运行；不复制研究账户的余额、持仓和成交。",
  "researchReturn.workspace": "目标工作区", "researchReturn.target": "目标图表", "researchReturn.origin": "原图表",
  "researchReturn.version": "选定运行：{run} · 策略版本：{revision}", "researchReturn.apply": "创建独立图表草稿",
  "researchReturn.unsupported": "该版本无法应用到当前图表连续执行规格（{field}）。目前支持编辑器 Python、原生加密市场 1 分钟 BAR、1 倍杠杆 V1 账户、权益比例下单、相同挂单/吃单费率与标准执行设置；研究版本仍保留。",
  "researchReturn.changed": "保存期间目标图表或工作区发生了变化，请重新选择目标后再试。已有运行与草稿仍保留。",
};
export const researchReturnJapanese: Record<keyof typeof researchReturnEnglish, string> = {
  "researchReturn.select": "選択したバージョンをチャートへ戻す", "researchReturn.loading": "選択したバージョンを読み込み中…",
  "researchReturn.title": "選択した研究バージョンを適用",
  "researchReturn.help": "選択したコード、パラメータ、市場、期間、執行設定で独立したチャート下書きを作成し、対象チャートのグループ連動を解除します。既存の実行は元のバージョンで継続します。Python の権限を確認し、「履歴からリアルタイム」を選んで新しい実行を初期化してください。研究口座の残高、建玉、約定はコピーしません。",
  "researchReturn.workspace": "対象ワークスペース", "researchReturn.target": "対象チャート", "researchReturn.origin": "元のチャート",
  "researchReturn.version": "選択した実行：{run} · 戦略バージョン：{revision}", "researchReturn.apply": "独立したチャート下書きを作成",
  "researchReturn.unsupported": "このバージョンは現在のチャート継続実行条件では適用できません（{field}）。対応範囲はエディタの Python、暗号資産のネイティブ1分足 BAR、レバレッジ1倍の V1 口座、純資産比率による注文、同率のメイカー・テイカー手数料、標準執行設定です。研究バージョンは保持されます。",
  "researchReturn.changed": "保存中に対象チャートまたはワークスペースが変更されました。対象を選び直して再試行してください。既存の実行と下書きは保持されます。",
};
export const researchReturnKorean: Record<keyof typeof researchReturnEnglish, string> = {
  "researchReturn.select": "선택한 버전을 차트에 적용", "researchReturn.loading": "선택한 버전을 읽는 중…",
  "researchReturn.title": "선택한 연구 버전 적용",
  "researchReturn.help": "선택한 코드, 매개변수, 시장, 기간, 체결 설정으로 독립된 차트 초안을 만들고 대상 차트의 그룹 연동을 해제합니다. 기존 실행은 원래 버전으로 계속됩니다. Python 권한을 검토한 뒤 ‘과거에서 실시간으로’를 선택하고 새 실행을 초기화하세요. 연구 계좌의 잔액, 포지션, 체결은 복사하지 않습니다.",
  "researchReturn.workspace": "대상 작업 공간", "researchReturn.target": "대상 차트", "researchReturn.origin": "원래 차트",
  "researchReturn.version": "선택한 실행: {run} · 전략 버전: {revision}", "researchReturn.apply": "독립된 차트 초안 만들기",
  "researchReturn.unsupported": "이 버전은 현재 차트 연속 실행 조건에 적용할 수 없습니다({field}). 편집기 Python, 암호화폐 시장의 기본 1분 BAR, 레버리지 1배 V1 계좌, 자산 비율 주문, 동일한 메이커·테이커 수수료와 표준 체결 설정을 지원합니다. 연구 버전은 유지됩니다.",
  "researchReturn.changed": "저장 중 대상 차트나 작업 공간이 변경되었습니다. 대상을 다시 선택하고 재시도하세요. 기존 실행과 초안은 유지됩니다.",
};
export const researchReturnPortuguese: Record<keyof typeof researchReturnEnglish, string> = {
  "researchReturn.select": "Aplicar a versão selecionada a um gráfico", "researchReturn.loading": "Lendo a versão selecionada…",
  "researchReturn.title": "Aplicar versão de pesquisa selecionada",
  "researchReturn.help": "Cria um rascunho de gráfico independente com código, parâmetros, mercado, período e configurações de execução selecionados, removendo a vinculação do gráfico ao grupo. As execuções existentes continuam com a versão original. Revise as permissões do Python, escolha histórico com continuação ao vivo e inicialize uma nova execução. Saldo, posições e negócios da conta de pesquisa não são copiados.",
  "researchReturn.workspace": "Área de trabalho de destino", "researchReturn.target": "Gráfico de destino", "researchReturn.origin": "Gráfico original",
  "researchReturn.version": "Execução selecionada: {run} · Versão da estratégia: {revision}", "researchReturn.apply": "Criar rascunho de gráfico independente",
  "researchReturn.unsupported": "Esta versão não pode ser aplicada às condições atuais de execução contínua do gráfico ({field}). São aceitos Python do editor, barras nativas de cripto de 1 minuto, conta V1 com alavancagem 1, ordens por proporção do patrimônio, taxas iguais para ordens passivas e agressoras e configurações de execução padrão. A versão de pesquisa é mantida.",
  "researchReturn.changed": "O gráfico ou a área de trabalho de destino mudou durante o salvamento. Selecione o destino e tente novamente. As execuções e os rascunhos existentes são mantidos.",
};
