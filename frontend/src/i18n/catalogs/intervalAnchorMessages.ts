// Calendar boundaries affect candle contents, independently of display time zones.
const texts = {
  "en": [
    "Use an event anchor",
    "Anchor time (UTC, whole minutes)",
    "Buckets extend both ways. Fixed minute-multiple periods only; seconds are not rounded. ↔ shows the grid offset.",
    "Enter a whole-minute UTC time and a fixed minute-multiple period.",
    "Use local calendar boundaries",
    "Calendar time zone",
    "Days, weeks and months start at local midnight; 12M is a calendar year. DST changes the actual duration. Available for 1970–2399.",
    "Choose 1–366 days, 1–52 weeks or 1–12 months."
  ],
  "zh-CN": [
    "手动设置事件锚点",
    "锚点时间（UTC，整分钟）",
    "K 线从锚点向前、向后连续延伸。仅支持整分钟倍数的固定周期；秒级时间不会自动取整。↔ 表示分桶偏移。",
    "请填写整分钟的 UTC 时间，并选择整分钟倍数的固定周期。",
    "按时区日历分桶",
    "分桶时区",
    "日、周、月从当地零点开始；12M 为自然年。夏令时会改变实际时长。支持 1970–2399 年。",
    "请选择 1–366 日、1–52 周或 1–12 月。"
  ],
  "zh-Hant": [
    "手動設定事件錨點",
    "錨點時間（UTC，整分鐘）",
    "K 線從錨點向前、向後連續延伸。僅支援整分鐘倍數的固定週期；秒級時間不會自動取整。↔ 表示分桶偏移。",
    "請填寫整分鐘的 UTC 時間，並選擇整分鐘倍數的固定週期。",
    "按時區日曆分桶",
    "分桶時區",
    "日、週、月從當地零點開始；12M 為曆年。夏令時間會改變實際時長。支援 1970–2399 年。",
    "請選擇 1–366 日、1–52 週或 1–12 月。"
  ],
  "ja": [
    "イベント基準時刻を設定",
    "基準時刻（UTC、分単位）",
    "足は基準時刻の前後に続きます。分の整数倍の固定周期のみ対応。秒は丸めません。↔ は区切りの差です。",
    "分単位の UTC 時刻と、分の整数倍の固定周期を入力してください。",
    "現地の暦で区切る",
    "区切りのタイムゾーン",
    "日・週・月は現地の午前0時から開始。12M は暦年です。夏時間により長さが変わります。1970～2399年に対応。",
    "1～366日、1～52週、1～12か月を選択してください。"
  ],
  "ko": [
    "이벤트 기준 시각 설정",
    "기준 시각 (UTC, 분 단위)",
    "캔들은 기준 시각의 앞뒤로 이어집니다. 1분 배수의 고정 주기만 지원하며 초는 반올림하지 않습니다. ↔는 구간 오프셋입니다.",
    "분 단위 UTC 시각과 1분 배수의 고정 주기를 입력하세요.",
    "현지 달력 기준 구간",
    "구간 시간대",
    "일·주·월은 현지 자정부터 시작하며 12M은 달력 연도입니다. 서머타임에 따라 길이가 변합니다. 1970~2399년 지원.",
    "1~366일, 1~52주 또는 1~12개월을 선택하세요."
  ],
  "de": [
    "Ereignisanker verwenden",
    "Ankerzeit (UTC, ganze Minuten)",
    "Kerzen reichen in beide Richtungen. Nur feste Vielfache einer Minute; Sekunden werden nicht gerundet. ↔ zeigt den Versatz.",
    "UTC-Zeit in ganzen Minuten und ein festes Minutenvielfaches eingeben.",
    "Lokale Kalendergrenzen verwenden",
    "Kalenderzeitzone",
    "Tage, Wochen und Monate beginnen um Mitternacht; 12M ist ein Kalenderjahr. Sommerzeit verändert die Dauer. Gültig für 1970–2399.",
    "1–366 Tage, 1–52 Wochen oder 1–12 Monate wählen."
  ],
  "fr": [
    "Utiliser une ancre événementielle",
    "Heure de référence (UTC, minutes entières)",
    "Les bougies se prolongent dans les deux sens. Périodes fixes multiples de la minute uniquement ; les secondes ne sont pas arrondies. ↔ indique le décalage.",
    "Saisissez une heure UTC à la minute et une période fixe multiple de la minute.",
    "Utiliser le calendrier local",
    "Fuseau du calendrier",
    "Les jours, semaines et mois commencent à minuit local ; 12M représente une année civile. Le changement d’heure modifie la durée. De 1970 à 2399.",
    "Choisissez 1–366 jours, 1–52 semaines ou 1–12 mois."
  ],
  "es": [
    "Usar un ancla de evento",
    "Hora del ancla (UTC, minutos enteros)",
    "Las velas se extienden en ambas direcciones. Solo períodos fijos múltiplos de un minuto; los segundos no se redondean. ↔ indica el desfase.",
    "Introduce una hora UTC en minutos enteros y un período fijo múltiplo de un minuto.",
    "Usar límites del calendario local",
    "Zona horaria del calendario",
    "Días, semanas y meses comienzan a medianoche local; 12M es un año natural. El cambio de hora modifica la duración. Disponible para 1970–2399.",
    "Elige 1–366 días, 1–52 semanas o 1–12 meses."
  ],
  "pt-BR": [
    "Definir uma âncora de evento",
    "Horário da âncora (UTC, minutos inteiros)",
    "Os candles se estendem nos dois sentidos. Apenas períodos fixos múltiplos de um minuto; segundos não são arredondados. ↔ indica o deslocamento.",
    "Informe um horário UTC em minutos inteiros e um período fixo múltiplo de um minuto.",
    "Usar limites do calendário local",
    "Fuso do calendário",
    "Dias, semanas e meses começam à meia-noite local; 12M é um ano civil. O horário de verão altera a duração. Disponível para 1970–2399.",
    "Escolha 1–366 dias, 1–52 semanas ou 1–12 meses."
  ],
  "pt-PT": [
    "Definir uma âncora de evento",
    "Hora da âncora (UTC, minutos inteiros)",
    "As velas estendem-se nos dois sentidos. Apenas períodos fixos múltiplos de um minuto; os segundos não são arredondados. ↔ indica o desvio.",
    "Introduza uma hora UTC em minutos inteiros e um período fixo múltiplo de um minuto.",
    "Usar limites do calendário local",
    "Fuso do calendário",
    "Dias, semanas e meses começam à meia-noite local; 12M é um ano civil. A hora de verão altera a duração. Disponível para 1970–2399.",
    "Escolha 1–366 dias, 1–52 semanas ou 1–12 meses."
  ],
  "it": [
    "Usa un riferimento evento",
    "Ora di riferimento (UTC, minuti interi)",
    "Le candele si estendono in entrambe le direzioni. Solo periodi fissi multipli di un minuto; i secondi non vengono arrotondati. ↔ indica lo scarto.",
    "Inserisci un’ora UTC in minuti interi e un periodo fisso multiplo di un minuto.",
    "Usa i limiti del calendario locale",
    "Fuso del calendario",
    "Giorni, settimane e mesi iniziano a mezzanotte locale; 12M è un anno solare. L’ora legale modifica la durata. Disponibile per il 1970–2399.",
    "Scegli 1–366 giorni, 1–52 settimane o 1–12 mesi."
  ],
  "nl": [
    "Gebeurtenisanker gebruiken",
    "Ankertijd (UTC, hele minuten)",
    "Kaarsen lopen in beide richtingen door. Alleen vaste veelvouden van een minuut; seconden worden niet afgerond. ↔ toont de verschuiving.",
    "Voer een UTC-tijd in hele minuten en een vaste periode in minuten in.",
    "Lokale kalendergrenzen gebruiken",
    "Kalendertijdzone",
    "Dagen, weken en maanden beginnen om lokale middernacht; 12M is een kalenderjaar. Zomertijd verandert de duur. Beschikbaar voor 1970–2399.",
    "Kies 1–366 dagen, 1–52 weken of 1–12 maanden."
  ],
  "sv": [
    "Använd ett händelseankare",
    "Ankartid (UTC, hela minuter)",
    "Staplarna sträcker sig åt båda håll. Endast fasta perioder i hela minuter; sekunder avrundas inte. ↔ visar förskjutningen.",
    "Ange en UTC-tid i hela minuter och en fast period i hela minuter.",
    "Använd lokala kalendergränser",
    "Kalenderns tidszon",
    "Dagar, veckor och månader börjar vid lokal midnatt; 12M är ett kalenderår. Sommartid ändrar längden. Gäller 1970–2399.",
    "Välj 1–366 dagar, 1–52 veckor eller 1–12 månader."
  ],
  "pl": [
    "Użyj kotwicy zdarzenia",
    "Czas kotwicy (UTC, pełne minuty)",
    "Świece rozciągają się w obu kierunkach. Tylko stałe okresy będące wielokrotnością minuty; sekundy nie są zaokrąglane. ↔ oznacza przesunięcie.",
    "Podaj czas UTC w pełnych minutach i stały okres będący wielokrotnością minuty.",
    "Użyj lokalnych granic kalendarza",
    "Strefa czasowa kalendarza",
    "Dni, tygodnie i miesiące zaczynają się o lokalnej północy; 12M to rok kalendarzowy. Zmiana czasu wpływa na długość. Zakres: 1970–2399.",
    "Wybierz 1–366 dni, 1–52 tygodnie lub 1–12 miesięcy."
  ],
  "cs": [
    "Použít kotvu události",
    "Čas kotvy (UTC, celé minuty)",
    "Svíčky pokračují oběma směry. Pouze pevné násobky minuty; sekundy se nezaokrouhlují. ↔ označuje posun.",
    "Zadejte čas UTC v celých minutách a pevný násobek minuty.",
    "Použít místní kalendářní hranice",
    "Časové pásmo kalendáře",
    "Dny, týdny a měsíce začínají o místní půlnoci; 12M je kalendářní rok. Letní čas mění délku. Rozsah 1970–2399.",
    "Vyberte 1–366 dní, 1–52 týdnů nebo 1–12 měsíců."
  ],
  "hu": [
    "Eseményhorgony használata",
    "Horgony ideje (UTC, egész percek)",
    "A gyertyák mindkét irányba folytatódnak. Csak egész perces rögzített időközök; a másodperceket nem kerekítjük. ↔ az eltolást jelzi.",
    "Adjon meg egész perces UTC-időt és egész perces rögzített időközt.",
    "Helyi naptári határok használata",
    "Naptár időzónája",
    "A napok, hetek és hónapok helyi éjfélkor kezdődnek; 12M egy naptári év. A nyári időszámítás módosítja a hosszt. 1970–2399 között elérhető.",
    "Válasszon 1–366 napot, 1–52 hetet vagy 1–12 hónapot."
  ],
  "ro": [
    "Folosește o ancoră de eveniment",
    "Ora ancorei (UTC, minute întregi)",
    "Lumânările se extind în ambele sensuri. Doar perioade fixe în multipli de un minut; secundele nu se rotunjesc. ↔ indică decalajul.",
    "Introdu o oră UTC în minute întregi și o perioadă fixă multiplu de un minut.",
    "Folosește limite calendaristice locale",
    "Fusul calendarului",
    "Zilele, săptămânile și lunile încep la miezul nopții locale; 12M este un an calendaristic. Ora de vară modifică durata. Disponibil pentru 1970–2399.",
    "Alege 1–366 zile, 1–52 săptămâni sau 1–12 luni."
  ],
  "ru": [
    "Использовать привязку к событию",
    "Время привязки (UTC, целые минуты)",
    "Свечи продолжаются в обе стороны. Только фиксированные периоды, кратные минуте; секунды не округляются. ↔ показывает смещение.",
    "Введите время UTC в целых минутах и фиксированный период, кратный минуте.",
    "Использовать местный календарь",
    "Часовой пояс календаря",
    "Дни, недели и месяцы начинаются в местную полночь; 12M — календарный год. Перевод часов меняет длительность. Диапазон: 1970–2399.",
    "Выберите 1–366 дней, 1–52 недели или 1–12 месяцев."
  ],
  "uk": [
    "Використовувати прив’язку до події",
    "Час прив’язки (UTC, цілі хвилини)",
    "Свічки продовжуються в обидва боки. Лише фіксовані періоди, кратні хвилині; секунди не округлюються. ↔ показує зсув.",
    "Введіть час UTC у цілих хвилинах і фіксований період, кратний хвилині.",
    "Використовувати місцевий календар",
    "Часовий пояс календаря",
    "Дні, тижні та місяці починаються опівночі за місцевим часом; 12M — календарний рік. Переведення годинника змінює тривалість. Діапазон: 1970–2399.",
    "Виберіть 1–366 днів, 1–52 тижні або 1–12 місяців."
  ],
  "tr": [
    "Olay çapası kullan",
    "Çapa zamanı (UTC, tam dakika)",
    "Mumlar her iki yönde uzanır. Yalnızca dakikanın katı olan sabit dönemler; saniyeler yuvarlanmaz. ↔ kaymayı gösterir.",
    "Tam dakikalı UTC zamanı ve dakikanın katı olan sabit bir dönem girin.",
    "Yerel takvim sınırlarını kullan",
    "Takvim saat dilimi",
    "Gün, hafta ve aylar yerel gece yarısında başlar; 12M bir takvim yılıdır. Yaz saati süreyi değiştirir. 1970–2399 için kullanılabilir.",
    "1–366 gün, 1–52 hafta veya 1–12 ay seçin."
  ],
  "id": [
    "Gunakan jangkar peristiwa",
    "Waktu jangkar (UTC, menit penuh)",
    "Candle berlanjut ke kedua arah. Hanya periode tetap kelipatan satu menit; detik tidak dibulatkan. ↔ menunjukkan pergeseran.",
    "Masukkan waktu UTC dalam menit penuh dan periode tetap kelipatan satu menit.",
    "Gunakan batas kalender lokal",
    "Zona waktu kalender",
    "Hari, minggu, dan bulan dimulai tengah malam setempat; 12M adalah tahun kalender. DST mengubah durasi. Tersedia untuk 1970–2399.",
    "Pilih 1–366 hari, 1–52 minggu, atau 1–12 bulan."
  ],
  "ms": [
    "Gunakan sauh peristiwa",
    "Masa sauh (UTC, minit penuh)",
    "Lilin bersambung ke kedua-dua arah. Hanya tempoh tetap gandaan satu minit; saat tidak dibundarkan. ↔ menunjukkan anjakan.",
    "Masukkan masa UTC dalam minit penuh dan tempoh tetap gandaan satu minit.",
    "Gunakan sempadan kalendar tempatan",
    "Zon waktu kalendar",
    "Hari, minggu dan bulan bermula pada tengah malam tempatan; 12M ialah tahun kalendar. Waktu musim panas mengubah tempoh. Tersedia untuk 1970–2399.",
    "Pilih 1–366 hari, 1–52 minggu atau 1–12 bulan."
  ],
  "vi": [
    "Dùng mốc sự kiện",
    "Thời gian mốc (UTC, phút tròn)",
    "Nến kéo dài về cả hai phía. Chỉ hỗ trợ chu kỳ cố định là bội số của phút; không làm tròn giây. ↔ chỉ độ lệch.",
    "Nhập thời gian UTC tròn phút và chu kỳ cố định là bội số của phút.",
    "Dùng ranh giới lịch địa phương",
    "Múi giờ phân kỳ",
    "Ngày, tuần và tháng bắt đầu lúc nửa đêm địa phương; 12M là năm dương lịch. Giờ mùa hè làm thay đổi độ dài. Hỗ trợ 1970–2399.",
    "Chọn 1–366 ngày, 1–52 tuần hoặc 1–12 tháng."
  ],
  "th": [
    "ใช้จุดอ้างอิงเหตุการณ์",
    "เวลาอ้างอิง (UTC ระดับนาทีเต็ม)",
    "แท่งเทียนต่อเนื่องทั้งก่อนและหลังจุดอ้างอิง รองรับเฉพาะช่วงคงที่ที่เป็นจำนวนเท่าของนาที ไม่ปัดเศษวินาที ↔ แสดงระยะเลื่อน",
    "ป้อนเวลา UTC เป็นนาทีเต็มและช่วงคงที่ที่เป็นจำนวนเท่าของนาที",
    "ใช้ขอบเขตปฏิทินท้องถิ่น",
    "เขตเวลาของปฏิทิน",
    "วัน สัปดาห์ และเดือนเริ่มที่เที่ยงคืนท้องถิ่น 12M คือปีปฏิทิน เวลาออมแสงทำให้ระยะเวลาเปลี่ยน รองรับปี ค.ศ. 1970–2399",
    "เลือก 1–366 วัน 1–52 สัปดาห์ หรือ 1–12 เดือน"
  ],
  "hi": [
    "घटना का आधार समय चुनें",
    "आधार समय (UTC, पूरे मिनट)",
    "कैंडल दोनों दिशाओं में बढ़ती हैं। केवल मिनट के गुणज वाले स्थिर अंतराल; सेकंड पूर्णांकित नहीं होते। ↔ खिसकाव दिखाता है।",
    "पूरे मिनट में UTC समय और मिनट के गुणज वाला स्थिर अंतराल दर्ज करें।",
    "स्थानीय कैलेंडर की सीमाएँ उपयोग करें",
    "कैलेंडर का समय क्षेत्र",
    "दिन, सप्ताह और महीने स्थानीय मध्यरात्रि से शुरू होते हैं; 12M एक कैलेंडर वर्ष है। डेलाइट सेविंग से अवधि बदलती है। 1970–2399 के लिए उपलब्ध।",
    "1–366 दिन, 1–52 सप्ताह या 1–12 महीने चुनें।"
  ],
  "ar": [
    "استخدام مرساة حدث",
    "وقت المرساة (UTC، دقائق كاملة)",
    "تمتد الشموع في الاتجاهين. فترات ثابتة من مضاعفات الدقيقة فقط؛ لا تُقرّب الثواني. ↔ يوضح الإزاحة.",
    "أدخل وقت UTC بدقائق كاملة وفترة ثابتة من مضاعفات الدقيقة.",
    "استخدام حدود التقويم المحلي",
    "المنطقة الزمنية للتقويم",
    "تبدأ الأيام والأسابيع والأشهر عند منتصف الليل المحلي؛ 12M سنة تقويمية. يغيّر التوقيت الصيفي المدة. متاح للأعوام 1970–2399.",
    "اختر 1–366 يومًا أو 1–52 أسبوعًا أو 1–12 شهرًا."
  ],
  "he": [
    "שימוש בעוגן אירוע",
    "זמן העוגן (UTC, דקות שלמות)",
    "הנרות נמשכים לשני הכיוונים. רק פרקי זמן קבועים בכפולות של דקה; שניות אינן מעוגלות. ↔ מציין את ההיסט.",
    "יש להזין זמן UTC בדקות שלמות ופרק זמן קבוע בכפולות של דקה.",
    "שימוש בגבולות לוח השנה המקומי",
    "אזור הזמן של לוח השנה",
    "ימים, שבועות וחודשים מתחילים בחצות המקומי; 12M הוא שנה קלנדרית. שעון קיץ משנה את משך הזמן. זמין לשנים 1970–2399.",
    "יש לבחור 1–366 ימים, 1–52 שבועות או 1–12 חודשים."
  ]
} as const;

function messages(values: readonly string[]) {
  return {
    "interval.anchorEnabled": values[0]!,
    "interval.anchorTime": values[1]!,
    "interval.anchorHelp": values[2]!,
    "interval.anchorInvalid": values[3]!,
    "interval.calendarEnabled": values[4]!,
    "interval.calendarZone": values[5]!,
    "interval.calendarHelp": values[6]!,
    "interval.calendarInvalid": values[7]!,
  };
}

export const intervalBasisMessages = Object.fromEntries(Object.entries(texts).map(([locale, values]) => [locale, messages(values)])) as { [K in keyof typeof texts]: ReturnType<typeof messages> };
