export const readerEnglish = {
  "reader.title": "Saved continuous accounts", "reader.readonly": "Read-only accounts saved in this profile, independent of the chart and study cursor. Closing this view leaves backend execution running.",
  "reader.refresh": "Refresh account list", "reader.loading": "Loading saved accounts…", "reader.empty": "No saved continuous accounts in this profile.",
  "reader.select": "Saved account", "reader.identity": "Account: {id}", "reader.partial": "Initialization is incomplete. This is the committed partial account.",
} as const;
export const readerChinese: Record<keyof typeof readerEnglish, string> = {
  "reader.title": "保存的常驻账户", "reader.readonly": "仅查看本配置保存的账户，独立于图表和研究游标。关闭此视图不会停止后台运行。",
  "reader.refresh": "刷新账户列表", "reader.loading": "正在读取保存账户…", "reader.empty": "本配置暂无保存的常驻账户。",
  "reader.select": "保存账户", "reader.identity": "账户：{id}", "reader.partial": "初始计算尚未完成；这里显示已提交的部分账户结果。",
};
export const readerJapanese: Record<keyof typeof readerEnglish, string> = {
  "reader.title": "保存済み継続口座", "reader.readonly": "このプロファイルの保存済み口座を読み取り専用で表示します。チャートや研究カーソルとは独立し、画面を閉じてもバックエンドの実行は続きます。",
  "reader.refresh": "口座一覧を更新", "reader.loading": "保存済み口座を読み込み中…", "reader.empty": "このプロファイルに保存済み継続口座はありません。",
  "reader.select": "保存済み口座", "reader.identity": "口座：{id}", "reader.partial": "初期計算は未完了です。確定済みの途中結果を表示しています。",
};
export const readerKorean: Record<keyof typeof readerEnglish, string> = {
  "reader.title": "저장된 연속 계좌", "reader.readonly": "이 프로필의 저장된 계좌를 읽기 전용으로 표시합니다. 차트와 연구 커서와 독립적이며 화면을 닫아도 백엔드 실행은 계속됩니다.",
  "reader.refresh": "계좌 목록 새로 고침", "reader.loading": "저장된 계좌를 읽는 중…", "reader.empty": "이 프로필에 저장된 연속 계좌가 없습니다.",
  "reader.select": "저장된 계좌", "reader.identity": "계좌: {id}", "reader.partial": "초기 계산이 완료되지 않았으며 확정된 부분 계좌 결과를 표시합니다.",
};
export const readerPortuguese: Record<keyof typeof readerEnglish, string> = {
  "reader.title": "Contas contínuas salvas", "reader.readonly": "Contas salvas neste perfil em modo de leitura, independentes do gráfico e do cursor de estudo. Fechar esta tela mantém a execução no backend.",
  "reader.refresh": "Atualizar lista de contas", "reader.loading": "Carregando contas salvas…", "reader.empty": "Nenhuma conta contínua salva neste perfil.",
  "reader.select": "Conta salva", "reader.identity": "Conta: {id}", "reader.partial": "A inicialização está incompleta. Esta é a conta parcial confirmada.",
};
