# SRC-005 — organizer materials sent 2026-09-23: kickoff-link ТЗ (PDF) and presentation template (PPTX)

Extraction and comparison for the two files the owner placed in
`requirements/sources/05-organizer-materials/` on 2026-09-23, said to come from the chat msg201
links (15.09.2026): «9. Деп Обороны и ЧС (1).pdf» and «ЛЦТ2026 Шаблон презентации (1).pptx». IDs
REQ-5001–REQ-5199 (range reserved for this source set). This file records what the sources say and
how the PDF differs, paragraph by paragraph, from the ТЗ docx already extracted as SRC-001
(`requirements/normalized/SRC-001-formal-docs.md`, REQ-2001–REQ-2375). It assigns no implementation
status; per `requirements/README.md` every item here is «не обработано» until evidence is attached.

## 1. Sources covered, how read, what could not be read

| File (`requirements/sources/05-organizer-materials/`) | What it is | Items |
|---|---|---|
| «9. Деп Обороны и ЧС (1).pdf» | The ТЗ «Учебное программное обеспечение для подготовки оператора ДДС города Москвы с использованием искусственного интеллекта», 20 pages, full text layer, one full-page cover image (p.1) + a 5-logo header image repeated on every content page. Metadata: `dc:creator`/`xmp` author «Катенька», `CreatorTool` «Acrobat PDFMaker 23 for Word», `CreateDate`/`ModifyDate` 2026-09-11 12:44/12:47 MSK. | REQ-5001–REQ-5003 (new/changed content only); 18 diff entries D1–D18 against REQ-2xxx |
| «ЛЦТ2026 Шаблон презентации (1).pptx» | Organizer's 37-slide, 16:9 (13.33×7.5 in) PowerPoint template. `docProps/core.xml`: creator «Анастасия Юшкова», created 2023-05-15T07:36:23Z, modified 2026-09-14T11:14:59Z (i.e. the template itself predates this task; it was last touched 9 days before being sent). | REQ-5004–REQ-5036 |

### How the documents were read
- PDF: `pdftotext` (raw and `-layout`), `pdfinfo`/`pdfinfo -meta`, `pdfimages -list`, and pages 1, 2 and
  20 rendered with `pdftoppm` and viewed (page 1 = full-page cover image; page 2 = a typical content
  page showing the repeated 5-logo header banner; page 20 = last content page, confirming no
  unreadable trailing page). The `-layout` output was used as the primary transcript because raw-mode
  `pdftotext` reflows multi-column/justified lines out of order in a few places (verified harmless,
  see Methodology note M1). Every quoted PDF fragment below was checked against the `-layout` text.
- The docx side of the comparison reuses the paragraph-indexed extraction already on file for SRC-001
  (same method: `uv run --with python-docx`, iterating `document.xml` body paragraphs and table rows
  in order) plus a fresh read of the docx's own Table-of-Contents content control (`w:sdt` with
  `docPartGallery=Table of Contents`, static text, no `PAGEREF` fields — i.e. the docx TOC page
  numbers are typed, not auto-computed) to compare against the PDF's TOC.
- Comparison method: both texts normalised (collapsed whitespace, de-hyphenated line-wraps, page
  footers/repeated headers stripped) and diffed paragraph-by-paragraph in reading order; every
  surviving difference was then re-checked by eye against both original texts before being logged
  below. Nothing else was auto-normalised (case, dash style „—" vs „-", colon vs dash, bullet-symbol
  choice were left visible and are reported, then explained where they are a single systematic
  pattern rather than per-item content).
- PPTX: `uv run --with python-pptx`, iterating every slide's shapes (text frames, tables, charts,
  pictures) and, for slides 7–11 and 12–29 where the slide itself carries no text override, the
  **slide layout's** placeholder prompt text (the text a participant sees before typing, e.g. «НАЗВАНИЕ
  КОМАНДЫ»), because that prompt text is what actually defines each slide's required content — this
  is stored on the layout, not the slide, so plain slide-only extraction would have shown these five
  slides as empty. Shape positions (`shape.top`/`shape.left`, converted to inches) were read to pair
  each heading box with the correct prompt box where several floating text boxes shared a slide (slide
  8, slide 10, slide 11); every pairing below was confirmed this way, not guessed from XML order.
  `docProps/core.xml` and `app.xml` gave authorship/dates/slide-count; `notesSlides/*.xml` were
  checked and contain only the auto slide-number placeholder (no real speaker notes despite
  `app.xml` reporting `<Notes>3</Notes>`).
- Both files' text layers/text runs are complete; nothing was OCR'd (not needed — both have live text)
  and nothing was password-protected.

### What could not be read / is not in the archive
- Nothing in either file was unreadable.
- Nine of the pptx's 37 slides (31–37, plus the picture parts of slide 6) are pure icon/picture
  libraries (hundreds of `PICTURE` shapes with no distinguishing text beyond a category label such as
  «Иконки», «Пользователи», «Бизнес», «Графики»); individual icon images were not identified one by
  one (no requirement content there — see REQ-5014, REQ-5036).
- The three embedded chart objects on slides 21–23 (shape type `CHART`) were identified as present but
  their internal series data was not extracted (they are sample/placeholder charts on non-mandatory
  slides; no ТЗ requirement depends on their content).
- Whether the cloud-hosted ТЗ behind the 15.09 link (msg201) is byte-identical to this archived PDF
  cannot be verified — only the archived copy was read.

