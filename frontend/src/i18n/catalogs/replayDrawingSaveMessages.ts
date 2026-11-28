/** Replay training: drawings the run record refused and left out of the save, for every registered locale. */
const english = {
  "replay.drawings.notSaved": "Not saved in this replay's record: {drawings}. Your other drawings are saved. Edit or delete these to try again; they disappear when you reload.",
  "replay.drawings.notSavedUnsupported": "The replay record does not accept this drawing type or one of its options.",
  "replay.drawings.notSavedInvalid": "The drawing data is not valid.",
} as const;

type ReplayDrawingSaveMessages = Readonly<Record<keyof typeof english, string>>;

const traditional: ReplayDrawingSaveMessages = {
  "replay.drawings.notSaved": "未儲存到本次回放記錄：{drawings}。其他繪圖已正常儲存。編輯或刪除這些繪圖即可重試；重新整理頁面後它們會消失。",
  "replay.drawings.notSavedUnsupported": "回放記錄不支援這種繪圖類型或其中某個選項。",
  "replay.drawings.notSavedInvalid": "繪圖資料無效。",
};

type CatalogLocale = "en" | "zh-CN" | "zh-TW" | "zh-Hant" | "zh-HK" | "zh-MO" | "ja" | "ko" | "ar" | "cs"
  | "de" | "es" | "fr" | "he" | "hi" | "hu" | "id" | "it" | "ms" | "nl" | "pl" | "pt-BR" | "pt-PT" | "ro"
  | "ru" | "sv" | "th" | "tr" | "uk" | "vi";

