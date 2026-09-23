# SRC-001 — Domain documents (real 112 card, card-entry instruction, services, DDS screen, incident classifier)

Task: X3 (worker: i2). IDs REQ-3001–REQ-3999.

## 1. Sources covered, method, and coverage

Source directory: `requirements/sources/01-qna-session-telegram/files/` (part of `SRC-001` in
`requirements/INDEX.md`). Five files, all `.docx`/`.xlsx`, provided by the organizers (this task's
scope does not include the Telegram chat transcript itself — see other X-tasks):

1. `КАРТОЧКА 112.docx` — the real Moscow 112 incident card (operator-facing screenshots + a master
   table of all "Что случилось?" (What happened?) scenario types).
2. `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx` — 9 annotated screenshots of the card in use, with 4 operator captions.
3. `Инструкция_по_заведению_карточки_2507ГСИ.docx` — the full operator user manual ("Модуль «Прием и
   обработка вызовов 112»", "Инструкция пользователя. Заведение карточки происшествия").
4. `СЛУЖБЫ 112.docx` — 55 full-screen screenshots of the "Добавьте службы" (Add services) picker,
   scrolled frame by frame.
5. `СКРИНШОТ ДДСГСИ.docx` — 20 annotated screenshots of the DDS (duty dispatch service / «ДДС», the
   receiving-service side of the system) screen, login through status lifecycle.
6. `Классификатор_происшествий_v_046_11_ДТУ_15_11_2024_искл_пожар_задымление.xlsx` — the incident
   classifier spreadsheet (1 sheet, 90 columns, 1308 rows).

### How each file was read
- `.docx` files: opened with `python-docx` (`uv run --with python-docx python ...`) to extract all
  paragraph/table text in document order, and separately unzipped (`unzip`) to pull every embedded
  image out of `word/media/` for direct viewing (no OCR was needed — every image is a native-resolution
  PNG screen capture (1920×1080 or similar), not a scan, and was read directly with the image-viewing
  tool; `tesseract` was available with `rus` trained data but was not required because all text was
  legible directly).
- `Классификатор_....xlsx`: opened with `openpyxl` (`uv run --with openpyxl python ...`), read
  data-only, dimensions and headers inspected programmatically, then the full "Пожары и задымления"
  (fire/smoke) category and every other fire/smoke-relevant row elsewhere in the sheet were extracted
  verbatim; the other 23 categories were counted but not transcribed in full (see §2.6 rule below).

### What could NOT be read / was not exhaustively transcribed, and why
- `КАРТОЧКА 112.docx` has 39 embedded images; ~24 were viewed directly (covering every distinct field
  layout reached from "Где: Улица" and "Где: Транспорт" for the fire scenario, i.e. the branches the
  filename/scope points to). The remaining images are scroll-repeats of the same "Улица (пламя, дым)"
  form with different toggle states (доступ/угроза/газификация/правонарушение) already documented once
  each; they were not re-transcribed to avoid duplicate items.
- `СЛУЖБЫ 112.docx` (55 full-screen screenshots) is a frame-by-frame scroll capture of one long
  dropdown list. ~20 of 55 frames were sampled (start, middle, end, and transition points) — sufficient
  to reconstruct the *pattern* and *scale* of the list (a fixed set of ~25 city-level services followed
  by ~140 near-identical "Поселение X (ДДС района X города Москвы)" district-dispatch entries and a
  block of district road-maintenance "ГБУ АД <округ>" entries) but NOT every one of the ~190+ entries
  individually — this is recorded as a documented sampling gap, not a silent omission (see REQ-3044).
- `Классификатор_....xlsx`: per the task instruction, the 1281 total classifier rows were **not** all
  pasted; only the "Пожары и задымления" category (271 rows) plus 13 fire/smoke-relevant rows found in
  other categories are given verbatim. The other 23 categories are given as structure + row counts only.
- The `.xlsx` filename itself contains the fragment "искл_пожар_задымление"; it is ambiguous whether
  this means the file is an "exclusion" (excluding fire/smoke, e.g. a specific edited variant) or an
  "excerpt/inclusion" version — the file nonetheless DOES contain a full "Пожары и задымления" category
  (271 rows) with the same structure as the rest of the sheet, so the fire/smoke content is present
  regardless of what the filename fragment means. This is flagged as OPEN-QUESTION REQ-3999.
- One truncated/apparently-abandoned text fragment "Аппа" (word start, spell-check marked and closed
  immediately) is the entire non-image text content of `СЛУЖБЫ 112.docx`; it is not a complete word and
  is not used as evidence of anything.

### How organizers were identified
None of these five files carry chat metadata (author/date/handle) — they are standalone reference
documents (a real production system's screenshots, a real operator manual, and a real government
incident classifier spreadsheet), supplied by the organizers as domain source material via the Telegram
files folder. There is no participant/organizer dialogue inside these specific files, so the
`Speaker` column is `organizer (document)` for every item — the entire file is organizer-supplied
ground truth about what the real system contains, not a chat statement. Any requirement derived from
these files is a DOMAIN-FACT (what the real 112/DDS system contains) unless the wording is explicitly
prescriptive for the *product being built* (none of these 5 files address the training-simulator
product directly — they describe the real system it imitates).

### Counts per Kind (this file)
- DOMAIN-FACT: 43
- REQUIREMENT: 3 (these state what the *real* system requires of its operators — e.g. "all four card
  blocks must be filled" — not what the *simulator* must do; docs/SPEC.md's imitation requirements are
  out of this task's scope)
- CLARIFICATION: 1
- CONSTRAINT: 1
- OPEN-QUESTION: 1
- Total items: 49 (REQ-3001–REQ-3049)

## 2. Items

### REQ-3001 — КАРТОЧКА 112: master "Что случилось?" (What happened?) scenario list

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `КАРТОЧКА 112.docx`, table 1 ("КАРТОЧКА ПРОИСШЕСТВИЯ", column "Что случилось") |
| Speaker | organizer (document) |

**Verbatim (RU, full 51-item list, document order):**
101; 102; 103; 104; Аварии и происшествия в городском хозяйстве; Аварии и происшествия на
транспортных объектах; Аварии на гидротехнических сооружениях; Аварии на опасных и производственных
объектах; Благодарность службам; БПЛА; Взрыв; Внутренний звонок (звонок от работников); Вызов на
иностранном языке; Дополнительный звонок от заявителя; Дорожные помехи; ДТП; Жалоба на действие или
бездействие служб; Животные; Консультация; Нецелевой вызов; Обрушение; Отзыв о работе 112 Москва;
Отмена вызова; Ошибочно набран номер; Передача дежурства; Помощь службам; Природная стихия; Прочие
происшествия; Радиация; Разбитый градусник; Ребенок в опасности; Сбор; Скопление воды; Смертельный
исход; Социальная помощь; Справка 101; Справка 102; Справка 103; Справка 104; Справка ГИБДД; Справка
Городское хозяйство; Справка МЧС; Тестовый вызов; Технический сбой (сбой в работе с оборудованием 112
Москва); Тренировка; Уведомление о ЧС; Угроза взрыва/террористического акта; Угроза выброса опасных
веществ и радиации; Угроза обрушения; Человек в опасности; Экологическое происшествие.

**English:** The real Moscow 112 card's top-level incident-type picker ("Что случилось?") offers
exactly these 51 named scenario types (includes the three hotline numbers 101/102/103/104 as literal
picker entries, plus admin/meta entries such as "Тестовый вызов" (test call), "Тренировка" (drill),
"Передача дежурства" (shift handover), "Технический сбой" (equipment fault), and six "Справка ..."
(reference/certificate) entries).

**Notes:** Cross-reference: `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx` frame 5 (image5.png) shows this same
picker mid-scroll with the same items in the same order, and `Инструкция...docx` §"Заполнение блока
«Что случилось?»" states "В системе предусмотрено около 50 типов происшествий" — consistent with the
51-item count here (see REQ-3020).

---

### REQ-3002 — КАРТОЧКА 112: "101" incident, top-level location branches ("Где")

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `КАРТОЧКА 112.docx`, image14.png (annotated "101") |
| Speaker | organizer (document) |

**Verbatim (RU):** Где: Улица . Транспорт . Дом . Здание / объект . Опасный объект .

**English:** Selecting the "101" (fire brigade) incident type opens a sub-form whose first field is
"Where" with five mutually-selectable location buttons: Street, Transport, House/Home, Building/
Facility, Hazardous facility. Each location branch reveals its own further field set (see REQ-3003,
REQ-3007 for the two branches captured in full).

---

### REQ-3003 — КАРТОЧКА 112: "101" → "Улица" (Street) fire field set

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `КАРТОЧКА 112.docx`, image15–17.png, image19.png (annotated "УЛИЦА", "ОТКРЫТОЕ ПЛАМЯ/ДЫМ") |
| Speaker | organizer (document) |

**Verbatim (RU), full field set when Где=Улица and Признак пожара=Открытое пламя/Дым is selected:**
Где: Улица . Признак пожара (улица): Открытое пламя / Дым . Запах гари . Доступ: Нет доступа .
Улица (пламя, дым): Мусор . Трава, пух . Парк . Лес . Торф . Мачта освещения . Опора контактной сети .
ЛЭП . Провода . Дерево, деревья . Горит человек . Что горит неизвестно . Место происшествия: Тоннель .
Пешеходный переход . Угроза людям: Да / Нет . Правонарушение: Есть правонарушение . Медицинская
помощь: Да / Нет . Требуется эвакуация: Да / Нет . Проведена ли газификация: Да / Нет / Нет данных .
Описание: [free-text field, 1999-character limit — see REQ-3025 for the identical limit on the "Описание
со слов заявителя" field].

**English:** For a street fire/smoke incident the card exposes: a fire-sign toggle (open flame/smoke
vs. smell of burning), an access toggle, a 12-item "what's burning" material list (litter, grass/fluff,
park, forest, peat, streetlight mast, contact-line support, power line, wires, tree(s), "a person is
burning", "burning object unknown"), a place-of-incident toggle (tunnel / pedestrian crossing), a
people-threatened yes/no, an "offence exists" toggle, medical-help yes/no, evacuation-needed yes/no,
and a gasification-done yes/no/no-data toggle.

**Notes:** Matches classifier rows REQ-3048 (Группа 1, п1=1 "на улице", п2 = Мусор/Трава/Пух/Парк/
Лес/Торф/Мачта освещения/Опора контактной сети/ЛЭП/Провода — see fire_rows table).

---

### REQ-3004 — КАРТОЧКА 112: "101" → "Улица" → "Запах гари" (smell of burning) collapses the form

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `КАРТОЧКА 112.docx`, image29–30.png |
| Speaker | organizer (document) |

**Verbatim (RU):** Где: Улица . Признак пожара (улица): Запах гари . Доступ: Нет доступа . Место
происшествия: Тоннель . Пешеходный переход . Описание.

**English:** When the fire sign chosen is "smell of burning" (as opposed to open flame/smoke), the form
does NOT show the material list, threat/medical/evacuation/gasification fields, or the offence field —
only Access, Place-of-incident, and free-text Description remain.

---

### REQ-3005 — КАРТОЧКА 112: "101" → "Транспорт" (Transport) fire field set

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `КАРТОЧКА 112.docx`, image34–35.png (annotated "ТРАНСПОРТ-ОТКРЫТОЕ ПЛАМЯ/ДЫМ") |
| Speaker | organizer (document) |

**Verbatim (RU), full field set when Где=Транспорт and Признак пожара=Открытое пламя/Дым:**
Где: Транспорт . Признак пожара (транспорт): Открытое пламя / Дым . Сработала пожарная сигнализация .
Доступ: Нет доступа . Транспорт (пламя, дым): Общественный транспорт . Автомашина . ДТП с пожаром .
Опасный груз . Воздушный транспорт . Аэропорт . Ж/Д транспорт . Вокзал Ж/Д, платформа Ж/Д . Транспорт
прочее . Водный . Мост . Эстакада . Тоннель . Переход подземный/наземный . Метро . МЦК, МЦД . Ж/Д
пути . Релейный шкаф Ж/Д . Угроза людям: Да / Нет . Медицинская помощь: Да / Нет . Требуется
эвакуация: Да / Нет . Описание.

**English:** For a transport fire, the fire-sign toggle offers open flame/smoke vs. fire-alarm
triggered; when open flame/smoke is picked, a 16-item transport-type list appears (public transport,
car, "accident with fire", dangerous cargo, air transport, airport, rail transport, rail
station/platform, other transport, water transport, bridge, overpass, tunnel, underground/surface
crossing, metro, MCC/MCD, rail track, rail relay cabinet), followed by threat/medical/evacuation
yes/no fields and free-text Description. No gasification or offence field appears in this branch
(unlike the Street branch).

**Notes:** Matches classifier "Аварии и происшествия на транспортных объектах" category (see
REQ-3049 rows for Пожар: Аэропорт/порт/Вокзал/Ж-д транспорт/Метро/МЦК).

---

### REQ-3006 — КАРТОЧКА 112: "104" (gas) incident field set

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `КАРТОЧКА 112.docx`, image39.png (caption block "Происшествие 104") |
| Speaker | organizer (document) |

**Verbatim (RU):** Происшествие 104 . Признаки происшествия: Запах газа вне помещения (на улице) .
Запах газа в помещении (в квартире, в доме) . Нарушение в работе газового оборудования . Повреждение
газопровода . Повышенное давление газа . Угроза людям: Да / Нет .

**English:** The "104" (gas service) incident type offers four feature toggles (gas smell outdoors, gas
smell indoors, gas-equipment malfunction, pipeline damage, elevated gas pressure — five buttons total)
plus a people-threatened yes/no.

---

### REQ-3007 — КАРТОЧКА 112: "Взрыв" (Explosion) incident field set

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `КАРТОЧКА 112.docx`, image39.png (caption block "П: Взрыв") |
| Speaker | organizer (document) |

**Verbatim (RU):** П: Взрыв . Где взрыв: Здание / Объект . Транспорт . Звуки похожие на взрыв, что
взорвалось сообщить не может . Есть возгорание: Да / Нет . Есть угроза обрушения: Да / Нет . Какие
видят разрушения: [free-text field].

**English:** The "Explosion" incident type asks where the explosion was (building/object, transport, or
"sounds like an explosion, caller cannot say what exploded"), a fire-present yes/no, a
collapse-threat yes/no, and a free-text "what damage is visible" field.

---

### REQ-3008 — СКРИНШОТ КАРТОЧКИ 112ГСИ: operator note on scenario/tag selection

| Field | Value |
|---|---|
| Kind | CLARIFICATION |
| Source | `СКРИНШОт КАРТОЧКИ 112ГСИ.docx`, paragraph 2 (below image1) |
| Speaker | organizer (document) |

**Verbatim (RU):** "В поле ЧТО СЛУЧИЛОСЬ выбирается сценарий (ИХ ОЧЕНЬ МНОГО). Далее к каждому
сценарию подтягиваются ТЭГИ под конкретный сценарий где оператор выбирает необходимую информацию"

**English:** "In the WHAT HAPPENED field a scenario is chosen (THERE ARE VERY MANY OF THEM). Then, for
each scenario, TAGS specific to that scenario are pulled in, where the operator selects the necessary
information."

---

### REQ-3009 — СКРИНШОТ КАРТОЧКИ 112ГСИ: automatic service attachment note

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx`, paragraph 8 (below image2) |
| Speaker | organizer (document) |

**Verbatim (RU):** "После выбора информации АВТОМАТИЧЕСКИ ПОДТЯГИВАЮТСЯ СЛУЖБЫ которые можно
дополнительно подтягивать в ручную"

**English:** "After the information is selected, SERVICES ARE PULLED IN AUTOMATICALLY, which can also
be pulled in manually in addition."

**Notes:** Consistent with `Инструкция...docx` §"Добавление служб на вызов" (REQ-3026).

---

### REQ-3010 — СКРИНШОТ КАРТОЧКИ 112ГСИ: red field = card-entry time exceeded

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx`, paragraph 10 (below image3) |
| Speaker | organizer (document) |

**Verbatim (RU):** "Далее для примера (КРАСНЫЙ ЦВЕТ ПОЛЯ ГОВОРИТ ОТОМ ЧТО ВРЕМЯ НАБОРВ КАРТОЧКИ
ПРЕВЫШЕНО)" [sic, verbatim including typos "ОТОМ", "НАБОРВ"]

**English:** "Next, for example (THE RED COLOR OF THE FIELD INDICATES THAT THE CARD-ENTRY TIME HAS BEEN
EXCEEDED)." — the on-screen elapsed-time counter (top right of the card) turns red once a time
threshold for filling in the card is exceeded (screenshot shows the counter red at 01:23–02:38 minutes
elapsed while filling a "101" card).

### REQ-3011 — Инструкция: document title / scope

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция_по_заведению_карточки_2507ГСИ.docx`, paragraphs 1–4 (title page) |
| Speaker | organizer (document) |

**Verbatim (RU):** "Выполнение научно-исследовательских и опытно-конструкторских работ по созданию
комплексной информационной системы мониторинга и управления силами и средствами Департамента по делам
гражданской обороны, чрезвычайным ситуациям и пожарной безопасности города Москвы (вторая очередь)" /
"МОДУЛЬ «ПРИЕМ И ОБРАБОТКА ВЫЗОВОВ 112»" / "Инструкция пользователя" / "Заведение карточки
происшествия"

**English:** This is the user instruction ("Card creation") for the "112 Call Reception and Processing"
module, part of R&D work building an integrated monitoring/command information system for Moscow's
Civil Defense, Emergencies and Fire Safety Department (phase two).

---

### REQ-3012 — Инструкция: system login procedure and session timeout

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Авторизация в Системе 112" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Перейти по адресу: [credential redacted — internal URL, see source]. Ввести свои
логин и пароль, а также номер АРМ (Рисунок 1). Нажать кнопку «Войти» или клавишу Enter." / "Если не
закрывать вкладку с Системой 112 на протяжении 24 часов, то выход произойдет автоматически."

**English:** Operator navigates to [internal URL — redacted], enters login, password, and workstation
("АРМ") number, and clicks "Войти" (Log in) or presses Enter. If the browser tab is left open for 24
hours without closing, the system logs the operator out automatically.

**Notes:** The literal internal server address that appeared in the source, and an example login value
that appeared in a `СКРИНШОТ ДДСГСИ.docx` screenshot (REQ-3038), are both access credentials/links and
have been redacted from this file per instruction; both are cited by source only, not reproduced here.

---

### REQ-3013 — Инструкция: telephony status values for the operator

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Проверить в АРМ наличие подключения к телефонии" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Возможны следующие статусы: - доступен – пользователь может принимать вызовы; -
недоступен – пользователь подключен к телефонии, но не может принимать вызовы; - не подключен –
отсутствует подключение к телефонии; - ошибка – при подключении к телефонии произошла ошибка."

**English:** Possible telephony statuses: "available" (can take calls), "unavailable" (connected but
cannot take calls), "not connected" (no telephony connection), "error" (a connection error occurred).
Available/unavailable can be toggled manually; "unavailable" is set automatically while a card is open,
and reverts to "available" 10 seconds after the card is closed.

---

### REQ-3014 — Инструкция: the four mandatory card blocks

| Field | Value |
|---|---|
| Kind | REQUIREMENT |
| Source | `Инструкция...docx`, §"Заполнение блоков карточки происшествия" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Карточка состоит из следующих блоков: номера телефонов (заявителя); что случилось;
адрес происшествия; подробности происшествия. Внимание! Для корректной обработки происшествия
необходимо заполнить все блоки карточки."

**English:** The (real-system) card consists of four blocks — caller phone numbers, what happened,
incident address, incident details — and correct processing of the incident requires all four blocks
to be filled in. Blocks can be filled partially and revisited in any order. An elapsed-time timer
starts when a new card opens and stops when "Сохранить" (Save) is pressed; this time is stored and
shown in reports.

---

### REQ-3015 — Инструкция: "Телефоны заявителя" (Caller phones) block fields

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Раздел «Телефоны заявителя» (Alt+F1/Alt+F2/Alt+F3)" |
| Speaker | organizer (document) |

**Verbatim (RU):** "При приеме вызова заявителя поле Телефон АОН заполняется автоматически. ...
оператор заполняет в блоке поля: Предоставленный номер (Alt+F2) – телефонный номер, указанный
заявителем как его контактный; Телефон на место (Alt+F3) – контактный телефон на место происшествия;
... Если определившийся или предоставленный номер начинается не с +7 (код РФ), следует отметить
признак «зарубежный номер»"

**English:** The caller-ID phone field ("АОН") auto-fills on call receipt. The operator additionally
fills "Provided number" (caller's stated contact number, hotkey Alt+F2) and "Phone at the scene"
(hotkey Alt+F3). If a number doesn't start with +7, a "foreign number" flag should be set. A "channel"
(канал связи) dropdown records how the call arrived, and auto-detects for Tele2/MTS/Megafon/Beeline
operators (per doc, "новое в версии 2.0").

---

### REQ-3016 — Инструкция: caller name/status fields and "No contact"/"Call dropped" buttons

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Заполнение блоков карточки" (ФИО заявителя / Нет контакта / Срыв звонка) |
| Speaker | organizer (document) |

**Verbatim (RU):** "Для быстрой обработки нерезультативных вызовов предусмотрены кнопки (Рисунок 11):
«Нет контакта» при отсутствии контакта с заявителем; «Срыв звонка», если звонок сорвался. ... карточки
... автоматически переводятся в статус «Завершена» с установкой признака «Проверено»."

**English:** Caller name/status/foreign-language-call fields sit top-left of the card. Two quick-close
buttons exist for unproductive calls: "No contact" (no contact with caller) and "Call dropped"; cards
created via either button auto-close to status "Завершена" (Completed) with the "Проверено" (Checked)
flag, with an option to instead return to filling the card if pressed by mistake.

---

### REQ-3017 — Инструкция: "Что случилось?" (What happened) selection methods and search hints

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Заполнение блока «Что случилось?» (Alt+T)" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Блок можно заполнить двумя способами: Нажатием на вариант происшествия из
представленных часто используемых вариантов ... Нажатием на вариант происшествия из набора значимых
типов происшествий ... Вводом типа происшествия в строку поиска ... В системе предусмотрено около 50
типов происшествий, и при поиске нужного могут помочь следующие действия: - Ищите по менее
распространенным в типах происшествий словам, либо подбирайте синонимы к опросным картам. Например,
синонимом к опросной карте «101» является слово «пожар». К синонимам относятся также «взрыв»,
«обрушение», «ДТП», «происшествие», «вызов 03», «запах газа», «авария» («аварии»), «авиакатастрофа»,
«выброс», «нападение». - Учитывайте, что слова могут использоваться в разных формах ... - Слова при
поиске можно вводить в любом порядке. - Знаки препинания (дефис, запятую) можно не вводить."

**English:** Three ways to fill "What happened": tap a frequently-used-scenario tile; tap a tile from a
smaller "significant incident types" set (curated "по согласованию с руководством Службы 112" — by
agreement with Service 112 management); or type into a search box (partial-word, any word order,
punctuation-insensitive, stem-matching). Multiple types may be selected and combined via any of the
three methods. ~50 incident types exist system-wide (matches the 51-row list in REQ-3001). Documented
synonyms include: "пожар" (fire) → opens the "101" form; "взрыв" (explosion), "обрушение" (collapse),
"ДТП" (road accident), "происшествие" (incident), "вызов 03" (call-03/ambulance), "запах газа" (gas
smell), "авария"/"аварии" (accident/accidents), "авиакатастрофа" (air crash), "выброс" (release/spill),
"нападение" (attack).

---

### REQ-3018 — Инструкция: "Отказ от реагирования" (Refuse response) flag, currently only for 103

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Заполнение блока «Что случилось?»", final paragraph |
| Speaker | organizer (document) |

**Verbatim (RU):** "В случае, если нужно отменить реагирование службы на происшествие, необходимо
выбрать признак «Отказ от реагирования». В настоящее время он реализован для карточки 103 (отказ от
реагирования скорой помощи) [новое в версии 2.1]."

**English:** To cancel a service's response to an incident, the operator sets an "Отказ от реагирования"
(Refuse response) flag; as of the documented version (2.1) this is implemented only for the "103"
(ambulance) card.

---

### REQ-3019 — Инструкция: Address block — single address line, source dropdowns, auto-fill

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Заполнение блока «Адрес» (Alt+A)" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Для заполнения адреса нужно начать вводить часть адреса в единую адресную строку.
Адрес вводится с домом включительно ... Система покажет выпадающий список с возможными вариантами
адреса ... Варианты адреса в списке могут быть представлены из следующих сервисов: Яндекс.Карты,
Яндекс.Организации, ФИАС. ... Система автоматически заполнит в карточке отдельные поля адреса в
соответствии с выбранным ... Система также автоматически определит район и округ ..."

**English:** Address entry uses one unified text field (house number included), with a dropdown of
candidates sourced from three services: Yandex.Maps, Yandex.Organizations, FIAS (Russia's federal
address registry). Choosing a candidate auto-fills the card's structured address fields plus
district/okrug, and opens a map window at 1:50 scale centered on the incident. Known data-quality
caveats stated in the doc: FIAS-sourced addresses do NOT auto-add services (must add manually);
some Yandex.Organizations addresses (example given: "Охотный ряд, Манежная площадь, 1, стр. 2") do not
record a house number — Yandex addresses should be preferred.

---

### REQ-3020 — Инструкция: map — radius, layers, socially-significant-objects rule

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Работа со справочником социальных объектов", §"Использование карты" |
| Speaker | organizer (document) |

**Verbatim (RU):** "При выборе слоя «Объекты», на карте отображаются социально значимые объекты ...
Объекты появляются в пределах установленного радиуса ... Если точка места происшествия располагается
в 50 метрах от объекта, то его наименование отображается в Описательном адресе." / "На карте можно
просмотреть наличие камер, техники и объектов в радиусе от 50 до 1000 метров."

**English:** An "Objects" map layer shows socially-significant objects near the incident point within a
configurable search radius (50–1000 m, chosen via a "Радиус" control); if the incident is within 50 m
of such an object, its name is auto-inserted into the card's "Описательный адрес" (descriptive address)
field. Camera and equipment ("техника") locations can also be shown via the same radius/layer controls.

---

### REQ-3021 — Инструкция: mandatory fields warning ("Заполнение остальных полей карточки")

| Field | Value |
|---|---|
| Kind | REQUIREMENT |
| Source | `Инструкция...docx`, §"Заполнение остальных полей карточки" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Внимание! Для корректной обработки происшествия необходимо заполнить поля
«Описание со слов заявителя», «ФИО заявителя», «Статус заявителя» и группу полей «Пострадавшие»."

**English:** Beyond the four blocks (REQ-3014), correct processing additionally requires: "Description
in the caller's own words", "Caller's full name", "Caller's status", and the "Injured/affected persons"
field group.

---

### REQ-3022 — Инструкция: "Описание со слов заявителя" — 100-char cutoff to service 03

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Заполнение блока «Описание со слов заявителя»" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Примечание: При заполнении блока «Описание со слов заявителя» важно учитывать, что
в службу 03 передаются только первые 100 символов." / "В данный блок может поступить следующая
информация от оператора связи об абоненте: ФИО; дата рождения; место жительства."

**English:** Only the first 100 characters of the free-text "Description in caller's own words" field
are forwarded to "службу 03" (ambulance service). The field can also be auto-populated by the telecom
carrier with subscriber name, date of birth, and address, when available.

---

### REQ-3023 — Инструкция: "ФИО заявителя" and caller status list

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Добавление ФИО заявителя и его статуса" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Панель выбора содержит следующие статусы: очевидец; пострадавший; родственник;
знакомый; ребенок; участник." / "После сохранения карточки происшествия изменить ФИО и статус
заявителя будет нельзя."

**English:** Caller status options: witness, injured party, relative, acquaintance, child, participant.
Once the card is saved, the caller's name and status can no longer be edited.

---

### REQ-3024 — Инструкция: "Пострадавшие" (Injured) count entry

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Пострадавшие" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Если заявитель сообщает, что есть пострадавшие, нужно нажать кнопку «Есть» в
правом верхнем углу экрана. Появится окно для ввода количества пострадавших ... Ввести количество
пострадавших." / (elsewhere) "Возможно изменять признак наличия пострадавших после сохранения карточки
[новое в 1.8]."

**English:** An "Есть" (Yes/There are) button opens a numeric-count entry for injured persons. This
flag remains editable even after the card is saved (change introduced in version 1.8).

---

### REQ-3025 — Инструкция: services auto-assignment and the "do not touch manually" constraint

| Field | Value |
|---|---|
| Kind | CONSTRAINT |
| Source | `Инструкция...docx`, §"Добавление служб на вызов" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Когда выбран тип происшествия и указан адрес, в левой нижней части экрана появится
автоматически сформированный список служб, назначенных на вызов ... Внимание! В системе предусмотрен
функционал удаления и добавления служб на вызов, однако в штатной ситуации пользоваться им не следует.
Система автоматически определяет службы, которые необходимо проинформировать, в соответствии с Единым
классификатором происшествий, согласованным со всеми службами. Информация ниже может пригодиться
только в нештатной ситуации."

**English:** Once an incident type and address are set, the system auto-generates the list of services
to notify, per the "Единый классификатор происшествий" (Unified Incident Classifier, i.e. the
`Классификатор_....xlsx` reviewed in REQ-3044–3049), agreed with all services. The real operator manual
explicitly warns that manual add/remove of services should NOT be used in normal operation — it exists
only for exceptional situations. Services from the auto-list can be individually removed (✕ on the
tile); manual additions use a "+" button, searchable picker, with already-auto-selected services shown
highlighted; "Сохранить и закрыть" confirms, "Закрыть" cancels.

---

### REQ-3026 — Инструкция: "ВИС"-tagged externally-added services

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Добавление служб на вызов", final paragraph |
| Speaker | organizer (document) |

**Verbatim (RU):** "В карточку, созданной в системе оператором Службы 112, из внешней системы по
решению оператора службы могут быть добавлены дополнительные службы для реагирования. В этом случае
добавленная служба будет отображаться с пометкой «ВИС»."

**English:** A service added from an external system (rather than by the 112 operator) is tagged "ВИС"
(external information system) on its tile.

---

### REQ-3027 — Инструкция: saving the card and the notify-and-save confirmation

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Сохранение карточки происшествия" |
| Speaker | organizer (document) |

**Verbatim (RU):** "После заполнения всех блоков карточки происшествия карточку следует сохранить.
... Службы, которые являются основными для типа происшествия, подчеркиваются двойной линией. ... После
нажатия кнопки «Сохранить» система предложит подтвердить сохранение карточки и оповещение служб или
вернуться к заполнению карточки. При нажатии кнопки «Оповестить и сохранить карточку» происходит
передача информации о происшествии в выбранные службы, и карточка становится доступна для просмотра в
общем списке."

**English:** Before saving, the operator should review the assigned-services list (services that are
"primary" for the incident type are underlined with a double line). Pressing "Сохранить" (Save) opens a
confirm dialog; "Оповестить и сохранить карточку" (Notify and save the card) both dispatches the
incident data to the chosen services and publishes the card to the shared incident list. If network
connectivity fails mid-entry, the card can be saved locally and syncs once connectivity returns
(feature "новое в 1.8").

---

### REQ-3028 — Инструкция: card linking ("Совпадение" / main-subordinate)

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Связи между карточками происшествия" |
| Speaker | organizer (document) |

**Verbatim (RU):** "При заведении карточки система может сообщить, что карточка с таким же номером
заявителя или местом происшествия уже была добавлена в систему недавно. При этом появляется кнопка
«Совпадение»." / "Если связь для карточки устанавливается впервые, то карточка, к которой идет
привязка становится «главной», а карточка, из которой создается связь – «подчиненной»." / "Связи между
карточками передаются в систему КИС УСС (служба 101) [новое в версии 2.0]."

**English:** If a new card shares a caller phone number or incident address with a recently-created
card, a "Match" ("Совпадение") button appears, letting the operator link the two. On first link, the
target card becomes "main", the new one "subordinate"; roles can be swapped later, and two subordinate
chains can be merged by linking their two main cards. Links are forwarded to the "КИС УСС" system
(service 101).

---

### REQ-3029 — Инструкция: call-transfer-to-service modes

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Перевод вызова в службу" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Доступны три режима перевода вызова: Перевести – осуществляется соединение
заявителя и службы без проверки оператором. ... Перевести с удержанием - соединение заявителя и
абонента с проверкой оператором дозвона до службы. ... Добавить в конференцию – добавление оператора
службы в режиме конференции. ... В конференцию возможно добавить до 4х участников."

**English:** Three call-transfer modes to a service while the caller is on the line: plain "Transfer"
(blind, no operator verification), "Transfer with hold" (operator verifies the service answers before
connecting caller), and "Add to conference" (up to 4 participants total).

---

### REQ-3030 — Инструкция: automatic service-status updates and 48-hour "Не завершено" rule

| Field | Value |
|---|---|
| Kind | REQUIREMENT |
| Source | `Инструкция...docx`, §"Автоматическое обновление статуса службы в карточке" |
| Speaker | organizer (document) |

**Verbatim (RU):** "После сохранения карточки обновление статуса службы, назначенной на вызов, в
карточке происходит автоматически. ... Если в течении 48 часов с момента добавления службы от нее не
пришел статус "Завершение работ", карточка происшествия переходит в статус «Не завершено» [новое в
версии 2.1]."

**English:** After saving, each assigned service's status auto-updates on the card (history viewable via
an arrow over the service name). If a service does not report "Завершение работ" (Work completed)
status within 48 hours of being added, the whole incident card auto-transitions to status "Не
завершено" (Not completed).

**Notes:** Cross-reference: this is the *instruction manual's* description of the same status lifecycle
shown live in `СКРИНШОТ ДДСГСИ.docx` (REQ-3033–3034).

---

### REQ-3031 — Инструкция: "Добавить отработку" (Add follow-up call) fields

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Добавление отработки" |
| Speaker | organizer (document) |

**Verbatim (RU):** "При совершении исходящего вызова нужно нажать кнопку «Добавить отработку» и
заполнить поля: Служба. ... Куда звонили. ... Телефон. ... Кто принял. ... Суть сообщения. ..."

**English:** For calls to services not auto-notified, the operator logs a manual follow-up ("отработка")
with fields: Service (searchable dropdown, no free text), "Where called" (free text, used when the
service isn't in the dropdown), Phone (auto-fills from the picked service, or manual), "Who answered"
(name/operator number of the service dispatcher), and "Message gist" (outcome of the call).

---

### REQ-3032 — Инструкция: ending work on a card ("Отработана")

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Окончание работы по карточке" |
| Speaker | organizer (document) |

**Verbatim (RU):** "По окончании работы по происшествию в карточке происшествия необходимо нажать
кнопку «Отработана»."

**English:** When work on the incident is finished, the operator presses the "Отработана" (Worked/
Processed) button.

---

### REQ-3033 — Инструкция: reminder and "important incident" buttons

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Установить напоминание / Привлечь внимание главного специалиста" |
| Speaker | organizer (document) |

**Verbatim (RU):** "При нажатии на кнопку «Установить напоминание «будильник» на экране появится окно
ввода текста и установки времени напоминания. ... Если оператор закроет окно напоминания, не совершив
с его помощью никаких действий, оно будет появляться на экране каждые 20 секунд." / "При нажатии на
кнопку «Важное происшествие» на экране главных специалистов появится информация с номером АРМ и Ф.И.О.
специалиста, которому требуется консультация."

**English:** A reminder ("будильник"/alarm clock) button opens a text+time popup; if dismissed without
action it re-appears every 20 seconds (only while the card is closed). A separate "Важное происшествие"
(Important incident) button alerts senior specialists' screens with the requesting operator's
workstation number and full name.

---

### REQ-3034 — Инструкция: advanced search parameter list

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Расширенный поиск по параметрам" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Поиск происходит по следующим параметрам: Что случилось; АРМ ...; Статус ...;
Адрес; Описательный адрес [новое в версии 2.1]; Служба ...; Субъект; Описание; Заявитель (ФИО/АОН);
Канал связи ...; Оператор; Источник происшествия ... [новое в версии 2.0]; Номер карточки."

**English:** Advanced incident search parameters (13 total, several multi-select): What happened, АРМ
(workstation), Status, Address, Descriptive address, Service, Subject (region), Description, Caller
(name/caller-ID), Communication channel, Operator, Incident source, Card number — plus date/time
filtering.

---

### REQ-3035 — Инструкция: incoming SMS handling

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Обработка новых СМС" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Заявители имеют возможность отправлять СМС в систему в качестве обращения за
помощью. ... После получения уведомления нужно нажать кнопку «Принять». В карточке происшествия будет
автоматически заполнена следующая информация: - АОН заявителя; - Поле «Описание со слов заявителя». В
нем отобразится текст полученного СМС-сообщения; - полигон местоположения заявителя на карте."

**English:** Callers can text the system for help; a notification is routed to an available Specialist/
Senior Specialist. Accepting it auto-fills the caller-ID phone, puts the SMS text into "Description in
caller's own words", and plots the caller's location polygon on the map. The operator can also send SMS
back to the caller, and multiple SMS from the same caller-ID all route into one card until it is closed.

---

### REQ-3036 — Инструкция: "Аудит" (Audit) event list

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Просмотр событий отдела «Аудит»" |
| Speaker | organizer (document) |

**Verbatim (RU):** "Также отображаются следующие события: Автоматический переход в статус ошибки:
Переход в Не оповещено; Переход в Не завершено; Переход в Отказ; Автоматический переход из статуса
ошибки: Переход в Зарегистрирована; Переход в Отработана; Переход в Проверена; Переход из статуса
ошибки при исправлении нарушений: Нарушения исправлены. Переход из Не оповещено; ... Переход из Не
завершено; ... Переход из Отказ [новое в версии 2.1]."

**English:** The card-status state machine includes (at minimum) these named statuses, visible in the
Audit log: Не оповещено (Not notified), Не завершено (Not completed), Отказ (Refused/Rejected),
Зарегистрирована (Registered), Отработана (Worked/Processed), Проверена (Checked) — with both
automatic transitions into an "error" state and automatic/manual transitions back out once violations
are fixed.

---

### REQ-3037 — Инструкция: hotkey table

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Инструкция...docx`, §"Горячие клавиши" (table, 39 rows) |
| Speaker | organizer (document) |

**Verbatim (RU) — full table:**

| Комбинация клавиш | Действие |
|---|---|
| Alt (зажатие)* | Отображение подсказок по комбинациям клавиш |
| Insert | Создать новую карточку |
| Esc | Закрыть карточку или закрыть всплывающее окно |
| Tab / Shift+Tab | Переход вперед/назад между полями и кнопками карточки |
| Alt+F1 / Alt+F2 / Alt+F3 | К блокам телефонных номеров |
| Alt+K | К блоку "канал связи" |
| Alt+Q | К блоку заявителя |
| Alt+А | К блоку «Адрес» |
| Alt+P | К блоку пострадавших |
| Alt+N | К блоку Нет контакта / Срыв звонка |
| Alt+T | К блоку «Что случилось» |
| Alt+R | К блоку выбора значимого типа происшествия |
| Alt+O | К блоку описания |
| Alt+Z | К блоку управления службами |
| Alt+<n>** | К блокам добавленных опросных карт (н: Alt+1) |
| Alt+Ctrl+<n>*** | К определенным вопросам в опросных картах |
| Alt+S | Сохранение карточки |
| Alt+W | Создание связи |
| Alt+B | Создание напоминания |
| Alt+V | Указание происшествия как важного |
| Alt+M | Создание сообщения об ошибке |
| Alt+O (view mode) | К блоку отработок |
| Shift+F1 | Пункт меню «Просмотр» |
| Shift+F2 | Пункт меню «Дополнить» |
| Alt+S (view mode) | Выбор опции Отработана / Завершить (в зависимости от статуса КП) |
| Alt+Y | Выбор опции Проверена (в статусе Проверена) |
| Alt+N (view mode) | Выбор опции Вернуть на доработку (в статусе Проверена) |
| Alt+1 (link window) | К блоку поиска происшествия |
| Alt+2 (link window) | К блоку списка происшествий |
| Alt+3 (link window) | К кнопке возврата |

**English:** Full documented keyboard-shortcut set for the real card-entry UI (create card = Insert,
save = Alt+S, jump to each block via Alt+letter, etc. — see table).

**Notes:** `Alt+O` is documented twice with two different targets ("к блоку описания" in create mode
and "к блоку отработок" in view mode) — recorded verbatim as in source, not resolved here.

### REQ-3038 — СКРИНШОТ ДДСГСИ: DDS login screen

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СКРИНШОТ ДДСГСИ.docx`, image1.png (captioned "ВХОД В СИСТЕМУ ДЛЯ ДДС") |
| Speaker | organizer (document) |

**Verbatim (RU):** "112 ВХОД В СИСТЕМУ" / "логин: [credential redacted]" / "пароль:" / "Техподдержка
+7 (495) 197-89-81 (многоканальный) hd-112@mos.ru"

**English:** The DDS (duty dispatch service) side of the system has its own login screen: 112 branding,
login field (example value redacted — a real login string), blank password field, a "ВОЙТИ" (Log in)
button, and public tech-support contact (phone +7 (495) 197-89-81, multichannel; email hd-112@mos.ru).

**Notes:** The example login value and the internal server address in REQ-3012 are both credentials/
access strings and have been redacted here per instruction; both are visible in the cited source file
if verification is needed.

---

### REQ-3039 — СКРИНШОТ ДДСГСИ: incident-search list column set

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СКРИНШОТ ДДСГСИ.docx`, image2–5.png (captioned "РАБОЧЕЕ ПОЛЕ ДДС") |
| Speaker | organizer (document) |

**Verbatim (RU):** "Поиск происшествий" / columns: "Связи | ЧС | Опер. | АРМ | Номер | Дата | Время |
Тип происшествия | Постр. Адрес | Статус службы" / row example: "0 | 4 | 36814845 | 17.09.26 |
11:12:43 | 101 | Москва, (ТАО, Вороновское), Троицкий административный округ | [Нет/статус icon] |
Добавлена" with expandable one-line description row underneath (e.g. "17.09.2026 11:13:19 0 УМЦ О.п. -
Пожар в квартире").

**English:** The DDS "Поиск происшествий" (Incident search) list — the DDS-side equivalent of the 112
operator's incident list — has columns: Links, ChS (emergency-situation flag), Operator, АРМ
(workstation), Number, Date, Time, Incident type, Struct./Address, Service status; each row expands to
show a one-line description with timestamp and organizational unit.

---

### REQ-3040 — СКРИНШОТ ДДСГСИ: incident card read-only view on the DDS side

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СКРИНШОТ ДДСГСИ.docx`, image6.png (captioned "РАБОЧЕЕ ПОЛЕ КАРТОЧКИ ДДС") |
| Speaker | organizer (document) |

**Verbatim (RU):** "Пострадавшие: нет Отказ от скорой: нет Заблокированные: нет" / icon toggles
"ЧС" (with lightning icon) and "ЧП" (highlighted orange, with warning triangle) / "Происшествие 101" /
"Дом . Открытое пламя / Дым (дом), Запах гари (дом) . Дом многоквартирный . квартира . Есть угроза
людям . Есть газификация ." / "Класс.: пожар: квартира ;" / "[ВИС] Класс.:"

**English:** The DDS view of an incoming card is read-only summary text: caller/incident header flags
(Injured: no, Ambulance refused: no, Blocked: no), ЧС/ЧП status toggles, the incident-type sentence
built from the operator's selected card fields (e.g., "House. Open flame/Smoke (house), Smell of
burning (house). Multi-unit residential building. Apartment. People are threatened. Gasification
present."), a classifier line ("Класс.: пожар: квартира" — matches the classifier's "Итоговый тип
происшествия" field, see REQ-3047), and a second "[ВИС] Класс.:" line for an externally-supplied
classification.

---

### REQ-3041 — СКРИНШОТ ДДСГСИ: service status entry — status lifecycle, and free-text fields

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СКРИНШОТ ДДСГСИ.docx`, image8–20.png (captioned "РАБОЧЕЕ ПОЛЕ ДЛЯ ЗАПОЛНЕНИЯ СТАТУСА...", "СТАТУС ПРИНЯТО/НЕ ПРИНЯТО...", "...можно проставлять новые статусы...") |
| Speaker | organizer (document) |

**Verbatim (RU) — caption text:** "РАБОЧЕЕ ПОЛЕ ДЛЯ ЗАПОЛНЕНИЯ СТАТУСА при выборе ПОСЕЛЕНИЕ
ВОРОНОВСКОЕ" / "СТАТУС ПРИНЯТО/НЕ ПРИНЯТО формируется путем выбора из двух статусов, остальные поля
заполняются в ручную" / "Далее при нажатии карандашика можно проставлять новые статусы (НАЧАЛО
РЕАГИРОВАНИЯ/ ОТКАЗ ОТ ВЫПОЛНЕНИЯ РАБОТ/ РАБОТЫ ЗАВЕРШЕНЫ) и комментарии"

**Verbatim (RU) — full status sequence observed in the screenshots, one service's history panel
("Поселение Вороновское"), each entry a timestamp + status + free-text comment:** "Добавлена" →
"Получена службой" → "Принята" (comment field example: "Отправлн сантехник для перекрытия воды") →
"Начало реагирования" (comment: "Сантехники приступили к работе по перекрытию воды в доме") →
"Прибытие" (comment: "Дополнительно прибыли рабочие") → "Проведение работ" (comment: "Работы ведутся")
→ "Работы завершены" (comment: "Работы завершены"). The status-entry form itself has three fields:
"Статус" (dropdown), "Номер наряда" (order/dispatch number, free text — example value "23"), and
"Комментарий" (free text). The dropdown for the next-status step offers: "Прибытие" / "Отказ от
выполнения работ" / "Работы завершены".

**English:** The DDS service-status lifecycle for one assigned service on a card is: Added → Received
by service → Accepted (Принята — operator manually chooses one of two outcomes at this step, i.e. an
accept/decline binary the caption calls "СТАТУС ПРИНЯТО/НЕ ПРИНЯТО") → Response started ("Начало
реагирования") → Arrival ("Прибытие") → Work in progress ("Проведение работ") → Work completed
("Работы завершены"); "Отказ от выполнения работ" (Refusal to carry out the work) is an alternative
branch instead of arrival/completion. Every status change is entered via a pencil-icon edit action with
a status dropdown, a free-text dispatch/order number, and a free-text comment, and each change is
timestamped and appended to a visible history panel per service.

**Notes:** Cross-reference: matches `Инструкция...docx`'s description of automatic service-status
updates and the 48-hour "Не завершено" rule (REQ-3030); "Работы завершены" corresponds to that
instruction's "Завершение работ" trigger.

### REQ-3042 — СЛУЖБЫ 112: city-level services picker, sampled entries

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СЛУЖБЫ 112.docx`, image1–8.png, image35–55.png (all frames of the "Добавьте службы" scroll picker, same UI as `КАРТОЧКА 112.docx` image4.png / REQ-3002's "Добавьте службы" popup) |
| Speaker | organizer (document) |

**Verbatim (RU), city-level (non-district) services observed, in on-screen order (list is a live
alphabetically/logically-grouped scroll — not necessarily complete; see REQ-3043 for scope note):**
Служба 101 (ГУ МЧС России по г.Москве, ГКУ "Пожарно спасательный центр" ОДС); ФСБ; ЦЭМП; Служба 103
(ГБУ города Москвы Станция скорой и неотложной медицинской помощи им.А.С. Пучкова); Служба 104 (АО
"МОСГАЗ" Диспетчерское управление); ОГДЦ; ЦОДД (ГКУ "Центр организации дорожного движения"); Гормост
(Гормост); Мосгортранс; Автодороги; Мосводоканал (АО "Мосводоканал"); Россети МР; МОЭК; Деп. ЖКХ
(Департамент ЖКХ); Метро; АСУ НС (Автоматизированная система управления...); Мос.Без. (Московская
Безопасность); 112 Моск. обл. (112 Московской области); ФГУП РСВО (Российские сети вещания и
оповещения); ОЭК (Объединенная энергетическая компания); Мослифт (Лифт МСК); Мосводосток (Мосводосток);
Москоллектор (Москоллектор); Воен. комендатура (Воен. комендатура); ОАТИ (Объединение
Административно-Технических Инспекций города Москвы); ГБУ МСППН (Московская служба психологической
помощи населению ГБУ города Москвы); Мособлгаз (Мособлгаз); Центррегионводхоз (Центррегионводхоз);
ГБУ АД ВАО / СВАО / ЮВАО / ЗелАО / ЮЗАО / ЮАО (ГБУ Автодороги, per-okrug); Департамент культуры города
Москвы; ГКУ ЦСА (Центр социальной помощи); Мостуризм (Комитет по туризму города Москвы); Департамент
строительства; Комитет ветеринарии города Москвы; Мосжилинспекция (Государственная жилищная инспекция
города Москвы).

**English:** The service-picker popup ("Добавьте службы") lists roughly two dozen city-wide services
(the three-digit hotline services 101/103/104, plus utility/infrastructure/safety bodies such as ФСБ,
ЦЭМП, ЦОДД, Гормост, Мосгортранс, Мосводоканал, МОЭК, Мослифт, Мосводосток, Москоллектор, ОАТИ, and
various "Департамент"/"Комитет" city bodies), each shown with its full institutional name in
parentheses.

**Notes:** Cross-reference: overlaps with the classifier's column headers (REQ-3044), which name the
same organizations as routing-matrix columns (Классификатор МЧС/МВД/СМП/МОСГАЗ/ФСБ/Мособлгаз, Автодороги,
Мосгортранс, ГОРМОСТ, Метро, Мосводоканал, МОЭК, МОЭСК/Россети, ОЭК, Мослифт, ЦОДД, Деп.ЖКХ, and ~40
more).

---

### REQ-3043 — СЛУЖБЫ 112: district-level "ДДС района" entries — pattern, scale, and sampling limit

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `СЛУЖБЫ 112.docx`, image9–34.png (sampled) |
| Speaker | organizer (document) |

**Verbatim (RU), representative sample entries (exact naming pattern, in on-screen order across the
sampled frames):** "Поселение Чертаново Северное (ДДС района Чертаново Северное города Москвы)";
"Поселение Академический (ДДС Академического района города Москвы)"; "Поселение Ломоносовский (ДДС
Ломоносовского района города Москвы)"; "Поселение Бибирево (ДДС района Бибирево города Москвы)";
"Поселение ЮВАО (ДДС префектуры Юго-Восточного административного округа города Москвы)"; "Поселение
ВАО (ДДС префектуры Восточного административного округа города Москвы)"; "Поселение Зябликово (ДДС
района Зябликово города Москвы)"; "Поселение Силино (ДДС района Силино города Москвы)"; "Упр. района
Вешняки (ДДС района Вешняки города Москвы)"; "Поселение Крюково (ДДС района Крюково города Москвы)";
"Поселение Матушкино (ДДС района Матушкино города Москвы)"; "Поселение Новогиреево (ДДС района
Новогиреево города Москвы)"; "Поселение Бирюлево Западное (ДДС района Бирюлево Западное города
Москвы)"; "Поселение Ивановский (ДДС Ивановского района города Москвы)"; "Поселение Ново-Переделкино
(ДДС района Ново-Переделкино города Москвы)"; "Поселение Восточное Дегунино (ДДС района Восточное
Дегунино города Москвы)"; "Поселение Ховрино (ДДС района Ховрино города Москвы)"; "Поселение Перово
(ДДС района Перово города Москвы)"; "Поселение Алтуфьевский (ДДС Алтуфьевского района города Москвы)";
"Поселение Можайский (ДДС Можайского района города Москвы)"; "Поселение Раменки (ДДС района Раменки
города Москвы)"; "Поселение Алексеевский (ДДС Алексеевского района города Москвы)"; "Поселение
Гагаринский (ДДС Гагаринского района города Москвы)"; "Поселение Обручевский (ДДС Обручевского района
города Москвы)"; "Поселение Зюзино (ДДС района Зюзино города Москвы)"; "Поселение Коньково (ДДС района
Коньково города Москвы)"; "Поселение Котловка (ДДС района Котловка города Москвы)"; "Поселение
Воскресенское (ДДС поселения Воскресенское в городе Москве)"; "Поселение Краснопахорское (ДДС поселения
Краснопахорское в городе Москве)"; "Поселение Вороновское (ДДС поселения Вороновское в городе Москве)".

**English:** Below the ~25 city-wide services, the picker continues with a long, near-uniform list of
one dispatch-service entry per Moscow district/settlement ("Поселение <name> (ДДС района <name> города
Москвы)" for "old Moscow" districts, "Поселение <name> (ДДС поселения <name> в городе Москве)" for New
Moscow/TiNAO settlements), interspersed with a few prefecture-level DDS entries (по округам — "ДДС
префектуры <округ> административного округа") and a block of per-okrug road-maintenance entries ("ГБУ
АД <округ>", e.g. ВАО/СВАО/ЮВАО/ЗелАО/ЮЗАО/ЮАО).

**Notes:** Sampling limitation stated in §1: only ~20 of the 55 scroll frames were viewed; the district
entries shown above are a representative sample of the pattern, not an exhaustive transcription of
every district. The Moscow city government recognizes roughly 125+ districts/settlements, consistent
with the scale of this list, but the exact total count in this specific dropdown was not verified row
by row.

### REQ-3044 — Классификатор: file/sheet structure and full column set

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Классификатор_происшествий_v_046_11_ДТУ_15_11_2024_искл_пожар_задымление.xlsx`, sheet "Лист1" |
| Speaker | organizer (document) |

**Verbatim (RU):** Single sheet "Лист1", dimensions A1:CL1308 (90 columns × 1308 rows). Header rows
1–3 (merged group headers row 1, sub-headers row 2, sub-sub-headers row 3), data from row 4 (category
headers) / row 5 (first data row) onward.

**Full column set (group header from row 1 → sub-header row 2 → sub-sub-header row 3, `—` = blank):**
A "Генерация номера"→"Г"; B →"п1"; C →"п2"; D →"п3"; E →"Номер"; F →"Группа происшествий Учет в
статистике в службе 112"; G "Блок, как происшествие отображается для специалиста службы 112 (типовые
признаки происшествия)"→"112 - Признак.1 (тип происшествия)"; H →"112-Признак.2"; I →"112-Признак.3";
J →"Дополнительные признаки (не влияют на тип происшествия)"; K →"Итоговый тип происшествия"; L
→"ТИП происшествия ЕКП 35"; M "Сценарий реагирования"; N "Главная служба"; O–U "Классификатор МЧС"
(O "Служба 101" →"Служба 101 (признак НД - НЕТ ДОСТУПА не выбран)"/"...выбран..."; Q "ОДС ПСЦ"→4
conditional sub-columns "другие признаки не выбраны"/"УЛ-УГРОЗА ЛЮДЯМ"/"ПП-ПОСТРАДАВШИЕ ПОГИБШИЕ"/
"НД-НЕТ ДОСТУПА"; U "МГПСС"); V–X "Классификатор МВД" (признак Правонарушение/Пострадавшие
не выбран / выбран Правонарушение / выбран Пострадавшие); Y–AA "Классификатор СМП" (Пострадавшие не
выбран / выбран / выбран, не на месте); AB–AC "Классификатор МОСГАЗ" (признак не выбран / газификация);
AD–AH "ЦЭМП" (признаки не выбраны / угроза людям / пострадавшие-погибшие / мед.помощь /
треб.эвакуация); AI–AJ "Классификатор ФСБ" (признак не выбран / >5 чел/ОД); AK "Классификатор
Мособлгаз"; AL "Автомобильные дороги"; AM–AO "Мосгортранс" (признак не выбран / постр-погибшие /
перекрытие движение); AP "Гор. Хозяйство"; AQ–AT "ГОРМОСТ" (признак не выбран / тоннель / пеш / ав);
AU "Канал имени Москвы"; AV–AW "МГТС" (реагирование всегда / на объектах связи); AX "Метро"; AY
"Мосводоканал"; AZ "МОЭК"; BA "МОЭСК (ПАО «Россети Московский регион»)"; BB "ОЭК"; BC "Мослифт"; BD
"ЦОДД"; BE "Деп. ЖКХ"; BF–BG "Департамент РБиПК (ГКУ МОСБЕЗ)" (Дежурная служба АРМ-112 / МКП,
Аналитика (Старый КРИМ)); BH "Аппарат МЭРА"; BI "Москоллектор"; BJ "РЖД"; BK "Департамент образования";
BL "Центррегионводхоз (Московско-Окское БВУ)"; BM "Военная комендатура"; BN "ОАТИ"; BO "Мосводосток";
BP "Департамент ППиООС"; BQ "ОД Департамент ТСЗН"; BR "РСВО"; BS "ЭВАЖД"; BT "МСППН"; BU "ДТУ_Р
(Ритуал)"; BV "ДТУ"; BW "Росгвардия"; BX "Территориальные ОИВ"; BY "Территориальные ОИВ ТиНАО"; BZ
"Автомобильные дороги АО г.Москвы"; CA–CB "Департамент строительства города Москвы" (признак не
выбран / стройка); CC "Комитет ветеринарии"; CD "Мосжилинспекция"; CE "Департамент культуры" (объект
из перечня); CF "ГКУ ЦСА имени Е.П.Глинки"; CG "ГКУ НТУ"; CH "ФСО"; CI "ГУП МСР" (КУБ); CJ "Комитет по
туризму г.Москвы"; CK–CL "ДГП (Департамент градостроительной политики)" (интеграция / АРМ-112).

**English:** 12 classification columns (A–L: numeric group/sub-group codes, the incident's stable
numeric code "Номер", the group name, up to 3 "признак" (feature) fields, additional features, the
final derived incident-type string, and its mapping to a separate "ЕКП 35" classifier), followed by a
78-column routing/notification matrix (columns M–CL) — one or more columns per receiving organization
(≈65 distinct organizations/services, several with 2–6 conditional sub-columns) — recording whether/how
each row's incident routes to that organization depending on which features are set.

---

### REQ-3045 — Классификатор: 24 top-level categories with row counts

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Классификатор_....xlsx`, column F category-header rows |
| Speaker | organizer (document) |

**English + verbatim category names (RU), full table, all 1281 data rows accounted for:**

| # | Top-level category (Группа происшествий) | Rows (Номер codes) | Data-row count |
|---|---|---|---|
| 1 | Пожары и задымления | 5-275 | 271 |
| 2 | ДТП | 277-323 | 47 |
| 3 | Взрывы | 325-369 | 45 |
| 4 | Угрозы взрывов и террористических актов | 371-399 | 29 |
| 5 | Обрушения | 401-440 | 40 |
| 6 | Угрозы обрушений | 442-471 | 30 |
| 7 | Опасные геологические, гидрологические и метеорологические явления | 473-502 | 30 |
| 8 | Экологические происшествия | 504-518 | 15 |
| 9 | Аварии на гидротехнических сооружениях | 520-521 | 2 |
| 10 | Аварии на опасных и производственных объектах | 523-540 | 18 |
| 11 | Угрозы выброса опасных веществ | 542-573 | 32 |
| 12 | Аварии и происшествия на транспортных объектах | 575-637 | 63 |
| 13 | Запах газа | 639-670 | 32 |
| 14 | Аварии и происшествия в городском хозяйстве | 672-864 | 193 |
| 15 | Нарушение правопорядка | 866-1039 | 174 |
| 16 | Проблемы на дороге | 1041-1070 | 30 |
| 17 | Человек в опасности | 1072-1156 | 85 |
| 18 | Ребенок в опасности | 1158-1173 | 16 |
| 19 | Смертельный исход человека | 1175-1205 | 31 |
| 20 | Социальная помощь | 1207-1214 | 8 |
| 21 | Происшествия с участием животных | 1216-1228 | 13 |
| 22 | Оказание медицинской скорой и неотложной помощи | 1230-1288 | 59 |
| 23 | Прочие происшествия | 1290-1295 | 6 |
| 24 | БПЛА | 1297-1308 | 12 |
| **Total** | | rows 5-1308 | **1281** |

**Notes:** "Пожары и задымления" (Fires and smoke) is the largest category (271 rows, 21% of all
1281). "Аварии и происшествия в городском хозяйстве" (City-services accidents/incidents, 193 rows) and
"Нарушение правопорядка" (Public-order violations, 174 rows) are the next largest.

---

### REQ-3046 — Классификатор: "Пожары и задымления" — subgroup breakdown by location (п1)

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Классификатор_....xlsx`, rows 5–275, column B ("п1") cross-tabulated with column G ("Признак1") |
| Speaker | organizer (document) |

| п1 code | Location group (Признак1) | Data-row count |
|---|---|---|
| 1 | на улице (street) | 23 |
| 2 | транспорт (transport) | 28 |
| 3 | метро (metro) | 7 |
| 4 | МЦК (Moscow Central Circle rail) | 7 |
| 5 | жилой дом (residential building) | 35 |
| 6 | объект (facility/site) | 27 |
| 99 | Не отображается оператору 112 (not shown to the 112 operator — MChS-only premises-type list, alphabetical, e.g. Пожар: Автобаза, Автовокзал, Автокомбинат, Автосалон, Автосервис, Автостоянка, Ангар, Аптека, Ателье, Аэродром, Аэровокзал, Баня, Бар, Бассейн, Башня, Беседка, ... continuing alphabetically) | 144 |
| **Total** | | **271** |

**English:** Of the 271 fire/smoke rows, 127 (23+28+7+7+35+27) are reachable from the 112 operator's
card (matching the "Где" location buttons documented in REQ-3002: street/transport/metro/MCC/
residential/facility), while 144 rows (53%) are flagged "Не отображается оператору 112" — an
alphabetical premises-type list (e.g. "Пожар: Автобаза", "...Автовокзал", "...Автокомбинат", ...,
continuing alphabetically) used only downstream (e.g. by the МЧС/fire-brigade classifier column) and
never shown as a choice to the 112 call-taker.

### REQ-3047 — Классификатор: "Пожары и задымления" category — full verbatim (271 rows)

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Классификатор_....xlsx`, rows 5–275 (all 271 data rows of category 1, columns A,B,C,D,E,G,H,I,J,K,L,O) |
| Speaker | organizer (document) |

Columns: Г (group #) . п1/п2/п3 (sub-codes) . Номер (stable numeric incident code) . Признак1/2/3
(the up-to-3 selectable features that build this row) . Доп.признаки (additional non-classifying
features) . Итоговый_тип (final derived incident-type string, shown to the 112 operator) . ЕКП35
(mapping to the separate "ЕКП 35" classifier) . Служба101 (routing outcome for Служба 101, the fire
brigade — repeats ЕКП35 for almost every row in this category).

**Verbatim, full table (RU), all 271 rows, document order:**

| Г | п1 | п2 | п3 | Номер | Признак1 | Признак2 | Признак3 | Доп.признаки | Итоговый_тип | ЕКП35 | Служба101 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 1010101 | на улице | мусор | открытое пламя |  | пожар: мусор | пожар: мусор | пожар: мусор |
| 1 | 1 | 1 | 2 | 1010102 | на улице | мусор | дым |  | задымление: мусор | пожар: мусор | пожар: мусор |
| 1 | 1 | 2 | 1 | 1010201 | на улице | Трава | открытое пламя |  | пожар: трава | пожар: трава, пух | пожар: трава, пух |
| 1 | 1 | 2 | 2 | 1010202 | на улице | Трава | дым |  | задымление: трава | пожар: трава, пух | пожар: трава, пух |
| 1 | 1 | 3 | 1 | 1010301 | на улице | Пух | открытое пламя |  | пожар: пух | пожар: трава, пух | пожар: трава, пух |
| 1 | 1 | 3 | 2 | 1010302 | на улице | Пух | дым |  | задымление: пух | пожар: трава, пух | пожар: трава, пух |
| 1 | 1 | 4 | 1 | 1010401 | на улице | Парк | открытое пламя |  | пожар: парк | пожар: лесопосадки | пожар: лесопосадки |
| 1 | 1 | 4 | 2 | 1010402 | на улице | Парк | дым |  | задымление: парк | пожар: лесопосадки | пожар: лесопосадки |
| 1 | 1 | 5 | 1 | 1010501 | на улице | Лес | открытое пламя |  | пожар: лес | пожар: лесопосадки | пожар: лесопосадки |
| 1 | 1 | 5 | 2 | 1010502 | на улице | Лес | дым |  | задымление: лес | пожар: лесопосадки | пожар: лесопосадки |
| 1 | 1 | 6 | 1 | 1010601 | на улице | торф | открытое пламя |  | пожар: торф | пожар: торф | пожар: торф |
| 1 | 1 | 6 | 2 | 1010602 | на улице | торф | дым |  | задымление: торф | пожар: торф | пожар: торф |
| 1 | 1 | 7 | 1 | 1010701 | на улице | Мачта освещения | открытое пламя |  | пожар: мачта освещения | пожар: электрические сети | пожар: электрические сети |
| 1 | 1 | 7 | 2 | 1010702 | на улице | Мачта освещения | дым |  | задымление: мачта освещения | пожар: электрические сети | пожар: электрические сети |
| 1 | 1 | 8 | 1 | 1010801 | на улице | опора контактной сети | открытое пламя |  | пожар: опора контактной сети | НЕТ в ЕКП | пожар: электрические сети |
| 1 | 1 | 8 | 2 | 1010802 | на улице | опора контактной сети | дым |  | задымление: опора контактной сети | НЕТ в ЕКП | пожар: электрические сети |
| 1 | 1 | 9 | 1 | 1010901 | на улице | ЛЭП | открытое пламя |  | пожар: ЛЭП | пожар: электрические сети | пожар: электрические сети |
| 1 | 1 | 9 | 2 | 1010902 | на улице | ЛЭП | дым |  | задымление: ЛЭП | пожар: электрические сети | пожар: электрические сети |
| 1 | 1 | 10 | 1 | 1011001 | на улице | Провода | открытое пламя |  | пожар: провода на улице | пожар: электрические сети | пожар: электрические сети |
| 1 | 1 | 10 | 2 | 1011002 | на улице | Провода | дым |  | задымление: провода на улице | пожар: электрические сети | пожар: электрические сети |
| 1 | 1 | 11 | 0 | 1011100 | на улице | запах гари |  |  | запах гари на улице | НЕТ в ЕКП | пожар |
| 1 | 1 | 12 | 1 | 1011201 | на улице | дерево, деревья | открытое пламя |  | пожар: дерево, деревья | пожар: дерево | пожар: дерево |
| 1 | 1 | 12 | 2 | 1011202 | на улице | дерево, деревья | дым |  | задымление: дерево, деревья | пожар: дерево | пожар: дерево |
| 1 | 2 | 1 | 1 | 1020101 | транспорт | общественный транспорт | открытое пламя |  | пожар: автобус | пожар: автобус | Пожар: Общественный транспорт |
| 1 | 2 | 1 | 2 | 1020102 | транспорт | общественный транспорт | дым |  | задымление: автобус | пожар: автобус | Пожар: Общественный транспорт |
| 1 | 2 | 2 | 1 | 1020201 | транспорт | автомашина | открытое пламя |  | пожар: машина | Пожар: машина | Пожар: Транспортное средство |
| 1 | 2 | 2 | 2 | 1020202 | транспорт | автомашина | дым |  | задымление: машина | Пожар: машина | Пожар: Транспортное средство |
| 1 | 2 | 3 | 1 | 1020301 | транспорт | ДТП с пожаром | открытое пламя |  | пожар при ДТП | ДТП с пожаром | Пожар: Транспортное средство |
| 1 | 2 | 3 | 2 | 1020302 | транспорт | ДТП с пожаром | дым |  | задымление при ДТП | ДТП с пожаром | Пожар: Транспортное средство |
| 1 | 2 | 4 | 1 | 1020401 | транспорт | опасный груз | открытое пламя |  | пожар: опасный груз | Пожар: машина | Пожар: Транспортное средство |
| 1 | 2 | 4 | 2 | 1020402 | транспорт | опасный груз | дым |  | задымление: опасный груз | Пожар: машина | Пожар: Транспортное средство |
| 1 | 2 | 5 | 1 | 1020501 | транспорт | воздушный транспорт | открытое пламя |  | пожар: воздушный транспорт | НЕТ В ЕКП | Пожар: Воздушное судно |
| 1 | 2 | 5 | 2 | 1020502 | транспорт | воздушный транспорт | дым |  | задымление: воздушный транспорт | НЕТ В ЕКП | Пожар: Воздушное судно |
| 1 | 2 | 6 | 1 | 1020601 | транспорт | Аэропорт | открытое пламя |  | пожар: аэропорт | пожар: аэропорт | пожар: аэропорт |
| 1 | 2 | 6 | 2 | 1020602 | транспорт | Аэропорт | дым |  | задымление: аэропорт | пожар: аэропорт | пожар: аэропорт |
| 1 | 2 | 7 | 1 | 1020701 | транспорт | ж/д транспорт | открытое пламя |  | пожар: жд транспорт | пожар: ж-д транспорт | пожар: ж-д транспорт |
| 1 | 2 | 7 | 2 | 1020702 | транспорт | ж/д транспорт | дым |  | задымление: жд транспорт | пожар: ж-д транспорт | пожар: ж-д транспорт |
| 1 | 2 | 8 | 1 | 1020801 | транспорт | Вокзал ж/д, платформа жд | открытое пламя |  | пожар: вокзал | пожар: вокзал | пожар: вокзал |
| 1 | 2 | 8 | 2 | 1020802 | транспорт | Вокзал ж/д, платформа жд | дым |  | задымление: вокзал | пожар: вокзал | пожар: вокзал |
| 1 | 2 | 9 | 1 | 1020901 | транспорт | транспорт прочее | открытое пламя |  | пожар: транспорт (прочее) | Пожар: машина | Пожар: Транспортное средство |
| 1 | 2 | 9 | 2 | 1020902 | транспорт | транспорт прочее | дым |  | задымление: транспорт (прочее) | Пожар: машина | Пожар: Транспортное средство |
| 1 | 2 | 10 | 1 | 1021001 | транспорт | водный | открытое пламя |  | пожар: водный транспорт | НЕТ в ЕКП | Пожар: Морское/речное судно |
| 1 | 2 | 10 | 2 | 1021002 | транспорт | водный | дым |  | задымление: водный транспорт | НЕТ в ЕКП | Пожар: Морское/речное судно |
| 1 | 2 | 11 | 1 | 1021101 | транспорт | мост | открытое пламя |  | пожар: мост | НЕТ в ЕКП | Пожар: Мост |
| 1 | 2 | 11 | 2 | 1021102 | транспорт | мост | дым |  | задымление: мост | НЕТ в ЕКП | Пожар: Мост |
| 1 | 2 | 12 | 1 | 1021201 | транспорт | эстакада | открытое пламя |  | пожар: эстакада | НЕТ в ЕКП | Пожар: Мост |
| 1 | 2 | 12 | 2 | 1021202 | транспорт | эстакада | дым |  | задымление: эстакада | НЕТ в ЕКП | Пожар: Мост |
| 1 | 2 | 13 | 1 | 1021301 | транспорт | тоннель | открытое пламя |  | пожар: тоннель | пожар: тоннель | Пожар: Тоннель |
| 1 | 2 | 13 | 2 | 1021302 | транспорт | тоннель | дым |  | задымление: тоннель | пожар: тоннель | Пожар: Тоннель |
| 1 | 2 | 14 | 1 | 1021401 | транспорт | переход подземный / наземный | открытое пламя |  | пожар: переход | пожар: пешеходный переход | пожар |
| 1 | 2 | 14 | 2 | 1021402 | транспорт | переход подземный / наземный | дым |  | задымление: переход | пожар: пешеходный переход | пожар |
| 1 | 3 | 0 | 1 | 1030001 | метро |  | открытое пламя |  | пожар: метро | пожар: метро | пожар: метро |
| 1 | 3 | 0 | 2 | 1030002 | метро |  | дым |  | задымление: метро | пожар: метро | пожар: метро |
| 1 | 3 | 1 | 1 | 1030101 | метро | вагон/поезд,  | открытое пламя |  | пожар: метро (вагон, поезд) | пожар: подвижной состав метро | пожар: метро |
| 1 | 3 | 1 | 2 | 1030102 | метро | вагон/поезд,  | дым |  | задымление: метро (вагон, поезд) | пожар: подвижной состав метро | пожар: метро |
| 1 | 3 | 2 | 1 | 1030201 | метро | станция/вестибюль, тоннель / перегон, переход, платформа, эскалатор, прочее | открытое пламя |  | пожар: метро (станция, тоннель) | пожар: метро | пожар: метро |
| 1 | 3 | 2 | 2 | 1030202 | метро | станция/вестибюль, тоннель / перегон, переход, платформа, эскалатор, прочее | дым |  | задымление: метро (станция, тоннель) | пожар: метро | пожар: метро |
| 1 | 3 | 3 | 0 | 1030300 | метро | сработала сигнализация |  |  | пожарная сигнализация (метро) | пожар: сигнализация | пожар: сигнализация |
| 1 | 4 | 0 | 1 | 1040001 | МЦК |  | открытое пламя |  | пожар: МЦК | пожар: метро | Пожар: МЦК/МЦД |
| 1 | 4 | 0 | 2 | 1040002 | МЦК |  | дым |  | задымление: МЦК | пожар: метро | Пожар: МЦК/МЦД |
| 1 | 4 | 1 | 1 | 1040101 | МЦК | вагон/поезд,  | открытое пламя |  | пожар: МЦК (вагон, поезд) | пожар: подвижной состав метро | Пожар: МЦК/МЦД |
| 1 | 4 | 1 | 2 | 1040102 | МЦК | вагон/поезд,  | дым |  | задымление: МЦК (вагон, поезд) | пожар: подвижной состав метро | Пожар: МЦК/МЦД |
| 1 | 4 | 2 | 1 | 1040201 | МЦК | станция/вестибюль, тоннель / перегон, переход, платформа, эскалатор, прочее | открытое пламя |  | пожар: МЦК (станция, перегон) | пожар: метро | Пожар: МЦК/МЦД |
| 1 | 4 | 2 | 2 | 1040202 | МЦК | станция/вестибюль, тоннель / перегон, переход, платформа, эскалатор, прочее | дым |  | задымление: МЦК (станция, перегон) | пожар: метро | Пожар: МЦК/МЦД |
| 1 | 4 | 3 | 0 | 1040300 | МЦК | сработала сигнализация |  |  | пожарная сигнализация (МЦК) | пожар: сигнализация | пожар: сигнализация |
| 1 | 5 | 0 | 1 | 1050001 | жилой дом |  | открытое пламя |  | пожар: жилой дом | пожар: квартира | пожар: квартира |
| 1 | 5 | 1 | 1 | 1050101 | жилой дом | квартира | открытое пламя |  | пожар: квартира | пожар: квартира | пожар: квартира |
| 1 | 5 | 2 | 1 | 1050201 | жилой дом | балкон | открытое пламя |  | пожар: балкон | пожар: балкон | пожар: балкон |
| 1 | 5 | 3 | 1 | 1050301 | жилой дом | газовая колонка | открытое пламя |  | пожар: газовая колонка | пожар: газовая колонка | пожар: квартира |
| 1 | 5 | 4 | 1 | 1050401 | жилой дом | газовая плита | открытое пламя |  | пожар: газовая плита | пожар: газовая плита | пожар: квартира |
| 1 | 5 | 5 | 1 | 1050501 | жилой дом | лифт | открытое пламя |  | пожар: лифт | пожар: лифт | пожар: лифт |
| 1 | 5 | 6 | 1 | 1050601 | жилой дом | мусоропровод | открытое пламя |  | пожар: мусоропровод | пожар: мусоропровод | пожар: мусоропровод |
| 1 | 5 | 7 | 1 | 1050701 | жилой дом | подъезд | открытое пламя |  | пожар: подъезд | пожар: подъезд | пожар: подъезд |
| 1 | 5 | 16 | 0 | 1051600 | жилой дом | сигнализация |  |  | пожарная сигнализация (жилой дом) | пожар: сигнализация | пожар: сигнализация |
| 1 | 5 | 8 | 1 | 1050801 | жилой дом | счетчик электричества | открытое пламя |  | пожар: счетчик электричества | пожар: счетчик электричества | пожар: счетчик электричества |
| 1 | 5 | 9 | 1 | 1050901 | жилой дом | частный дом | открытое пламя |  | пожар: частный дом | пожар: частный дом | пожар: частный дом |
| 1 | 5 | 10 | 1 | 1051001 | жилой дом | электрическая проводка | открытое пламя |  | пожар: электрическая проводка | пожар: электрическая проводка | пожар: электрическая проводка |
| 1 | 5 | 11 | 1 | 1051101 | жилой дом | электрощит | открытое пламя |  | пожар: электрощит | пожар: электрощит | пожар: электрощит |
| 1 | 5 | 12 | 1 | 1051201 | жилой дом | лестничная клетка | открытое пламя |  | пожар: лестничная клетка | пожар: лестничная клетка | пожар: лестничная клетка |
| 1 | 5 | 13 | 1 | 1051301 | жилой дом | подвал | открытое пламя |  | пожар: подвал | пожар: подвал | пожар: подвал |
| 1 | 5 | 14 | 1 | 1051401 | жилой дом | дача | открытое пламя |  | пожар: дача | пожар: дача | пожар: дача |
| 1 | 5 | 15 | 1 | 1051501 | жилой дом | прочие внутридомовые объекты | открытое пламя |  | пожар: жилой дом (прочее) | пожар: квартира | пожар: квартира |
| 1 | 5 | 0 | 2 | 1050002 | жилой дом |  | дым |  | задымление: жилой дом | пожар: квартира | пожар: квартира |
| 1 | 5 | 1 | 2 | 1050102 | жилой дом | квартира | дым |  | задымление: квартира | пожар: квартира | пожар: квартира |
| 1 | 5 | 2 | 2 | 1050202 | жилой дом | балкон | дым |  | задымление: балкон | пожар: балкон | пожар: балкон |
| 1 | 5 | 3 | 2 | 1050302 | жилой дом | газовая колонка | дым |  | задымление: газовая колонка | пожар: газовая колонка | пожар: квартира |
| 1 | 5 | 4 | 2 | 1050402 | жилой дом | газовая плита | дым |  | задымление: газовая плита | пожар: газовая плита | пожар: квартира |
| 1 | 5 | 5 | 2 | 1050502 | жилой дом | лифт | дым |  | задымление: лифт | пожар: лифт | пожар: лифт |
| 1 | 5 | 6 | 2 | 1050602 | жилой дом | мусоропровод | дым |  | задымление: мусоропровод | пожар: мусоропровод | пожар: мусоропровод |
| 1 | 5 | 7 | 2 | 1050702 | жилой дом | подъезд | дым |  | задымление: подъезд | пожар: подъезд | пожар: подъезд |
| 1 | 5 | 8 | 2 | 1050802 | жилой дом | счетчик электричества | дым |  | задымление: счетчик электричества | пожар: счетчик электричества | пожар: счетчик электричества |
| 1 | 5 | 9 | 2 | 1050902 | жилой дом | частный дом | дым |  | задымление: частный дом | пожар: частный дом | пожар: частный дом |
| 1 | 5 | 10 | 2 | 1051002 | жилой дом | электрическая проводка | дым |  | задымление: электрическая проводка | пожар: электрическая проводка | пожар: электрическая проводка |
| 1 | 5 | 11 | 2 | 1051102 | жилой дом | электрощит | дым |  | задымление: электрощит | пожар: электрощит | пожар: электрощит |
| 1 | 5 | 12 | 2 | 1051202 | жилой дом | лестничная клетка | дым |  | задымление: лестничная клетка | пожар: лестничная клетка | пожар: лестничная клетка |
| 1 | 5 | 13 | 2 | 1051302 | жилой дом | подвал | дым |  | задымление: подвал | пожар: подвал | пожар: подвал |
| 1 | 5 | 14 | 2 | 1051402 | жилой дом | дача | дым |  | задымление: дача | пожар: дача | пожар: дача |
| 1 | 5 | 15 | 2 | 1051502 | жилой дом | прочие внутридомовые объекты | дым |  | задымление: жилой дом (прочие) | пожар: квартира | пожар: квартира |
| 1 | 5 | 1 | 3 | 1050103 | жилой дом | квартира | запах гари |  | запах гари в доме | запах гари в квартире | пожар: квартира |
| 1 | 5 | 7 | 3 | 1050703 | жилой дом | подъезд | запах гари |  | запах гари в подъезде | запах гари в подъезде | пожар: подъезд |
| 1 | 6 | 1 | 1 | 1060101 | объект | учебное | открытое пламя |  | Пожар: учебное заведение | пожар: школа | пожар: школа |
| 1 | 6 | 1 | 2 | 1060102 | объект | учебное | дым |  | задымление: учебное заведение | пожар: школа | пожар: школа |
| 1 | 6 | 2 | 1 | 1060201 | объект | лечебное | открытое пламя |  | пожар: лечебное заведение | пожар: больница | пожар: больница |
| 1 | 6 | 2 | 2 | 1060202 | объект | лечебное | дым |  | задымление: лечебное заведение | пожар: больница | пожар: больница |
| 1 | 6 | 3 | 1 | 1060301 | объект | административное | открытое пламя |  | пожар: административное здание | пожар: административное здание | пожар: административное здание |
| 1 | 6 | 3 | 2 | 1060302 | объект | административное | дым |  | задымление: административное здание | пожар: административное здание | пожар: административное здание |
| 1 | 6 | 4 | 1 | 1060401 | объект | общестенное место | открытое пламя |  | пожар: общественное место | пожар: гостиница | пожар: административное здание |
| 1 | 6 | 4 | 2 | 1060402 | объект | общестенное место | дым |  | задымление: общественное место | пожар: гостиница | пожар: административное здание |
| 1 | 6 | 5 | 1 | 1060501 | объект | опасный | открытое пламя |  | пожар: опасный объект | пожар: завод | пожар: завод |
| 1 | 6 | 5 | 2 | 1060502 | объект | опасный | дым |  | задымление: опасный объект | пожар: завод | пожар: завод |
| 1 | 6 | 6 | 0 | 1060600 | объект | газопровод |  |  | пожар: газопровод | пожар: газопровод | пожар |
| 1 | 6 | 7 | 0 | 1060700 | объект | газохранилище |  |  | пожар: газохранилище | пожар: газопровод | пожар |
| 1 | 6 | 8 | 0 | 1060800 | объект | нефтепровод |  |  | пожар: нефтебаза | пожар: нефтебаза | пожар: нефтебаза |
| 1 | 6 | 9 | 0 | 1060900 | объект | нефтехранилище |  |  | пожар: нефтехранилище | пожар: нефтебаза | пожар: нефтебаза |
| 1 | 6 | 10 | 1 | 1061001 | объект | наземные коммуникации | открытое пламя |  | пожар: наземные коммуникации | пожар: пешеходный переход | пожар |
| 1 | 6 | 10 | 2 | 1061002 | объект | наземные коммуникации | дым |  | задымление: наземные коммуникации | пожар: пешеходный переход | пожар |
| 1 | 6 | 11 | 1 | 1061101 | объект | подземные коммуникации | открытое пламя |  | пожар: подземные коммуникации | пожар: подземные коммуникации | пожар: подземные коммуникации |
| 1 | 6 | 11 | 2 | 1061102 | объект | подземные коммуникации | дым |  | задымление: подземные коммуникации | пожар: подземные коммуникации | пожар: подземные коммуникации |
| 1 | 6 | 12 | 1 | 1061201 | объект | гидросооружение | открытое пламя |  | пожар: гидросооружение | НЕТ в ЕКП | пожар |
| 1 | 6 | 12 | 2 | 1061202 | объект | гидросооружение | дым |  | задымление:  гидросооружение | НЕТ в ЕКП | пожар |
| 1 | 6 | 13 | 0 | 1061300 | объект | сигнализация |  |  | пожарная сигнализация на объекте | пожар: сигнализация | пожар: сигнализация |
| 1 | 6 | 14 | 1 | 1061401 | объект | производство | открытое пламя |  | пожар: производство | Пожар: Производственный комплекс | Пожар: Производственный комплекс |
| 1 | 6 | 14 | 2 | 1061402 | объект | производство | дым |  | задымление: производство | Пожар: Производственный комплекс | Пожар: Производственный комплекс |
| 1 | 6 | 15 | 1 | 1061501 | объект | АЗС | открытое пламя |  | пожар: АЗС | Пожар: Азс | Пожар: Азс |
| 1 | 6 | 15 | 2 | 1061502 | объект | АЗС | дым |  | задымление:  АЗС | Пожар: Азс | Пожар: Азс |
| 1 | 6 | 16 | 1 | 1061601 | объект | прочие объекты | открытое пламя |  | Пожар: прочие объекты | Пожар | Пожар |
| 1 | 6 | 16 | 2 | 1061602 | объект | прочие объекты | дым |  | задымление:  прочие объекты | Пожар | Пожар |
| 1 | 99 | 0 | 2 | 1990002 | Не отображается оператору 112 |  |  |  | Пожар: Автобаза | Пожар: Автобаза | Пожар: Автобаза |
| 1 | 99 | 0 | 4 | 1990004 | Не отображается оператору 112 |  |  |  | Пожар: Автовокзал | Пожар: Автовокзал | Пожар: Автовокзал |
| 1 | 99 | 0 | 5 | 1990005 | Не отображается оператору 112 |  |  |  | Пожар: Автокомбинат | Пожар: Автокомбинат | Пожар: Автокомбинат |
| 1 | 99 | 0 | 6 | 1990006 | Не отображается оператору 112 |  |  |  | Пожар: Автосалон | Пожар: Автосалон | Пожар: Автосалон |
| 1 | 99 | 0 | 7 | 1990007 | Не отображается оператору 112 |  |  |  | Пожар: Автосервис | Пожар: Автосервис | Пожар: Автосервис |
| 1 | 99 | 0 | 8 | 1990008 | Не отображается оператору 112 |  |  |  | Пожар: Автостоянка | Пожар: Автостоянка | Пожар: Автостоянка |
| 1 | 99 | 0 | 11 | 1990011 | Не отображается оператору 112 |  |  |  | Пожар: Ангар | Пожар: Ангар | Пожар: Ангар |
| 1 | 99 | 0 | 12 | 1990012 | Не отображается оператору 112 |  |  |  | Пожар: Аптека | Пожар: Аптека | Пожар: Аптека |
| 1 | 99 | 0 | 13 | 1990013 | Не отображается оператору 112 |  |  |  | Пожар: Ателье | Пожар: Ателье | Пожар: Ателье |
| 1 | 99 | 0 | 16 | 1990016 | Не отображается оператору 112 |  |  |  | Пожар: Аэродром | Пожар: Аэродром | Пожар: Аэродром |
| 1 | 99 | 0 | 15 | 1990015 | Не отображается оператору 112 |  |  |  | Пожар: Аэровокзал | Пожар: Аэровокзал | Пожар: Аэровокзал |
| 1 | 99 | 0 | 19 | 1990019 | Не отображается оператору 112 |  |  |  | Пожар: Баня | Пожар: Баня | Пожар: Баня |
| 1 | 99 | 0 | 20 | 1990020 | Не отображается оператору 112 |  |  |  | Пожар: Бар | Пожар: Бар | Пожар: Бар |
| 1 | 99 | 0 | 21 | 1990021 | Не отображается оператору 112 |  |  |  | Пожар: Бассейн | Пожар: Бассейн | Пожар: Бассейн |
| 1 | 99 | 0 | 22 | 1990022 | Не отображается оператору 112 |  |  |  | Пожар: Башня | Пожар: Башня | Пожар: Башня |
| 1 | 99 | 0 | 23 | 1990023 | Не отображается оператору 112 |  |  |  | Пожар: Беседка | Пожар: Беседка | Пожар: Беседка |
| 1 | 99 | 0 | 24 | 1990024 | Не отображается оператору 112 |  |  |  | Пожар: Библиотека | Пожар: Библиотека | Пожар: Библиотека |
| 1 | 99 | 0 | 25 | 1990025 | Не отображается оператору 112 |  |  |  | Пожар: Биржа | Пожар: Биржа | Пожар: Биржа |
| 1 | 99 | 0 | 26 | 1990026 | Не отображается оператору 112 |  |  |  | Пожар: Бойлерная | Пожар: Бойлерная | Пожар: Бойлерная |
| 1 | 99 | 0 | 28 | 1990028 | Не отображается оператору 112 |  |  |  | Пожар: Бомбоубежище | Пожар: Бомбоубежище | Пожар: Бомбоубежище |
| 1 | 99 | 0 | 29 | 1990029 | Не отображается оператору 112 |  |  |  | Пожар: Будка консъержки | Пожар: Будка консъержки | Пожар: Будка консъержки |
| 1 | 99 | 0 | 30 | 1990030 | Не отображается оператору 112 |  |  |  | Пожар: Бытовка | Пожар: Бытовка | Пожар: Бытовка |
| 1 | 99 | 0 | 31 | 1990031 | Не отображается оператору 112 |  |  |  | Пожар: Вагон электрички (вагон электропоезда) | Пожар: Вагон электрички (вагон электропоезда) | Пожар: Вагон электрички (вагон электропоезда) |
| 1 | 99 | 0 | 32 | 1990032 | Не отображается оператору 112 |  |  |  | Пожар: Велотрек | Пожар: Велотрек | Пожар: Велотрек |
| 1 | 99 | 0 | 34 | 1990034 | Не отображается оператору 112 |  |  |  | Пожар: Войсковая часть | Пожар: Войсковая часть | Пожар: Войсковая часть |
| 1 | 99 | 0 | 36 | 1990036 | Не отображается оператору 112 |  |  |  | Пожар: Выселенное здание | Пожар: Выселенное здание | Пожар: Выселенное здание |
| 1 | 99 | 0 | 37 | 1990037 | Не отображается оператору 112 |  |  |  | Пожар: Вытрезвитель | Пожар: Вытрезвитель | Пожар: Вытрезвитель |
| 1 | 99 | 0 | 40 | 1990040 | Не отображается оператору 112 |  |  |  | Пожар: Газовая тепловая станция | Пожар: Газовая тепловая станция | Пожар: Газовая тепловая станция |
| 1 | 99 | 0 | 42 | 1990042 | Не отображается оператору 112 |  |  |  | Пожар: Галерея | Пожар: Галерея | Пожар: Галерея |
| 1 | 99 | 0 | 43 | 1990043 | Не отображается оператору 112 |  |  |  | Пожар: Гараж | Пожар: Гараж | Пожар: Гараж |
| 1 | 99 | 0 | 44 | 1990044 | Не отображается оператору 112 |  |  |  | Пожар: Гимназия | Пожар: Гимназия | Пожар: Гимназия |
| 1 | 99 | 0 | 45 | 1990045 | Не отображается оператору 112 |  |  |  | Пожар: Голубятня | Пожар: Голубятня | Пожар: Голубятня |
| 1 | 99 | 0 | 46 | 1990046 | Не отображается оператору 112 |  |  |  | Пожар: Госпиталь | Пожар: Госпиталь | Пожар: Госпиталь |
| 1 | 99 | 0 | 51 | 1990051 | Не отображается оператору 112 |  |  |  | Пожар: Детский сад | Пожар: Детский сад | Пожар: Детский сад |
| 1 | 99 | 0 | 52 | 1990052 | Не отображается оператору 112 |  |  |  | Пожар: Дом быта | Пожар: Дом быта | Пожар: Дом быта |
| 1 | 99 | 0 | 53 | 1990053 | Не отображается оператору 112 |  |  |  | Пожар: Дом культуры | Пожар: Дом культуры | Пожар: Дом культуры |
| 1 | 99 | 0 | 54 | 1990054 | Не отображается оператору 112 |  |  |  | Пожар: Дом отдыха | Пожар: Дом отдыха | Пожар: Дом отдыха |
| 1 | 99 | 0 | 55 | 1990055 | Не отображается оператору 112 |  |  |  | Пожар: Дом ребенка | Пожар: Дом ребенка | Пожар: Дом ребенка |
| 1 | 99 | 0 | 56 | 1990056 | Не отображается оператору 112 |  |  |  | Пожар: Дом-интернат | Пожар: Дом-интернат | Пожар: Дом-интернат |
| 1 | 99 | 0 | 59 | 1990059 | Не отображается оператору 112 |  |  |  | Пожар: Ж-д цистерна | Пожар: Ж-д цистерна | Пожар: Ж-д цистерна |
| 1 | 99 | 0 | 61 | 1990061 | Не отображается оператору 112 |  |  |  | Пожар: Замыкание электропроводки | Пожар: Замыкание электропроводки | Пожар: Замыкание электропроводки |
| 1 | 99 | 0 | 62 | 1990062 | Не отображается оператору 112 |  |  |  | Пожар: Зоопарк | Пожар: Зоопарк | Пожар: Зоопарк |
| 1 | 99 | 0 | 63 | 1990063 | Не отображается оператору 112 |  |  |  | Пожар: Игровой клуб | Пожар: Игровой клуб | Пожар: Игровой клуб |
| 1 | 99 | 0 | 64 | 1990064 | Не отображается оператору 112 |  |  |  | Пожар: Издательство | Пожар: Издательство | Пожар: Издательство |
| 1 | 99 | 0 | 65 | 1990065 | Не отображается оператору 112 |  |  |  | Пожар: Институт | Пожар: Институт | Пожар: Институт |
| 1 | 99 | 0 | 67 | 1990067 | Не отображается оператору 112 |  |  |  | Пожар: Кадетский корпус | Пожар: Кадетский корпус | Пожар: Кадетский корпус |
| 1 | 99 | 0 | 68 | 1990068 | Не отображается оператору 112 |  |  |  | Пожар: Кафе | Пожар: Кафе | Пожар: Кафе |
| 1 | 99 | 0 | 70 | 1990070 | Не отображается оператору 112 |  |  |  | Пожар: Киностудия | Пожар: Киностудия | Пожар: Киностудия |
| 1 | 99 | 0 | 71 | 1990071 | Не отображается оператору 112 |  |  |  | Пожар: Кинотеатр | Пожар: Кинотеатр | Пожар: Кинотеатр |
| 1 | 99 | 0 | 72 | 1990072 | Не отображается оператору 112 |  |  |  | Пожар: Кладбище | Пожар: Кладбище | Пожар: Кладбище |
| 1 | 99 | 0 | 73 | 1990073 | Не отображается оператору 112 |  |  |  | Пожар: Клиника | Пожар: Клиника | Пожар: Клиника |
| 1 | 99 | 0 | 74 | 1990074 | Не отображается оператору 112 |  |  |  | Пожар: Клуб | Пожар: Клуб | Пожар: Клуб |
| 1 | 99 | 0 | 75 | 1990075 | Не отображается оператору 112 |  |  |  | Пожар: Книгохранилище | Пожар: Книгохранилище | Пожар: Книгохранилище |
| 1 | 99 | 0 | 76 | 1990076 | Не отображается оператору 112 |  |  |  | Пожар: Козырек подъезда | Пожар: Козырек подъезда | Пожар: Козырек подъезда |
| 1 | 99 | 0 | 77 | 1990077 | Не отображается оператору 112 |  |  |  | Пожар: Колледж | Пожар: Колледж | Пожар: Колледж |
| 1 | 99 | 0 | 78 | 1990078 | Не отображается оператору 112 |  |  |  | Пожар: Комбинат | Пожар: Комбинат | Пожар: Комбинат |
| 1 | 99 | 0 | 79 | 1990079 | Не отображается оператору 112 |  |  |  | Пожар: Консерватория | Пожар: Консерватория | Пожар: Консерватория |
| 1 | 99 | 0 | 80 | 1990080 | Не отображается оператору 112 |  |  |  | Пожар: Конюшня | Пожар: Конюшня | Пожар: Конюшня |
| 1 | 99 | 0 | 81 | 1990081 | Не отображается оператору 112 |  |  |  | Пожар: Костер | Пожар: Костер | Пожар: Костер |
| 1 | 99 | 0 | 82 | 1990082 | Не отображается оператору 112 |  |  |  | Пожар: Котельная | Пожар: Котельная | Пожар: Котельная |
| 1 | 99 | 0 | 83 | 1990083 | Не отображается оператору 112 |  |  |  | Пожар: Крыша | Пожар: Крыша | Пожар: Крыша |
| 1 | 99 | 0 | 84 | 1990084 | Не отображается оператору 112 |  |  |  | Пожар: Лаборатория | Пожар: Лаборатория | Пожар: Лаборатория |
| 1 | 99 | 0 | 87 | 1990087 | Не отображается оператору 112 |  |  |  | Пожар: Лицей | Пожар: Лицей | Пожар: Лицей |
| 1 | 99 | 0 | 88 | 1990088 | Не отображается оператору 112 |  |  |  | Пожар: Магазин | Пожар: Магазин | Пожар: Магазин |
| 1 | 99 | 0 | 89 | 1990089 | Не отображается оператору 112 |  |  |  | Пожар: Манеж | Пожар: Манеж | Пожар: Манеж |
| 1 | 99 | 0 | 90 | 1990090 | Не отображается оператору 112 |  |  |  | Пожар: Мастерская | Пожар: Мастерская | Пожар: Мастерская |
| 1 | 99 | 0 | 92 | 1990092 | Не отображается оператору 112 |  |  |  | Пожар: Медсанчасть | Пожар: Медсанчасть | Пожар: Медсанчасть |
| 1 | 99 | 0 | 94 | 1990094 | Не отображается оператору 112 |  |  |  | Пожар: Мечеть | Пожар: Мечеть | Пожар: Мечеть |
| 1 | 99 | 0 | 95 | 1990095 | Не отображается оператору 112 |  |  |  | Пожар: Монастырь | Пожар: Монастырь | Пожар: Монастырь |
| 1 | 99 | 0 | 96 | 1990096 | Не отображается оператору 112 |  |  |  | Пожар: Мототранспорт | Пожар: Мотоцикл | Пожар: Мототранспорт |
| 1 | 99 | 0 | 97 | 1990097 | Не отображается оператору 112 |  |  |  | Пожар: Музей | Пожар: Музей | Пожар: Музей |
| 1 | 99 | 0 | 100 | 1990100 | Не отображается оператору 112 |  |  |  | Пожар: Нии | Пожар: Нии | Пожар: Нии |
| 1 | 99 | 0 | 101 | 1990101 | Не отображается оператору 112 |  |  |  | Пожар: Новостройка | Пожар: Новостройка | Пожар: Новостройка |
| 1 | 99 | 0 | 102 | 1990102 | Не отображается оператору 112 |  |  |  | Пожар: Обмотка труб | Пожар: Обмотка труб | Пожар: Обмотка труб |
| 1 | 99 | 0 | 103 | 1990103 | Не отображается оператору 112 |  |  |  | Пожар: Общежитие | Пожар: Общежитие | Пожар: Общежитие |
| 1 | 99 | 0 | 104 | 1990104 | Не отображается оператору 112 |  |  |  | Пожар: Офис | Пожар: Офис | Пожар: Офис |
| 1 | 99 | 0 | 105 | 1990105 | Не отображается оператору 112 |  |  |  | Пожар: Палатка | Пожар: Палатка | Пожар: Палатка |
| 1 | 99 | 0 | 106 | 1990106 | Не отображается оператору 112 |  |  |  | Пожар: Пансионат | Пожар: Пансионат | Пожар: Пансионат |
| 1 | 99 | 0 | 109 | 1990109 | Не отображается оператору 112 |  |  |  | Пожар: Планетарий | Пожар: Планетарий | Пожар: Планетарий |
| 1 | 99 | 0 | 66 | 1990066 | Не отображается оператору 112 |  |  |  | Пожар: кабельный коллектор | Пожар: кабельный коллектор | Пожар: кабельный коллектор |
| 1 | 99 | 0 | 113 | 1990113 | Не отображается оператору 112 |  |  |  | Пожар: Подстанция | Пожар: Подстанция | Пожар: Подстанция |
| 1 | 99 | 0 | 115 | 1990115 | Не отображается оператору 112 |  |  |  | Пожар: Покрышки автомобильные | Пожар: Покрышки автомобильные | Пожар: Покрышки автомобильные |
| 1 | 99 | 0 | 116 | 1990116 | Не отображается оператору 112 |  |  |  | Пожар: Полигон | Пожар: Полигон | Пожар: Полигон |
| 1 | 99 | 0 | 117 | 1990117 | Не отображается оператору 112 |  |  |  | Пожар: Поликлиника | Пожар: Поликлиника | Пожар: Поликлиника |
| 1 | 99 | 0 | 118 | 1990118 | Не отображается оператору 112 |  |  |  | Пожар: Порт | Пожар: Порт | Пожар: Порт |
| 1 | 99 | 0 | 119 | 1990119 | Не отображается оператору 112 |  |  |  | Пожар: Посольство | Пожар: Посольство | Пожар: Посольство |
| 1 | 99 | 0 | 120 | 1990120 | Не отображается оператору 112 |  |  |  | Пожар: Прачечная | Пожар: Прачечная | Пожар: Прачечная |
| 1 | 99 | 0 | 121 | 1990121 | Не отображается оператору 112 |  |  |  | Пожар: Префектура | Пожар: Префектура | Пожар: Префектура |
| 1 | 99 | 0 | 122 | 1990122 | Не отображается оператору 112 |  |  |  | Пожар: Приемник-распределитель | Пожар: Приемник-распределитель | Пожар: Приемник-распределитель |
| 1 | 99 | 0 | 123 | 1990123 | Не отображается оператору 112 |  |  |  | Пожар: Пристройка | Пожар: Пристройка | Пожар: Пристройка |
| 1 | 99 | 0 | 124 | 1990124 | Не отображается оператору 112 |  |  |  | Пожар: Провода | Пожар: Провода | Пожар: Провода |
| 1 | 99 | 0 | 125 | 1990125 | Не отображается оператору 112 |  |  |  | Пожар: Производственно-складское здание | Пожар: Производственно-складское здание | Пожар: Производственно-складское здание |
| 1 | 99 | 0 | 127 | 1990127 | Не отображается оператору 112 |  |  |  | Пожар: Прокуратура | Пожар: Прокуратура | Пожар: Прокуратура |
| 1 | 99 | 0 | 128 | 1990128 | Не отображается оператору 112 |  |  |  | Пожар: Ресторан | Пожар: Ресторан | Пожар: Ресторан |
| 1 | 99 | 0 | 129 | 1990129 | Не отображается оператору 112 |  |  |  | Пожар: Роддом | Пожар: Роддом | Пожар: Роддом |
| 1 | 99 | 0 | 130 | 1990130 | Не отображается оператору 112 |  |  |  | Пожар: Рынок | Пожар: Рынок | Пожар: Рынок |
| 1 | 99 | 0 | 131 | 1990131 | Не отображается оператору 112 |  |  |  | Пожар: Салон | Пожар: Салон | Пожар: Салон |
| 1 | 99 | 0 | 132 | 1990132 | Не отображается оператору 112 |  |  |  | Пожар: Санаторий | Пожар: Санаторий | Пожар: Санаторий |
| 1 | 99 | 0 | 133 | 1990133 | Не отображается оператору 112 |  |  |  | Пожар: Сарай | Пожар: Сарай | Пожар: Сарай |
| 1 | 99 | 0 | 134 | 1990134 | Не отображается оператору 112 |  |  |  | Пожар: Сауна | Пожар: Сауна | Пожар: Сауна |
| 1 | 99 | 0 | 135 | 1990135 | Не отображается оператору 112 |  |  |  | Пожар: Свалка | Пожар: Свалка | Пожар: Свалка |
| 1 | 99 | 0 | 137 | 1990137 | Не отображается оператору 112 |  |  |  | Пожар: Склад | Пожар: Склад | Пожар: Склад |
| 1 | 99 | 0 | 138 | 1990138 | Не отображается оператору 112 |  |  |  | Пожар: Собор | Пожар: Собор | Пожар: Собор |
| 1 | 99 | 0 | 139 | 1990139 | Не отображается оператору 112 |  |  |  | Пожар: Спортзал | Пожар: Спортзал | Пожар: Спортзал |
| 1 | 99 | 0 | 140 | 1990140 | Не отображается оператору 112 |  |  |  | Пожар: Спорткомплекс | Пожар: Спорткомплекс | Пожар: Спорткомплекс |
| 1 | 99 | 0 | 141 | 1990141 | Не отображается оператору 112 |  |  |  | Пожар: Стадион | Пожар: Стадион | Пожар: Стадион |
| 1 | 99 | 0 | 143 | 1990143 | Не отображается оператору 112 |  |  |  | Пожар: Станция телефонная | Пожар: Станция телефонная | Пожар: Станция телефонная |
| 1 | 99 | 0 | 144 | 1990144 | Не отображается оператору 112 |  |  |  | Пожар: Столовая | Пожар: Столовая | Пожар: Столовая |
| 1 | 99 | 0 | 145 | 1990145 | Не отображается оператору 112 |  |  |  | Пожар: Суд | Пожар: Суд | Пожар: Суд |
| 1 | 99 | 0 | 148 | 1990148 | Не отображается оператору 112 |  |  |  | Пожар: Таможня | Пожар: Таможня | Пожар: Таможня |
| 1 | 99 | 0 | 149 | 1990149 | Не отображается оператору 112 |  |  |  | Пожар: Телебашня | Пожар: Телебашня | Пожар: Телебашня |
| 1 | 99 | 0 | 150 | 1990150 | Не отображается оператору 112 |  |  |  | Пожар: Телецентр | Пожар: Телецентр | Пожар: Телецентр |
| 1 | 99 | 0 | 151 | 1990151 | Не отображается оператору 112 |  |  |  | Пожар: Техникум | Пожар: Техникум | Пожар: Техникум |
| 1 | 99 | 0 | 152 | 1990152 | Не отображается оператору 112 |  |  |  | Пожар: Типография | Пожар: Типография | Пожар: Типография |
| 1 | 99 | 0 | 154 | 1990154 | Не отображается оператору 112 |  |  |  | Пожар: Торговый центр | Пожар: Торговый центр | Пожар: Торговый центр |
| 1 | 99 | 0 | 156 | 1990156 | Не отображается оператору 112 |  |  |  | Пожар: Трамвай | Пожар: Трамвай | Пожар: Трамвай |
| 1 | 99 | 0 | 157 | 1990157 | Не отображается оператору 112 |  |  |  | Пожар: Трансформаторная будка | Пожар: Трансформаторная будка | Пожар: Трансформаторная будка |
| 1 | 99 | 0 | 158 | 1990158 | Не отображается оператору 112 |  |  |  | Пожар: Троллейбус | Пожар: Троллейбус | Пожар: Троллейбус |
| 1 | 99 | 0 | 159 | 1990159 | Не отображается оператору 112 |  |  |  | Пожар: Тэц | Пожар: Тэц | Пожар: Тэц |
| 1 | 99 | 0 | 160 | 1990160 | Не отображается оператору 112 |  |  |  | Пожар: Тюрьма | Пожар: Тюрьма | Пожар: Тюрьма |
| 1 | 99 | 0 | 161 | 1990161 | Не отображается оператору 112 |  |  |  | Пожар: Университет | Пожар: Университет | Пожар: Университет |
| 1 | 99 | 0 | 162 | 1990162 | Не отображается оператору 112 |  |  |  | Пожар: Училище | Пожар: Училище | Пожар: Училище |
| 1 | 99 | 0 | 163 | 1990163 | Не отображается оператору 112 |  |  |  | Пожар: Фабрика | Пожар: Фабрика | Пожар: Фабрика |
| 1 | 99 | 0 | 164 | 1990164 | Не отображается оператору 112 |  |  |  | Пожар: Хладокомбинат | Пожар: Хладокомбинат | Пожар: Хладокомбинат |
| 1 | 99 | 0 | 165 | 1990165 | Не отображается оператору 112 |  |  |  | Пожар: Хлебозавод | Пожар: Хлебозавод | Пожар: Хлебозавод |
| 1 | 99 | 0 | 166 | 1990166 | Не отображается оператору 112 |  |  |  | Пожар: Холодильник | Пожар: Холодильник | Пожар: Холодильник |
| 1 | 99 | 0 | 167 | 1990167 | Не отображается оператору 112 |  |  |  | Пожар: Храм | Пожар: Храм | Пожар: Храм |
| 1 | 99 | 0 | 168 | 1990168 | Не отображается оператору 112 |  |  |  | Пожар: Хранилище | Пожар: Хранилище | Пожар: Хранилище |
| 1 | 99 | 0 | 169 | 1990169 | Не отображается оператору 112 |  |  |  | Пожар: Церковь | Пожар: Церковь | Пожар: Церковь |
| 1 | 99 | 0 | 170 | 1990170 | Не отображается оператору 112 |  |  |  | Пожар: Цех | Пожар: Цех | Пожар: Цех |
| 1 | 99 | 0 | 171 | 1990171 | Не отображается оператору 112 |  |  |  | Пожар: Цирк | Пожар: Цирк | Пожар: Цирк |
| 1 | 99 | 0 | 172 | 1990172 | Не отображается оператору 112 |  |  |  | Пожар: Часовня | Пожар: Часовня | Пожар: Часовня |
| 1 | 99 | 0 | 174 | 1990174 | Не отображается оператору 112 |  |  |  | Пожар: Чердак | Пожар: Чердак | Пожар: Чердак |
| 1 | 99 | 0 | 175 | 1990175 | Не отображается оператору 112 |  |  |  | Пожар: Шахта лифта | Пожар: Шахта лифта | Пожар: Шахта лифта |
| 1 | 99 | 0 | 176 | 1990176 | Не отображается оператору 112 |  |  |  | Пожар: Шахта метро вентиляционная | Пожар: Шахта метро вентиляционная | Пожар: Шахта метро вентиляционная |
| 1 | 99 | 0 | 177 | 1990177 | Не отображается оператору 112 |  |  |  | Пожар: Шиномонтаж авто | Пожар: Шиномонтаж авто | Пожар: Шиномонтаж авто |
| 1 | 99 | 0 | 179 | 1990179 | Не отображается оператору 112 |  |  |  | Пожар: Школа-интернат | Пожар: Школа-интернат | Пожар: Школа-интернат |
| 1 | 99 | 0 | 180 | 1990180 | Не отображается оператору 112 |  |  |  | Пожар: Шпалы | Пожар: Шпалы | Пожар: Шпалы |
| 1 | 99 | 0 | 181 | 1990181 | Не отображается оператору 112 |  |  |  | Пожар: Элеватор | Пожар: Элеватор | Пожар: Элеватор |
| 1 | 99 | 0 | 184 | 1990184 | Не отображается оператору 112 |  |  |  | Пожар: Электроподстанция | Пожар: Электроподстанция | Пожар: Электроподстанция |
| 1 | 99 | 0 | 188 | 1990188 | Не отображается оператору 112 |  |  |  | Пожар: Вагончик для жилья | Пожар: Вагончик для жилья | Пожар: Вагончик для жилья |
| 1 | 99 | 0 | 189 | 1990189 | Не отображается оператору 112 |  |  |  | Пожар: Корт | Пожар: Корт | Пожар: Корт |
| 1 | 99 | 0 | 190 | 1990190 | Не отображается оператору 112 |  |  |  | Пожар: Санэпидстанция | Пожар: Санэпидстанция | Пожар: Санэпидстанция |
| 1 | 99 | 0 | 193 | 1990193 | Не отображается оператору 112 |  |  |  | Пожар: Электропроводка в подъезде | Пожар: Электропроводка в подъезде | Пожар: Электропроводка в подъезде |
**English:** This is the complete, row-by-row real-world fire/smoke incident taxonomy: 6 location
groups reachable from the 112 card (street materials 1–13; transport sub-types; metro; MCC; residential
building rooms/areas; generic "facility") each crossed with an "open flame/дым" vs. "smell of burning"
(and, for some, other) feature, plus the 144-row "not shown to operator" premises-type list (REQ-3046).
Each row's "Итоговый тип" is the exact string the operator/DDS ultimately sees (cf. REQ-3040's "Класс.:
пожар: квартира" DDS-card line, which is exactly one of these Итоговый_тип values).

---

### REQ-3048 — Классификатор: 13 additional fire/smoke-relevant rows found outside the main category

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Классификатор_....xlsx`, rows 287, 309, 525, 578, 581, 591, 592, 602, 603, 611, 623, 649, 661 (categories "ДТП", "Аварии на опасных и производственных объектах", "Аварии и происшествия на транспортных объектах", "Запах газа") |
| Speaker | organizer (document) |

**Verbatim (RU), full rows:**

| Row | Номер | Признак1 | Признак2 | Признак3 | Доп.признаки | Итоговый_тип | ЕКП35 |
|---|---|---|---|---|---|---|---|
| 287 | 2010800 | ДТП | Горит дымится |  |  | ДТП без пострадавших с пожаром | ДТП с пожаром |
| 309 | 2021000 | ДТП пострадавшие | Горит дымится |  |  | ДТП с пострадавшими с пожаром | ДТП с пострадавшими ДТП с пожаром |
| 525 | 10010300 | Авария - опасный объект | Взрывопожарный |  |  | Авария на взрывопожароопасном объекте | Аварии на взрывопожароопасных объектах |
| 578 | 12010300 | Транспорт воздушный | Пожар |  |  | Транспорт воздушный - горит  | Пожар: Аэропорт |
| 581 | 12020300 | Аэропорт | Пожар |  |  | Аэропорт пожар | Пожар : Аэропорт |
| 591 | 12030300 | Транспорт водный | Пожар |  |  | Транспорт водный - горит | Пожар |
| 592 | 12040200 | Порт причал | Пожар |  |  | Порт (причал) пожар | Пожар: порт |
| 602 | 12060200 | Вокзал жд платформа жд станция жд депо | Пожар |  |  | Вокзал жд платформа жд станция жд  - горит | пожар: Вокзал |
| 603 | 12050300 | Транспорт жд  | Пожар |  |  | Транспорт жд - горит | пожар: Ж-д транспорт |
| 611 | 12070700 | Метро (вагон, поезд, перегон, тоннель, вестибюль, станция, платформа, переход, экскалатор, депо) | Пожар |  |  | Метро пожар | Пожар метро |
| 623 | 12080700 | МЦК (вагон, поезд, перегон, тоннель, вестибюль, станция, платформа, переход, экскалатор, депо) | Пожар |  |  | МЦК пожар | Пожар метро |
| 649 | 13020203 | Запах газа в помещении | Квартира помещение | После пожара |  | Запах бытового газа в квартире (после пожара) | Запах газа в квартире (после пожара) |
| 661 | 13030301 | Нарушение работы газового оборудования | Хлопок газа (Плита, колонка, котел) | Возгорание |  | Пожар (газовая плита) | Пожар: газовая плита |
**English:** Fire/smoke is not confined to the "Пожары и задымления" category: a road accident "with
fire" ("ДТП ... с пожаром", 2 rows), an explosive/fire-hazardous-facility accident (1 row), and 9
transport-object rows explicitly say "горит"/"Пожар" (air transport, airport, water transport, port/
pier, rail station/platform, rail transport, metro, MCC) live under "ДТП" / "Аварии на опасных и
производственных объектах" / "Аварии и происшествия на транспортных объектах" instead. Two "Запах
газа" (gas-smell) rows also reference fire ("После пожара" / "Пожар (газовая плита)" / "Пожар: газовая
плита") — i.e. a gas-smell call can itself resolve to a fire-classified incident.

---

### REQ-3049 — OPEN-QUESTION: meaning of "искл_пожар_задымление" in the classifier filename

| Field | Value |
|---|---|
| Kind | OPEN-QUESTION |
| Source | filename `Классификатор_происшествий_v_046_11_ДТУ_15_11_2024_искл_пожар_задымление.xlsx` |
| Speaker | organizer (document, filename only — no accompanying text explains it) |

**Verbatim (RU):** "...искл_пожар_задымление" (file name fragment, no further gloss provided anywhere
in the file or elsewhere in this task's source set).

**English:** The filename fragment translates literally to "excl./exception_fire_smoke" but the file
actually contains a full, populated "Пожары и задымления" category (271 rows, documented in full above)
— i.e., the file is not missing fire/smoke content. It is ambiguous, without further organizer
clarification, whether "искл" here means this is (a) a cut *excluding* something else fire/smoke-
related that exists in a different, unseen version of the classifier, (b) an *excerpt/inclusion*
naming convention, or (c) something else entirely (e.g. a change-log tag meaning "the 15.11.2024 fire/
smoke section was the one most recently revised"). No other source in this task's scope discusses this
file's versioning history. Flagged here rather than guessed at, per the "state ambiguity, don't resolve
it" rule.

## 3. Conflicts and changes over time

No direct contradictions were found between the five sources in this task's scope — they describe
different, complementary views of the same real system (operator card UI, operator manual text, DDS
receiving-side UI, service picker, and the underlying incident classifier) and are internally
consistent with each other wherever they overlap (see the cross-reference Notes on REQ-3001, REQ-3003,
REQ-3005, REQ-3009, REQ-3030, REQ-3040, REQ-3042, REQ-3047).

Two points are recorded as ambiguous/unresolved rather than as conflicts, because no second source
contradicts them — they are simply unclear on their own:

1. REQ-3049 — the classifier filename's "искл_пожар_задымление" fragment is ambiguous in meaning
   (see REQ-3049 for detail); it does not conflict with the file's actual (full) fire/smoke content.
2. `Инструкция...docx`'s hotkey table (REQ-3037) documents `Alt+O` for two different targets in two
   different modes (create-mode "к блоку описания" vs. view-mode "к блоку отработок") — recorded
   verbatim, not resolved, since the source itself distinguishes the two modes without flagging this as
   a clash.

The `Инструкция...docx` manual carries internal version/date tags on individual features (e.g. "[новое
в версии 2.0]", "[новое в версии 2.1]", "[новое в 1.7]", "[новое в 1.8]") showing the real system
evolved through at least versions 1.7 → 1.8 → 2.0 → 2.1; these are recorded inline in the relevant REQ
items (REQ-3012, REQ-3015, REQ-3018, REQ-3022, REQ-3024, REQ-3025, REQ-3028, REQ-3030, REQ-3034,
REQ-3036) as "as of version X" facts about the real system, not as conflicts.