### Methodology notes (apply to the whole diff section)
- **M1 — heading/list numerals.** The PDF text layer shows visible numerals on every top-level
  heading («1. Описание работы компании…», «18. Требования к сдаче решений на платформе») and on two
  list blocks («Требования к сервису» 1–6, «Требования к сдаче решений на платформе» 1–4) that have
  **no such numerals** in the docx's own paragraph text (`python-docx` reads only literal `w:t` runs;
  Word auto-numbering from a list/heading style is not a text run). The docx's own criteria-group
  numbers («1. Подход коллектива…», «2. Техническая проработка…», 1–5 under «Критерии…») **are**
  literal typed text in the docx and match the PDF exactly. Conclusion, checked against the PDF's
  rendering (pages 1 and 20 were visually rendered): the extra PDF numerals are Word's own
  auto-numbering flattened into rendered glyphs during PDF export (both files carry `Acrobat
  PDFMaker`/Word toolchain fingerprints); this is **not** logged as a content difference below.
- **M2 — case and punctuation of list items.** Throughout the body, wherever the docx renders a bullet
  list as separate Word-list paragraphs (each auto-capitalised, no trailing punctuation), the PDF
  renders the same content as one flowing sentence with lower-case continuations and `;`/`.`
  punctuation (e.g. docx «Интеграцию с существующей инфраструктурой системы-112» vs PDF «интеграцию с
  существующей инфраструктурой системы-112;»). This pattern recurs at essentially every bulleted list
  in the document (confirmed section-by-section, §1 through §18) and is not re-logged bullet by
  bullet; only bullets whose **wording** (not just case/punctuation) changed are logged as D-items
  below.
- **M3 — pagination offset.** The PDF's own Table of Contents (page 1, static text, `pdftotext`
  layout) gives every section a page number exactly **one less** than the same section's page number
  in the docx's own Table-of-Contents content control (e.g. «Постановка задачи»: PDF p.6, docx p.7;
  «Требования к сдаче решений на платформе»: PDF p.19, docx p.20 — checked for all 23 TOC lines, the
  offset is uniform). The docx has a separate one-paragraph cover (¶14/¶16/¶18) followed by a
  dedicated TOC page; the PDF's page 1 combines a designed cover (title, four programme logos, a
  department crest, a city-skyline illustration, the label «Техническое задание» and «2026») with the
  TOC on the same page — one fewer page is spent before content starts. Both TOCs list the same 23
  headings in the same order (both omit «2. Предназначение разрабатываемого сервиса» and
  «4. Границы решения» as separate TOC entries, i.e. this omission is common to both files, not new to
  the PDF). Logged once (D1), not per section.
- **How organizers were identified**: unchanged from SRC-001 — the ТЗ (in either format) is the
  customer's (department's) text; the presentation template and msg201 are ЛЦТ-organizer material
  (msg201 author = moderator Str1fe, per SRC-001 §"How organizers were identified"). Speaker labels
  used below: «organizer — customer (ТЗ)», «organizer — ЛЦТ (presentation template)», «organizer — ЛЦТ
  (moderator Str1fe, chat)».

### Counts
- PDF-vs-docx comparison: content is paragraph-for-paragraph **identical** except for 18 logged
  differences (D1–D18); of those, 3 are systematic formatting patterns (grouped as one row each) and
  15 are individual wording/content changes. Zero numeric thresholds, deadlines, hardware minimums or
  legal citations differ between the two versions (all checked, see §2).
- New content found only in the PDF (not a reworded existing paragraph): 3 items (REQ-5001–REQ-5003),
  all on the cover/header design, none in the requirements body.
- Presentation template: 33 items (REQ-5004–REQ-5036). Per Kind: DELIVERABLE 19, CLARIFICATION 11,
  DOMAIN-FACT 3.
- Total REQ-5xxx items issued: 36 (REQ-5001–REQ-5036).

## 2. Paragraph-level comparison: PDF ТЗ vs docx ТЗ (SRC-001)

