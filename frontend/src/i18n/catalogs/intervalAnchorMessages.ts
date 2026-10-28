export const intervalAnchorEn = {
  "interval.anchorEnabled": "Use an event anchor",
  "interval.anchorTime": "Anchor time (UTC, whole minutes)",
  "interval.anchorHelp": "Buckets extend before and after this time. Use minute-multiple fixed periods; seconds, calendar weeks and months are not supported. ↔ +Nm shows the offset from the default grid.",
  "interval.anchorInvalid": "Enter a whole-minute UTC time and a fixed period divisible by one minute. Seconds are not rounded.",
} as const;

export const intervalAnchorZh = {
  "interval.anchorEnabled": "手动设置事件锚点",
  "interval.anchorTime": "锚点时间（UTC，整分钟）",
  "interval.anchorHelp": "K 线从锚点向前、向后连续延伸。支持整分钟倍数的固定周期，不支持秒级锚点、日历周和月。↔ +Nm 表示相对默认分桶的偏移。",
  "interval.anchorInvalid": "请填写整分钟的 UTC 时间，并选择整分钟倍数的固定周期；秒级时间不会自动取整。",
} as const;

export const intervalAnchorZhHant = {
  "interval.anchorEnabled": "手動設定事件錨點",
  "interval.anchorTime": "錨點時間（UTC，整分鐘）",
  "interval.anchorHelp": "K 線從錨點向前、向後連續延伸。支援整分鐘倍數的固定週期，不支援秒級錨點、日曆週和月。↔ +Nm 表示相對預設分桶的偏移。",
  "interval.anchorInvalid": "請填寫整分鐘的 UTC 時間，並選擇整分鐘倍數的固定週期；秒級時間不會自動取整。",
} as const;

export const intervalAnchorPtBR = {
  "interval.anchorEnabled": "Definir uma âncora de evento",
  "interval.anchorTime": "Horário da âncora (UTC, minutos inteiros)",
  "interval.anchorHelp": "Os candles se estendem antes e depois desse horário. Escolha períodos fixos em múltiplos de um minuto; segundos, semanas e meses de calendário não são aceitos. ↔ indica, em minutos, o deslocamento da grade padrão.",
  "interval.anchorInvalid": "Informe um horário UTC em minutos inteiros e um período fixo múltiplo de um minuto. Os segundos não são arredondados.",
} as const;

export const intervalAnchorKo = {
  "interval.anchorEnabled": "이벤트 기준 시각 설정",
  "interval.anchorTime": "기준 시각 (UTC, 분 단위)",
  "interval.anchorHelp": "캔들은 기준 시각의 앞뒤로 이어집니다. 1분 배수인 고정 주기만 지원하며 초 단위 기준 시각과 달력 기준 주·월은 지원하지 않습니다. ↔ +Nm은 기본 구간 대비 오프셋입니다.",
  "interval.anchorInvalid": "초가 없는 UTC 시각과 1분 배수인 고정 주기를 입력하세요. 초 단위 시각은 반올림하지 않습니다.",
} as const;