export const replayDrawingSaveMessages: Readonly<Record<CatalogLocale, ReplayDrawingSaveMessages>> = {
  en: english,
  "zh-CN": {
    "replay.drawings.notSaved": "未保存到本次回放记录：{drawings}。其他绘图已正常保存。编辑或删除这些绘图即可重试；刷新页面后它们会消失。",
    "replay.drawings.notSavedUnsupported": "回放记录不支持这种绘图类型或其中某个选项。",
    "replay.drawings.notSavedInvalid": "绘图数据无效。",
  },
  "zh-TW": traditional,
  "zh-Hant": traditional,
  "zh-HK": traditional,
  "zh-MO": traditional,
  ja: {
    "replay.drawings.notSaved": "このリプレイの記録に保存されませんでした：{drawings}。ほかの描画は保存されています。編集または削除すると再試行します。再読み込みするとこれらは消えます。",
    "replay.drawings.notSavedUnsupported": "リプレイの記録は、この描画の種類またはそのオプションのいずれかに対応していません。",
    "replay.drawings.notSavedInvalid": "描画データが無効です。",
  },
  ko: {
    "replay.drawings.notSaved": "이 리플레이 기록에 저장되지 않음: {drawings}. 다른 그리기는 저장되었습니다. 수정하거나 삭제하면 다시 시도하며, 새로 고치면 사라집니다.",
    "replay.drawings.notSavedUnsupported": "리플레이 기록은 이 그리기 유형이나 그 옵션 중 하나를 지원하지 않습니다.",
    "replay.drawings.notSavedInvalid": "그리기 데이터가 올바르지 않습니다.",
  },
  ar: {
    "replay.drawings.notSaved": "لم يُحفظ في سجل هذه الإعادة: {drawings}. حُفظت رسوماتك الأخرى. عدّل هذه الرسومات أو احذفها لإعادة المحاولة؛ وستختفي عند إعادة تحميل الصفحة.",
    "replay.drawings.notSavedUnsupported": "لا يقبل سجل الإعادة نوع الرسم هذا أو أحد خياراته.",
    "replay.drawings.notSavedInvalid": "بيانات الرسم غير صالحة.",
  },
  cs: {
    "replay.drawings.notSaved": "Neuloženo do záznamu tohoto přehrávání: {drawings}. Ostatní kresby jsou uložené. Úpravou nebo smazáním těchto kreseb to zkusíte znovu; po obnovení stránky zmizí.",
    "replay.drawings.notSavedUnsupported": "Záznam přehrávání nepřijímá tento typ kresby nebo některou z jejích voleb.",
    "replay.drawings.notSavedInvalid": "Data kresby nejsou platná.",
  },
  de: {
    "replay.drawings.notSaved": "Nicht im Protokoll dieses Replays gespeichert: {drawings}. Ihre anderen Zeichnungen sind gespeichert. Bearbeiten oder löschen Sie diese, um es erneut zu versuchen; beim Neuladen verschwinden sie.",
    "replay.drawings.notSavedUnsupported": "Das Replay-Protokoll akzeptiert diesen Zeichnungstyp oder eine seiner Optionen nicht.",
    "replay.drawings.notSavedInvalid": "Die Zeichnungsdaten sind ungültig.",
  },
  es: {
    "replay.drawings.notSaved": "No se guardó en el registro de esta repetición: {drawings}. Tus otros dibujos están guardados. Edítalos o elimínalos para volver a intentarlo; desaparecen al recargar.",
    "replay.drawings.notSavedUnsupported": "El registro de la repetición no admite este tipo de dibujo ni alguna de sus opciones.",
    "replay.drawings.notSavedInvalid": "Los datos del dibujo no son válidos.",
  },
  fr: {
    "replay.drawings.notSaved": "Non enregistré dans le journal de cette relecture : {drawings}. Vos autres dessins sont enregistrés. Modifiez-les ou supprimez-les pour réessayer ; ils disparaissent au rechargement.",
    "replay.drawings.notSavedUnsupported": "Le journal de relecture n’accepte pas ce type de dessin ou l’une de ses options.",
    "replay.drawings.notSavedInvalid": "Les données du dessin ne sont pas valides.",
  },
  he: {
    "replay.drawings.notSaved": "לא נשמר ברשומת ההפעלה החוזרת הזו: {drawings}. השרטוטים האחרים שלך נשמרו. ערכו או מחקו אותם כדי לנסות שוב; הם ייעלמו בטעינה מחדש.",
    "replay.drawings.notSavedUnsupported": "רשומת ההפעלה החוזרת אינה מקבלת את סוג השרטוט הזה או אחת מהאפשרויות שלו.",
    "replay.drawings.notSavedInvalid": "נתוני השרטוט אינם תקינים.",
  },
  hi: {
    "replay.drawings.notSaved": "इस रीप्ले के रिकॉर्ड में सहेजा नहीं गया: {drawings}। आपकी अन्य ड्रॉइंग सहेजी गई हैं। फिर से कोशिश करने के लिए इन्हें संपादित करें या हटाएँ; पेज फिर से लोड करने पर ये गायब हो जाएँगी।",
    "replay.drawings.notSavedUnsupported": "रीप्ले रिकॉर्ड इस ड्रॉइंग प्रकार या इसके किसी विकल्प को स्वीकार नहीं करता।",
    "replay.drawings.notSavedInvalid": "ड्रॉइंग डेटा मान्य नहीं है।",
  },
  hu: {
    "replay.drawings.notSaved": "Nem került mentésre ennek a visszajátszásnak a rekordjába: {drawings}. A többi rajz mentve van. Szerkessze vagy törölje ezeket az újrapróbálkozáshoz; újratöltéskor eltűnnek.",
    "replay.drawings.notSavedUnsupported": "A visszajátszási rekord nem fogadja el ezt a rajztípust vagy annak valamelyik beállítását.",
    "replay.drawings.notSavedInvalid": "A rajz adatai érvénytelenek.",
  },
  id: {
    "replay.drawings.notSaved": "Tidak disimpan di catatan replay ini: {drawings}. Gambar Anda yang lain sudah disimpan. Edit atau hapus gambar ini untuk mencoba lagi; gambar ini hilang saat halaman dimuat ulang.",
    "replay.drawings.notSavedUnsupported": "Catatan replay tidak menerima jenis gambar ini atau salah satu opsinya.",
    "replay.drawings.notSavedInvalid": "Data gambar tidak valid.",
  },
  it: {
    "replay.drawings.notSaved": "Non salvato nel registro di questo replay: {drawings}. Gli altri disegni sono salvati. Modificali o eliminali per riprovare; scompaiono quando ricarichi.",
    "replay.drawings.notSavedUnsupported": "Il registro del replay non accetta questo tipo di disegno o una delle sue opzioni.",
    "replay.drawings.notSavedInvalid": "I dati del disegno non sono validi.",
  },
  ms: {
    "replay.drawings.notSaved": "Tidak disimpan dalam rekod main semula ini: {drawings}. Lukisan anda yang lain telah disimpan. Edit atau padam lukisan ini untuk mencuba lagi; ia hilang apabila halaman dimuat semula.",
    "replay.drawings.notSavedUnsupported": "Rekod main semula tidak menerima jenis lukisan ini atau salah satu pilihannya.",
    "replay.drawings.notSavedInvalid": "Data lukisan tidak sah.",
  },
  nl: {
    "replay.drawings.notSaved": "Niet opgeslagen in het record van deze replay: {drawings}. Je andere tekeningen zijn opgeslagen. Bewerk of verwijder deze om het opnieuw te proberen; bij herladen verdwijnen ze.",
    "replay.drawings.notSavedUnsupported": "Het replayrecord accepteert dit tekeningtype of een van de opties ervan niet.",
    "replay.drawings.notSavedInvalid": "De tekeninggegevens zijn ongeldig.",
  },
  pl: {
    "replay.drawings.notSaved": "Nie zapisano w zapisie tej powtórki: {drawings}. Pozostałe rysunki są zapisane. Edytuj lub usuń te rysunki, aby spróbować ponownie; po przeładowaniu znikną.",
    "replay.drawings.notSavedUnsupported": "Zapis powtórki nie obsługuje tego typu rysunku ani jednej z jego opcji.",
    "replay.drawings.notSavedInvalid": "Dane rysunku są nieprawidłowe.",
  },
  "pt-BR": {
    "replay.drawings.notSaved": "Não salvo no registro deste replay: {drawings}. Seus outros desenhos foram salvos. Edite ou exclua estes para tentar de novo; eles somem ao recarregar.",
    "replay.drawings.notSavedUnsupported": "O registro do replay não aceita este tipo de desenho ou uma de suas opções.",
    "replay.drawings.notSavedInvalid": "Os dados do desenho são inválidos.",
  },
  "pt-PT": {
    "replay.drawings.notSaved": "Não guardado no registo desta repetição: {drawings}. Os seus outros desenhos estão guardados. Edite ou elimine estes para tentar novamente; desaparecem ao recarregar.",
    "replay.drawings.notSavedUnsupported": "O registo da repetição não aceita este tipo de desenho nem uma das suas opções.",
    "replay.drawings.notSavedInvalid": "Os dados do desenho não são válidos.",
  },
  ro: {
    "replay.drawings.notSaved": "Nu s-a salvat în înregistrarea acestei reluări: {drawings}. Celelalte desene sunt salvate. Editați-le sau ștergeți-le pentru a reîncerca; dispar la reîncărcare.",
    "replay.drawings.notSavedUnsupported": "Înregistrarea reluării nu acceptă acest tip de desen sau una dintre opțiunile lui.",
    "replay.drawings.notSavedInvalid": "Datele desenului nu sunt valide.",
  },
  ru: {
    "replay.drawings.notSaved": "Не сохранено в записи этого повтора: {drawings}. Остальные рисунки сохранены. Измените или удалите их, чтобы повторить попытку; после перезагрузки они исчезнут.",
    "replay.drawings.notSavedUnsupported": "Запись повтора не принимает этот тип рисунка или один из его параметров.",
    "replay.drawings.notSavedInvalid": "Данные рисунка недействительны.",
  },
  sv: {
    "replay.drawings.notSaved": "Inte sparat i den här reprisens post: {drawings}. Dina andra ritningar är sparade. Redigera eller ta bort dessa för att försöka igen; de försvinner när du laddar om.",
    "replay.drawings.notSavedUnsupported": "Reprisposten godtar inte den här ritningstypen eller något av dess alternativ.",
    "replay.drawings.notSavedInvalid": "Ritningsdata är ogiltiga.",
  },
  th: {
    "replay.drawings.notSaved": "ไม่ได้บันทึกในบันทึกของรีเพลย์นี้: {drawings} ภาพวาดอื่นของคุณบันทึกแล้ว แก้ไขหรือลบภาพวาดเหล่านี้เพื่อลองอีกครั้ง ภาพวาดเหล่านี้จะหายไปเมื่อโหลดหน้าใหม่",
    "replay.drawings.notSavedUnsupported": "บันทึกรีเพลย์ไม่รองรับภาพวาดประเภทนี้หรือตัวเลือกบางอย่างของภาพวาด",
    "replay.drawings.notSavedInvalid": "ข้อมูลภาพวาดไม่ถูกต้อง",
  },
  tr: {
    "replay.drawings.notSaved": "Bu tekrar oynatmanın kaydına kaydedilmedi: {drawings}. Diğer çizimleriniz kaydedildi. Yeniden denemek için bunları düzenleyin veya silin; sayfayı yenilediğinizde kaybolurlar.",
    "replay.drawings.notSavedUnsupported": "Tekrar oynatma kaydı bu çizim türünü veya seçeneklerinden birini kabul etmiyor.",
    "replay.drawings.notSavedInvalid": "Çizim verileri geçersiz.",
  },
  uk: {
    "replay.drawings.notSaved": "Не збережено в записі цього повтору: {drawings}. Інші малюнки збережено. Змініть або видаліть їх, щоб спробувати ще раз; після перезавантаження вони зникнуть.",
    "replay.drawings.notSavedUnsupported": "Запис повтору не приймає цей тип малюнка або один із його параметрів.",
    "replay.drawings.notSavedInvalid": "Дані малюнка недійсні.",
  },
  vi: {
    "replay.drawings.notSaved": "Chưa lưu vào bản ghi của phiên phát lại này: {drawings}. Các hình vẽ khác của bạn đã được lưu. Hãy sửa hoặc xóa các hình này để thử lại; chúng sẽ biến mất khi tải lại trang.",
    "replay.drawings.notSavedUnsupported": "Bản ghi phát lại không chấp nhận loại hình vẽ này hoặc một trong các tùy chọn của nó.",
    "replay.drawings.notSavedInvalid": "Dữ liệu hình vẽ không hợp lệ.",
  },
};