Both documents were read start to end in parallel; column «Touches» gives the existing REQ-2xxx id or
range the difference sits inside (per SRC-001's own item boundaries). "PDF p.N" is the PDF's own
printed footer number (see M3).

| # | docx verbatim (¶, SRC-001 id) | PDF verbatim (page) | English | Touches | Notes |
|---|---|---|---|---|---|
| D1 | Cover = 3 plain paragraphs «ЛИДЕРЫ ЦИФРОВОЙ ТРАНСФОРМАЦИИ» / «ДЕПАРТАМЕНТ ПО ДЕЛАМ ГРАЖДАНСКОЙ ОБОРОНЫ…» / «ГБУ «Система 112»» (¶14,16,18), then TOC on a separate page (docx p.2) | Cover (PDF p.1, image) = title + TOC combined on one page; shows a designed cover (city-skyline illustration), a department crest + «ДЕПАРТАМЕНТ ПО ДЕЛАМ ГРАЖДАНСКОЙ ОБОРОНЫ, ЧРЕЗВЫЧАЙНЫМ СИТУАЦИЯМ И ПОЖАРНОЙ БЕЗОПАСНОСТИ ГОРОДА МОСКВЫ», the label «Техническое задание», the year «2026», and four small programme logos («ПРОЕКТ МЭРА МОСКВЫ», «БИЗНЕС МОСКВЫ», «РАЗВИТИЕ ЧЕЛОВЕЧЕСКОГО КАПИТАЛА», «ЛИДЕРЫ ЦИФРОВОЙ ТРАНСФОРМАЦИИ»); **«ГБУ «Система 112»» does not appear on the cover or on the repeated page-header banner at all** | The PDF cover is a full graphic redesign one page shorter than the docx's cover+TOC; it drops the «ГБУ «Система 112»» co-issuer credit shown in the docx and adds a document-type label, a year, and 3 new partner-programme logos (a 4th, «Лидеры цифровой трансформации», already existed as docx body text). All 23 PDF TOC page numbers are exactly 1 less than the matching docx TOC page numbers (checked for all 23 lines). | REQ-2001, REQ-2002 | See REQ-5001–REQ-5003 for the new cover elements, extracted as new statements. |
| D2 | Table 1 row 5 (REQ-2006): «ИИ/искусственный интеллект — искусственный интеллект - комплекс технологических решений, позволяющий имитировать когнитивные функции человека» | «ИИ/искусственный интеллект — Комплекс технологических решений, позволяющий имитировать когнитивные функции человека.» (PDF p.2) | docx defines ИИ as "artificial intelligence — a complex of technological solutions…"; PDF drops the self-referential "artificial intelligence -" lead and starts directly at "A complex of technological solutions…" (capitalised, period added). | REQ-2006 | Definition content unchanged past the dropped lead phrase. |
| D3 | Table 1 row 9 (REQ-2010): «ПО — программное обеспечение, совокупность программ, баз данных и файлов, обеспечивающих работу компьютерной систем» (no final "-ы", no period) | «ПО — Программное обеспечение, совокупность программ, баз данных и файлов, обеспечивающих работу компьютерной системы.» (PDF p.2) | docx text is truncated/ungrammatical ("...of a computer syst"); PDF reads "...of a computer system." (grammatically complete, period added). | REQ-2010 | Typo present in the docx is absent in the PDF. |
| D4 | ¶102, lead-in to REQ-2093–REQ-2098: «Сервис должен решить следующие задачи:» | «Необходимо, чтобы сервис решал следующие задачи:» (PDF p.6) | docx: "The service must solve the following tasks:" (perfective "решить"). PDF: "It is necessary that the service perform (solve) the following tasks:" (different construction, imperfective "решал"). | REQ-2093–REQ-2098 (lead-in only; the 6 listed tasks are unchanged) | Modality rephrased; the 6 items under it are identical in both. |
| D5 | ¶109, lead-in to REQ-2099–REQ-2104: «Сервис должен:» | Sub-heading «Требования к сервису» stands alone before the same numbered list (PDF p.6) | docx: a lead-in sentence "The service must:". PDF: a stand-alone heading "Requirements for the service" (not itself a TOC entry — see M3) directly above numbered items 1–6. | REQ-2099–REQ-2104 (lead-in only; items 1–6 unchanged, incl. REQ-2100's "or text messages" alternative) | Relabelled as a heading rather than a sentence; the 6 requirement items themselves are word-for-word identical. |
| D6 | REQ-2193 (¶231): «Просматривать результаты выполнения заданий (автоматическая оценка И + экспертная оценка)» — SRC-001's own Notes flag this as ambiguous ("a single letter «И»") | «просматривать результаты выполнения заданий (автоматическая оценка ИИ + экспертная оценка);» (PDF p.10) | docx: "...automatic assessment 'И' + expert assessment" (single-letter typo). PDF: "...automatic assessment AI + expert assessment" (full "ИИ", i.e. the AI abbreviation used throughout the rest of the document). | REQ-2193 | Resolves the ambiguity SRC-001 had flagged for this exact item. |
| D7 | REQ-2259 (¶316) — SRC-001's own Notes flag «например?» (a "?" as printed) and capitalised «Мосводоканал, Москоллектор, Управы, службы газа» | «…чтобы в их ленту попадали только профильные события (например, от Мосводоканала, Москоллектора, управ, служб газа и пр.).» (PDF p.13) | docx: "...(e.g.? Mosvodokanal, Moskollektor, Upravy, gas services etc.)" — nominative-looking list with a stray "?". PDF: "...(e.g., from Mosvodokanal, Moskollektor, district upravy [lower-case], gas services etc.)" — genitive case with "от" ("from"), "?" replaced by ",", "управ" lower-cased. | REQ-2259 | Grammar/typo fix; the four example services named are the same four in both. |
| D8 | REQ-2268 (¶326): «Система имитирует звонок участника событий» — Notes already flag chat conflicts (msg570, msg624/msg638, outside this task's scope) | «Имитация системой звонка участника событий.» (PDF p.13) | Active "The system simulates a call" (docx) vs nominal "Simulation by the system of a call" (PDF). Same meaning. | REQ-2268 | No new information beyond voice/construction; the pre-existing chat-conflict flag on this item is unaffected. |
| D9 | REQ-2269 (¶327): «Обучающиеся заполняют карточки событий…» (plural "trainees… cards") | «Заполнение Обучающимся карточки событий (имитация интерфейса системы АРМ-112).» (PDF p.13) | docx: "Trainees [pl.] fill in event cards [pl.]…". PDF: "Filling-in by the trainee [sing.] of the event card [sing.]…". | REQ-2269 | Cardinality changed from plural (multiple trainees/multiple cards) to singular (one trainee/one card) in the PDF's phrasing of this scenario step. |
| D10 | REQ-2286 (¶341): «Обучающийся производит действия с карточкой события, в том числе вводит текст…» (uses the role term «Обучающийся», same word used everywhere else, incl. «Роль: Обучающийся») | «Произведение учащимся действия с карточкой события, в том числе введение текста…» (PDF p.14) | docx uses "Обучающийся" (the defined role name). PDF uses "учащимся" ("the pupil/learner", a synonym not defined anywhere in either document's «Термины и определения» and not used as the role name elsewhere). | REQ-2286 | Terminology substitution; "учащийся" does not otherwise occur in either document. |
| D11 | ¶144, lead-in to REQ-2127–REQ-2129: «Система должна интегрироваться с:» (bullets below have no leading "с") | «Система должна интегрироваться:» — bullets below each start with their own "с" (PDF p.7: «• с форматами данных…», «• с локальной системой…», «• с локальными средствами…») | Same information, preposition "с" moved from the end of the lead-in sentence to the start of each bullet. | REQ-2127–REQ-2129 (lead-in only; the 3 integration targets are unchanged) | Punctuation/placement only. |
| D12 | ¶151–155, lead-in «Рекомендуется реализовать:» items REQ-2132–REQ-2136 use a colon, e.g. «Дополнительные модули аналитики: расширенная визуализация…» | Same 5 items use an em-dash, e.g. «дополнительные модули аналитики — расширенная визуализация…» (PDF p.7–8) | Same content; colon (docx) vs em-dash (PDF) separating the item name from its description, in all 5 optional-requirement bullets. | REQ-2132–REQ-2136 | Systematic punctuation swap, grouped as one row; no wording changed in any of the 5 items. |
| D13 | ¶396 (REQ-2324/REQ-2325): «Все необходимые для использования решения методы должны быть доступны и подробно описаны, а также предоставлен перечень…» (elliptical — no verb before "предоставлен") | «Все необходимые для использования решения методы должны быть доступны и подробно описаны, а также должен быть предоставлен перечень…» (PDF p.17) | docx: "...and also [a] list of libraries [is] provided" (verb dropped, grammatically incomplete). PDF: "...and also a list of libraries **must be** provided" (adds "должен быть", grammatically complete). | REQ-2325 | Two words added ("должен быть"); the underlying deliverable (a list of libraries/components) is unchanged. |
| D14 | ¶408 (REQ-2335): «…в приоритете, должны отвечать требованиям…» | «…приоритетно, должны отвечать требованиям…» (PDF p.17) | docx: "as a priority" (prepositional phrase "в приоритете"). PDF: "preferentially/with priority" (adverb "приоритетно"). Same general sense, different lexical choice. | REQ-2335 | Word substitution; the named standards (149-ФЗ, 152-ФЗ, dated 27.07.2006) are byte-identical in both — checked. |
| D15 | ¶462 (REQ-2365, final-expertise criterion 3 item 5): «…оценка достоверности диаграмм будет проводится на основании их визуальной восприимчивости и отражении данных);» | «…оценка достоверности диаграмм будет проводиться на основании их визуальной наглядности и отражения ими данных);» (PDF p.18) | docx: reliability of diagrams assessed "on the basis of their visual **receptiveness/perceptibility** ('восприимчивости') and [how they] reflect the data". PDF: "...on the basis of their visual **clarity/intuitiveness** ('наглядности') and their reflection of the data (with 'ими' = 'by them' added)". Also fixes docx's "проводится" (typo) to "проводиться" (correct reflexive). | REQ-2365 | This is a wording change to an EVALUATION criterion (final-expertise judging basis for diagram review), not only a typo fix — the assessed quality changed from "perceptibility" to "clarity/intuitiveness". |
| D16 | ¶466–469 (REQ-2367–REQ-2370, final-expertise criterion 4): noun-phrase form, e.g. «Соответствие прогнозов реальному поведению инфраструктуры;» | Same 4 items as full sentences, e.g. «прогнозы соответствуют реальному поведению инфраструктуры;» (PDF p.18) | docx: "Correspondence of forecasts to real infrastructure behaviour" (noun phrase). PDF: "Forecasts correspond to real infrastructure behaviour" (verb sentence). Same 4 criteria, same meaning. | REQ-2367–REQ-2370 | Grammatical restructuring only, in all 4 items of this criterion group; no criterion added, removed or reworded in substance. |
| D17 | Table 1, all 33 remaining rows (REQ-2003–REQ-2005, REQ-2007–REQ-2009, REQ-2011–REQ-2036 except REQ-2006/REQ-2010 above) | Same 33 definitions, PDF p.2–3 | Same content; PDF capitalises the first letter of each Cyrillic-starting definition and adds a terminal period (docx definitions are lower-case, no period), and swaps the internal hyphen "-" for an em-dash "—" where a dash separates clauses inside a definition (e.g. ДДС, СУБД, API rows). One row (MP3) was **not** restyled and stayed lower-case/no-period in the PDF too, matching the docx exactly — the one place the two texts are still byte-identical at the punctuation level. | REQ-2003–REQ-2036 (minus REQ-2006, REQ-2010 which also changed in wording, logged separately as D2/D3) | Grouped as one row: a document-wide proofreading pass (capitalisation + terminal punctuation + dash style), not a per-definition content change. |
| D18 | General list punctuation (§1 onward): docx renders every bulleted requirement as a separate, capitalised, unpunctuated Word-list paragraph | PDF renders the same lists as flowing sentences: lower-case continuations, "；"/"." punctuation (see Methodology M2) | Same content throughout the document (checked section by section, §1–§18); only a typesetting/paragraph-vs-run-on-sentence difference. | All REQUIREMENT/CONSTRAINT items with bullet-list `Source` (the large majority of REQ-2043–REQ-2375) | Not re-logged per bullet; recorded once here per M2. |

**Sections/items checked and found identical (content, not just case/punctuation):** all numeric
thresholds and minimums (§7 «Требования к производительности», incl. 2 s response time / 100 users,
≥20 concurrent sessions, ≤150 ms VoIP latency, ≤30 s network-outage recovery, ≥100 DB ops/s, ≤30 s
report generation, ≥6-month security-log retention, daily backup, i5/16 GB/256 GB SSD workstation
minimum, i7-or-Xeon-6-core/32 GB/512 GB NVMe server minimum, 30-second default task timer in §8
«Роль: Преподаватель»); §4 «Границы решения» (all 4 exclusions + all 8 obligations); §9
«Нефункциональные требования» (all reliability/security/compatibility bullets, incl. Windows
10/11+Ubuntu 20.04, PostgreSQL ≥12); §11 «Источники данных»; §12 «Форматы данных» (all format bullets
in all 7 sub-groups); §13's two cited federal laws (149-ФЗ and 152-ФЗ of 27.07.2006, verbatim);
§14 «Требования к презентации» («Презентация представляется в формате pptx или pdf.» — byte-identical
in both, directly relevant to REQ-5015 ff. below); §15 «Требования к UX/UI»; §16 «Критерии…
предварительной экспертизы» (all 4 groups); §17 criterion groups 1, 2 and criterion 5 («Выступление
коллектива на питч-сессии.»); §18 «Требования к сдаче решений на платформе» (all 4 deliverables).

## 3. New content found only in the PDF (cover/header design)

| ID | Kind | Source | Speaker | Verbatim | English | Notes |
|---|---|---|---|---|---|---|
| REQ-5001 | CLARIFICATION | PDF cover, p.1 (image) | organizer — customer (ТЗ) | Техническое задание | The label "Technical specification" appears on the cover; not present anywhere in the docx's extracted text. |  |
| REQ-5002 | CLARIFICATION | PDF cover, p.1 (image) | organizer — customer (ТЗ) | 2026 | The year "2026" appears on the cover; not present in the docx's extracted text. |  |
| REQ-5003 | DOMAIN-FACT | PDF cover p.1 and repeated header banner on every content page (image) | organizer — customer (ТЗ) | Логотипы: «ПРОЕКТ МЭРА МОСКВЫ», «БИЗНЕС МОСКВЫ», «РАЗВИТИЕ ЧЕЛОВЕЧЕСКОГО КАПИТАЛА», «ЛИДЕРЫ ЦИФРОВОЙ ТРАНСФОРМАЦИИ», плюс герб и название Департамента; «ГБУ «Система 112»» на обложке/колонтитуле не показано. | Logos shown: "Mayor of Moscow Project", "Business of Moscow", "Human Capital Development", "Leaders of Digital Transformation", plus the Department's crest and name; "ГБУ «Система 112»" is not shown on the cover or header banner. | See D1; only "Leaders of Digital Transformation" previously existed as docx body text (¶14). |

## 4. Presentation template («ЛЦТ2026 Шаблон презентации (1).pptx»)

msg201 (task-9 Telegram chat, 15.09.2026, author Str1fe): «Слайды с 7 по 11 являются строго
обязательными и должны быть сохранены именно в том дизайне и структуре.» = "Slides 7 through 11 are
strictly mandatory and must be preserved in exactly that design and structure." This is quoted
verbatim in the brief for this task; it is recorded here as REQ-5004 because it is the operative
DELIVERABLE-defining organizer statement for the whole template and is not otherwise itemised in
SRC-001/SRC-001-chat. The template's own slide 3 independently corroborates it (REQ-5007/REQ-5008
below use the words «Обязательный блок», "mandatory block", for exactly slides 7 and 8–11).

| ID | Kind | Source | Speaker | Verbatim | English | Notes |
|---|---|---|---|---|---|---|
| REQ-5004 | DELIVERABLE | Task-9 Telegram chat, msg201, 15.09.2026 | organizer — ЛЦТ (moderator Str1fe, chat) | Слайды с 7 по 11 являются строго обязательными и должны быть сохранены именно в том дизайне и структуре. | Slides 7 through 11 are strictly mandatory and must be preserved in exactly that design and structure. | Governs REQ-5015–REQ-5031 below. |
| REQ-5005 | DOMAIN-FACT | pptx `docProps/core.xml`, `app.xml` | organizer — ЛЦТ (presentation template) | 37 slides; PresentationFormat «Широкоэкранный» (16:9, 13.33×7.5 in); dc:creator «Анастасия Юшкова»; created 2023-05-15T07:36:23Z; modified 2026-09-14T11:14:59Z. | File identity/authorship/dates as recorded in the file's own metadata. | Template predates this hackathon (2023) and was last edited 9 days before being sent (14.09, sent 15.09 per msg201). |
| REQ-5006 | CLARIFICATION | pptx slide 2 «ВВОДНЫЕ» | organizer — ЛЦТ (presentation template) | Привет, участник хакатона! Эта презентация — готовая основа для оформления решения команды. Внутри — примеры слайдов, логотипы, шрифты, цвета, иконки и различные графические элементы. Можешь смело доверить дизайн этому шаблону и сосредоточить свою энергию и время на действительно важном — подготовке инновационного решения для твоей победы! Удачи! | Hi, hackathon participant! This presentation is a ready-made base for designing the team's solution. Inside are example slides, logos, fonts, colours, icons and various graphic elements. You can safely trust this template's design and focus your energy and time on what really matters — preparing an innovative solution for your win! Good luck! | Introductory/orientation text, not a checkable requirement by itself. |
| REQ-5007 | DELIVERABLE | pptx slide 3, block labelled «Обязательный блок» over «Используй для оформления слайд 7» | organizer — ЛЦТ (presentation template) | Титульный слайд: название команды / название задачи / логотип / логотипы постановщика задачи. | Title slide (mandatory): team name / task name / logo(s) of the task's customer/organizer. | Corroborates msg201/REQ-5004 for slide 7 specifically. |
| REQ-5008 | DELIVERABLE | pptx slide 3, block labelled «Обязательный блок» over «Используй для оформления слайды 8-11» | organizer — ЛЦТ (presentation template) | Слайды про задачу и команду: описание сути и уникальности решения; план по дальнейшему развитию решения; ФИО и контактные данные всех участников; роли в команде; сложности и вызовы во время решения задачи. | Slides about the task and team (mandatory): description of the solution's substance and uniqueness; plan for the solution's further development; full names and contact details of all participants; roles in the team; difficulties and challenges faced while solving the task. | Corroborates msg201/REQ-5004 for slides 8–11; the 5 topics listed here are spread across the actual slides 8–11 content (REQ-5019–REQ-5031). |
| REQ-5009 | CLARIFICATION | pptx slide 3, block over «Используй для оформления шаблоны на слайдах 12-29» | organizer — ЛЦТ (presentation template) | Презентация решения: рекомендуемая структура полной презентации решения приведена на следующем слайде; этот блок должен быть размещен после описанных общих обязательных слайдов. | Solution presentation: the recommended structure of the full solution presentation is given on the next slide; this block must be placed after the general mandatory slides described above. | Unlike slides 7 and 8–11, this block is **not** labelled «Обязательный блок» in the source — i.e. slides 12–29 are of a recommendational character (per msg201's own «рекомендательный характер» framing for non-mandatory slides), with one hard constraint: they must come after the slide 7 / 8–11 mandatory block. |
| REQ-5010 | DELIVERABLE | pptx slide 4 «РЕКОМЕНДУЕМАЯ СТРУКТУРА ПРЕЗЕНТАЦИИ» / «Для продуктовых решений» | organizer — ЛЦТ (presentation template) | 01 Подробное описание решения; 02 Маркетинговая часть решения; 03 Бизнесовая составляющая решения; 04 Техническая проработка решения; 05 Уникальность решения; 06 Планы по развитию решения. | Recommended presentation structure for product solutions: 01 Detailed solution description; 02 Marketing part of the solution; 03 Business component of the solution; 04 Technical elaboration of the solution; 05 Uniqueness of the solution; 06 Plans for the solution's development. | Recommendational (slides 12–29 territory, per REQ-5009); no mandatory-block label. |
| REQ-5011 | CLARIFICATION | pptx slide 5 «ОФОРМЛЕНИЕ», «Шрифт:» | organizer — ЛЦТ (presentation template) | Montserrat: https://fonts-online.ru/fonts/montserrat | Font: Montserrat (link given). | Not a credential; a public font-download page. |
| REQ-5012 | CLARIFICATION | pptx slide 5 «ОФОРМЛЕНИЕ», group «акцентные» | organizer — ЛЦТ (presentation template) | HEX #FF0053; HEX #FFD6E4; HEX #8A83D1; HEX #FC3777; HEX #310F53; HEX #520978 | Accent colour palette (6 hex codes). | «Цветовая схема уже установлена в этом документе» = "the colour scheme is already set up in this document" (same slide). |
| REQ-5013 | CLARIFICATION | pptx slide 5 «ОФОРМЛЕНИЕ», group «базовые» | organizer — ЛЦТ (presentation template) | HEX #FFFFFF; HEX #1C1D22 | Base colour palette (2 hex codes: white, near-black). |  |
| REQ-5014 | DOMAIN-FACT | pptx slide 6 «ЛОГОТИПЫ ПОСТАНОВЩИКОВ ЗАДАЧ» | organizer — ЛЦТ (presentation template) | 22 logo images grouped under labels «Город» and «Бизнес»; caption «Черные версии: https://disk.yandex.ru/d/PXfwjMA16G2aTw» | 22 task-customer logo images, grouped "City" / "Business"; caption: "Black versions: [link]" (a shared cloud folder of black-on-white logo variants for all hackathon tasks). | Not identified image-by-image; this slide is a shared multi-task gallery, not task-9-specific (task 9's own department crest was seen separately on the ТЗ cover, D1). |
| REQ-5015 | DELIVERABLE | pptx slide 7 «Титульный слайд» (layout placeholder, `idx=0`, type CENTER_TITLE) | organizer — ЛЦТ (presentation template) | НАЗВАНИЕ КОМАНДЫ | TEAM NAME (title placeholder prompt). | Mandatory (REQ-5004/REQ-5007). |
| REQ-5016 | DELIVERABLE | pptx slide 7 (layout placeholder, `idx=12`, type BODY) | organizer — ЛЦТ (presentation template) | Номер и название задачи | Task number and name (body placeholder prompt). | Mandatory. |
| REQ-5017 | DELIVERABLE | pptx slide 7 (layout placeholder, `idx=10`, type PICTURE) | organizer — ЛЦТ (presentation template) | Иконка задачи | Task icon (picture placeholder prompt). | Mandatory. |
| REQ-5018 | DELIVERABLE | pptx slide 7 (layout placeholder, `idx=11`, type PICTURE) | organizer — ЛЦТ (presentation template) | Логотип/логотипы постановщика задачи | Logo(s) of the task's customer/organizer (picture placeholder prompt). | Mandatory; matches D1/REQ-5003's department crest. |
| REQ-5019 | DELIVERABLE | pptx slide 8 «1_Описание команды» (layout placeholder, `idx=0`, type TITLE) | organizer — ЛЦТ (presentation template) | КОМАНДА «НАЗВАНИЕ» | TEAM "NAME" (title placeholder prompt). | Mandatory (REQ-5004/REQ-5008). |
| REQ-5020 | DELIVERABLE | pptx slide 8 (layout placeholder, `idx=10`, type PICTURE) | organizer — ЛЦТ (presentation template) | Фото команды | Team photo (picture placeholder prompt). | Mandatory. |
| REQ-5021 | DELIVERABLE | pptx slide 8, text box «О команде» + fields box (top≈3.81–4.25 in, left≈0.37 in) | organizer — ЛЦТ (presentation template) | О команде: Капитан: ФИО, специальность; Кол-во участников: __ человек; Краткое описание: ; как образовалась команда? ; место работы/учебы участников?; Город и регион: | About the team: Captain: full name, specialty; Number of participants: __ people; Brief description: ; how did the team come together?; participants' place of work/study?; City and region: | Mandatory; fields paired by on-slide vertical position. |
| REQ-5022 | DELIVERABLE | pptx slide 8, heading (top≈2.52) + prompt (top≈2.87), both left≈7.46 in | organizer — ЛЦТ (presentation template) | Краткое описание решения: В чем суть вашего решения | Brief description of the solution: What is the essence of your solution. | Mandatory; heading/prompt pairing confirmed by shape position. |
| REQ-5023 | DELIVERABLE | pptx slide 8, heading (top≈4.97) + prompt (top≈5.33), both left≈7.46 in | organizer — ЛЦТ (presentation template) | Уникальность решения: Что делает ваше решение уникальным или инновационным? | Uniqueness of the solution: What makes your solution unique or innovative? | Mandatory; heading/prompt pairing confirmed by shape position. |
| REQ-5024 | DELIVERABLE | pptx slide 9 «Команда» (title = layout default «КОМАНДА «НАЗВАНИЕ»»; 5 identical member cards) | organizer — ЛЦТ (presentation template) | Имя Фамилия — Роль в команде; Ник в мессенджере; Номер телефона; Место работы/учебы. (×5 карточек) | First Last name — Role in the team; Messenger handle; Phone number; Place of work/study. (×5 identical member cards) | Mandatory; slide layout provides exactly 5 member-card slots, all with the same 4 fields. |
| REQ-5025 | DELIVERABLE | pptx slide 10 «Команда» (title = layout default, not overridden on the slide) | organizer — ЛЦТ (presentation template) | КОМАНДА «НАЗВАНИЕ» | TEAM "NAME" (title, inherited from layout). | Mandatory. |
| REQ-5026 | DELIVERABLE | pptx slide 10, block «01» (heading top≈1.40 + prompt top≈1.75, left≈0.58 in) | organizer — ЛЦТ (presentation template) | 01 Краткая история команды: Расскажите, как вы собрались, участвовали ли вместе в прошлых хакатонах или проектах, интересные факты о команде. | 01 Brief history of the team: Tell how you got together, whether you took part in past hackathons or projects together, interesting facts about the team. | Mandatory; pairing confirmed by shape position (number badge at same top coordinate as heading). |
| REQ-5027 | DELIVERABLE | pptx slide 10, block «02» (heading top≈3.17 + prompt top≈3.75) | organizer — ЛЦТ (presentation template) | 02 Почему вы выбрали именно эту задачу из предложенных на хакатоне? Что вас вдохновило или заинтересовало в этой проблеме? | 02 Why did you choose this particular task among those offered at the hackathon? What inspired or interested you in this problem? | Mandatory; pairing confirmed by shape position. |
| REQ-5028 | DELIVERABLE | pptx slide 10, block «03» (heading top≈5.00 + prompt top≈5.62) | organizer — ЛЦТ (presentation template) | 03 С какими основными сложностями или вызовами вы столкнулись и как их преодолели? Расскажите о самых интересных или сложных моментах в процессе разработки и как команда с ними справилась. Здесь можете поделиться, в том числе, и личными историями, которые повлияли на ход вашего участия в хакатоне. | 03 What main difficulties or challenges did you face and how did you overcome them? Tell about the most interesting or difficult moments in the development process and how the team dealt with them. Here you can also share personal stories that affected the course of your hackathon participation. | Mandatory; pairing confirmed by shape position. |
| REQ-5029 | DELIVERABLE | pptx slide 11 «Содержание_1», title override | organizer — ЛЦТ (presentation template) | КОРОТКО О РЕШЕНИИ | BRIEFLY ABOUT THE SOLUTION (title, overridden on the slide itself). | Mandatory. |
| REQ-5030 | DELIVERABLE | pptx slide 11, left column (heading top≈1.61 + prompt top≈2.10, left≈0.6 in) | organizer — ЛЦТ (presentation template) | Техническая суть решения: Опишите в чем техническая составляющая вашего решения. | Technical essence of the solution: Describe what the technical component of your solution is. | Mandatory; pairing confirmed by shape position. |
| REQ-5031 | DELIVERABLE | pptx slide 11, right column (heading top≈1.61 + prompt top≈2.10, left≈7.1 in) | organizer — ЛЦТ (presentation template) | Маркетинговая суть решения: Опишите ваши идеи по дальнейшему применению, развитию или внедрению проекта. | Marketing essence of the solution: Describe your ideas for the further application, development or implementation of the project. | Mandatory; pairing confirmed by shape position. |
| REQ-5032 | CLARIFICATION | pptx slides 12–29 (18 slides, layouts: 2× «Заголовок и объект», 2× «Фотографии», 2× «Пункты», 3× «Содержание_1», 3× «…Статистика» with embedded CHART objects, «Проблема и решение», «Стадии», 4× «…Демо_1») | organizer — ЛЦТ (presentation template) | Все плейсхолдеры этих 18 слайдов содержат только типовой образец PowerPoint («ОБРАЗЕЦ ЗАГОЛОВКА», «Образец текста», «Второй уровень»…«Пятый уровень»), кроме слайда 24 (см. REQ-5033). | All placeholders on these 18 slides hold only generic PowerPoint sample text ("SAMPLE HEADING", "Sample text", "Second level"…"Fifth level"), except slide 24 (see REQ-5033). | Recommendational (per REQ-5009/msg201's «рекомендательный характер»); these are reusable example layouts (bullets, photo grids, "content" cards, statistics/chart, problem-solution, 5-stage, demo), not slide-specific instructions. |
| REQ-5033 | CLARIFICATION | pptx slide 24 «Проблема и решение», layout placeholders | organizer — ЛЦТ (presentation template) | Проблема — Описание проблемы; Альтернативные решения — Примеры уже имеющихся способов решения данной проблемы; Решение — Ваше предложение решения данной проблемы. | Problem — Description of the problem; Alternative solutions — Examples of already-existing ways to solve this problem; Solution — Your proposed solution to this problem. | Recommendational; the one slide in the 12–29 range with distinct (non-generic) guidance text. |
| REQ-5034 | CLARIFICATION | pptx slide 25 «Стадии» (5-numbered-stage layout, badges «1»–«5») | organizer — ЛЦТ (presentation template) | 5 пронумерованных этапов (1–5), текст плейсхолдеров — типовой образец PowerPoint. | A 5-numbered-stage layout (badges 1–5); placeholder text is generic PowerPoint sample text. | Recommendational; a reusable "process/stages" layout, no stage-specific instructions given. |
| REQ-5035 | DATA-PROVIDED | pptx slide 30 «Полезные материалы» | organizer — ЛЦТ (presentation template) | Поможет выбрать цвет — https://colorscheme.ru/; Поможет выбрать изображение — https://www.neurascapes.com/; Тут ты найдешь иконки — https://www.flaticon.com/; Горячие клавиши PowerPoint — https://nice-slides.ru/powerpoint/lessons/quickstart/горячие-клавиши-powerpoint/ | "Useful materials": will help choose a colour — [link]; will help choose an image — [link]; icons here — [link]; PowerPoint hotkeys — [link]. | Public resource links, no credentials. |
| REQ-5036 | DOMAIN-FACT | pptx slides 31–37 (7 slides, all layout «Пустой с заголовком», all titled «ИКОНКИ» except 32–33) | organizer — ЛЦТ (presentation template) | Иконки, сгруппированные подписями: «Пользователи», «Доставка», «Программирование», «Креативный процесс» (сл.33); «Рассылка», «Медицина», «Еда», «Инфраструктура» (сл.34); «Локация», «Образование», «Природа», «Поддержка» (сл.35); «Разное» (сл.36); слайд 37 без подгрупп; слайд 32 = «Бизнес» / «Графики» picture galleries. | Icon libraries grouped by caption: "Users", "Delivery", "Programming", "Creative process" (sl.33); "Mailing", "Medicine", "Food", "Infrastructure" (sl.34); "Location", "Education", "Nature", "Support" (sl.35); "Miscellaneous" (sl.36); slide 37 ungrouped; slide 32 = "Business"/"Charts" picture galleries. | Pure asset library; hundreds of PICTURE shapes, not itemised individually (see §1 "what could not be read"). |

## 5. Conflicts and changes over time

- **Which artefact is chronologically later is ambiguous.** The docx's filename encodes
  «финал_01092026» (01.09.2026); it carries no author/date metadata (per SRC-001) and was **posted**
  in the task-9 chat on 18.09.2026 (msg587). The PDF's own embedded metadata gives `CreateDate`/
  `ModifyDate` = 2026-09-11 12:44/12:47 MSK (`dc:creator` "Катенька"), i.e. authored **after** the
  docx's filename date, but it was **linked** in the chat earlier, on 15.09.2026 (msg201) — 3 days
  before the docx was attached. So by filename the docx is "older"; by chat-post order the docx is
  "newer"; by file metadata the PDF is "newer". No statement in the archived chat or documents
  resolves this ordering explicitly for this specific PDF (it is new to the archive as of this task,
  2026-09-23).
- Already on file in SRC-001 (REQ-2259's own Notes, REQ-2268's own Notes): the docx-only ambiguities
  «например?» (stray question mark) and the chat conflicts referenced for ¶326 (msg570 18.09.2026,
  msg624/msg638) predate this task. D7 above shows the PDF's wording no longer contains the "?" typo;
  this is recorded as a fact about the PDF text, not as a resolution of the msg570/624/638 chat
  conflict (those messages are outside this task's scope — see SRC-001-chat.md).
- SRC-001 already records (its own header, not re-extracted here): msg625 «Ориентируемся на ТЗ, как
  первоисточник» ("We go by the ТЗ as the primary source") and msg637 «надо смотреть совокупность ТЗ и
  ответов на вопросы» ("one must look at the ТЗ and the Q&A together"), both from moderator Str1fe.
  Neither message names which file format ("ТЗ" as PDF vs docx) is meant; both were said in the
  context of the docx (the only ТЗ file in the archive at the time SRC-001 was written).
- D5 vs REQ-2099–REQ-2104's REQ-2100 (text-message alternative to IP telephony) and D15 (diagram
  evaluation basis) are the two differences in §2 with a plausible bearing on what "correct" looks
  like for the built product/evaluation; both are flagged there with dates as above, no resolution
  asserted.
