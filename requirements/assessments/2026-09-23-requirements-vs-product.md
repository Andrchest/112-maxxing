# Requirements vs product — assessment of 2026-09-23 (round 2 included)

Scope of this document: every statement extracted from the organizers' material in
`requirements/sources/` (950 items: round 1 `REQ-1001`…`REQ-4094`, 638 items; round 2
`REQ-5001`…`REQ-6047`, 312 items) compared with the repository at `main`,
HEAD `8ccad9f` (2026-09-23 15:03 +0300), and with `docs/SPEC.md`, the specification the product was
built from. It reports facts only: what a source says, what the repository contains, and where the
two differ. It contains no proposals, priorities or estimates.

Reading guide: §3 gives the numbers; §4 lists every point where `docs/SPEC.md` says something other
than the organizers; §9 sets out the dated organizer statements, re-checked against the Q&A recording
(speaker and timestamp per statement), including the caller-side AI voice (§9.1) and the ДДС role
(§9.2–§9.3); §6 lists what already matches; §7 lists every partial or missing item; §11 records the
owner's scope decisions of 2026-09-23 (facts, not statuses).

Round 2 (added the same day): the organizer materials behind the msg201 links (ТЗ PDF, presentation
template, 96-call tickets, ДДС memo, classifier v_046_24), the chat of 22.09 21:29–23.09 18:20 (incl.
the customer's answer on the ДДС role), and two further transcripts of the 16.09 Q&A recording checked
against the recording itself. Where round 2 corrects an earlier statement, the text says so.

---

## 1. Scope and method

### 1.1 Sources analysed

| Source ID (`requirements/INDEX.md`) | File(s) | Processed in |
|---|---|---|
| SRC-001 | `requirements/sources/01-qna-session-telegram/messages.html` (Telegram export of the task-9 chat, 407 messages, 29.06.2026–22.09.2026) | `requirements/normalized/SRC-001-chat.md` |
| SRC-001 | `…/files/ТЗ_ДГОЧСиПБ_финал_01092026ГСИ.docx`, `…/files/Ответы на вопросы.pdf`, `…/files/Инструкция для участника .pdf`, `…/files/РТУ Т16Р_Datasheet_ 2024_ГСИ.pdf` | `requirements/normalized/SRC-001-formal-docs.md` |
| SRC-001 | `…/files/КАРТОЧКА 112.docx`, `…/files/СКРИНШОТ КАРТОЧКИ 112ГСИ.docx`, `…/files/Инструкция_по_заведению_карточки_2507ГСИ.docx`, `…/files/СКРИНШОТ ДДСГСИ.docx`, `…/files/СЛУЖБЫ 112.docx`, `…/files/Классификатор_происшествий_v_046_11_ДТУ_15_11_2024_искл_пожар_задымление.xlsx` | `requirements/normalized/SRC-001-domain-docs.md` |
| SRC-001 | `…/video_files/IMG_2549.MP4` (2 min 34 s) | `requirements/normalized/SRC-002-003-video.md` (REQ-4075…4094); transcript in `requirements/evidence/IMG_2549-transcript.md` |
| SRC-002 | `requirements/sources/02-original-requirement/Город 9.txt` (921 lines, transcript of the task-9 Q&A session) | `requirements/normalized/SRC-002-003-video.md` (REQ-4001…4063) |
| SRC-003 | `requirements/sources/03-challenge-brief/brief-from-user.md` (task description) | `requirements/normalized/SRC-002-003-video.md` (REQ-4064…4074, 4090) |
| SRC-005 | `requirements/sources/05-organizer-materials/`: `9. Деп Обороны и ЧС (1).pdf` (ТЗ as PDF, the msg201 «Техническое задание» link), `ЛЦТ2026 Шаблон презентации (1).pptx` (template, msg201), `Билеты- задачи по C 112 . АГС_ГСИ (1).pdf` (tickets, «Датасет»), `Работа с АРМ-112 для ДДС от ОКр_ГСИ (1).pdf` (ДДС memo, «Датасет»), `Классификатор_происшествий_v_046_24_корректировка_МВД_+_Департамент (1).xlsx` | `requirements/normalized/SRC-005-tz-pdf-and-template.md` (REQ-5001…5036), `SRC-005-tickets-and-dds-memo.md` (REQ-5201…5363; OCR in `requirements/evidence/tickets-ocr.md`), `SRC-005-classifier-v046-24.md` (REQ-5701…5721) |
| SRC-006 | `requirements/sources/06-chat-update-2026-09-23/messages-2026-09-22-23.txt` (plain-text continuation of the chat, 22.09.2026 21:29 – 23.09.2026 18:20) | `requirements/normalized/SRC-006-chat-update.md` (REQ-5901…5945) |
| SRC-007 | `requirements/sources/07-qna-transcript-gigaam/` (second transcript of the 16.09 Q&A recording, GigaAM v3, 22-s windows) | `requirements/normalized/SRC-007-qna-gigaam.md` (REQ-6001…6047, and a verdict for each of REQ-4001…4063); comparison in `requirements/evidence/qna-transcripts-comparison.md` |
| SRC-008 | `requirements/sources/08-qna-transcript-whisper-large-v3/` (third transcript of the same recording, faster-whisper large-v3) | No items of its own; used as the third reading in `requirements/evidence/qna-transcripts-comparison.md` |
| SRC-004 | `requirements/sources/04-first-version-prompt/pront.txt` | Not itemised. Its text is identical to `docs/SPEC.md` apart from the first comment line of `docs/SPEC.md` (checked with `diff` for this report). `docs/SPEC.md` is used as the comparison baseline ("SPEC.md" column in the matrices) and is traced section by section in `docs/AUDIT.md`. |

Round 1: phase 1 (extraction, four files) produced 638 items; phase 2 (five traceability matrices in
`requirements/traceability/`) compared every item with `docs/SPEC.md` and the repository. Round 2:
five more extraction files produced 312 items, and two more matrices (`TRC-SRC-005.md`,
`TRC-SRC-007.md`) compared them; each has a Part 2 that re-judges earlier items in the light of the
new material. This report is built from the nine normalized files, seven matrices, two evidence files
and the phase reports, and from repository evidence re-opened where a matrix row was surprising or two
matrices disagreed (§1.6, §1.7).

### 1.2 What was not read, or not read in full

| Material | Status | Reason |
|---|---|---|
| Video recording of the Q&A session | Round 1: not read. Round 2: read (owner's copy, 01:05:45, not in the repository) | Round 1 had only the msg468 link. In round 2 the owner supplied the recording (`/home/andreipc/everything/Город 9. Департамент по делам гражданской обороны.mp4`, 522 MB, not copied). Three transcripts (W = `Город 9.txt`, faster-whisper turbo; G = GigaAM, SRC-007; L3 = whisper large-v3, SRC-008) were aligned and every disputed passage was re-transcribed from the audio with the repository's GigaAM provider and a second checkpoint (`requirements/evidence/qna-transcripts-comparison.md` §1). The audio is digital silence at 11:40–12:29: the start of the answer on scenario generation is lost in every reading (REQ-6003). The recording shows no date and has no `creation_time` tag. |
| «Техническое задание», «Датасет» and «Шаблон презентации» cloud links (chat msg201, 15.09.2026) | Round 1: not read. Round 2: files archived and read | The files behind the links are now in `requirements/sources/05-organizer-materials/` (ТЗ PDF, tickets, ДДС memo, template, classifier v_046_24). The access password is not reproduced ([credential redacted]). The ТЗ PDF differs from the docx in 18 logged places, none in a number, hardware minimum, deadline or legal citation (SRC-005-tz-pdf §2). Which of the two is later is not settled by the archive (file-name date, chat order and PDF metadata point different ways). |
| Tickets PDF | Read (OCR) | 32 scanned pages, no text layer; tesseract OCR of every page, 24 pages also viewed directly (`requirements/evidence/tickets-ocr.md`). |
| Classifier v_046_24 | Read, diff scoped | Joined to v_046_11 on the code column; МВД, Служба 101, main service, content columns and all «Департамент*» columns were diffed row by row, not all ~65 organisations. |
| Chat continuation (SRC-006) | Read in full | Plain-text export: attachments are placeholders only (`[ Photo ]`), so the 18:20 post's screenshot was not seen. |
| `СЛУЖБЫ 112.docx` | Read in part | 55 scroll frames of one drop-down; about 20 were viewed. The ~25 city-level services were read; the ~140+ district entries are a sample (REQ-3043). |
| Classifier `.xlsx` | Read in part verbatim | All 1308 rows × 90 columns were read programmatically; only the «Пожары и задымления» category (271 rows) and 13 related rows were copied verbatim (REQ-3047, REQ-3048); the other 23 categories are recorded as structure and counts (REQ-3045). |
| `КАРТОЧКА 112.docx` | Read in part | About 24 of 39 images were transcribed; the rest are scroll repeats of forms already transcribed. |
| `Город 9.txt` | Read in full; checked against the recording in round 2 | No speaker labels. In round 1 turns were attributed by content; the recording shows that 19 statements attributed to "a company representative" are the mentor's and 8 are split (§1.3). Of REQ-4001–4063, 29 are confirmed and 34 corrected in wording or speaker (SRC-007 §3); garbled phrases such as «ФТЗ», «инвестиционации», «несоединительной генерацией» are mis-hearings (§8). |
| `IMG_2549.MP4` | Read in full | Audio transcribed on CPU (GigaAM); 15 frames viewed. It is a promotional video (see §9.10), not the Q&A recording. |
| The product UI | Not rendered | No service was started for this analysis (brief rule). UI facts come from source code; runtime facts come from `docs/DOD_WALK.md` and `docs/AUDIT.md` §2 (the real-stack walk of 2026-09-22). |

### 1.3 How organizers were identified, and how the Q&A session was dated

- **Chat.** Organizer = the channel account «Задача #9 | Департамент по делам гражданской обороны,
  чрезвычайным ситуациям и пожарной безопасности | ЛЦТ 26» (welcome post msg6, chat rules msg7, all
  logistics posts) and the moderator «Str1fe», who introduces himself in msg15 (13.07.2026): «Меня
  зовут Михей, я модератор по задаче №9 от Департамента…» and labels relayed answers «Ответ
  заказчика» / «От заказчика» / «Ответ от заказчика». The other 37 senders are participants; their
  messages are context only. A message without a sender name belongs to the sender of the previous
  message (Telegram export convention), which attributes e.g. msg577, 625, 638 and 691 to Str1fe.
- **ТЗ.** Customer text: its title page names «ДЕПАРТАМЕНТ ПО ДЕЛАМ ГРАЖДАНСКОЙ ОБОРОНЫ, ЧРЕЗВЫЧАЙНЫМ
  СИТУАЦИЯМ И ПОЖАРНОЙ БЕЗОПАСНОСТИ ГОРОДА МОСКВЫ» and «ГБУ «Система 112»»; Str1fe posted it (msg587).
- **FAQ and Q&A guide.** Hackathon organizer (ЛЦТ) documents posted by the channel account (msg6) and
  Str1fe (msg216).
- **Datasheet.** Third-party vendor document (САТЕЛ), posted by Str1fe without caption (msg482); it is
  organizer-provided material, not an organizer statement.
- **Domain documents** (card screenshots, operator manual, service list, classifier). Posted by Str1fe
  (msg480–484, 17.09.2026; msg685–687, 21.09.2026: «Эксперты передали скриншоты системы для большего
  понимания интерфейса и бизнес-процесса»). They describe the real system, not the simulator.
- **`Город 9.txt`.** The session host opens with the cast (L14–17): «ментор задачи Галаган Станислав и
  представители компании-постановщика. Рушенков Александр, Шкиперов Александр и Сергаков Александр
  Григорьевич». Host, mentor and company representatives are organizer speakers; questions read out
  from the form or asked live are participant context.
- **Speakers in the recording (round 2).** The meeting is a Yandex Telemost call, which draws a green
  border around the tile of whoever is speaking. Frames at 1 fps (3 945) were measured for that border
  and the tile labels OCR-read and viewed (`requirements/evidence/qna-transcripts-comparison.md` §1.5,
  §5). Tiles: «Михей Модератор» = the host; «Станислав Галаган» (phone camera) and «Станислав» (screen
  share) = the task **mentor** Станислав Галаган («Я буду с двух аккаунтов…», 05:48); «Александр Ш.» =
  one room camera with four men, the customer's representatives (**room**; a participant names it
  «наши коллеги… которые под аккаунтом Александр Ш. сидят», 64:36). Which of the four men speaks is not
  visible; the first surname in the host's list has four readings (Рушенков / Варшунков / Паршенков /
  Паршунков). The highlight can lag speech by about a second; where two tiles are lit the evidence says
  "both". From 08:04 the mentor shares a sheet of the teams' questions and reads them aloud; those
  questions are participant context. In this report "mentor" and "room" follow this evidence; "the
  customer" means the room tile or a chat message labelled «Ответ заказчика».
- **Chat continuation (SRC-006).** Same rule as the chat: Str1fe and the channel account are
  organizers; «Ответ заказчика» marks a relayed customer answer; the other 20 senders are participants.
- **Round-2 documents.** The tickets and the ДДС memo came from the msg201 «Датасет» link (Str1fe); the
  memo's author line is «Отдел контроля реагирования Службы 112 ГБУ «Система 112»»; the tickets carry no
  author. The ТЗ PDF and template came from the msg201 links.
- **Date of the Q&A session.** The transcript carries no date. Its opening (L7–13) identifies it as
  «сессии вопросов и ответов… задачу номер 9», and the host says «Сессия придлится не более одного
  часа» (L22). The chat announces exactly one task-9 Q&A session: msg216 (15.09.2026, Str1fe) «По
  нашей задаче состоится сессия вопросов и ответов: среда, 16.09 в 11:00-12:00 по МСК»; msg316
  (16.09.2026 07:59) repeats «16 сентября в 11:00»; msg468 (16.09.2026 19:04) posts «запись нашей
  сессии вопросов и ответов с постановщиком и ментором»; msg674 (20.09.2026) answers «На данный
  момент не планируется» to «планируется ли еще QnA сессия?». On that basis the session in
  `Город 9.txt` is dated **16.09.2026, 11:00 MSK**. This is an inference from the chat; neither the
  transcripts nor the recording (checked in round 2: no visible date, clock or title; no
  `creation_time` tag) state a date. The recording's host says «Сессия продлится не более одного часа»
  (03:55).
- **`brief-from-user.md`.** The official task description (sections «Актуальность», «Описание
  задачи», «Ресурсы», «Описание итогового продукта»); it has no date.
- **`IMG_2549.MP4`.** Narrated by «Ащаулов Виктор Кимович», on-screen caption «старший преподаватель
  кафедры гражданской обороны учебно-методического центра ГОЧС города Москвы» (customer-side expert);
  forwarded into the chat by the channel account as msg34 (06.08.2026 19:05) with the task
  announcement text.

### 1.4 Status vocabulary

Only the four statuses of `requirements/README.md` are used:

| Status | Meaning (README) | How it is used here |
|---|---|---|
| `соблюдено` | Implemented and confirmed by sufficient evidence | Code, test, run record or archived file shows the statement is met. For a DOMAIN-FACT: the product's equivalent matches the real-system fact. For DATA-PROVIDED: the provided file is in `requirements/sources/`. |
| `частично` | Implementation or evidence covers part | The matching and non-matching parts are listed. |
| `не соблюдено` | Absent, contradicted, or reproducibly violated | The absent or contradicting fact is listed. |
| `не обработано` | Not yet processed | The item states no checkable obligation, cannot be checked in a repository, or needs a measurement that was not made. §3.4 splits these; they are not failures. |

`INDEX.md` adds: ambiguous or conflicting wording stays `не обработано` with the question recorded.
OPEN-QUESTION items follow that rule.

### 1.5 What counts as evidence

A status other than `не обработано` rests on something that was opened: source code
(`path:line`), a test (`path::test`; tests run for the matrices, CPU only: 71 + 204 + 17 + 17 passed in
round 1, 28 + 28 in round 2;
API/integration tests that need PostgreSQL were read, not run), a documented real run
(`docs/DOD_WALK.md`, `docs/AUDIT.md` §2: real-stack walk of 2026-09-22, 12 PASS / 4 PARTIAL), a
configuration file, a command output recorded in the matrix (e.g. `git ls-files`, `gh repo view`), or
a file present in `requirements/sources/`. A comment, a plan, a TODO or a self-assessment in the
repository is not evidence. "SPEC.md" coverage values: `same` (SPEC says the same), `differs` (SPEC
says something else; both quoted), `not covered` (SPEC is silent).

### 1.6 Corrections made to the phase-2 matrices for this report

Rows were re-opened where a matrix was surprising or where two matrices judged the same wording or
the same facts differently. The matrices now carry these corrections, each edited row marked «(corrected by the report, §1.6)»;
the corrected statuses below are the ones used in the matrices, this report and `requirements/INDEX.md`.

**Status corrections (10):**

| ID | Matrix status | Status here | Evidence re-opened |
|---|---|---|---|
| REQ-4016 | соблюдено | частично | Source: ДДС «может… либо ответить, либо отказаться, либо перенаправить еще куда-то» after a «строчку нового сообщения» appears. `backend/app/domain/session/transitions.py` has no reject/decline transition (grep `reject\|decline`: 0 hits); `ClosureReason` = RESOLVED, FALSE_CALL, TRANSFERRED, CANCELLED_BY_CALLER (`backend/app/domain/enums.py:302-306`); the DDS UI has no incident list (REQ-3039). Card → DDS delivery exists. |
| REQ-4034 | соблюдено | частично | Source: «может появиться новая карточка… проверять… чтобы особенно критических не было ошибок в адресах». Address check exists: rule `card_house_correct`, `critical: true` (`scenarios/examples/apartment-fire/v1.yaml:233-244`). A new card cannot appear: one incident per session (`uq_incidents_session`, `backend/app/db/models/session.py:161`). |
| REQ-4053 | соблюдено | частично | Source: «минимальные требования к самому пакету… к MVP… в ТЗ указаны, это должно быть соблюдено». The ТЗ package items REQ-2338/2373 (presentation) and REQ-2374 (prototype link) are `не соблюдено`, REQ-2375 (.docx/.pdf docs) is `частично`; Docker Compose packaging exists. |
| REQ-4054 | не соблюдено | не обработано (superseded in round 2 → частично, §1.7) | The «96 билетов» were then in the external «Датасет» link, not in the archive; the same situation was `не обработано` in REQ-2292 and REQ-1049. Fact kept: the repository ships one scenario. |
| REQ-4072 | не соблюдено | не обработано | Organizer-side resource («Действующее программное обеспечение системы-112… база данных») not in the archive; treated like REQ-2294–2296. |
| REQ-4083 | не соблюдено | не обработано | Organizer-side «реальные данные» not in the archive; same treatment. |
| REQ-4065 | соблюдено | не обработано | Relevance/motivation statement («Актуальность… отсутствие специального обучающего программного обеспечения…»); the ТЗ's equivalent statements REQ-2038–2042 are `не обработано`. |
| REQ-4066 | соблюдено | частично | «работы диспетчерского персонала ДДС со специальным программным обеспечением, применяемого в системе 112»: same substance as REQ-2058/REQ-2093 (`частично`): the product trains on its own interface, which differs from the archived screenshots of the real one (REQ-1044, REQ-1045, REQ-4022). |
| REQ-2145 | не соблюдено | частично | Verbatim-identical to REQ-2251 (`частично`), same facts in both rows: no multi-node deployment; a Redis runner lock lets a second backend instance adopt a session (`backend/tests/unit/application/simulation/test_runner.py::test_after_the_ttl_expires_the_other_instance_adopts_the_session`, run: passed). |
| REQ-2123 | не обработано | частично | Verbatim-identical in substance to REQ-2240 (`частично`). The term «многоуровневая аутентификация» was defined by the organizer in the Q&A (REQ-4056): «три уровня, администратор, преподаватель, обучаемый… каждым своими логинами и паролями… Больше ничего не нужно». Three account roles with password login exist; «Просто двухфакторка» remains ambiguous (§8). |

**Gap-text corrections (no status change):**

- REQ-2058, REQ-2081, REQ-2093, REQ-2104, REQ-2217 say the repository contains no screenshot or
  material of the real system-112 interface. That is not so: `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx`,
  `СКРИНШОТ ДДСГСИ.docx`, `КАРТОЧКА 112.docx`, `СЛУЖБЫ 112.docx` and the operator manual
  `Инструкция_по_заведению_карточки_2507ГСИ.docx` are in `requirements/sources/01-qna-session-telegram/files/`
  (checked with `ls`). The correct fact: no product code, scenario or doc (SPEC, AUDIT, HLD, README)
  references them, and the product's card and colours differ from them (REQ-1044, REQ-1045,
  REQ-3001–REQ-3043).
- REQ-2095, REQ-2120, REQ-2219 say no official regulation or standard-procedure text is in the
  repository. The archived operator manual (REQ-3011–REQ-3037) describes the real card-entry
  procedure; it is a user manual, not a regulation. No product file references it.
- REQ-2334, REQ-2372 say repository visibility cannot be verified. `gh repo view --json visibility`
  run for this report (2026-09-23) returns `"visibility":"PRIVATE"` for `Andrchest/112-maxxing`. The
  organizer's submission instruction (msg700) accepts «публичный Git-репозиторий… или предоставлен
  гостевой доступ»; whether guest access has been granted is not visible from the repository. The
  same applies to REQ-1015.

**Status disagreements left as recorded** (same facts, different judgement between matrices; the
facts are stated together in §7):

- The customer department is named nowhere in the product: REQ-2004, REQ-2012, REQ-3011, REQ-4001,
  REQ-4064, REQ-4093 are `не соблюдено`; REQ-1001 and REQ-2001 (the same department names) are
  `не обработано` as "no product obligation".
- AI/ML-based assessment: REQ-2063, REQ-2091, REQ-2121, REQ-4017 `не соблюдено`; REQ-2090, REQ-2102,
  REQ-4067 `частично`; REQ-4082 `соблюдено` («независимую оценку», no mention of AI). The facts are
  the same (deterministic scoring, LLM explanation only); the wording of the sources differs.

### 1.7 Round-2 re-judgements applied to the earlier matrices

`TRC-SRC-005.md` Part 2 and `TRC-SRC-007.md` Part 2 re-judged earlier items with the new material and
the recording-verified text. Their status changes are applied to the earlier matrices' rows, marked
«(re-judged by TRC-SRC-005 Part 2)» / «(re-judged by TRC-SRC-007 Part 2)», and the count blocks were
regenerated.

| ID | Before | After | Why (facts) |
|---|---|---|---|
| REQ-1049 | не обработано | не соблюдено | The organizer-posted dataset contains the tickets (32 «БИЛЕТ» pages × 3 calls = 96 rows, extractor's count); the repository has none of them (TRC-SRC-005). |
| REQ-2290 | не обработано | частично | The memo «Работа на АРМ-112. Памятка для дежурно-диспетчерских служб» is now archived; of its 121 items 3 соблюдено, 31 частично, 70 не соблюдено, 17 не обработано; no repository file references it (TRC-SRC-005). |
| REQ-2292 | не обработано | не соблюдено | «Билеты и задачи» now archived; no scenario reproduces a ticket call (TRC-SRC-005). |
| REQ-4024 | не обработано | не соблюдено | Recording: the mentor continues «Надо будет просто попробовать повторить то, что вы будете видеть на скриншоте»; the UI does not reproduce the screenshots (TRC-SRC-007). |
| REQ-4025 | не обработано | частично | Recording: mentor's description (card, tags, muted colours, next call); judged from static facts (TRC-SRC-007). |
| REQ-4027 | не обработано | частично | Mentor's evaluation list names checkable properties: interface resemblance no, card filled yes, questions generated yes, real requests no (TRC-SRC-007). |
| REQ-4043 | не соблюдено | не обработано | Recording: 40:42–40:58 is the mentor («будет хорошо оценено тоже»); the room's part only removes the question for this competition and contains no prohibition (TRC-SRC-007). |
| REQ-4054 | не обработано (§1.6) | частично | TRC-SRC-005 Part 2 judged `не соблюдено` on the old wording and the tickets; TRC-SRC-007 Part 2, on the recording-verified text («основа для генерации новых, но можно использовать и эталонные»; room: «хотите — генерируйте новые… исходя из жизненных… ситуаций… и то, и то приветствуется»), judges `частично`. The two Part 2 tables disagree; the later, recording-based `частично` is used, and the row records both. |
| REQ-4055 | не обработано | частично | Mentor: experts may use arbitrary scenarios; import only via API/CLI files; tickets absent as scenarios (TRC-SRC-007). |

Also corrected: `TRC-SRC-002-003-video.md` REQ-4003 cited `DEV_3060TI.yaml:71,81` as the LLM on
`cuda`; those lines are the ASR and TTS devices. The LLM's GPU use is `n_gpu_layers: -1`
(`DEV_3060TI.yaml:51`, same key in every profile). The status (`не соблюдено`) is unchanged.

Speaker corrections without a status change (recording): REQ-4009, 4010, 4020, 4021, 4028–4030,
4037–4039, 4050, 4052, 4053, 4060–4062 are wholly the mentor's; REQ-4005, 4006, 4031, 4044, 4051 are
split between mentor and room; REQ-4063 is the room's, not the mentor's (TRC-SRC-007 Part 2).

---

## 2. Sources at a glance

| # | Document | What it is | Issued by | Date | Items | IDs |
|---|---|---|---|---|---:|---|
| 1 | `messages.html` | Telegram chat of task 9: organizer announcements, moderator answers (many relayed as «Ответ заказчика»), participant questions | Channel account «Задача #9 \| Департамент…» and moderator Str1fe; 37 participant senders (context only) | 29.06.2026 – 22.09.2026 (last message msg703, 22.09.2026 22:29) | 58 | REQ-1001–1058 |
| 2 | `ТЗ_ДГОЧСиПБ_финал_01092026ГСИ.docx` | Technical specification «Учебное программное обеспечение для подготовки оператора ДДС города Москвы с использованием искусственного интеллекта»; unnumbered bullet clauses under 23 headings | Customer (Department + ГБУ «Система 112»), posted by Str1fe | File name 01.09.2026; link in msg201 15.09.2026; file in msg587 18.09.2026 | 375 | REQ-2001–2375 |
| 3 | `Ответы на вопросы.pdf` | One-page generic ЛЦТ-2026 FAQ (teams, age, website, chats); nothing task-9 specific | ЛЦТ organizer, posted by the channel account (msg6) | 29.06.2026 | 15 | REQ-2376–2390 |
| 4 | `Инструкция для участника .pdf` | 4-page guide to the Q&A session | ЛЦТ organizer, posted by Str1fe (msg216) | 15.09.2026 | 24 | REQ-2391–2414 |
| 5 | `РТУ Т16Р_Datasheet_ 2024_ГСИ.pdf` | Vendor datasheet of a corporate IP phone | Vendor САТЕЛ; posted by Str1fe without caption (msg482) | PDF 25.09.2024; posted 17.09.2026 | 16 | REQ-2415–2430 |
| — | (ambiguities across docs 2–5) | OPEN-QUESTION items written by the extractor | — | — | 7 | REQ-2431–2437 |
| 6 | `КАРТОЧКА 112.docx` | Screenshots of the real 112 card incl. the 51-item «Что случилось?» list | Organizer-supplied («Эксперты передали скриншоты…», msg687) | Posted 21.09.2026 (msg685) | 7 | REQ-3001–3007 |
| 7 | `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx` | 9 annotated card screenshots with operator captions | Organizer-supplied | Posted 17.09.2026 (msg480–484) | 3 | REQ-3008–3010 |
| 8 | `Инструкция_по_заведению_карточки_2507ГСИ.docx` | User manual of the real module «Прием и обработка вызовов 112» (versions 1.7–2.1 tagged inside) | Organizer-supplied | Posted 17.09.2026 | 27 | REQ-3011–3037 |
| 9 | `СКРИНШОТ ДДСГСИ.docx` | 20 annotated screenshots of the real ДДС screen | Organizer-supplied | Posted 17.09.2026 | 4 | REQ-3038–3041 |
| 10 | `СЛУЖБЫ 112.docx` | 55 frames of the real «Добавьте службы» picker | Organizer-supplied | Posted 21.09.2026 (msg686) | 2 | REQ-3042–3043 |
| 11 | `Классификатор_происшествий_…_искл_пожар_задымление.xlsx` | Real incident classifier, 1308 rows × 90 columns (codes, types, routing matrix of ~65 organisations) | Organizer-supplied | Version date 15.11.2024 in file name; posted 17.09.2026 | 6 | REQ-3044–3049 |
| 12 | `Город 9.txt` | Transcript of the task-9 Q&A session (no speaker labels; speakers established from the recording in round 2) | Host, mentor Галаган Станислав, customer company representatives | 16.09.2026 (inferred, §1.3) | 63 | REQ-4001–4063 |
| 13 | `brief-from-user.md` | Official task description | Hackathon/customer text | Undated | 12 | REQ-4064–4074, REQ-4090 |
| 14 | `IMG_2549.MP4` + chat msg34 text | Promotional video of task 9 and its announcement text | Customer-side expert Ащаулов В.К.; «ЛЦТ 2026 \| Хакатон» / task channel | 06.08.2026 (msg34) | 18 | REQ-4075–4088, REQ-4091–4094 |
| — | (cross-source) | OPEN-QUESTION: the «ТЗ/ФТЗ» named in the transcript | — | — | 1 | REQ-4089 |
| 15 | `pront.txt` (SRC-004) | The first-version prompt = `docs/SPEC.md` | Product owner | — | 0 (baseline, not itemised) | — |
| 16 | `9. Деп Обороны и ЧС (1).pdf` | The ТЗ as PDF (msg201 «Техническое задание» link); same requirements as the docx, 18 logged wording/format differences; new cover items only | Customer | PDF metadata 11.09.2026; linked 15.09.2026 | 3 | REQ-5001–5003 |
| 17 | `ЛЦТ2026 Шаблон презентации (1).pptx` | Presentation template, 37 slides; slides 7–11 labelled «Обязательный блок» | ЛЦТ organizer (msg201 link) | Modified 14.09.2026; linked 15.09.2026 | 33 | REQ-5004–5036 |
| 18 | `Билеты- задачи по C 112 . АГС_ГСИ (1).pdf` | 32 scanned pages «БИЛЕТ N — Отработайте вызовы от заявителя», 3 calls each (96 rows): situation, caller, phone, address | Organizer-supplied («Датасет», msg201); no author line | Linked 15.09.2026 | 42 | REQ-5201–5242 |
| 19 | `Работа с АРМ-112 для ДДС от ОКр_ГСИ (1).pdf` | 40-page memo «Работа на АРМ-112. Памятка для дежурно-диспетчерских служб» (statuses, 30-s rule, card statuses, search, control department) | ГБУ «Система 112», Отдел контроля реагирования («Датасет», msg201) | Memo dated 2025; PDF created 21.10.2025 | 121 | REQ-5243–5363 |
| 20 | `Классификатор_происшествий_v_046_24_корректировка_МВД_+_Департамент (1).xlsx` | Classifier v_046_24, 99 columns × 1310 rows; diffed against v_046_11 | Organizer-supplied (msg201 link) | — | 21 | REQ-5701–5721 |
| 21 | `messages-2026-09-22-23.txt` (SRC-006) | Chat continuation: training organisation, concurrent cards, AI endpoint vs demo, the customer's answer on the ДДС role, presentation/submission/evaluation timeline | Str1fe (incl. «Ответ заказчика»), channel account; participants as context | 22.09.2026 21:29 – 23.09.2026 18:20 | 45 | REQ-5901–5945 |
| 22 | Q&A recording + transcripts G (SRC-007) and L3 (SRC-008) | Re-check of the 16.09 session against the recording: verified wording, timestamps, speakers | Host, mentor Галаган Станислав, customer room «Александр Ш.» | 16.09.2026 (inferred); transcripts made 23.09.2026 | 47 | REQ-6001–6047 |
| | **Total** | | | | **950** | |

---

## 3. Summary in numbers

All numbers use the statuses now carried by the seven matrices (round-1 corrections §1.6 and round-2
re-judgements §1.7 applied). Totals: **соблюдено 130 · частично 239 · не соблюдено 309 · не обработано
272** (950 items). Round 1 alone (638 items, REQ-1001–4094) now stands at 106 · 186 · 153 · 193 (it
was 106 · 181 · 151 · 200 before §1.7); round 2 (312 items, REQ-5001–6047) is 24 · 53 · 156 · 79.

### 3.1 Items per source × status

| # | Document | соблюдено | частично | не соблюдено | не обработано | Total |
|---|---|---:|---:|---:|---:|---:|
| 1 | Chat `messages.html` | 13 | 14 | 4 | 27 | 58 |
| 2 | ТЗ docx | 75 | 128 | 82 | 90 | 375 |
| 3 | FAQ pdf | 0 | 0 | 0 | 15 | 15 |
| 4 | Q&A guide pdf | 0 | 0 | 0 | 24 | 24 |
| 5 | РТУ Т16Р datasheet | 0 | 4 | 12 | 0 | 16 |
| — | Open questions on docs 2–5 | 0 | 0 | 0 | 7 | 7 |
| 6 | КАРТОЧКА 112 | 0 | 2 | 5 | 0 | 7 |
| 7 | СКРИНШОТ КАРТОЧКИ 112 | 0 | 1 | 2 | 0 | 3 |
| 8 | Инструкция (operator manual) | 0 | 7 | 20 | 0 | 27 |
| 9 | СКРИНШОТ ДДС | 0 | 2 | 2 | 0 | 4 |
| 10 | СЛУЖБЫ 112 | 0 | 0 | 2 | 0 | 2 |
| 11 | Классификатор v_046_11 | 0 | 0 | 5 | 1 | 6 |
| 12 | `Город 9.txt` (Q&A session) | 12 | 24 | 17 | 10 | 63 |
| 13 | `brief-from-user.md` | 3 | 3 | 1 | 5 | 12 |
| 14 | Video + msg34 | 3 | 1 | 1 | 13 | 18 |
| — | Cross-source open question | 0 | 0 | 0 | 1 | 1 |
| 16 | ТЗ PDF (cover items) | 0 | 0 | 0 | 3 | 3 |
| 17 | Presentation template | 0 | 0 | 20 | 13 | 33 |
| 18 | Tickets («96 билетов») | 2 | 3 | 35 | 2 | 42 |
| 19 | ДДС memo «Работа с АРМ-112» | 3 | 31 | 70 | 17 | 121 |
| 20 | Классификатор v_046_24 | 0 | 0 | 12 | 9 | 21 |
| 21 | Chat continuation 22–23.09 (SRC-006) | 6 | 5 | 9 | 25 | 45 |
| 22 | Q&A recording, verified (SRC-007) | 13 | 14 | 10 | 10 | 47 |
| | **Total** | **130** | **239** | **309** | **272** | **950** |

Items are counted once per source statement. The same requirement often appears in several sources
(the ТЗ repeats clauses verbatim; the chat, the Q&A and the memo restate ТЗ points; SRC-007 restates
REQ-40xx with verified wording). §5–§7 group such duplicates under one finding, so the narrative
counts are smaller than these item counts.

### 3.2 Coverage by `docs/SPEC.md`

| SPEC.md coverage | Items | соблюдено | частично | не соблюдено | не обработано |
|---|---:|---:|---:|---:|---:|
| `same` — SPEC says the same thing | 153 | 77 | 69 | 0 | 7 |
| `differs` — SPEC says something else | 71 | 4 | 33 | 24 | 10 |
| `not covered` — SPEC is silent | 726 | 49 | 137 | 285 | 255 |

Facts that follow from the table:
- No item that SPEC covers in the same way is `не соблюдено`.
- 24 of the 309 `не соблюдено` items are points where SPEC chose differently from the organizers
  (§4); the other 285 are points SPEC never addressed.
- `docs/SPEC.md` contains no occurrence of «ТЗ», Cyrillic «ДДС» (it writes Latin "DDS"), «Москв»/Moscow,
  «ГБУ», «ЕКП», «опросн», classifier, district, screenshot, register/«реестр», account, backup, TLS,
  statistic, Excel, PDF, XML, mobile or grammar (grep run for this report); it never mentions a
  presentation, template, tickets, АРМ-112, ПОВ-112, response statuses or search (grep in TRC-SRC-005).
  Its only "export" is «Export benchmark results to JSON/CSV» (§40); its only hardware terms are
  GPU/VRAM profiles (§26, §38); it names SIP only as a later complement to LiveKit (§15).

### 3.3 Items where SPEC.md `differs` from organizer material (71)

Round 1 (55): REQ-1021, 1024, 1028, 1037, 1038, 1044; REQ-2002, 2041, 2044, 2054, 2055, 2057, 2063,
2081, 2082, 2084, 2085, 2089, 2090, 2091, 2100, 2102, 2104, 2109, 2112, 2113, 2118, 2121, 2139, 2145,
2152, 2155, 2186, 2195, 2220, 2223, 2249, 2256, 2257, 2287, 2301, 2320, 2432; REQ-3011; REQ-4003, 4008,
4015, 4017, 4018, 4022, 4038, 4040, 4043, 4044, 4045.
Round 2 (16): REQ-5276, 5912, 5914, 5916, 5918, 5926; REQ-6004, 6007, 6012, 6021, 6024, 6027, 6028,
6029, 6041, 6046. Each group is quoted on both sides in §4.

### 3.4 The 272 `не обработано` items: why they carry no verdict

They are not failures. They split as follows.

**A. Not checkable in a repository (258):**

| Code | Reason | Count | IDs |
|---|---|---:|---|
| A1 | ТЗ term definitions, issuing parties, relevance/motivation, expected outcomes | 47 | REQ-2001, 2003, 2006–2011, 2014–2036, 2038–2042, 2048–2052, 2076–2080, 4065 |
| A2 | Hackathon administration, events, tooling, FAQ, Q&A-session procedure, acknowledgements | 65 | REQ-1002, 1003, 1006, 1008, 1011, 1012, 1018, 1019, 1051–1057, 2376–2414, 4002, 4013, 4074, 4076, 4085, 4091, 5902, 5905, 5911, 6002, 6047 |
| A3 | Deadlines, post-deadline rules and future hackathon events not reached on 2026-09-23 | 13 | REQ-1004, 1009, 1014, 1016, 1058, 5936–5938, 5940–5944 |
| A4 | Customer/background/marketing narrative, meta-statements | 11 | REQ-1001, 4046, 4068, 4077–4079, 4084, 4087, 4090, 4092, 4094 |
| A5 | Facts about a source file, its versions or its framing (incl. contact numbers, encouragement, duplicate rows) | 20 | REQ-5001–5003, 5005, 5207, 5208, 5244–5246, 5304, 5318, 5326, 5342, 5702, 5703, 5706, 5710, 5711, 5718, 5719 |
| A6 | Non-mandatory («рекомендательный», not «Обязательный блок») template slides, styling, logo/icon libraries, links | 12 | REQ-5006, 5009–5014, 5032–5036 |
| A7 | Jury judgement and judging methodology | 23 | REQ-1017, 1033, 2344–2348, 2350, 2351, 2354–2358, 2360, 2366–2368, 2371, 4029, 4061, 6016, 6039 |
| A8 | Participant text (questions, proposals, hearsay) without an organizer answer to judge here | 13 | REQ-1023, 1040, 1041, 1043, 5901, 5906–5908, 5921, 5922, 5928, 5929, 6004 |
| A9 | OPEN-QUESTION items and ambiguous referents (INDEX.md rule) | 17 | REQ-2431–2437, 3049, 4088, 4089, 5359, 5360, 5363, 5720, 5721, 6003, 6030 |
| A10 | Organizer-side data or material not in the archive, or not yet existing | 9 | REQ-2293–2296, 4011, 4012, 4048, 4072, 4083 |
| A11 | Legal references; obligations or limitations of real services/sites with no product counterpart | 10 | REQ-2335–2337, 5251, 5252, 5263, 5291, 5325, 5344, 5346 |
| A12 | Wording undefined or subjective; not decidable from code | 9 | REQ-2110, 2155, 2183, 2327, 2339–2341, 4026, 5904 |
| A13 | Permissions (not obligations) and branches that do not apply | 6 | REQ-5912, 5926, 5931, 5934, 5935, 6031 |
| A14 | The verified statement removes an obligation for this stage and sets none | 3 | REQ-4043, 6027, 6046 |

**B. Need a running measurement or a run on named hardware/software that was not made (14):**

| Item | What would have to be measured |
|---|---|
| REQ-2137 | UI response ≤ 2 s at up to 100 users |
| REQ-2138 | ≥ 20 simultaneous sessions |
| REQ-2139 | VoIP voice latency ≤ 150 ms (the measured speech-end→first-audio p50 1566 ms / p95 4622 ms is a different quantity: it includes ASR, LLM and TTS) |
| REQ-2141 | ≥ 100 DB writes/s |
| REQ-2142 | analytical report ≤ 30 s |
| REQ-2146–2149 | run on the trainee workstation minimum (i5, 16 GB, SSD 256 GB, Gigabit) |
| REQ-2153, REQ-2154 | server RAM 32 GB / NVMe 512 GB sufficiency |
| REQ-2247 | run in current Chrome, Firefox, Яндекс.Браузер |
| REQ-2343 | run on a tablet |
| REQ-4086 | video frame of a real workstation is not legible; no rendered product UI to compare |

(REQ-4025 left this list in round 2: the recording-verified text was judged from static facts, §1.7.)

### 3.5 Totals check across the report, `requirements/INDEX.md` and the matrices

Each matrix's status column was recounted by script from its rows (7-column rows only; the Part 2
re-judgement tables of TRC-SRC-005/007 are not counted, their outcomes are in the earlier matrices'
rows):

| Matrix | соблюдено | частично | не соблюдено | не обработано | Rows |
|---|---:|---:|---:|---:|---:|
| TRC-SRC-001-chat.md | 13 | 14 | 4 | 27 | 58 |
| TRC-SRC-001-formal-docs-a.md | 38 | 85 | 37 | 60 | 220 |
| TRC-SRC-001-formal-docs-b.md | 37 | 47 | 57 | 76 | 217 |
| TRC-SRC-001-domain-docs.md | 0 | 12 | 36 | 1 | 49 |
| TRC-SRC-002-003-video.md | 18 | 28 | 19 | 29 | 94 |
| TRC-SRC-005.md (Part 1) | 11 | 39 | 146 | 69 | 265 |
| TRC-SRC-007.md (Part 1) | 13 | 14 | 10 | 10 | 47 |
| **Sum of matrices** | **130** | **239** | **309** | **272** | **950** |
| §3.1 of this report | 130 | 239 | 309 | 272 | 950 |
| `requirements/INDEX.md` requirement registry (recounted) | 130 | 239 | 309 | 272 | 950 |

Each matrix's own count block states the same numbers as its row recount.

## 4. Where the organizers' material and `docs/SPEC.md` differ

All 71 `differs` items (55 from round 1, 16 from round 2), grouped by subject. Each group gives the
organizer's words (verbatim, with an English rendering), the SPEC's words, and what the product does.
Current status (after §1.6 and §1.7) in brackets. Q&A quotes carry the recording time and speaker
(mentor / room, §1.3); `Город 9.txt` line numbers are kept where round 1 cited them.

### 4.1 What arrives at the 112 stage: an AI-voiced caller vs. no caller at this stage

IDs: REQ-1024 [частично], REQ-4017 [не соблюдено], REQ-4018 [частично], REQ-4040, REQ-4044,
REQ-4045 [не соблюдено], REQ-4043 [не обработано after §1.7]; round 2: REQ-6027 [не обработано],
REQ-6028 [не соблюдено], REQ-6029 [не соблюдено], REQ-6046 [не обработано].

- Organizer:
  - Q&A session, 16.09.2026, **room**, 39:07–39:22 (`Город 9.txt` L572–574): «на этапе разработки программного обеспечения,
    значит, заявителя мы исключаем, то есть никаких заранее подготовленных записей, голосов нет» —
    "at this development stage we exclude the caller: no pre-recorded recordings, no voices".
  - **room**, 42:06–42:28 (L628–631; REQ-6028): «Нет, пока. Давайте мы здесь вообще снимем, то есть никаких голосовых диалогов… голосовой диалог
    только, скажем так, ДДС — руководитель, которому они будут звонить. Вот и всё» — "let's drop it
    entirely: no voice dialogues… the only voice dialogue is ДДС and the head they will call".
  - **room**, 42:28–43:19 (L641–643; REQ-6029): «в рамках вот этой задачи, нас интересует диалог между Б и С… Точку А мы пока
    исключаем. Заявителя. Заявителя, да, и 112 мы пока убираем» — "within this task we are interested
    in the dialogue between B and C… Point A we exclude for now. The caller and 112 we remove for now".
  - **room**, 40:58–41:49 (REQ-6027, REQ-4043): «давайте мы, если на следующий год вот эту идею пусть они
    проработают… снимаем как бы этот вопрос. Но он будет возник[ать] как раз именно в следующем конкурсе»
    — the question is removed for this competition; the recording shows no prohibiting sentence.
  - **room**, 21:41–22:54 (L294–309, REQ-4017): «на первом этапе… мы 112 убираем… заменяем преподавателем и искусственным
    интеллектом… И вторая часть наиболее сложная, это чтобы искусственный интеллект или машина
    оценивала действия обучаемых» — "at the first stage we remove 112 and replace it with the teacher
    and AI… the second, hardest part: AI or the machine evaluates the trainees' actions".
  - Chat msg570, 18.09.2026 11:22, Str1fe («Ответ»): «Конкретно звонок участника событий мы
    исключаем… То есть имитировать голос живого человека оказавшегося на происшествии или попавшего в
    беду не надо» — "we exclude the event-participant's call… no need to imitate the voice of a live
    person at the incident".
  - The **mentor** in the same session: 40:42–40:58 «вы сделаете генерацию всех историй там, например,
    входящими звонками тоже голосовыми… это будет хорошо оценено тоже» (REQ-6026, соблюдено); 43:19–43:22
    «Ну, если коллеги сделают, будет здорово» (REQ-6030, referent not settled); 65:00–65:10, to a
    participant asking for automatically generated, dialogue-adapting telephony: «коллеги как раз
    сказали, что нет, не надо, потому что это сложно… на втором-третьем этапе» (REQ-6046). The chat
    adds msg576, msg624, msg642. All are set out side by side in §9.1.
- SPEC: §1 «The primary implemented flow is: incoming emergency call → Operator 112 interview →
  trainee manually fills incident card…»; §16 «Required pipeline: LiveKit audio → resample/normalize →
  VAD → ASR → semantic dialogue interpretation → deterministic Fact Access Gate → caller-response
  generation → response validation → streaming TTS → LiveKit audio»; §2 «The LLM MUST NOT: …
  calculate numeric scores».
- Product: the AI caller is built. `docs/AUDIT.md` §15–§25 record the voice transport, nine-stage
  pipeline, VAD, barge-in, ASR, interpreter, Fact Access Gate, caller LLM, prompt rules, validation and
  TTS as IMPLEMENTED (PARTIAL only for streaming inside the TTS adapters, the Chatterbox benchmark and
  the model-size choice). Real-stack walk 2026-09-22, `docs/AUDIT.md` §2 items 2–3: «Receive a
  realistic incoming call — PASS», «Talk naturally with an AI caller — PASS (E20-I)», caller voiced by
  Qwen3-TTS «Serena». No mode without the caller exists. Scoring is deterministic
  (`backend/app/domain/scoring/`); the LLM does not evaluate actions. The only in-scope voice dialogue
  the room names (ДДС → руководитель over IP telephony) does not exist: the DDS stage has no voice or
  phone (grep over the DDS code, TRC-SRC-007 [DDS-NOVOICE]).

### 4.2 ДДС communication: phone/IP telephony vs. radio log

IDs: REQ-1028 [частично], REQ-1037 [частично], REQ-1038 [частично]; round 2: REQ-5914 [частично],
REQ-5916 [частично], REQ-5918 [частично].

- Organizer: msg638 (18.09.2026 16:37, Str1fe): «Роль «Диспетчер ДДС» (Точка B)… 3- Взаимодействие с
  Точкой C: Совершает исходящие звонки руководителям служб через симулятор IP-телефонии для передачи
  информации» — "makes outgoing calls to service heads through an IP-telephony simulator". msg691
  (21.09.2026, «Ответ от заказчика»): «Мы ограничивается только телефоном» — "we limit ourselves to
  the phone only"; «старший группы звонит в ДДС докладывает об обстановке… Или диспетчер сам через
  определенное время набирает по телефону старшего… Работают как правило два варианта» — "the group
  leader phones ДДС… or the dispatcher phones the leader… both variants operate". Customer answer
  («Ответ заказчика», 23.09.2026 15:46, SRC-006 L109-113): «Ответ. Да. Соответствует.» (to the
  participant's ДДС definition), «Однако диспетчер ДДС правильность заполнения карты от заявителя не
  контролирует…»; «Диспетчер ДДС только выбирает статусы ( в карте нижние поля см карту и добавляет
  статусы своими комментариями).»; «Общение с реагирующей на вызов бригадой тоже происходит либо по
  телефону или по другим каналам связи или через стороннее программное обеспечение, минуя 112.» (the
  full answer is laid out point by point in §9.3).
- SPEC: §11 lists «incoming work item; acknowledgment; … dispatch actions; … status changes; incident
  updates; closure» — no telephony at DDS; §12: a world event may create a radio/status update.
- Product: DDS radio log (`frontend/src/features/dds/radio-log.tsx`; effect `CREATE_RADIO_MESSAGE`,
  `backend/app/domain/world/effects.py:74-78`); no call, phone or voice code in
  `backend/app/application/dds`, `backend/app/domain/dds`, `frontend/src/features/dds` (grep for
  voice/phone/телефон/livekit, re-run for this report: no functional hit). Unit progress advances
  from ETA data (`backend/app/domain/world/resource_movement.py`), not from a report or a call. The DDS
  trainee also selects and dispatches resources (not in «только выбирает статусы»), and EN_ROUTE /
  ARRIVED / WORKING / RESOLVED are set by the simulation, not selected (`transitions.py:230-336`).

### 4.3 Which document is authoritative

ID: REQ-1021 [частично].

- Organizer: msg625 (18.09.2026 11:53): «По поводу противоречий в ТЗ… Ориентируемся на ТЗ, как
  первоисточник» — "on contradictions in the ТЗ… we treat the ТЗ as the primary source".
- SPEC: first lines: «The owner's specification, verbatim… the contract every epic is checked
  against» and «Follow this specification literally». SPEC does not mention the ТЗ.
- Product/docs: `docs/AUDIT.md` traces SPEC §1–§47 only; no code, doc or test traces to the ТЗ. The
  ТЗ is archived and now normalized (`requirements/normalized/SRC-001-formal-docs.md`).

### 4.4 Interface: copy of the real system vs. "professional operational software"

IDs: REQ-1044 [не соблюдено], REQ-4022 [не соблюдено], REQ-2081 [частично], REQ-2104 [частично];
round 2: REQ-6012 [не соблюдено] (mentor, 26:36: «Надо будет просто попробовать повторить то, что вы
будете видеть на скриншоте»; same fact as REQ-4024).

- Organizer: Q&A, **room**, L354–362: «наше требование однозначно, интерфейс должен быть точный, копировать
  интерфейс рабочей программы… по цветовым решениям… максимально близко приближены к реальному…
  привязаться уже к имеющимся шаблону и меньше вот самодеятельности» — "our requirement is
  unambiguous: the interface must be exact, copy the working program's interface… colours as close as
  possible… stick to the existing template, less improvisation". msg679 (21.09.2026): «надо стремиться
  повторить и цвета и конфигурацию, чтобы решение было знакомо в первую очередь самим
  преподавателям». ТЗ ¶88: «Реалистичную имитацию рабочих процессов и интерфейса системы-112»; ¶115:
  «Имитировать функционал и интерфейс системы-112 в изолированном контуре…».
- SPEC: §32 «The role interface must look like professional operational software, not a chatbot.»
  No reference UI is named.
- Product: shadcn neutral palette, all tokens `oklch(L 0 0)` except `--destructive`
  (`frontend/src/index.css:51-85`); the reference card (`СКРИНШОТ КАРТОЧКИ 112ГСИ.docx` image1) has an
  orange «Службы: +» bar and an orange «сохранить» bar. Card fields and labels differ (REQ-1045,
  REQ-3001–REQ-3027); no register/incident-list screen (REQ-1045, REQ-3039). Work processes (ring →
  answer → card → services → handoff → DDS) are imitated (`backend/app/domain/session/transitions.py`).

### 4.5 Assessment by AI / machine learning vs. deterministic scoring

IDs: REQ-2041 [не обработано], REQ-2063 [не соблюдено], REQ-2090 [частично], REQ-2091
[не соблюдено], REQ-2102 [частично], REQ-2121 [не соблюдено], REQ-2223 [соблюдено], REQ-4038
[частично], REQ-4008 [частично]; round 2: REQ-6024 [частично] (mentor, 38:08: teacher priority; the
same statement as REQ-4038, now attributed to the mentor).

- Organizer (ТЗ): ¶67 «Анализ эффективности обучения на основе машинного обучения»; ¶99
  «Контролировать качество обучения через автоматизированную систему оценки (на базе ИИ)»; ¶113
  «Внедрить систему оценки действий операторов на основе нейросетевого анализа»; ¶137 «Оценку
  эффективности обучения на основе машинного обучения (ИИ)»; ¶268 «Анализировать свои ошибки (на
  основе отчетов ИИ)»; ¶39 relevance factor «объективной оценки… с использованием технологий
  машинного обучения». Q&A, **mentor**, 38:08 (L554–560, REQ-4038): «если он отметил это неправильным ответом, ИИшка все
  равно там настаивает на правильности, такого не быть не должно»; L192–199 (REQ-4008): «здесь у нас
  требований таких серьезных нет… приоритет преподавателю».
- SPEC: §2 «The LLM MUST NOT: … calculate numeric scores»; §28 «Numeric scoring is deterministic.
  The LLM must never assign points.»; §29 «LLM-generated explanation may be displayed only after
  deterministic scores exist»; §43 «Target for the deterministic/context boundary: 0.»
- Product: ten deterministic evaluators (`backend/app/domain/scoring/evaluators/`; INV9–INV11
  tests); the LLM writes an optional per-session explanation over the finished `ScoreReport`
  (`backend/app/application/reports/explanation/prompt.py`); adversarial leak suite
  `backend/tests/adversarial/test_forbidden_fact_leak_suite.py`. No ML model evaluates actions; no
  analysis across sessions. Because the AI produces no verdict, no teacher-vs-AI conflict can arise;
  there is no teacher-override function either.

### 4.6 AI insights on a group's typical errors

ID: REQ-2195 [частично].

- Organizer (ТЗ ¶233): «Получать аналитические рекомендации от системы (инсайты ИИ по типичным ошибкам
  группы)».
- SPEC: §29 «LLM-generated explanation may be displayed only after deterministic scores exist.»
- Product: per-session LLM explanation only (`frontend/src/features/report/explanation-panel.tsx`); no
  group concept and no cross-session analysis.

### 4.7 Hardware: no GPU in the organizer's minimum vs. GPU-only profiles

IDs: REQ-2054, REQ-2112, REQ-2152, REQ-4003 [не соблюдено], REQ-2113 [частично]; round 2: REQ-6004
[не обработано] (the question read aloud).

- Organizer: ТЗ ¶178–180 «Минимальные требования к серверу (для работы ИИ-модуля): Процессор: Intel Core
  i7 / Xeon (или аналог) от 6 ядер; Оперативная память: от 32 ГБ; Накопитель: NVMe SSD от 512 Гб» (no
  GPU listed); ¶54 «Соответствие системным требованиям к аппаратному обеспечению»; ¶126 «Совместимость
  с аппаратным обеспечением учебного центра». The question read by the mentor at 08:47 (sheet C2,
  REQ-6004): «…все ИИ-функции (STT, LLM, TTS) должны работать на CPU?» (round 1's «на ГПУ» is a
  mis-hearing; the on-screen text says CPU). Q&A, **room**, 09:20–10:09 (L128–135): «никаких
  требований к видеокарте, скажем, сильных нет… в основном это будут все функции работы на центральном
  процессе… проверка решений на стандартных бытовых компьютерах». Later in the same session the **room**
  answers a participant's live question (61:59–62:27, REQ-6042, соблюдено): «Конечно, хотите,
  используйте видеокарту. Не вопрос… закупим новое оборудование… возможности закупки есть» (§9.4). Chat
  23.09.2026 14:41 (REQ-5911): «Уточню у заказчика, смогут ли они оперативно раздобыть данные машины
  для докалки» — no later answer in SRC-006.
- SPEC: §26 profiles `DEV_3060TI`, `FINAL_3080TI_12GB`, `FINAL_3080TI_16GB`; §38 preflight «must
  verify: CUDA/GPU available; expected GPU detected».
- Product: every profile in `backend/app/config/profiles/` targets an NVIDIA GPU; the LLM is fully
  offloaded to the GPU in every profile (`n_gpu_layers: -1`, e.g. `DEV_3060TI.yaml:51`), and
  `DEV_3060TI_SHARED` moves only ASR/TTS to CPU; preflight check #1 fails without CUDA
  (`backend/app/cli/preflight.py:142-152`). No CPU-only profile exists. FINAL profiles are unmeasured
  (`docs/AUDIT.md` §3 item 2).

### 4.8 Telephony transport: IP telephony / SIP server vs. LiveKit WebRTC

IDs: REQ-2044, REQ-2100, REQ-2118 [соблюдено], REQ-2249 [не соблюдено], REQ-2432 [не обработано],
REQ-2139 [не обработано].

- Organizer (ТЗ): ¶42 «Система эмуляции вызовов с использованием IP-телефонии и технологий VoIP»; ¶111
  «Обеспечить имитацию входящих вызовов (через виртуальную IP-телефонию или текстовые сообщения)»; ¶134
  «Обработку вызовов через виртуальную IP-телефонию (VoIP)»; ¶302 «Поддержка IP-телефонии (VoIP) через
  локальный SIP-сервер»; ¶161 «Задержку при передаче голоса (VoIP) не более 150 мс». The ТЗ glossary
  defines VoIP as «технология передачи голоса через IP-сеть» (REQ-2033).
- SPEC: §15 «Use self-hosted LiveKit for realtime audio… CallTransport abstraction so LiveKit can later
  be complemented by SIP/real telephony… No actual PSTN integration is required for the initial demo»;
  §27 latency target is speech-end → first caller audio (p50 < 1.2 s final).
- Product: voice over IP through LiveKit WebRTC (meets the ТЗ's own VoIP definition); no SIP server in
  `infra/`; `SipCallTransport` raises `NotImplementedError` in every method
  (`workers/voice_agent/voice_agent/transport/sip_transport.py:24-51`); no text-message call channel.
  One-way VoIP latency is not measured anywhere.

### 4.9 Isolated contour and data protection

IDs: REQ-2082, REQ-2089, REQ-2055, REQ-2085, REQ-2109 [частично]; round 2: REQ-5912, REQ-5926
[не обработано: permissions].

- Organizer (ТЗ): ¶88 «без доступа к внешним сетям (локальный контур)»; ¶98 «…эмуляции вызовов в
  изолированном контуре»; ¶55 «Обеспечение безопасности обрабатываемых данных»; ¶91/¶123 «Защиту данных
  пользователей и учебных материалов».
- SPEC: §41 «Core demo must work without external AI APIs. No OpenAI/Anthropic/etc API is allowed in the
  runtime path. Keep recordings, transcripts, cards, scoring and models local… Secrets/configuration
  belong in environment/config files». SPEC does not address external networks in general.
- Product: LLM/TTS URLs must be loopback or compose-internal
  (`backend/app/inference/llm/llama_cpp_client.py:59-84`, test passed); GigaAM loads with
  `HF_HUB_OFFLINE=1`; no external URL in runtime code. Not present: an isolated compose network
  (`networks:` absent in `infra/docker-compose.yml`), a recorded run with external networks disabled,
  TLS, backup, encryption at rest. Setup downloads models and images from the internet
  (`Makefile:77-222`).
- Round 2, chat 23.09.2026 (Str1fe, own replies): 14:41 «на демонстрации можно показать работу без
  локалки (главное, чтобы решение не хардкодило только обращение во вне)»; 15:53 «в ТЗ указано, что
  Внутренний API - решение для расширения функционала системы собственными модулями (без взаимодействия
  с внешними системами)… То есть API есть, но оно для взаимодействия без выхода во вне»; 15:58 «На
  демонстрации можно показать, как будет работать система, если развернуть модель внутри (такая
  возможность должна быть), но раз это должно быть обеспечено мощностью самого заказчика, а он не совсем
  готов, то на ДЕМО можно показать во вне, но в самом решении должна быть возможность прописать, куда
  обращаться к модели, если она будет не во вне, а локально». SPEC §41 forbids external AI APIs in the
  runtime path. Product: the model endpoint is configuration (`SIM_LLM_BASE_URL`,
  `llm_allowed_internal_hosts`); any host that is not loopback, `localhost` or an allow-listed internal
  name is refused (`backend/app/inference/loopback.py:29-70`; 28 tests passed, including
  `test_everything_else_is_rejected` with `https://api.openai.com/v1`). The permission to demonstrate
  with an external model (REQ-5912, 5926) therefore cannot be used without a code change; the
  obligations REQ-5913, 5925, 5927 are `соблюдено` (§6).

### 4.10 Scenario generation by a neural network and automatic reference answers

IDs: REQ-2084, REQ-2186 [частично], REQ-2256, REQ-2257 [не соблюдено]; round 2: REQ-6007 [частично],
REQ-6041 [не соблюдено].

- Organizer (ТЗ): ¶90 «Снижение нагрузки на преподавательский состав за счет автоматизации генерации
  сценариев и первичной оценки действий обучающихся»; ¶222 «Создавать, редактировать и валидировать
  (утверждать) учебные сценарии, в том числе сгенерированные нейросетью»; ¶313 «Выбор категории
  событий, настройка нейросети на генерацию конкретных типов происшествий (ДТП, пожары, медицина и пр.)
  в зависимости от темы занятия»; ¶314 «Формирование «эталона» - автоматическое формирование системой
  эталонных ответов (сценариев), с которыми система будет сравнивать действия обучающегося». Q&A,
  **room**, 12:29–13:12 (REQ-6007; the start of the answer is lost in the 11:40–12:29 audio gap):
  «…должен быть симбиоз. На низших уровнях преподаватель, на более высоких — искусственный интеллект,
  но под контролем … преподавателей … Помимо шаблонов … предусмотреть самостоятельную генерацию»;
  **room**, 57:59 (REQ-6041): «искусственный интеллект должен предложить преподавателю … что …
  сгенерировал … стоить десять баллов … или пять … или шесть».
- SPEC: §2 «The LLM MUST NOT: create incident truth; decide what services are objectively required»;
  §4 «Scenario source files must be YAML or JSON and version-controlled»; §45 «Do not start by asking an
  LLM to generate an entire scenario at runtime.»
- Product: one hand-written scenario (`scenarios/examples/apartment-fire/v1.yaml`, fire); expected
  response and scoring rules are authored in that file (l.128-360); import/validate via REST or CLI
  only (`backend/app/api/routers/scenarios.py:115-160`); no generator, no approval step, no category.

### 4.11 Automatic service routing from the card

ID: REQ-4015 [частично].

- Organizer: Q&A L263–280: «эта карточка автоматически направляется в те службы, которые программа
  определяет… на основе опросных карт… у него с правой стороны есть так называемые теги-подсказки»
  — "the card is automatically sent to the services the program determines… from the questionnaire
  cards… tag hints on the right".
- SPEC: §9 «ASR MUST NOT auto-fill fields in assessment/training mode»; §2 the LLM must not «decide
  what services are objectively required».
- Product: services are selected by hand from six types (`frontend/src/features/operator/services-panel.tsx:20`);
  no tag-hint UI; no classifier (REQ-3009, REQ-3044).

### 4.12 One card per session vs. a stream of cards

IDs: REQ-2287 [не соблюдено]; round 2: REQ-6021 [частично]; related (not covered by SPEC): REQ-5909,
REQ-5910 [не соблюдено].

- Organizer (ТЗ ¶341): «После завершения действий система выдает новую карточку события, если занятие
  не завершено». Q&A, 35:48–36:24 (REQ-6021, round-1 transcript had omitted ≈29 s): «Да, появится новая
  карточка, которая генерируется… Норматив по-прежнему работает. Многозадач[ность], здесь будет
  интересно решение… Когда появляется скорость, то появляются и ошибки»; room: «мы их должны проверять
  именно с точки зрения того, чтобы особенно критических не было ошибок в адресах». Chat 23.09.2026
  14:31 (Str1fe, to a participant asking whether cards reach the ДДС one by one or as a stream):
  «Одновременно, как в текущей работе. В этом ещё доп мотивация - когда работаешь с карточкой, тайминг
  идёт и для этой работы и для тех карточек, что в очереди».
- SPEC: §1 «A simulation is one persistent incident»; §13 «A full-cycle session uses one:
  SimulationSession, Incident, ScenarioVersion».
- Product: `uq_incidents_session` (`backend/app/db/models/session.py:161`); after closure the session
  is COMPLETED; no next card, no queue, no concurrent cards, no timer in the DDS console. Address
  errors are scored (`card_house_correct`, `critical: true`).

### 4.13 Horizontal scaling

ID: REQ-2145 [частично after §1.6].

- Organizer (ТЗ ¶169, repeated ¶305): «Возможность горизонтального масштабирования (добавление узлов в
  локальный кластер) при росте нагрузки».
- SPEC: §36 «Use Docker Compose for the current product/demo… Do not introduce Kubernetes.»
- Product: single-host compose; `infra/livekit/livekit.yaml:8-9` «A multi-node deployment is not in
  scope»; a Redis runner lock lets another backend instance adopt a session (test passed).

### 4.14 Data formats

IDs: REQ-2301 [не соблюдено], REQ-2320 [частично].

- Organizer (ТЗ): ¶363 «JSON для хранения профилей пользователей»; ¶389 «Совместимость с основными
  СУБД».
- SPEC: §30 «Use PostgreSQL… Do not replace the relational model with a generic JSON document store.»
- Product: `users` is relational (`backend/app/db/models/reference.py:32-38`); PostgreSQL-specific
  schema (plpgsql triggers, JSONB, pgcrypto).

### 4.15 Identity: Moscow, ДДС, the real system

IDs: REQ-2002, REQ-2057 [частично], REQ-3011 [не соблюдено].

- Organizer: ТЗ title «Учебное программное обеспечение для подготовки оператора ДДС города Москвы с
  использованием искусственного интеллекта»; ¶60 «…операторов ДДС, взаимодействующих с системой-112
  города Москвы»; operator manual title «МОДУЛЬ «ПРИЕМ И ОБРАБОТКА ВЫЗОВОВ 112»», part of work for
  «Департамента по делам гражданской обороны, чрезвычайным ситуациям и пожарной безопасности города
  Москвы».
- SPEC: §1 «The product is a local AI-powered training and assessment simulator for
  emergency-response personnel»; roles «Operator 112», «Profile DDS dispatcher»; no city, no customer.
- Product: `frontend/src/shared/i18n/ru.ts:5` «Тренажёр 112»; the DDS role is labelled «ЕДДС» (ru.ts:8,
  38) and EDDS «РЕДДС» (ru.ts:39); the only scenario is set in Smolensk (`v1.yaml:12`); no mention of
  Moscow, the Department, ГБУ «Система 112» or the real module in code, UI or docs.

### 4.16 Reaction time in the trainee's results

ID: REQ-2220 [частично].

- Organizer (ТЗ ¶265): «Просматривать свои результаты обучения (оценки, время реакции)».
- SPEC: §29 «timing metrics», defined by §27 as inference latencies.
- Product: `backend/app/application/reports/timing_metrics.py:54-64` holds ASR/LLM/TTS latencies; the
  trainee's times appear only as timeline offsets and in DEADLINE-rule evidence.

### 4.17 "Intuitive for all users"

ID: REQ-2155 [не обработано].

- Organizer (ТЗ ¶183): «Интуитивную понятность для всех категорий пользователей».
- SPEC: §32 «must look like professional operational software, not a chatbot».
- Product: no usability evaluation exists in the repository.

### 4.18 The map in the ДДС card

ID: REQ-5276 [не соблюдено].

- Organizer material (ДДС memo, p.18): the «карта» icon opens a map with the incident point.
- SPEC: §11 «Do not depend on an external online maps API for core operation.»
- Product: no map component anywhere in `frontend/src` (REQ-3020 finding).

---

## 5. Findings by area

Every REQ is placed in one area below. Areas follow the ТЗ's own headings where the ТЗ has a
section for the subject; subjects the ТЗ does not structure (the real card, the ДДС screen, the
classifier, the voice scope, the datasheet, hackathon logistics) get their own area. Rows that
restate the same requirement from several sources are merged and list all IDs. Round-2 rows (REQ-5xxx,
REQ-6xxx, and re-judged round-1 items) are added to the area they belong to. Status letters in
multi-ID rows: S = соблюдено, P = частично, N = не соблюдено, U = не обработано. "F-nn" points to
the detailed finding in §7, "S-n" to the group in §6, "A-/B-" to the reason table in §3.4.

### 5.1 Product, customer, purpose, target users
ТЗ sections: title page, «Термины и определения», «Описание работы компании, актуальность задачи и
описание сервиса». Other sources: chat msg6/15/624, brief «Актуальность», video, Q&A L10–13, L249–255.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-1007, REQ-4075, REQ-4081 | Training simulator for dispatchers handling 112 calls; AI generates incident messages | S | `README.md:1-10`; SPEC §1; AUDIT §1, §12 | — (S-1) |
| REQ-1026, REQ-1027, REQ-4014 | One interface, one account, two mini-roles (112 operator / ДДС); trainee placed in either | S | `frontend/src/app/router.tsx:47-58`; `backend/app/domain/enums.py:59-64` | Shipped scenario has `role_chain: [OPERATOR_112, DDS]`; a single-role run needs a one-role scenario (S-1) |
| REQ-2013 | «Система-112 — единый номер экстренных служб» | S | `ru.ts:5,7` | — (S-1) |
| REQ-2068 | Target users include teachers/instructors | S | INSTRUCTOR role, `/instructor` | — (S-1) |
| REQ-2072 | Use for «Аттестационных мероприятий» | S | ASSESSMENT mode, `policy.py:62-70` | — (S-5) |
| REQ-1001 (U), REQ-2001 (U), REQ-2004, REQ-2012, REQ-3011, REQ-4001, REQ-4064, REQ-4093 | Customer department, ГБУ «Система 112», Система 104, real module name | N (1001, 2001: U) | grep over code/UI/docs: 0 hits | Named nowhere in the product (F-01) |
| REQ-2002, REQ-2005, REQ-2037, REQ-2057 | Trainee = «оператор ДДС города Москвы»; ДДС receives calls from system-112 via АРМ | P | `ru.ts:8,38,39`; `v1.yaml:12` | DDS labelled «ЕДДС»; Smolensk scenario; «АРМ» not used (F-02) |
| REQ-2064, REQ-2065, REQ-2066, REQ-2067, REQ-2069 | Target users: Гормост, housing services, other ДДС, heads of dispatch services | P/N | `RoleType`, `ServiceType` | Only generic DDS role; no Гормост/housing/head roles (F-03) |
| REQ-2043, REQ-2070, REQ-2071, REQ-2073, REQ-2074, REQ-2075, REQ-2088 | Components lead-in; uses: basic training, retraining, knowledge control, non-standard situations, monitoring effectiveness; automate ДДС training | P | F3–F6 of matrix a | One scenario; no knowledge test, periodicity, cross-session monitoring (F-04) |
| REQ-2058, REQ-2059, REQ-2093, REQ-2094, REQ-4066 | Train work with system-112 software; practise various incidents | P | operator console; one fire scenario | Own interface, differs from archived screenshots; one incident type (F-05) |
| REQ-4080 | Real duties: dispatch, quality control, inform leadership, relay | P | handoff/dispatch code | No "inform leadership", no quality control of aid (F-13) |
| REQ-2003, REQ-2006–REQ-2011, REQ-2014–REQ-2036 | ТЗ Table 1 term definitions | U | — | A: definitions |
| REQ-2038–REQ-2042, REQ-2048–REQ-2052, REQ-2076–REQ-2080, REQ-4065 | Relevance factors and expected outcomes | U | — | A: motivation/outcomes |
| REQ-4068, REQ-4077, REQ-4078, REQ-4079, REQ-4084, REQ-4087, REQ-4092 | No analogues; background narrative; narrator; B-roll | U | — | A: background |
| REQ-6001 | Host 03:14 (recording): «…от департамента гражданской обороны, чрезвычайным ситуациям и пожарной безопасности» | N | grep: 0 hits | Named nowhere (F-01) |
| REQ-5249, REQ-5255, REQ-5258 | Memo: ГБУ «Система 112» is the operator of Moscow's system-112; >210 participants; «КИС УСС», «ПОВ-112» | N | [NO-REAL] (TRC-SRC-005); 6 service types | F-01, F-14 |
| REQ-5001, REQ-5002, REQ-5003 | ТЗ PDF cover: «Техническое задание», «2026», programme logos; «ГБУ «Система 112»» not on the cover | U | — | A5 |

### 5.2 Call emulation and voice
ТЗ sections: «Описание работы компании…» (components), «Постановка задачи», «Общие требования к
сервису», «Нефункциональные требования» (SIP), «Требования к производительности» (АРМ periphery).
Other sources: Q&A L118–159, L294–324, L572–645; chat msg570/576/624; brief «Описание задачи».

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2044, REQ-2061, REQ-2099, REQ-2100, REQ-2117, REQ-2118, REQ-2216, REQ-2268, REQ-4069 | Call emulation over IP telephony/VoIP (or text); system imitates a call from an event participant; AI-driven call to the operator's headset | S | LiveKit WebRTC; AUDIT §2 items 2–3 PASS | No text channel (offered as «или»); SIP stub (S-2) |
| REQ-1025 | «Только имитация звонков в базе… для mvp достаточно имитации» | S | CALL_* events, transcripts in PostgreSQL | — (S-2) |
| REQ-4004, REQ-4005, REQ-2105, REQ-2106, REQ-2107, REQ-2108 | No hardware phone needed; simulation only; no real calls; imitation only | S | SIP/PSTN stub; scenario-defined world | — (S-2) |
| REQ-1024, REQ-4017, REQ-4018, REQ-4040, REQ-4044, REQ-4045 | Caller («точка А») excluded at this stage (room, recording-verified); card-generated message to ДДС; AI evaluates actions | N (1024, 4018: P) | AUDIT §15–§25; DOD items 2–3 | Built product centres on the excluded AI caller; §9.1 (F-06) |
| REQ-4041, REQ-4042 | Male/female voices by category; ДДС operator voice-informs a leader | P / N | grep voice in DDS code: 0 | No ДДС-side voice; one `voice_id` per scenario (F-07) |
| REQ-2249, REQ-2151, REQ-2150 | Local SIP server; hardware IP phone with headset; headset with software IP phone | N/N/P | `sip_transport.py:24-51` | SIP stub; browser softphone only (F-08) |
| REQ-6005, REQ-6010, REQ-6026 | Simulation only (mentor 11:00, room 11:07); a voiced incoming call → card → system check (mentor 24:16); voiced incoming calls «будет хорошо оценено тоже» (mentor 40:42) | S | SIP stub; `docs/DOD_WALK.md` items 2, 3, 6, 14 PASS | — (S-2) |
| REQ-6028, REQ-6029 | Room 42:06–43:19: the only voice dialogue is «ДДС — руководитель»; B↔C over the IP-telephony simulator; point A excluded | N | no voice/phone in DDS code | F-07, F-06 |
| REQ-4043, REQ-6027, REQ-6030, REQ-6046 | Room 40:58: caller voice «снимаем как бы этот вопрос… в следующем конкурсе»; mentor 43:20 «если коллеги сделают, будет здорово» (referent unsettled); mentor 65:00 «нет, не надо… на втором-третьем этапе» | U | — | A14, A9; §9.1 |

### 5.3 The 112 operator card
ТЗ sections: «Возможные пользовательские пути» (scenario «…на АРМ-112 (карточки)» step 5), «Общие
требования к сервису» (formats of ГБУ «Система 112»), «Роль: Обучающийся» (card items). Other
sources: `КАРТОЧКА 112.docx`, `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx`, the operator manual, chat
msg628/635/642/680, Q&A L530–536.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-1031, REQ-1032, REQ-2214, REQ-2215, REQ-2218 | Trainee fills the card manually; voice-vs-card correspondence and chosen services are checked; intermediate results saved | S | `operator_card.py`; CARD_CONTRADICTION; INV4 | Contradiction rule covers one field in the demo (S-3) |
| REQ-1045, REQ-2127, REQ-2269, REQ-4035, REQ-2217 | Card and «реестр обращений» «100% должны быть похожи»; data formats/visual standards of ГБУ «Система 112» = the displayed fields | N/N/P/P/P | `operator_card.py:86-391` | No register screen; fields/labels differ; no card number (F-10) |
| REQ-1030 | 112 operator: address, caller data, «Описание со слов заявителя», «Добавить тип происшествия», services | P | `operator_card.py`, `services-panel.tsx:20` | Label «Описание происшествия»; 8-value type select (F-10) |
| REQ-3001, REQ-3002, REQ-3003, REQ-3004, REQ-3005, REQ-3006, REQ-3007, REQ-3008, REQ-3014, REQ-3021 | Real card structure: 51 types, «Где» branches, per-type tag fields, 4 mandatory blocks, required fields | P/N | `IncidentType` 8 values; static `CARD_FIELDS` | No branches, no per-type tags; required is advisory (F-10) |
| REQ-3010, REQ-3012, REQ-3013, REQ-3015, REQ-3016, REQ-3017, REQ-3018, REQ-3019, REQ-3020, REQ-3022, REQ-3023, REQ-3024, REQ-3027, REQ-3028, REQ-3029, REQ-3031, REQ-3033, REQ-3034, REQ-3035, REQ-3036, REQ-3037 | Real card functions: red timer, АРМ login, telephony status, 3 phone fields, quick-close buttons, type search, address autocomplete, map, statuses, linking, transfer, SMS, audit, hotkeys | P/N | grep over code (see matrix) | Most functions absent (F-11) |
| REQ-5273, REQ-5274 | Memo: an operator card vs a ВИС card (no workstation number, questionnaire, formal features); selected features blue, notification list orange | N | no ВИС, no feature selection, greyscale | F-10, F-12 |
| REQ-5204 | Tickets: «Ситуация» = narrative + caller name + phone + relation (очевидец/сосед/прохожий/родственник) | S | scenario fields `scene_summary_ru`, `caller.*`, `CallerRelationship` | — (S-16) |

### 5.4 ДДС work
Sources without a ТЗ section: chat msg638/635/691/701, Q&A L280–293 and L343–347,
`СКРИНШОТ ДДСГСИ.docx`, operator manual (48-hour rule, «Отработана»).

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-4021 | ДДС operator distributes the activity to a specific service | S | `backend/app/domain/dds/resources.py`; AUDIT §11 | — (S-4) |
| REQ-1028, REQ-1029, REQ-1039, REQ-4016 | ДДС receives a card (system-generated or from 112), validates it, calls service heads by IP phone; sees other recipients; accept/decline/redirect | P | `transitions.py:231-311`; `prefab_handoff.py`; `work-item-panel.tsx` | No validation/reject/redirect, no phone, one work item for all services (F-13) |
| REQ-1037, REQ-1038 | Phone only; leader reports or dispatcher calls the leader | P | `radio-log.tsx`; `resource_movement.py` | Radio log, no phone, no pull (F-07, F-13) |
| REQ-3030, REQ-3032, REQ-3038, REQ-3039, REQ-3040, REQ-3041 | Real ДДС screen: 48 h «Не завершено», «Отработана», own login, incident list, read-only sentence view, status lifecycle | P/N | `DDSStageState`, `status-update-form.tsx` | No list, no 48 h rule, different vocabulary (F-13) |
| REQ-5915, REQ-5267, REQ-5358 | «Ответ заказчика» 23.09 15:46: ДДС does not check the card's fill-in; memo: screens by user category; ДДС does not add services | S | no validation action; role gates; no service add on DDS | — (S-15); conflicts with msg638, §9.2 |
| REQ-5914, REQ-5916, REQ-5918 | 23.09 15:46: participant's ДДС definition «Да. Соответствует»; ДДС «только выбирает статусы… своими комментариями»; brigade contact by phone / other channels / third-party software | P | [DDS-SM], [SUK], radio log | F-13 |
| REQ-5917, REQ-5919, REQ-5920 | 23.09 15:46: ДДС may phone the claimant directly, bypassing 112; does not name the card number | N | no DDS call function | F-13 |
| REQ-5909, REQ-5910, REQ-5254, REQ-5283, REQ-5298, REQ-6020, REQ-6021 | Cards reach the ДДС concurrently, timers run for queued cards (23.09 14:31); memo: accept within 30 s else «Не оповещено»; room 34:47: 30 s to react, 3 min to fill; a new card may appear | N (5909, 5910) / P | one incident per session; no 30 s rule | F-38 |
| REQ-2290, REQ-5247, REQ-5248, REQ-5250, REQ-5253, REQ-5256, REQ-5257, REQ-5259, REQ-5270, REQ-5277, REQ-5278, REQ-5281, REQ-5282, REQ-5285–REQ-5288, REQ-5292, REQ-5293, REQ-5295, REQ-5299–REQ-5302, REQ-5305, REQ-5306, REQ-5311, REQ-5324, REQ-5361 | Memo «Работа на АРМ-112» (ТЗ primary data): one-window model, response statuses Добавлена…Работы завершены, pencil dropdown, sequential statuses, comments, control checks, card statuses Зарегистрирована/Отработана/Завершена | P | [DDS-SM], [SUK], [DDS-LBL] | Equivalents under other names; not per service; no «Не принята» (F-39) |
| REQ-5260–REQ-5262, REQ-5264–REQ-5266, REQ-5275, REQ-5276, REQ-5279, REQ-5280, REQ-5284, REQ-5289, REQ-5290, REQ-5294, REQ-5296, REQ-5297, REQ-5303, REQ-5307–REQ-5310, REQ-5312, REQ-5313, REQ-5327, REQ-5328, REQ-5362 | Memo: ЕКП routing, ВИС/ЭРА-ГЛОНАСС cards, specialist-112 may add but not remove services, map (§4.18), «Не принята», «Отказ от выполнения работ», 103 variant, per-service blocks/history, card statuses Проверена/Не оповещено/Отказ/Не завершено, red flags, refusal-legitimacy check | N | [DDS-SM], [SVC-MANUAL], [NO-CLS] | F-39 |
| REQ-5268, REQ-5269, REQ-5314–REQ-5317, REQ-5319–REQ-5323, REQ-5329–REQ-5341 | Memo: support contact and «Сообщить о проблеме»; violation examples; control-department / СТП / МосЭДО / «112» call procedures | N | no such function or scenario | F-40 |
| REQ-5271, REQ-5272, REQ-5343, REQ-5345, REQ-5347–REQ-5357 | Memo: list of received cards and «Поиск происшествий» by address, округ, район, service, description, channel, source, operator, status | N | one work item, no search | F-41 |
| REQ-5244–REQ-5246, REQ-5304, REQ-5318, REQ-5326, REQ-5342, REQ-5251, REQ-5252, REQ-5263, REQ-5291, REQ-5325, REQ-5344, REQ-5346 | Memo framing, contacts, legal acts, limitations of real services | U | — | A5, A11 |
| REQ-5359, REQ-5360, REQ-5363 | Memo silent on ДДС calling another service, on ДДС access to the call audio; comparison memo vs chat | U | — | A9 |

### 5.5 Incident classifier, services and routing
ТЗ section: «Источники данных» («Классификатор происшествий»). Other sources: the classifier
`.xlsx`, `СЛУЖБЫ 112.docx`, card screenshots, operator manual, chat msg648/683/684/690, Q&A L263–293.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-1042 | Classifier has «Сценарий реагирования» codes (1_2, 1_26…) | S | file present, read with openpyxl | Not used by the product (S-13) |
| REQ-1034, REQ-1035, REQ-1036, REQ-2291, REQ-3009, REQ-3025, REQ-3026, REQ-3042, REQ-3043, REQ-3044, REQ-3045, REQ-3046, REQ-3047, REQ-3048, REQ-4015 | Services pulled in automatically per ЕКП/опросная карта, by district and subordination; ~25 city services + ~140 district ДДС; classifier structure | P/N | `ServiceType` 6 values; `services-panel.tsx:20`; grep classifier: 0 | Manual selection only; no classifier, district or subordination model (F-14) |
| REQ-3049 | Meaning of «искл_пожар_задымление» in the file name | U | — | A: open question |
| REQ-5701, REQ-5704, REQ-5705, REQ-5707–REQ-5709, REQ-5712–REQ-5717 | Classifier v_046_24: structure, new organisations (ЦУКБ Минобороны, Мосэкомониторинг, Ситиэнерго…), 24 categories / 1283 rows, 2 new codes, МВД routing changes, fire rows unchanged | N | [NO-CLS] | Neither version used (F-14) |
| REQ-5702, REQ-5703, REQ-5706, REQ-5710, REQ-5711, REQ-5718, REQ-5719, REQ-5720, REQ-5721 | Differences between the two classifier versions; file names; «+ Департамент» and «искл_пожар_задымление» unexplained | U | — | A5, A9 |

### 5.6 Training management, the teacher role and lesson scenarios
ТЗ sections: «Описание…» and «Постановка задачи» (difficulty, teacher tools, remote control),
«Опциональные требования» (import), «Роль: Преподаватель», «Возможные пользовательские пути
(сценарии)» (scenarios 1–3). Other sources: Q&A L164–174, L200–210, L294–332, L501–521, L544–553,
L653–697, L783–842; brief «Описание задачи».

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2047, REQ-2188, REQ-2196 | Instructor interface; real-time control/monitoring | S | `/instructor`, live overview (WS) | — (S-6) |
| REQ-2203, REQ-2204 | Teacher restricted from admin settings and deleting critical data | S | ADMIN-only endpoints; append-only tables | — (S-8) |
| REQ-2264, REQ-2267, REQ-2270, REQ-2277, REQ-2284, REQ-2288 | Scenario actors; teacher starts and ends the lesson (any moment) | S | `startSession`, `abortSession` | Abort yields no report (S-6) |
| REQ-2286 | Trainee acts on the card incl. entering text | S | DDS status update `text_ru`, close comment | — (S-7) |
| REQ-2045, REQ-2062, REQ-2098, REQ-2103, REQ-2119, REQ-2187, REQ-2191, REQ-2224, REQ-4007, REQ-4047, REQ-4049, REQ-4059, REQ-4063, REQ-4070 | Difficulty levels; distribute tasks per trainee/workstation; AI adjusts level | P/N | `difficulty` int in scenario file | Not shown/settable in UI; one scenario; no per-trainee tasks, no adaptive level (F-15) |
| REQ-2084, REQ-2186, REQ-2192, REQ-2199, REQ-2254, REQ-2256, REQ-2257, REQ-2258, REQ-2260, REQ-2261, REQ-2263, REQ-2266, REQ-2279, REQ-2280, REQ-2281, REQ-2282, REQ-2283, REQ-2285, REQ-2287, REQ-4009, REQ-4010, REQ-4037 | NN scenario generation, auto reference answers, teacher confirmation/preview/correction, categories, generated/random/next cards, grammar check, fine-tuning | P/N | hand-written YAML; REST/CLI import | Absent except manual import (F-16) |
| REQ-2101, REQ-2185, REQ-2197, REQ-2198, REQ-2200, REQ-2201, REQ-2202, REQ-2205, REQ-2206, REQ-2225, REQ-4019, REQ-4033, REQ-4058, REQ-2087, REQ-2116 | Teacher tools, feedback, time limits (default 30 s; 30 s + 3 min), success criteria, non-interference, audit of grade changes, remote control, hints for beginners | P/N | F3 of matrix a; `v1.yaml:289-300` | No comments, no 30 s default, no per-session limit, instructors not isolated (F-17) |
| REQ-2190, REQ-2213, REQ-2207, REQ-2262, REQ-2134 | Training materials, reference base, upload, batch import | P/N | scenario import only | No materials store (F-18) |
| REQ-2259 | Trainee feed limited to profile events (Мосводоканал, Москоллектор, Управы…) | P | per-role visibility test | Split by role, not by service profile (F-14) |
| REQ-2255, REQ-2265, REQ-2278 | Secure login in the local complex without internet | P | password login; HTTP | No TLS; no offline run recorded (F-09) |
| REQ-4046 | Classes are held offline at the training centre | U | — | A: background |
| REQ-6011 | Mentor 24:42: the same or another person as ДДС operator distributes the activity to services | S | DDS dispatch; MULTI_TRAINEE | — (S-4) |
| REQ-6007, REQ-6041 | Room 12:29: «симбиоз… на высоких — искусственный интеллект… предусмотреть самостоятельную генерацию»; room 57:59: AI puts forward the task's points to the teacher | P / N | no generator; static `difficulty` | F-15, F-16 |
| REQ-6008, REQ-6009, REQ-6023, REQ-6044 | Mentor: teacher confirms the correctness of answers; further training of the model from teacher marks or new materials, minutes-long training acceptable | N | no confirm action; no training code | F-16 |
| REQ-5903 | «Да, все в классе» (23.09 13:48) | P | browser app, MULTI_TRAINEE; no classroom doc; concurrency untested | F-28 |
| REQ-5904 | «форматы разные, в группах может быть разное количество участников» | U | — | A12 |

### 5.7 Assessment
ТЗ sections: «Описание…» (2046, 2060, 2063, 2083), «Постановка задачи» (2090, 2091, 2095, 2096,
2102), «Общие требования к сервису» (2120, 2121). Other sources: Q&A L192–210, L338–342, L406–524,
L554–560; brief; video.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2046, REQ-2060, REQ-2083, REQ-2096, REQ-4020, REQ-4071, REQ-4082 | Automated assessment of actions incl. manual text vs. reference | S | 10 evaluators; AUDIT §2 item 7 | — (S-3, S-5) |
| REQ-2063, REQ-2090, REQ-2091, REQ-2102, REQ-2121, REQ-4008, REQ-4028, REQ-4038, REQ-4067 | ML/NN/AI-based assessment; teacher priority over AI; configurable accuracy; output to teacher and external monitor | P/N | SPEC §2, §28; `explanation/prompt.py` | Deterministic only; no ML; no external monitor (F-19) |
| REQ-2095, REQ-2120, REQ-4030, REQ-4031, REQ-4032, REQ-4034 | Timing and regulations; grammar/legibility of typed entries; completion time; address errors | P | DEADLINE, CARD_FIELD_CORRECT | No grammar evaluator; no «регламент» text; one incident per session (F-20) |
| REQ-6019 | Room 31:53: «такой методики не существует. Мы даём на откуп… это участникам» | S | own deterministic method | — (S-5) |
| REQ-6015, REQ-6017, REQ-6018, REQ-6024, REQ-6043 | Mentor: weights configurable «в самой настройке самой системы»; grammar only for legibility (street names); teacher priority over AI; evaluate against pre-filled criteria, not «в моменте»; room: «Дубнинская»/«Дубининская» | P | rules in YAML; no grammar evaluator | F-19, F-20 |

### 5.8 Reporting and statistics
ТЗ sections: «Постановка задачи» (2092, 2097, 2115), «Общие требования» (2122), «Опциональные
требования» (2132, 2133), «Роль: Преподаватель» (2189, 2193–2195), scenarios 2–3 (2271–2276, 2289).
Other source: Q&A L783–785.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2097, REQ-2115, REQ-2272, REQ-2273 | Reports on results; report contains actions and errors | S | report page, 14 sections | — (S-5) |
| REQ-2271, REQ-2274, REQ-2275, REQ-2276, REQ-2289 | Teacher's lesson report: actions, errors, card-filling time, deviation from norm, grammar | P/N | `timing_metrics.py`; `deadline.py:74-78` | Per session only; time only as rule evidence; no grammar; none for aborted sessions (F-21) |
| REQ-2092, REQ-2122, REQ-2132, REQ-2133, REQ-2189, REQ-2193, REQ-2194, REQ-2195, REQ-4057 | Progress records, statistics, charts/heat maps, Excel/PDF export, grade history, expert assessment, AI insights, leaderboard | P/N | no aggregate endpoint; no chart library | Absent (F-22) |

### 5.9 The trainee role
ТЗ section: «Пользовательские требования › Роль: Обучающийся».

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2208, REQ-2209, REQ-2211, REQ-2212, REQ-2223 | Practical tasks in emulation; feedback; results kept; list of assigned sessions; error analysis | S | consoles; report visibility tests | — (S-5, S-7) |
| REQ-2226, REQ-2227, REQ-2228, REQ-2229, REQ-2230, REQ-2232, REQ-2234 | Trainee restrictions; confidentiality; authentication at login | S | role-gate tests | — (S-8) |
| REQ-2210, REQ-2220, REQ-2221, REQ-2222 | Own progress/error history, reaction time, statistics, system advice («рекомендации») | P | `report-index-page.tsx` | Per-session only (F-22, F-21) |
| REQ-2219, REQ-2225, REQ-2231, REQ-2233 | Standard procedures; timer; personal-data protection; reliable history storage | P | see F-20, F-17, F-24, F-25 | See findings |
| REQ-2207, REQ-2213, REQ-2224 | Assigned materials; reference base; choose modules | P/N | — | No materials (F-18, F-15) |

### 5.10 The administrator role
ТЗ sections: «Роль: Администратор системы»; «Общие требования» (integration with access management
and monitoring).

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2177 | Control health indicators | S | `/health/ready`, preflight | — (S-8) |
| REQ-2159–REQ-2176, REQ-2178–REQ-2182, REQ-2184, REQ-2128, REQ-2129 | Start/stop, monitor, configure, update, backup, create accounts, roles, block, logs, statistics, load, policies, integrity, audit, restrictions, least privilege, access-management and monitoring integration | P/N | F1, F2, F12, F13 of matrix a | Shell/file operations only; no account administration; ADMIN reads all (F-23) |
| REQ-2183 | Admin restricted from changing base security settings without rights | U | no in-app settings function | A: undecidable |

### 5.11 Security, reliability, audit
ТЗ sections: «Описание…» (2055, 2085), «Постановка задачи» (2109, 2110, 2114), «Общие требования»
(«Необходимо реализовать»), «Требования к производительности» (2140, 2143), «Нефункциональные
требования». Other source: Q&A L775–779.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2124, REQ-2242 | Role-based access control | S | `require_roles`; tests | Roles fixed in code (S-8) |
| REQ-2055, REQ-2085, REQ-2109, REQ-2123, REQ-2125, REQ-2231, REQ-2240, REQ-2241, REQ-2243, REQ-4056 | Data security; channel protection/TLS; multi-level auth; protection from unauthorised access | P/N | argon2, JWT; compose ports | No TLS; single factor; redis without password on 16379 (F-24) |
| REQ-2126, REQ-2235, REQ-2233, REQ-2236, REQ-2237, REQ-2238, REQ-2253, REQ-2140, REQ-2143 | Daily backup; fault tolerance; auto recovery; monitoring; diagnostics/notification; 30 s network outage; buffering | P/N | compose restart policies; reconnect tests | No backup; single instances; no push alerts (F-25) |
| REQ-2114, REQ-2180, REQ-2239, REQ-2244, REQ-2245 | Record all user actions; security audit; security logs ≥ 6 months | P/N | `session_events` append-only | Logins, import, release not logged; no retention (F-26) |
| REQ-2110 | «Соответствие требованиям информационной безопасности» | U | — | A: undefined |

### 5.12 Performance, scalability, hardware, platforms
ТЗ sections: «Требования к производительности», «Нефункциональные требования › Совместимость /
Масштабируемость». Other sources: Q&A L118–136, L811–818.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2248 | PostgreSQL ≥ 12 | S | `postgres:16` | — (S-11) |
| REQ-2054, REQ-2112, REQ-2113, REQ-2152, REQ-4003 | Hardware minimum without GPU; CPU-mostly on consumer PCs | N (2113: P) | profiles; preflight | Every profile needs an NVIDIA GPU (F-27) |
| REQ-2056, REQ-2086, REQ-2111, REQ-2144, REQ-2145, REQ-2250, REQ-2251, REQ-4062 | Scalability for user groups; vertical/horizontal scaling; no crash at 10 users, 20–30 in class | P | single-host compose; runner lock | Unmeasured concurrency; no cluster (F-28) |
| REQ-2246 | Windows 10/11, Ubuntu 20.04+ | P | Linux containers | No Windows run/instructions (F-29) |
| REQ-2137, REQ-2138, REQ-2139, REQ-2141, REQ-2142, REQ-2146–REQ-2149, REQ-2153, REQ-2154, REQ-2247 | Measured figures and hardware/browser runs | U | — | B: measurement not made |
| REQ-6042 | Room 61:59: «Конечно, хотите, используйте видеокарту. Не вопрос… возможности закупки есть» | S | GPU profiles | — (S-16) |
| REQ-6040 | Mentor 56:28: no crash at 10 concurrent users; class 20–30 | P | untested | F-28 |
| REQ-6004 | Question read at 08:47: «…все ИИ-функции (STT, LLM, TTS) должны работать на CPU?» | U | — | A8 |

### 5.13 Isolation and integration
ТЗ sections: «Описание…» (2053, 2082), «Постановка задачи» (2089, 2104), «Общие требования ›
Система должна интегрироваться с», «Опциональные требования» (2131, 2136). Other sources: Q&A
L538–543, L706–735, L796–798.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2131, REQ-2136, REQ-4036, REQ-4050, REQ-4051, REQ-4060 | Local operation; optional modules keep isolation; internal API | S | loopback-only clients; RoleModule | — (S-9) |
| REQ-2082, REQ-2089, REQ-2104 | No access to external networks (local contour); imitation of interface in the isolated contour | P | F8 of matrix a | No isolated network, no offline run record (F-09; interface part F-12) |
| REQ-2053 | «Интеграцию с существующей инфраструктурой системы-112» | N | — | No connector; conflicts with isolation, REQ-2434 (F-30) |
| REQ-5913, REQ-5923–REQ-5925, REQ-5927, REQ-6022, REQ-6032, REQ-6033, REQ-6038, REQ-6045 | Not hard-coded to external calls; internal API without external interaction; internal model deployment must be possible and the model endpoint configurable; all local, no integrations; local priority | S | `SIM_LLM_BASE_URL`, loopback/allow-list (28 tests passed) | — (S-9) |
| REQ-5912, REQ-5926 | The demo may run with an external model (customer's compute not ready) | U | external hosts refused by the product | A13; §4.9 |

### 5.14 Data sources and data formats
ТЗ sections: «Источники данных», «Форматы данных». Other sources: chat attachments, Q&A L155–241,
L680–685, L761–764, brief «Ресурсы», video.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-1005, REQ-1046, REQ-1047, REQ-1048, REQ-4006, REQ-4023, REQ-4039 | Organizer files provided (FAQ, ТЗ, screenshots, manual, classifier, datasheet, card, services) | S | present in `requirements/sources/…/files/` | Not referenced by product code or docs (S-13) |
| REQ-2297, REQ-2300, REQ-2304, REQ-2306, REQ-2310, REQ-2311, REQ-2315, REQ-2317, REQ-2322, REQ-2323 | JSON exchange, SQL, JSON scenarios, WAV audio, validation, integrity | S | OpenAPI; `wav_writer.py`; JSON Schema | — (S-11) |
| REQ-2298, REQ-2299, REQ-2301, REQ-2302, REQ-2303, REQ-2305, REQ-2307, REQ-2308, REQ-2309, REQ-2312, REQ-2313, REQ-2314, REQ-2316, REQ-2318, REQ-2319, REQ-2320, REQ-2321 | XML, CSV, PDF, MP3, DOCX, JSON profiles/logs, DBMS compatibility, compression | P/N | grep: no XML/PDF/MP3/DOCX/compression | Absent (F-31) |
| REQ-2293–REQ-2296, REQ-4011, REQ-4012, REQ-4013, REQ-4048, REQ-4072, REQ-4083 | Other documents, DB exports, question algorithms, template solutions, de-identified/real data | U | not in archive / not yet existing | A10, A2 (4013) |
| REQ-5201, REQ-5243, REQ-6006, REQ-6025 | «Датасет»/ТЗ/template files provided; VoIP device documentation provided; manual with screenshots | S | files in `requirements/sources/` | — (S-13) |
| REQ-1049, REQ-2292, REQ-5206, REQ-5209–REQ-5242, REQ-5202, REQ-5203, REQ-5205, REQ-4054, REQ-6036 | Tickets «Билеты и задачи»: 32 «БИЛЕТ» × 3 calls = 96; base for generating new scenarios or usable as reference | N (1049, 2292, 5206, 5209–5242) / P (5202, 5203, 5205, 4054, 6036) | one scenario, none from the tickets | F-42 |
| REQ-5207, REQ-5208, REQ-6031 | Duplicate rows inside the tickets; «Да, пожалуйста, они уже обезличены…» | U | — | A5, A13 |

### 5.15 UI/UX, visual fidelity, language
ТЗ sections: «Пользовательские требования › Интерфейс системы должен обеспечивать», «Требования к
UX/UI», «Опциональные требования» (adaptive UI). Other sources: chat msg679/680, Q&A L354–396.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2156, REQ-2158 | Single style; Russian localisation | S | shared UI kit; `ru.ts` + guard tests | — (S-10) |
| REQ-1044, REQ-4022, REQ-2081 | Copy colours and layout of the real program | N/N/P | `index.css:51-85` | Greyscale; not derived from references (F-12) |
| REQ-2135, REQ-2157, REQ-2342 | Adaptive / mobile version | P | breakpoints; no device run | No mobile test (F-32) |
| REQ-2155, REQ-2339, REQ-2340, REQ-2341, REQ-2343, REQ-4026, REQ-4086, REQ-4090 | Intuitive, convenient; tablets; «RU / EN» labels | U | — | A12, A4; B (2343, 4086) |
| REQ-4024, REQ-6012, REQ-4025, REQ-6013 | Mentor 26:36: «повторить то, что вы будете видеть на скриншоте»; mentor 26:16: card, tags, colour scheme «не сильно цветастая», fast entry and next call | N (4024, 6012) / P (4025, 6013) | [PALETTE], [CARD] | F-12 |

### 5.16 The РТУ Т16Р IP-phone datasheet
Source: `РТУ Т16Р_Datasheet_ 2024_ГСИ.pdf` (vendor); why it was provided is not stated (REQ-2431).

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2415–REQ-2430 | Device facts: SIP lines, codecs, call functions, keys, screens, network | P (2415, 2422, 2425, 2426) / N (rest) | `phone-widget.tsx` | Browser widget: answer, hang-up, mute, timer (F-37) |

### 5.17 Solution requirements, deliverables, submission, deadlines
ТЗ sections: «Требования к решению», «Требования к презентации», «Требования к сдаче решений на
платформе», «Опциональные требования» (2130). Other sources: chat msg64/201/577/625/637/673/700,
Q&A L44–47, L740–757, brief «Описание итогового продукта».

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2326, REQ-4073 | A separate service / software product | S | compose stack; OpenAPI | — (S-1) |
| REQ-2328, REQ-2330, REQ-2331, REQ-2332, REQ-2333 | Comments; docs on methods, limits, build/install, architecture | S | docs/hld, AUDIT §3, README | — (S-12) |
| REQ-1020 | «тз не менялось, оно одно» | S | one ТЗ archived | — (S-14) |
| REQ-1013, REQ-2338, REQ-2373, REQ-2374, REQ-4052, REQ-1015, REQ-2372, REQ-2334, REQ-4053 | Presentation (slides 7–11 of template), prototype link/screencast, ≤5 min video, public repo + README, open source, ТЗ packaging | N/P | `git ls-files`; `gh repo view` | No presentation, video or prototype link; repo PRIVATE (F-33) |
| REQ-2252, REQ-2324, REQ-2325, REQ-2329, REQ-2375 | Documented install/config/recovery; methods; library list; docs .docx/.pdf | P | README, RUNBOOK, HLD | Markdown/English only; no recovery; no single library list (F-34) |
| REQ-1010, REQ-1021, REQ-1022, REQ-2130 | ТЗ is the detailed/primary source; read ТЗ + answers together; all mandatory functions in full | P / N (2130) | AUDIT traces SPEC only | Build contract not traced to ТЗ (F-35) |
| REQ-1004, REQ-1014, REQ-1016, REQ-1058, REQ-1009 | Deadline 29.09.2026 23:59 MSK, stop-code, presentation due 29.09, timeline | U | HEAD 2026-09-23 | A: deadline not reached |
| REQ-1017, REQ-4002 | Only the submitted version is judged; attach a link on the platform | U | — | A: judging/administration |
| REQ-2327, REQ-2335, REQ-2336, REQ-2337 | Number of external integrations; 149-ФЗ, 152-ФЗ, ГОСТ АС | U | — | A: undefined / legal |
| REQ-5004, REQ-5007, REQ-5008, REQ-5015–REQ-5031, REQ-5930, REQ-5932, REQ-5933, REQ-5945, REQ-6034 | Template slides 7–11 mandatory in the exact design; every team submits a presentation (full, with 7–11, when the ТЗ requires one); open repository access; ≤5 min video (mentor) | N | no presentation, repo PRIVATE, no video | F-33 |
| REQ-5939, REQ-6035 | 30.09–14.10 experts evaluate code, repositories, documentation, presentations; ТЗ packaging mandatory (mentor 50:14) | P | code/docs present; presentation absent | F-33 |
| REQ-5006, REQ-5009–REQ-5014, REQ-5032–REQ-5036, REQ-5005 | Non-mandatory («рекомендательные») slides, styling, logos, useful links; template metadata | U | — | A6, A5 |
| REQ-5931, REQ-5934, REQ-5935 | Only slides 7–11 if no presentation required (not applicable); slide-10 exception (template roster is slide 9); free slides before 7 / after 11 | U | — | A13 |
| REQ-5936–REQ-5938, REQ-5940–REQ-5944 | Deadline 29.09 23:59 via «Загрузить решение»; no pitches now; top-10 15.10; refinement 16–20.10; evaluation 20–23.10; pitches 23.10; ceremony 30.10 | U | — | A3 |

### 5.18 Evaluation criteria
ТЗ sections: «Критерии, учитываемые при проведении предварительной экспертизы», «… финальной
экспертизы». Other sources: chat msg643, Q&A L406–436, L766–808, msg34.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2364 | Additional configurable parameters | S | seed, time_scale, modes, profiles | — (S-12) |
| REQ-2349, REQ-2359 | Integration into any other systems | P | REST/JSON; `CallTransport` port | No XML, no SIP, no system-112 connector (F-30) |
| REQ-2353 | Completeness of documentation | P | docs exist | See F-34 |
| REQ-2352, REQ-2361, REQ-2362, REQ-2363, REQ-2365, REQ-2369, REQ-2370 | Forecasting vs real values; service «рекомендации» vs real ones; objectivity of diagrams | N | no forecasting; no charts | Absent; criteria have no counterpart in ТЗ requirements (REQ-2435) (F-36) |
| REQ-1033, REQ-2344–REQ-2348, REQ-2350, REQ-2351, REQ-2354–REQ-2358, REQ-2360, REQ-2366–REQ-2368, REQ-2371, REQ-4029, REQ-4061, REQ-4076, REQ-6016, REQ-6039 | Idea, originality, method, technologies, code quality, speed, calculations, UX, pitch; judging method; prize fund | U | — | A: jury |
| REQ-4027, REQ-4055, REQ-6014, REQ-6037 | Mentor: MVP judged as a whole (interface, card, generated questions, realism); experts may use arbitrary scenarios and value «творческий подход» | P | [REF-UI], import API only, no ticket scenarios | F-43 |

### 5.19 Hackathon administration, events, tooling, Q&A procedure
Sources: chat, `Ответы на вопросы.pdf`, `Инструкция для участника .pdf`, msg34, video.

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-1050 | SourceCraft optional | S | GitHub remote | — (S-14) |
| REQ-1002, REQ-1003, REQ-1006, REQ-1008, REQ-1011, REQ-1012, REQ-1018, REQ-1019, REQ-1051–REQ-1057, REQ-2376–REQ-2414, REQ-4074, REQ-4085, REQ-4091 | Registration, team size, chat rules, events, promo codes, FAQ, Q&A-session procedure, team roles, invitations | U | — | A: administration |
| REQ-5902, REQ-5905, REQ-5911, REQ-6002, REQ-6047 | Acknowledgements («Вернемся с ответом»), references to the ТЗ, pending GPU question, who is who at the session, answers to be published | U | — | A2 |

### 5.20 Open questions, unanswered participant questions, meta-statements

| ID | Requirement | Status | Evidence | Gap (facts) |
|---|---|---|---|---|
| REQ-2431–REQ-2437, REQ-4088, REQ-4089 | Datasheet purpose; call channel; mobile; integration vs isolation; forecasting criteria; trainee role; which Q&A list; no deadline in video; ТЗ outside X4 scope | U | — | A: open questions (§8) |
| REQ-1023, REQ-1040, REQ-1041, REQ-1043 | Participant questions (who is «участник событий»; training organisation; ДДС algorithm; ДДС access to audio) | U | — | A: no organizer answer (§8) |
| REQ-4094 | ASR confidence of the evidence process | U | — | A: meta |
| REQ-5901, REQ-5906–REQ-5908, REQ-5921, REQ-5922, REQ-5928, REQ-5929 | Participant texts of 22–23.09 (ДДС definition, card stream numbers, 103 call-back, external API, data transfer, hardware) | U | — | A8 (answers judged at REQ-5909–5920, 5923–5927) |
| REQ-6003 | 11:40–12:29 of the recording is silent; the start of the answer on scenario generation is lost | U | — | A9 |

---

## 6. What does NOT need to change — the 130 `соблюдено` items

Each group states the organizer's point and the evidence in one line. Detail per ID is in the
matrices (Appendix).

| Group | IDs | What the sources say | Evidence (one line) |
|---|---|---|---|
| S-1 Product purpose, roles, service | REQ-1007, 1026, 1027, 2013, 2068, 2326, 4014, 4073, 4075, 4081 | A 112 training simulator for dispatchers with AI-generated incident messages; one interface/account with 112-operator and ДДС mini-roles; instructors as users; a separate software service | `README.md:1-10`; `router.tsx:47-58`; `RoleType` OPERATOR_112/DDS (`enums.py:59-64`); INSTRUCTOR role; self-contained compose stack (`DOD_WALK.md` §7.1 `make up` exit 0) |
| S-2 Simulated call over IP, imitation only | REQ-1025, 2044, 2061, 2099, 2100, 2105, 2106, 2107, 2108, 2117, 2118, 2216, 2268, 4004, 4005, 4069, 6005, 6010, 6026 | Emulate incoming calls via IP telephony/VoIP to the operator's headset with AI; simulated calls are enough; no real calls, no real-system functions | LiveKit WebRTC call, `CALL_RINGING`/answer PASS and AI caller PASS (`AUDIT.md` §2 items 2–3); SIP/PSTN stub; world and resources scenario-defined Round 2 (recording): mentor and room «только симуляция» (11:00–11:12); mentor 24:16 describes the voiced call → card → check; mentor 40:42 voiced incoming calls «будет хорошо оценено тоже». |
| S-3 Manual card, checked against what was said and against the reference | REQ-1031, 1032, 2083, 2096, 2214, 2215, 2218, 4020 | Operator fills the card from the voice input; correspondence and chosen services are checked; manual entry compared with the reference | `set_field` by TRAINEE only (`operator_card.py:400`); INV4 test; evaluators CARD_CONTRADICTION, SERVICE_SELECTION, CARD_FIELD_CORRECT (tests passed); house «72» vs truth «27» → MISMATCH (`AUDIT.md` §2 item 7) |
| S-4 ДДС distributes to a service | REQ-4021, 6011 | The ДДС operator distributes the activity to a specific service | DDS resource selection/dispatch (`backend/app/domain/dds/resources.py`; `AUDIT.md` §2 item 11 PASS) Round 2: mentor 24:42 (same statement as REQ-4021). |
| S-5 Assessment and report | REQ-2046, 2060, 2072, 2097, 2115, 2209, 2223, 2272, 2273, 4071, 4082, 6019 | Assessment of actions, automated quality control, attestation use, detailed reports with actions and errors, trainee feedback | Deterministic evidence-backed score 45.0/78.0 with evidence per rule (`AUDIT.md` §2 item 14); report sections (`frontend/src/features/report/`); ASSESSMENT mode and release tests Round 2: room 31:53 «Мы даём на откуп… это участникам» — the team defines the method. |
| S-6 Instructor control of the lesson | REQ-2047, 2188, 2196, 2264, 2267, 2270, 2277, 2284, 2288 | Instructor interface; real-time monitoring; teacher starts and ends the lesson at any moment | `/instructor` live overview over WebSocket (`live-overview-page.test.tsx`, 9 cases); `startSession`/`abortSession` INSTRUCTOR/ADMIN (`sessions.py:134-187`) |
| S-7 Trainee practice | REQ-2208, 2211, 2212, 2286 | Practical tasks in emulation; results kept in a local profile; list of assigned sessions; actions on the card incl. text | Operator and DDS consoles; per-user results in PostgreSQL; `sessions-landing-page.tsx` (scope MINE); `StatusUpdateRequest.text_ru` |
| S-8 Access control | REQ-2124, 2177, 2203, 2204, 2226, 2227, 2228, 2229, 2230, 2232, 2234, 2242 | Role-based access; trainee and teacher restrictions; confidentiality of results; authentication at login; health indicators | `require_roles` (`security.py:68-95`) and role-gate tests; no delete API; append-only triggers; report visibility tests; `/health/ready` |
| S-9 Local operation and extension points | REQ-2131, 2136, 4036, 4050, 4051, 4060, 5913, 5923, 5924, 5925, 5927, 6022, 6032, 6033, 6038, 6045 | Everything local, no internet integrations; optional modules keep isolation; internal extension API | LLM/TTS URLs restricted to loopback/compose-internal (test passed); RoleModule interface (`backend/app/domain/roles/module.py`) Round 2: chat 23.09 14:41–15:58 (not hard-coded to external calls; internal deployment possible; configurable endpoint): `SIM_LLM_BASE_URL`, `llm_allowed_internal_hosts`, `backend/app/inference/loopback.py:29-70` (28 tests passed); Q&A local-only statements (mentor 46:52, room/mentor 47:21–48:35, 37:19, 55:06, 64:02). |
| S-10 Interface style and language | REQ-2156, 2158 | One design style; Russian localisation | One Vite app with shared `frontend/src/shared/ui/*`; all strings in `ru.ts`, guard tests forbid literals elsewhere |
| S-11 Database and formats | REQ-2248, 2297, 2300, 2304, 2306, 2310, 2311, 2315, 2317, 2322, 2323 | PostgreSQL ≥ 12; JSON exchange; SQL; JSON scenarios; MP3 or WAV; structure validation; integrity | `postgres:16`; OpenAPI JSON; SQLAlchemy/Alembic; scenario JSON Schema; WAV 16 kHz mono (`wav_writer.py:1`); FKs and append-only triggers |
| S-12 Documentation, comments, configurable parameters | REQ-2328, 2330, 2331, 2332, 2333, 2364 | Comments on complex logic; docs on methods, limits, build/install, architecture; configurable parameters | Module docstrings; `docs/hld/*`; `docs/AUDIT.md` §3; `README.md` «Fresh clone to a working demo» executed in `DOD_WALK.md` §7; seed/time_scale/modes/profiles |
| S-13 Organizer material archived | REQ-1005, 1042, 1046, 1047, 1048, 4006, 4023, 4039, 5201, 5243, 6006, 6025 | FAQ, ТЗ, screenshots, manual, classifier, datasheet, card and services documents provided | All present in `requirements/sources/01-qna-session-telegram/files/`. No product code or doc uses them (see F-10–F-14). Round 2: «Датасет» (tickets, ДДС memo), ТЗ PDF, template, classifier v_046_24 in `requirements/sources/05-organizer-materials/`; VoIP device documentation (datasheet) and the manual with screenshots confirmed by the recording. |
| S-14 Process points | REQ-1020, 1050 | One unchanged ТЗ; SourceCraft optional | One ТЗ file archived; GitHub remote |
| S-15 ДДС scope as stated by the customer and the memo | REQ-5267, 5358, 5915 | Screens and functions depend on the user category (memo p.11); services are not added on the ДДС card (memo p.14, msg701); «диспетчер ДДС правильность заполнения карты от заявителя не контролирует» (Ответ заказчика, 23.09.2026 15:46) | Role-gated routes and actions (`router.tsx:47-72`, tests); DDS API has no service add/edit (`openapi.yaml:952-1349`); DDS has no card-validation action (read-only frozen card, `work-item-panel.tsx:1-7`). REQ-5915 conflicts with msg638 (18.09); see §9.2 |
| S-16 Ticket fields; GPU permitted | REQ-5204, 6042 | A ticket «Ситуация» = narrative, caller name, phone, relation; room 61:59 «Конечно, хотите, используйте видеокарту. Не вопрос» | Scenario fields `scene_summary_ru`, `caller.full_name`, `caller.phone`, `CallerRelationship` (WITNESS/NEIGHBOUR/PASSERBY/RELATIVE); every profile runs the LLM on the GPU (`n_gpu_layers: -1`) |

---

## 7. What differs from the requirements — every `частично` and `не соблюдено` item

239 `частично` + 309 `не соблюдено` = 548 items (round 1: 186 + 153; round 2: 53 + 156), grouped
into 43 findings (F-38–F-43 are new in round 2; round-2 IDs are also added to F-01–F-37). Each finding gives the
requirement (verbatim, source), the current state of code and of docs, and the observable gap.
Statuses in brackets are the current ones (after §1.6 and §1.7). Q&A quotes carry the recording time
and speaker where round 2 verified them.

### 7.1 Product identity and purpose

**F-01 — The customer and the real system are named nowhere in the product.**
IDs: REQ-2004, REQ-2012, REQ-3011, REQ-4001, REQ-4064, REQ-4093, REQ-6001, REQ-5249, REQ-5258
[не соблюдено]; same facts in REQ-1001, REQ-2001, REQ-5003 [не обработано].
- Requirement: ТЗ Table 1 row 3: «ГБУ «Система 112» — государственное бюджетное учреждение, оператор
  системы-112 в городе Москве»; row 11: «Система 104 — автоматизированная информационная система
  Службы 104»; manual title: «МОДУЛЬ «ПРИЕМ И ОБРАБОТКА ВЫЗОВОВ 112»»; brief «Актуальность»: «В г.
  Москве имеется своя система-112 оператором которой является ГБУ Система 112»; video title card:
  «ДЕПАРТАМЕНТ ПО ДЕЛАМ ГРАЖДАНСКОЙ ОБОРОНЫ, ЧРЕЗВЫЧАЙНЫМ СИТУАЦИЯМ И ПОЖАРНОЙ БЕЗОПАСНОСТИ ГОРОДА
  МОСКВЫ»; Q&A host, 03:14 (recording, REQ-6001): «…от департамента гражданской обороны, чрезвычайным
  ситуациям и пожарной безопасности» (round 1's «природной» was a mis-hearing); ДДС memo p.3: «Оператором
  системы-112 Москвы… является ГБУ «Система 112» Москвы», p.6 «КИС УСС», «ПОВ-112… это и есть
  информационная система системы-112 Москвы». The ТЗ PDF cover omits «ГБУ «Система 112»» (REQ-5003).
- Code: grep for «ГБУ», «Москв», «Moscow», «Система 112», «Департамент», «104» service over
  `backend/app`, `frontend/src`, `scenarios`: no match; `ServiceType` has no Service 104 / System 104.
- Docs: `docs/SPEC.md`, `docs/AUDIT.md`, `docs/hld`, `README.md`: no match.
- Gap: no department, ГБУ «Система 112», System 104 or real-module name anywhere in the product.

**F-02 — Trainee role naming and city.**
IDs: REQ-2002, REQ-2005, REQ-2037, REQ-2057 [частично].
- Requirement: ТЗ title «Учебное программное обеспечение для подготовки оператора ДДС города Москвы с
  использованием искусственного интеллекта»; Table 1 row 4 «ДДС — дежурно-диспетчерская служба -
  служба, принимающая и обрабатывающая вызовы от системы-112»; ¶35 «…передачу информации в
  дежурно-диспетчерские службы (ДДС) через автоматизированные рабочие места (АРМ)».
- Code: roles OPERATOR_112 and DDS exist (`enums.py:59-64`); the UI labels the DDS role «ЕДДС»
  (`ru.ts:8,38`) and EDDS «РЕДДС» (`ru.ts:39`); the only scenario is «Apartment fire, Smolensk,
  Nikolaeva 27» (`v1.yaml:12`); the term «АРМ» does not occur in code or UI.
- Docs: SPEC §1 roles «Operator 112», «Profile DDS dispatcher», no city.
- Gap: the ДДС role is shown as «ЕДДС»; nothing Moscow-specific; «АРМ» not used.

**F-03 — Target user groups.**
IDs: REQ-2064, REQ-2067 [частично]; REQ-2065, REQ-2066, REQ-2069 [не соблюдено].
- Requirement: ТЗ ¶68–73 «Сервис должен быть предназначен для обучения операторов различных городских
  служб, включая: Специалисты ГБУ «Гормост»; Работники жилищных служб; Операторы других ДДС,
  взаимодействующих с системой-112; Преподаватели и инструкторы учебных центров; Руководители
  диспетчерских служб».
- Code: account roles TRAINEE/INSTRUCTOR/ADMIN; simulation roles OPERATOR_112/DDS/EDDS; `ServiceType`
  FIRE_RESCUE, POLICE, AMBULANCE, GAS_SERVICE, UTILITY_EMERGENCY, EDDS (`enums.py:77-90`).
- Docs: SPEC §1 lists no user groups beyond the roles.
- Gap: one generic DDS role; no role, scenario or service for Гормост, housing services or heads of
  dispatch services.

**F-04 — Uses of the service and the component list.**
IDs: REQ-2043, REQ-2070, REQ-2071, REQ-2073, REQ-2074, REQ-2075, REQ-2088 [частично].
- Requirement: ТЗ ¶75–80 «Сервис должен использоваться для: Базового обучения новых сотрудников;
  Периодической переподготовки действующих операторов; Аттестационных мероприятий; Контроля знаний и
  практических навыков; Отработки нестандартных ситуаций в безопасной среде; Мониторинга
  эффективности учебного процесса»; ¶97 «Автоматизировать процесс подготовки операторов ДДС»; ¶41
  component list.
- Code: sessions are created, assigned and started manually by an instructor
  (`frontend/src/features/instructor/create-session-form.tsx`); one scenario with `difficulty: 3`;
  complications inside it (wrong floor, fire spread, `v1.yaml:152-217`); no aggregate analytics
  endpoint.
- Docs: SPEC §1 modes SINGLE_ROLE, FULL_CYCLE_SINGLE_TRAINEE, MULTI_TRAINEE, ASSESSMENT.
- Gap: no content set for basic training, no periodicity/retraining tracking, no knowledge test (only
  practical scoring), one scenario of non-standard situations, no monitoring across sessions, no
  automatic assignment. Of the four ТЗ components, only the difficulty-distribution one is partial.

**F-05 — Training on the real system-112 software; variety of incidents.**
IDs: REQ-2058, REQ-2059, REQ-2093, REQ-2094, REQ-4066 [частично].
- Requirement: ТЗ ¶62 «Обучение операторов работе с программным обеспечением системы-112»; ¶103
  «Обеспечение обучения операторов работе с эмулятором ПО системы-112»; ¶63 «Отработка навыков
  обработки различных происшествий и чрезвычайных ситуаций»; brief: «необходимостью обучать, развивать
  и совершенствовать навыки работы диспетчерского персонала ДДС со специальным программным
  обеспечением, применяемого в системе 112».
- Code: the product's own operator console (`frontend/src/features/operator/console-page.tsx`,
  38-field card); one scenario (fire).
- Docs: SPEC §32 «professional operational software»; no reference to the real software.
- Gap: the interface is the product's own and differs from the archived screenshots of the real one
  (F-10, F-12); the repository holds one incident type.

### 7.2 Call emulation and voice

**F-06 — The caller-side AI voice: excluded by the organizer at this stage, built as the core of the
product.** Full dated statements in §9.1.
IDs: REQ-4017, REQ-4040, REQ-4044, REQ-4045 [не соблюдено]; REQ-1024, REQ-4018 [частично]. REQ-4043
left this finding in round 2 (now `не обработано`, §1.7); REQ-6028/6029 are in F-07.
- Requirement (verbatim; all Q&A lines below are the **room** per the recording, except where marked):
  Q&A 39:07 (L573–574) «заявителя мы исключаем, то есть никаких заранее подготовленных
  записей, голосов нет»; L577–586 «Это карточка и дальше IP-телефония… набирает там мышкой кнопку,
  какой-то номер… и ему в ответ уже слышно, слушаю вас. Вот оператор что-то произносит, ну и
  достаточно хотя бы на конкурсной основе говорит, я вас понял, информация принята»; L628–631
  «никаких голосовых диалогов… голосовой диалог только, скажем так, ДДС, руководитель, которому они
  будут звонить»; L642–643 «Точку А мы пока исключаем. Заявители, да, и 112 мы пока убираем»; L307–309
  «вторая часть наиболее сложная, это чтобы искусственный интеллект или машина оценивала действия
  обучаемых» (room, 22:40); msg570 «имитировать голос живого человека… не надо»; msg570 «Мы генерируем сообщение
  которое формируется карточкой системы 112 и направляется в конкретную службу ДДС… согласно ЕКП».
- Code: full AI caller — `workers/voice_agent/*`, `backend/app/application/dialogue/*`,
  `backend/app/domain/facts/gate.py`; the 112 stage starts with an empty card filled by hand (SPEC
  §9); a system-generated card (`expected_response.prefab_handoff`,
  `backend/app/application/handoff/prefab_handoff.py`) exists only for a `[DDS]`-only role chain and
  is tested (`backend/tests/api/modes/test_single_role_dds_prefab.py`, passed), but the shipped
  scenario's chain is `[OPERATOR_112, DDS]` (`v1.yaml:16`). No "caller excluded, telephony only" mode.
  Service routing is manual, not «согласно ЕКП» (F-14). Scoring is deterministic (F-19).
- Docs: SPEC §1, §15–§25; `docs/AUDIT.md` §15–§25 IMPLEMENTED/PARTIAL, none EXCLUDED; §46 items 2–3
  PASS.
- Gap: the leg the organizer excluded («точка А») is the product's most developed subsystem; the leg
  the organizer named as the only voice dialogue («ДДС, руководитель») does not exist (F-07).
  Recording correction: the two statements welcoming voiced incoming calls are the **mentor's**, not
  the customer room's — 40:42 «это будет хорошо оценено тоже» (REQ-6026, соблюдено) and 43:20 «если
  коллеги сделают, будет здорово» (REQ-6030, referent not settled); msg624/msg642 and the full dated
  sequence are in §9.1.

**F-07 — ДДС → responder voice/phone dialogue.**
IDs: REQ-4042, REQ-6028, REQ-6029 [не соблюдено]; REQ-4041, REQ-1037, REQ-1038 [частично].
- Requirement: room 42:06–42:28 (REQ-6028): «голосовой диалог только, скажем так, ДДС — руководитель,
  которому они будут звонить. Вот и всё. Вот здесь вот можно как-то пообщаться интерактивно»; room
  42:28–43:19 (REQ-6029): «нас интересует диалог между Б и С. Вот здесь, когда будут звониться по вот
  этому симулятору IP-телефонии»; room 40:27–40:42 (L594–597) «обратная сторона… должна быть не со стороны заявителя об опасности, а мы
  делаем наоборот, когда оператор ДДС информирует уже руководящий состав от той информации, которую
  он получил»; L588–590 «В зависимости от категории, там, женские голоса, мужской голос должен быть,
  ну, с разными интонациями»; msg691 «Мы ограничивается только телефоном»; «старший группы звонит в ДДС
  докладывает об обстановке… Или диспетчер сам через определенное время набирает по телефону
  старшего… Работают как правило два варианта»; «Ответ заказчика» 23.09.2026 15:46: «Общение с
  реагирующей на вызов бригадой тоже происходит либо по телефону или по другим каналам связи или через
  стороннее программное обеспечение, минуя 112» (REQ-5918, in F-13).
- Code: no call, phone or voice code in `backend/app/application/dds`, `backend/app/domain/dds`,
  `frontend/src/features/dds` (grep re-run for this report); unit reports arrive only as scenario
  radio messages (`CREATE_RADIO_MESSAGE`, `backend/app/domain/world/effects.py:74-78`; one in the demo,
  `v1.yaml:213-214`); unit status advances from ETA data (`resource_movement.py`); `voice_id` is one
  value per scenario (`backend/app/domain/caller/profile.py:23`; `v1.yaml:93` «ru_female_adult_01»).
- Docs: SPEC §11 (no telephony at DDS), §12 radio/status update; AUDIT §11.
- Gap: no ДДС-initiated call, no call to a leader, no phone channel, no voice per recipient
  category, no dispatcher "pull" of a status.

**F-08 — SIP server, hardware IP phone, headset.**
IDs: REQ-2249, REQ-2151 [не соблюдено]; REQ-2150 [частично].
- Requirement: ТЗ ¶302 «Поддержка IP-телефонии (VoIP) через локальный SIP-сервер»; ¶176 «IP-телефон с
  гарнитурой и поддержкой VoIP»; ¶175 «Периферия: Гарнитура с поддержкой VoIP (программная эмуляция
  IP-телефона)». (Q&A L145–148: «аппаратный телефон не нужен» — REQ-4004, соблюдено.)
- Code: `SipCallTransport` — every method raises `NotImplementedError`
  (`workers/voice_agent/voice_agent/transport/sip_transport.py:24-51`); no SIP server in `infra/`;
  browser phone widget with the local audio device (`phone-widget.tsx`, `call-media.ts`; 17 tests
  passed).
- Docs: SPEC §15 (SIP as a later complement); `docs/hld/50-voice-pipeline.md:187`; `docs/DOD_WALK.md:8-12`
  (the walk injected WAV audio; no browser microphone/headset path was exercised).
- Gap: no SIP; a hardware IP phone cannot connect; the headset path has unit tests but no recorded run.

**F-09 — Isolated contour and secure login.**
IDs: REQ-2082, REQ-2089, REQ-2255, REQ-2265, REQ-2278 [частично].
- Requirement: ТЗ ¶88 «без доступа к внешним сетям (локальный контур)»; ¶98 «Моделировать реальные
  ситуации с использованием эмуляции вызовов в изолированном контуре»; ¶323/¶333 «Вход участниками в
  систему через защищенный интерфейс в локальном учебном комплексе (без доступа к внешнему
  интернету)».
- Code: runtime URLs validated as local (`llama_cpp_client.py:59-84`, test passed); `HF_HUB_OFFLINE=1`
  for GigaAM; LiveKit `use_external_ip: false`; login over plain HTTP; `networks:` absent in
  `infra/docker-compose.yml`; `make models` downloads from the internet (`Makefile:81-94`).
- Docs: SPEC §41; AUDIT §41; no document records an offline run.
- Gap: isolation is not demonstrated by a run or a network configuration; login is not encrypted.

### 7.3 The 112 operator card

**F-10 — Card structure differs from the real card and from the «100 %» instruction.**
IDs: REQ-1045, REQ-2127, REQ-3002, REQ-3003, REQ-3004, REQ-3005, REQ-3007, REQ-3008, REQ-5273 [не соблюдено];
REQ-1030, REQ-2217, REQ-2269, REQ-3001, REQ-3006, REQ-3014, REQ-3021, REQ-4035 [частично].
- Requirement: msg680 (21.09.2026): «Карточка и реестр обращений 100% должны быть похожи, а всё новое
  или второстепенно - не критично, если будет немного отличаться»; ТЗ ¶145 «Форматами данных и
  визуальными стандартами ГБУ «Система 112» (для обеспечения реалистичности обучения)», explained in
  the Q&A L530–536: «это форматы данных, это поля… телефон заявителя… номер карточки… Те поля, которые
  там отображаются. Вот это и есть формат»; ТЗ ¶327 «Обучающиеся заполняют карточки событий (имитация
  интерфейса системы АРМ-112)»; card screenshot caption: «В поле ЧТО СЛУЧИЛОСЬ выбирается сценарий
  (ИХ ОЧЕНЬ МНОГО). Далее к каждому сценарию подтягиваются ТЭГИ под конкретный сценарий»; manual:
  «Карточка состоит из следующих блоков: номера телефонов (заявителя); что случилось; адрес
  происшествия; подробности происшествия. Внимание! Для корректной обработки происшествия необходимо
  заполнить все блоки карточки»; «…необходимо заполнить поля «Описание со слов заявителя», «ФИО
  заявителя», «Статус заявителя» и группу полей «Пострадавшие»»; `КАРТОЧКА 112.docx`: 51 «Что
  случилось?» types; «Где: Улица . Транспорт . Дом . Здание / объект . Опасный объект»; per-branch
  field sets (street 12 materials, transport 16 types, «Запах гари» collapses the form, 104 gas signs,
  «Взрыв» fields).
- Code: `CARD_FIELDS` — one static list of 38 fields in 9 groups for every incident type
  (`backend/app/domain/layers/operator_card.py:86-391`); `IncidentType` 8 values FIRE, MEDICAL, CRIME,
  TRAFFIC_ACCIDENT, GAS_LEAK, UTILITY_FAILURE, RESCUE, OTHER (`enums.py:152-162`) in a plain select
  (`card-form.tsx:38-47,154-172`); address = separate fields locality/street/house/building/entrance/
  floor/apartment/landmark/comment; description labelled «Описание происшествия»; one boolean
  `hazards.gas_leak`; `required_for_handoff` «remains advisory only» (`operator_card.py:14`);
  `caller.full_name`/`caller.relationship` not required; no card number (internal UUIDs); no
  conditional fields; no register screen (grep «реестр»: 0).
- Docs: SPEC §9 (manual card, revisions); `docs/hld/10-domain-model.md` §10.6 (the product's own
  field table); no doc references the archived card documents.
- Gap (reference `СКРИНШОТ КАРТОЧКИ 112ГСИ.docx` image1 vs product): absent fields «АОН», «Страна»,
  «Субъект», «Объект», «Округ», «Район», «Код», «Описательный адрес», card number; label «ФИО
  заявителя» vs «Фамилия и имя заявителя», «Описание происшествия» vs «Описание со слов заявителя»;
  8 generic types vs 51 named; no «Где» branch, no per-type tags, no «Запах гари» collapse, no
  «Взрыв» type; 9 groups vs 4 blocks, none enforced; no «реестр обращений» screen (the organizer
  files call the ДДС list «Список происшествий»/«Поиск происшествий»).

**F-11 — Real-card functions absent or different.**
IDs: REQ-3013, REQ-3015, REQ-3016, REQ-3017, REQ-3018, REQ-3019, REQ-3020, REQ-3022, REQ-3028,
REQ-3029, REQ-3031, REQ-3033, REQ-3034, REQ-3035, REQ-3036, REQ-3037 [не соблюдено]; REQ-3010,
REQ-3012, REQ-3023, REQ-3024, REQ-3027 [частично].
- Requirement (manual and screenshots, verbatim excerpts): «КРАСНЫЙ ЦВЕТ ПОЛЯ ГОВОРИТ ОТОМ ЧТО ВРЕМЯ
  НАБОРВ КАРТОЧКИ ПРЕВЫШЕНО»; «Ввести свои логин и пароль, а также номер АРМ… Если не закрывать
  вкладку… 24 часов, то выход произойдет автоматически»; telephony statuses «доступен… недоступен…
  не подключен… ошибка»; «Телефон АОН заполняется автоматически… Предоставленный номер (Alt+F2)…
  Телефон на место (Alt+F3)… признак «зарубежный номер»»; buttons «Нет контакта», «Срыв звонка»;
  «Вводом типа происшествия в строку поиска… синонимом к опросной карте «101» является слово
  «пожар»»; «Отказ от реагирования»; «единую адресную строку… Яндекс.Карты, Яндекс.Организации,
  ФИАС… автоматически определит район и округ»; map layer «Объекты»; «в службу 03 передаются только
  первые 100 символов»; caller statuses «очевидец; пострадавший; родственник; знакомый; ребенок;
  участник» and «После сохранения… изменить ФИО и статус заявителя будет нельзя»; «Пострадавшие» via
  «Есть»; «Оповестить и сохранить карточку», primary services double-underlined; «Совпадение»
  linking; three transfer modes, conference up to 4; «Добавить отработку»; reminder every 20 s,
  «Важное происшествие»; 13-parameter search; incoming SMS; «Аудит» statuses; 39 hotkeys.
- Code: phone widget `mm:ss` call timer without threshold colour (`phone-widget.tsx:68-85`); login
  username + password, JWT TTL 720 min (`login.py:53-63`, `settings.py:93`); one `caller.phone`;
  `CallerRelationship` VICTIM, WITNESS, NEIGHBOUR, RELATIVE, PASSERBY, OFFICIAL, UNKNOWN
  (`enums.py:165-174`), editable at any time; `people.victims_count` always visible; handoff dialog
  with a free-text comment (`stage-action-bar.tsx:126-140`); one Enter-to-blur key handler
  (`card-form.tsx:181-184`); no map component; no SMS; grep for the other features: 0 hits.
- Docs: SPEC §9, §10; no doc references the manual.
- Gap: of the listed functions, present in another form: an elapsed-time display (no red threshold),
  a login (no АРМ number, 12 h instead of 24 h), 3 of 6 caller statuses (WITNESS, VICTIM, RELATIVE),
  a victims count (no «Есть» reveal), a confirm dialog (no service review); all others absent.

**F-12 — Colours and layout of the real program.**
IDs: REQ-1044, REQ-4022, REQ-4024, REQ-6012, REQ-5274 [не соблюдено]; REQ-2081, REQ-2104, REQ-4025,
REQ-6013 [частично].
- Requirement: msg679 «надо стремиться повторить и цвета и конфигурацию, чтобы решение было знакомо в
  первую очередь самим преподавателям»; Q&A L356–362 «интерфейс должен быть точный, копировать
  интерфейс рабочей программы… по цветовым решениям… максимально близко приближены к реальному…
  меньше вот самодеятельности»; ТЗ ¶88 «Реалистичную имитацию рабочих процессов и интерфейса
  системы-112»; ¶115 «Имитировать функционал и интерфейс системы-112 в изолированном контуре…». Round 2,
  recording: **mentor** 26:36 (REQ-4024/6012) «Надо будет просто попробовать повторить то, что вы
  будете видеть на скриншоте»; room 26:12 «Да, он довольно несложный» and **mentor** 26:16 (REQ-4025/
  6013) «карточка, возможность выбрать… теги… цветовая гамма… не сильно цветастая… как можно быстрее
  забивать данные и переходить к следующему звонку»; round 1 had attributed the «наше требование
  однозначно… копировать интерфейс» passage (L354–362) to the customer, and the recording confirms it is
  the room. ДДС memo p.15/16: selected features blue, notification list orange (REQ-5274).
- Code: `frontend/src/index.css:51-85` shadcn neutral tokens, zero chroma except `--destructive`;
  layout grouped by field-path prefix (`frontend/src/entities/card/field-groups.ts`); grep «orange»
  in `frontend/src`: 0.
- Docs: SPEC §32 only «must look like professional operational software, not a chatbot»; no doc
  references the screenshots.
- Gap: greyscale palette vs the reference's orange «Службы: +» and «сохранить» bars and grey panels;
  layout not derived from the reference screens (F-10); no tag control; one call per session, so no
  «next call». Work-process imitation exists.

### 7.4 ДДС work

**F-13 — ДДС workflow, screen and statuses.**
IDs: REQ-3030, REQ-3038, REQ-3039 [не соблюдено]; REQ-1028, REQ-1029, REQ-1030 (ДДС part),
REQ-1039, REQ-3032, REQ-3040, REQ-3041, REQ-4016, REQ-4080 [частично]; round 2: REQ-5917, REQ-5919,
REQ-5920 [не соблюдено]; REQ-5914, REQ-5916, REQ-5918 [частично]. (REQ-5915 is `соблюдено`, §6 S-15.)
- Requirement: msg638 «Роль «Диспетчер ДДС» (Точка B). Его задачи 1 - Получение карточки: Принимает
  готовую карточку, которую сгенерировала система (имитируя работу 112) 2 - Проверка/Валидация:
  Проверяет корректность данных в карточке… 3- Взаимодействие с Точкой C: Совершает исходящие звонки
  руководителям служб через симулятор IP-телефонии»; msg628 (participant list confirmed «Да, в том
  числе», msg635): ДДС «б) Принимает либо отклоняет её… д) Управляет изменением первичных статусов»;
  msg701 «В карточке ДДС службы не добавляются. Карточка приходит в конкретное ДДС и оператор видит в
  какие службы помимо ее пришла эта карточка. И при необходимости может с этой службой связаться если
  есть немер телефона»; Q&A L286–293 «дежурно-диспетчерские службы видят у себя появившуюся строчку
  нового сообщения… либо ответить, либо отказаться, либо перенаправить еще куда-то»; manual «Если в
  течении 48 часов… не пришел статус "Завершение работ", карточка происшествия переходит в статус «Не
  завершено»», «нажать кнопку «Отработана»»; ДДС screenshots: own login «112 ВХОД В СИСТЕМУ», list
  «Поиск происшествий» with columns «Связи | ЧС | Опер. | АРМ | Номер | Дата | Время | Тип
  происшествия | Постр. Адрес | Статус службы», card view «Класс.: пожар: квартира», statuses
  «НАЧАЛО РЕАГИРОВАНИЯ/ ОТКАЗ ОТ ВЫПОЛНЕНИЯ РАБОТ/ РАБОТЫ ЗАВЕРШЕНЫ»; video: dispatchers «информируют
  руководство… контролируют качество оказания помощи». Round 2, «Ответ заказчика» 23.09.2026 15:46 (the
  answer to the ДДС definition, laid out point by point in §9.3): «Ответ. Да. Соответствует. Однако
  диспетчер ДДС правильность заполнения карты от заявителя не контролирует. Это прерогатива оператора
  112 и службы контроля 112. Диспетчер ДДС только выбирает статусы ( в карте нижние поля см карту и
  добавляет статусы своими комментариями). При необходимости диспетчер ДДС может напрямую выйти на
  заявителя по обычному телефону, т.к. номер заявителя есть уже в карточке, и далее общаться с ним минуя
  112. Общение с реагирующей на вызов бригадой тоже происходит либо по телефону или по другим каналам
  связи или через стороннее программное обеспечение, минуя 112.»; second answer, same time: «Как
  правило диспетчер ДДС номер карточки при дозвоне заявителю номер карты не называют. Общаются по сути
  заявления. Например. Вы звонили в 112 по поводу.... Что у вас случилось и т.д.»
- Code: DDS transitions acknowledge → resource selection → dispatch → simulation-driven EN_ROUTE/
  ARRIVED/WORKING/RESOLVED → close (`transitions.py:231-311`); no reject/redirect transition (grep:
  0); `ClosureReason` RESOLVED, FALSE_CALL, TRANSFERRED, CANCELLED_BY_CALLER; one stage-wide work item
  for all recipient services (`work-item-panel.tsx:8-10`) with a «Получатели» list; missing fields
  shown as «не указано оператором»; no DDS scoring rule for card errors (DDS rules in `v1.yaml:317-345`
  are RESOURCE_SELECTION and REQUIRED_STATUS_UPDATE); `StatusUpdateKind` ACKNOWLEDGEMENT, EN_ROUTE_REPORT,
  ON_SCENE_REPORT, SITUATION_UPDATE, ADDITIONAL_FORCES_REQUESTED, RESOLUTION_REPORT with free text
  (`status-update-form.tsx:17-24`); one shared login page; DDS route shows one work item per session,
  no list; no 48 h rule.
- Docs: SPEC §10, §11; AUDIT §2 items 9–13 PASS/PARTIAL.
- Gap: no validation, reject or redirect action; no phone; no incident list or search; no
  per-ДДС delivery; status vocabulary and «Номер наряда» differ; no «Отработана»; no 48 h rule; no
  "inform leadership" or quality-control function. Against the 23.09 answer: the missing validation
  action matches it (REQ-5915); the DDS trainee also selects and dispatches resources, which «только
  выбирает статусы» does not include, and EN_ROUTE…RESOLVED are set by the simulation (REQ-5916);
  the ДДС cannot call the claimant (no call function; the caller's phone is shown if the operator
  entered it, `card-field-labels.ts:29`) (REQ-5917, 5919, 5920); brigade contact is an inbound
  scenario radio log, no phone, no DDS→unit message (REQ-5918). The 18.09 check-the-card task
  (msg638) and the 23.09 answer contradict each other (§9.2).

### 7.5 Classifier, services, routing

**F-14 — No classifier, no automatic or district/subordination routing, 6 generic services.**
IDs: REQ-2291, REQ-3009, REQ-3025, REQ-3026, REQ-3042, REQ-3043, REQ-3044, REQ-3045, REQ-3046,
REQ-3047, REQ-3048, REQ-5255, REQ-5701, REQ-5704, REQ-5705, REQ-5707, REQ-5708, REQ-5709, REQ-5712–REQ-5717
[не соблюдено]; REQ-1034, REQ-1035, REQ-1036, REQ-2259, REQ-4015 [частично].
- Requirement: ТЗ ¶348 primary data «Классификатор происшествий»; card caption «После выбора
  информации АВТОМАТИЧЕСКИ ПОДТЯГИВАЮТСЯ СЛУЖБЫ которые можно дополнительно подтягивать в ручную»;
  manual «В системе предусмотрен функционал удаления и добавления служб на вызов, однако в штатной
  ситуации пользоваться им не следует. Система автоматически определяет службы… в соответствии с
  Единым классификатором происшествий»; «с пометкой «ВИС»»; msg683 «Под каждый сценарий реагирования
  для оператора 112 закладывается своя опросная карта. Для диспетчеров сценария нет. Под сценарием
  реагирования подтягиваются определенные ДДС»; msg684 «Если для 112 служба подтягивается
  автоматически исходя из опросной карты, но есть возможность добавлять в ручну. Для ДДС необходимые
  бригады выбираются в ручную… ПУСТЬ БУДЕТ УНИВЕРСАЛЬНЫЙ АЛГОРИТ ДЛЯ ВСЕХ»; msg690 «Службы
  подтягиваются по принципу района обслуживания. И по признаку подчинённости… поступит в 01, 02, 03…
  ДДС департамента образования… ДДС управы Щукино и ДДС Сев Зап административного округа»; ТЗ ¶316
  «…чтобы в их ленту попадали только профильные события (например? Мосводоканал, Москоллектор, Управы,
  службы газа и пр.)»; `СЛУЖБЫ 112.docx`: ~25 city services (Служба 101, ФСБ, ЦЭМП, Служба 103, Служба
  104, ЦОДД, Гормост, Мосгортранс, Мосводоканал, МОЭК…) and ~140+ «ДДС района…» entries; classifier:
  24 categories, 1281 data rows, 90 columns incl. «Сценарий реагирования» and a routing matrix of ~65
  organisations. Round 2: classifier v_046_24 («…_корректировка_МВД_+_Департамент») — 99 columns ×
  1310 rows, 24 categories, 1283 data rows (+2: 23060001, 24120200), «Сценарий реагирования» column
  removed, 7 new recipient organisations (e.g. «ЦУКБ Министерство обороны», «ГПБУ Мосэкомониторинг», «ООО
  Ситиэнерго»), 94 changed rows (90 in the МВД columns), fire/smoke content unchanged (REQ-5701–5717);
  memo p.5 «более 210 участников информационного взаимодействия» (REQ-5255).
- Code: `ServiceType` 6 values (`enums.py:77-90`; `UTILITY_EMERGENCY` documented as a distractor);
  manual toggles only (`services-panel.tsx:20,45-58`); `required_services` is a scoring target, not an
  auto-fill (`service_selection.py:25,48-49`); per-role visibility only
  (`test_multi_trainee_two_users.py`); grep «классификатор|classifier|ЕКП|опросн|district|район|
  подчин» in code: 0.
- Docs: SPEC §2 «The LLM MUST NOT: … decide what services are objectively required»; SPEC §10.4
  "Record selected recipient services"; no doc references the classifier.
- Gap: matches — ДДС picks brigades manually; one DDS algorithm for all services; 01/02/03 exist as
  FIRE_RESCUE/POLICE/AMBULANCE. Absent — classifier, response-scenario codes, опросная карта, automatic
  service pull-in, district and subordination routing, departmental/district/okrug ДДС, «ВИС» tag,
  service-profile feeds.

### 7.6 Training management and the teacher role

**F-15 — Difficulty levels and distribution of tasks.**
IDs: REQ-4049, REQ-4059, REQ-6041 [не соблюдено]; REQ-2045, REQ-2062, REQ-2098, REQ-2103, REQ-2119, REQ-2187,
REQ-2191, REQ-2224, REQ-4007, REQ-4047, REQ-4063, REQ-4070 [частично].
- Requirement: ТЗ ¶43 «Модуль управления обучением с возможностью распределения заданий по уровням
  сложности»; ¶223 «Назначать учащимся конкретные задания и группы»; ¶228 «Классифицировать задания по
  уровням сложности»; brief «управления процесса обучения (выбор, распределение заданий по уровням
  сложности)»; Q&A L788–789 «первому задание один, а пятому задание три… путем проставления галочек
  там на рабочие места»; L687–697 «машина может перескочить… и дать более сложное задание… или
  наоборот… автоматически перекидывает на более простые задания»; L822–842 «сложность задания должна
  определяться критерием весов… либо задаваться вручную… либо… искусственный интеллект… должен
  предложить преподавателю»; L164–174 «На низших уровнях преподаватель, на более высоких искусственный
  интеллект, но под контролем… преподавателя»; round 2, recording: the difficulty-weight answer is the
  **room**'s (57:59, «Станислав, я отвечу на этот вопрос»; REQ-4063/6041): «искусственный интеллект
  должен предложить преподавателю… стоить десять баллов… или пять… или шесть» (round 1's «100 и 10
  баллов» was a mis-hearing); the per-workstation distribution (L788–789, REQ-4059) is the room's
  (54:22–54:55, confirmed).
- Code: `difficulty: int` 1–5 on `ScenarioVersion` (`backend/app/domain/scenario/version.py:54`),
  set in the YAML (`v1.yaml:14`, value 3), not shown in the create-session form; one `ScenarioVersion`
  per session; `SessionParticipant` has no task field (`session.py:120-131`); no group entity; no
  adaptive logic.
- Docs: SPEC §4 lists `difficulty`; nothing on distribution.
- Gap: no difficulty selection or display, no per-workstation distinct tasks, no groups, no adaptive
  levelling, no AI-weighted difficulty; one scenario exists.

**F-16 — Scenario generation, reference answers, teacher approval, card selection.**
IDs: REQ-2256, REQ-2257, REQ-2258, REQ-2260, REQ-2261, REQ-2263, REQ-2266, REQ-2279, REQ-2280,
REQ-2281, REQ-2283, REQ-2285, REQ-2287, REQ-4009, REQ-4010, REQ-4037, REQ-6008, REQ-6009, REQ-6023,
REQ-6044 [не соблюдено]; REQ-2084, REQ-2186, REQ-2192, REQ-2199, REQ-2254, REQ-2282, REQ-6007 [частично].
- Requirement: ТЗ scenario «Настройка учебной среды» ¶313–320: «Выбор категории событий, настройка
  нейросети на генерацию конкретных типов происшествий…»; «Формирование «эталона» - автоматическое
  формирование системой эталонных ответов»; «Подтверждение (частичное или полное)… Преподавателем»;
  «Предпросмотр… с подсветкой правильных с точки зрения системы»; «Коррекция… контекстное поле, куда
  он может ввести комментарий, который должен быть отработан системой»; «Проверка грамматики (при
  необходимости) - принудительная проверка после ручных манипуляций с данными»; scenario «…действия с
  карточками» ¶334–341: multiple category choice, «Выбор Преподавателем категории вопросов»,
  «выбор сгенерированных системой карточек событий», «…сформированных обучающимися…», «смешанный
  выбор», «Система формирует для обучающегося случайную карточку события», «После завершения
  действий система выдает новую карточку события»; Q&A L200–207 «преподаватель является… фактическим
  подтверждающим те или иные итоги»; L208–210 and L544–553 local fine-tuning from teacher flags and
  new materials. Round 2, recording: these are the **mentor's** words and read «в ТЗ» (not «ФТЗ») and
  «галлюцинаций» (not «инвестиционации»); the mentor continues «искусственный интеллект выдал какие-то
  правильные ответы… но преподаватель сам подтверждает правильность ответа» (14:43, REQ-6008), «он
  помечает, какие ответы… ИИшка пометил как правильные, он считает их неправильными» (37:34, REQ-6023),
  and on further training «если оно будет длиться минуты, это нормально» (62:38, REQ-6044). The
  **room** (12:29–13:12, REQ-6007): «Помимо шаблонов… предусмотреть самостоятельную генерацию» (round
  1's «несоединительной генерацией» was a mis-hearing; the start of this answer is lost in the
  11:40–12:29 audio gap, REQ-6003).
- Code: scenarios are hand-written YAML, imported/validated by REST or CLI only
  (`scenarios.py:115-160`, `backend/app/tools/import_scenarios.py`; the frontend never calls import);
  `expected_response`/`scoring_rules` authored in the file; no edit/delete operation; the session form
  has one scenario, one version, one mode (`create-session-form.tsx:214-259`); one incident per
  session (`uq_incidents_session`); only one prefab card per scenario; no grammar checker (only a GBNF
  `grammar.py` for LLM output); no fine-tuning code; no confirmation of a `ScoreResult`.
- Docs: SPEC §2, §4, §45 («Do not start by asking an LLM to generate an entire scenario at runtime»).
- Gap: all listed steps absent except manual scenario import/versioning and the trainee-formed card
  reaching DDS inside its own session.

**F-17 — Teacher tools, feedback, time limits, non-interference.**
IDs: REQ-2197, REQ-2198, REQ-2201, REQ-2205, REQ-4019 [не соблюдено]; REQ-2087, REQ-2101, REQ-2116,
REQ-2185, REQ-2200, REQ-2202, REQ-2206, REQ-2225, REQ-4033, REQ-4058 [частично].
- Requirement: ТЗ ¶236 «Предоставлять обратную связь (комментарии к результатам) через интерфейс
  системы»; ¶237 «Давать рекомендации по улучшению навыков»; ¶240 «Устанавливать временные рамки
  (тайминг) выполнения заданий. По умолчанию значение - 30 сек.»; ¶241 «Настраивать критерии
  успешности (пороги допустимых ошибок, требования к синтаксису ответов)»; ¶245 «Вмешательстве в
  работу других преподавателей»; ¶246 «Изменении результатов обучения (оценок) без фиксации в журнале
  аудита»; ¶220 «…включая управление ИИ-модулем и оценку действий обучающихся»; ¶271 «Контролировать
  время выполнения заданий (таймер в интерфейсе)»; Q&A L505–515 «в течение 30 секунд… это норматив,
  который определен… давайте установим в течение 3 минут»; L786–789 «на отдельном компьютере он видит
  действия обучаемых, их результаты, да, всех обучаемых»; L326–332 «ему машина должна с помощью
  подсказок… объяснение интерфейса»; ¶93/¶130 «удаленного контроля учебного процесса».
- Code: release endpoint takes no body (`instructor.py:49-66`); grep `comment` in instructor
  features: 0; only DEADLINE rule is 240 000 ms answer→handoff (`v1.yaml:289-300`), no default; the
  session form sends only `time_scale`; any INSTRUCTOR may observe, start, abort, rescore, release any
  session (`authorisation.py:55-66`, `sessions.py:134-187`); rescore `persist: true` logs events with
  actor SYSTEM (`rescore_session.py:93-124`); call timer only in the 112 console; live overview is per
  session; CORS default `http://localhost:5173`; no tutorial/hint system.
- Docs: SPEC §7, §28, §32; RUNBOOK (no remote-access section).
- Gap: no comments or improvement advice by the teacher; no 30 s default or 30 s/3 min pair; no time
  limit at assignment; no pass thresholds; instructors not isolated from each other; instructor not
  recorded on persisted rescore; no DDS timer or norm display; no multi-trainee overview; remote use
  untested; no beginner hints; no AI-module control.

**F-18 — Training materials and reference base.**
IDs: REQ-2190, REQ-2213 [не соблюдено]; REQ-2134, REQ-2207, REQ-2262 [частично].
- Requirement: ТЗ ¶227 «Создавать новые учебные материалы и загружать дополнительные ресурсы»; ¶256
  «Просматривать инструкции и методические материалы (справочную базу)»; ¶249 «Доступ к назначенным
  учебным материалам и сценариям»; ¶319 «Обучение (при необходимости) - загрузка материалов в базу»;
  ¶153 (optional) «инструмент для пакетного обновления учебных материалов и сценариев (в ручном
  режиме)».
- Code: only scenario documents can be imported (REST/CLI); grep «справочн|методич»: 0.
- Docs: SPEC §4 (scenario files only).
- Gap: no material entity, upload, storage or viewer.

### 7.7 Assessment

**F-19 — AI/ML-based assessment and teacher priority.**
IDs: REQ-2063, REQ-2091, REQ-2121 [не соблюдено]; REQ-2090, REQ-2102, REQ-4008, REQ-4028, REQ-4038,
REQ-4067, REQ-6015, REQ-6024, REQ-6043 [частично]. (REQ-4017 in F-06.)
- Requirement: ТЗ ¶67, ¶99, ¶100, ¶113, ¶137 (quoted in §4.5); brief «объективного контроля и оценки,
  на основе машинного обучения, действий, ошибок, знаний и навыков, обучаемых с выводом информации на
  рабочее место преподавателя и внешний монитор»; Q&A L420–429 «мы можем эту точность поднастроить…
  По умолчанию там все было указано… какие у нас веса стоят по умолчанию, но их можем менять»;
  L554–560 teacher priority over AI. Round 2, recording: REQ-4028/6015 and REQ-4038/6024 are the
  **mentor's**; mentor 63:21 (REQ-6043): «вы можете сгенерировать вопросы-ответы до того… модель[ка] уже
  потом будет это оценивать, исходя из предзаполненных некоторых критериев… А если она будет каждый раз
  индивидуально оценивать в моменте… скорее всего, не взлетит, и мы в тайминг в 30 секунд не попадём».
- Code: deterministic evaluators (`backend/app/domain/scoring/`); FACT_OBTAINED counts
  `FACTS_DELIVERED` events produced after the LLM interpreter reads the trainee's speech
  (`fact_obtained.py:1-30`); per-rule points/penalties in the scenario file; LLM explanation after
  scoring; no second-display feature (grep: 0).
- Docs: SPEC §2, §28, §29, §43; AUDIT §28.
- Gap: no ML/NN model evaluates actions or training effectiveness; no analysis across sessions; no
  external-monitor output; no teacher-override function (the AI issues no verdict).

**F-20 — Timing, regulations, grammar and address checks.**
IDs: REQ-2095, REQ-2120, REQ-2219, REQ-4030, REQ-4031, REQ-4032, REQ-4034, REQ-6017, REQ-6018 [частично]. (REQ-2263,
REQ-2276 in F-16/F-21.)
- Requirement: ТЗ ¶105 «Контроль выполнения рабочих функций операторов (соблюдение тайминга и
  регламента)»; ¶263 «Применять стандартные процедуры обработки вызовов»; Q&A L437–448 «эта проверка
  грамматики нужна только в момент оценки работы самого оператора… насколько критичны… опечатки в
  названиях улиц»; L449–461 «на улице есть Дубнинска, а есть Дубининская»; L466–496 «обязательные
  критерии должны быть, это временное исполнение карточки… чем меньше грамматических ошибок»; L522–524
  «может появиться новая карточка… проверять… чтобы особенно критических не было ошибок в адресах».
  Round 2, recording: the grammar remark (REQ-4030/6017) is the **mentor's**; the street-name case is
  the room's: «Был случай, когда высылка пошла [не туда]» (REQ-6018; round 1's «выставка пошла» was a
  mis-hearing); «Мы даём на откуп… это участникам» (room, REQ-6019, not «наоборот»).
- Code: DEADLINE and WORKFLOW_ACTION evaluators; state machine rejects invalid transitions (INV8);
  `card_house_correct` CARD_FIELD_CORRECT, `critical: true` (`v1.yaml:233-244`); 10 `EvaluatorType`
  values, none textual (`enums.py:243-256`); one incident per session.
- Docs: SPEC §7, §28. The archived operator manual (REQ-3011–3037) describes the real procedure; no
  product file references it.
- Gap: no grammar/spelling evaluator; the workflow is the scenario author's, not traced to the manual;
  the demo's address error is a house-number transposition, no street-name pair; no concurrent card.

### 7.8 Reporting and statistics

**F-21 — The lesson report.**
IDs: REQ-2276 [не соблюдено]; REQ-2220, REQ-2271, REQ-2274, REQ-2275, REQ-2289 [частично].
- Requirement: ТЗ ¶329/¶343 «Преподаватель формирует отчёт о практическом занятии с информацией о
  действиях, замечаниях (ошибках), времени заполнения карточки, отличия времени от нормативного
  (заданного в системе), а также грамматики»; ¶265 «(оценки, время реакции)».
- Code: report per COMPLETED session; an aborted session returns `409 REPORT_NOT_READY`
  (`test_a_report_for_an_aborted_session_is_refused`); `timing_metrics` = inference latencies
  (`timing_metrics.py:54-65`); answer→handoff time only in the DEADLINE evidence note «N мс при норме
  M мс» (`deadline.py:74-78`); no grammar data.
- Docs: SPEC §29; AUDIT §29; AUDIT §2 item 16 PARTIAL.
- Gap: report is per session (one incident), not per lesson; no card-filling-time field or computed
  deviation; no grammar; no reaction time; nothing for instructor-ended sessions.

**F-22 — Statistics, progress, leaderboard, charts, export.**
IDs: REQ-2122, REQ-2132, REQ-2133, REQ-4057 [не соблюдено]; REQ-2092, REQ-2189, REQ-2193, REQ-2194,
REQ-2195, REQ-2210, REQ-2221, REQ-2222 [частично].
- Requirement: ТЗ ¶138 «Ведение статистики по результатам обучения»; ¶101 «Вести учет результатов
  обучения и прогресса операторов»; ¶151 (optional) «графики, тепловые карты ошибок»; ¶152 (optional)
  «Экспорт отчетности… (Excel, PDF)»; ¶225 «Отслеживать прогресс обучения и историю успеваемости»;
  ¶231 «(автоматическая оценка И + экспертная оценка)»; ¶232, ¶233, ¶252, ¶266, ¶267; Q&A L783–785
  «преподаватель должен смотреть, кто в лидерах обучающихся, кто в двоечник и почему… фамилия
  обучаемого, номер рабочего места… количество… синтактических ошибок… в виде графиков, в виде
  таблиц».
- Code: no aggregate endpoint in `docs/hld/openapi.yaml` (54 operations); session list has no score;
  no chart, spreadsheet or PDF library in `frontend/package.json`; per-session LLM explanation;
  no expert-assessment input.
- Docs: SPEC §29 (per-session report).
- Gap: no cross-session statistics, progress, grade history, leaderboard, charts, heat maps, export,
  expert assessment or group insights; no workstation number.

### 7.9 Administrator role

**F-23 — Administrator functions run from the shell, not the application; no account administration.**
IDs: REQ-2163, REQ-2164, REQ-2165, REQ-2166, REQ-2171, REQ-2173, REQ-2174, REQ-2175, REQ-2176,
REQ-2178, REQ-2184 [не соблюдено]; REQ-2128, REQ-2129, REQ-2159, REQ-2160, REQ-2161, REQ-2162,
REQ-2167, REQ-2168, REQ-2169, REQ-2170, REQ-2172, REQ-2179, REQ-2180, REQ-2181, REQ-2182 [частично].
- Requirement: ТЗ «Роль: Администратор системы» ¶188–218, e.g. «Запускать и останавливать сервисы
  системы», «Выполнять обновление программного обеспечения (пакетное обновление)», «Проводить резервное
  копирование данных», «Создавать учетные записи пользователей всех категорий», «Назначать роли и права
  доступа», «Блокировать/разблокировать учетные записи», «Просматривать системные журналы»,
  «Анализировать статистику использования системы», «Отслеживать нагрузку на сервер», «Доступе к
  персональным данным пользователей без необходимости (соблюдение принципа минимальных привилегий)»;
  ¶146–147 integration with a local access-management system and local monitoring tools.
- Code: ADMIN-only operations are `clear-fatal` and `recordings/purge` (`admin.py:51-107`); accounts
  only from `python -m app.tools.seed_users` (three fixed accounts, `seed_users.py:49-70`);
  `is_active` honoured but not settable; no admin page in the frontend; start/stop/config via
  `make up/down`, `.env`, profile YAML; no log viewer; `gpu_memory_mb` always `None`; ADMIN reads every
  session incl. transcripts and recordings (`visibility.py:186-193`); ADMIN may start/abort sessions.
- Docs: `docs/RUNBOOK.md` «Start / stop», «Switching a model profile», «Purging recordings».
- Gap: no in-app start/stop, configuration, update, backup, account creation, role assignment,
  block/unblock, log view, usage statistics, error report or load view; no least-privilege limit for
  ADMIN; the ADMIN is not kept out of active sessions.

### 7.10 Security, reliability, audit

**F-24 — Transport encryption, authentication, protection.**
IDs: REQ-2125, REQ-2241 [не соблюдено]; REQ-2055, REQ-2085, REQ-2109, REQ-2123, REQ-2231, REQ-2240,
REQ-2243, REQ-4056 [частично].
- Requirement: ТЗ ¶142 «Защиту каналов передачи данных»; ¶293 «Шифрование всех передаваемых данных
  (TLS/SSL внутри контура)»; ¶140/¶292 «Многоуровневая аутентификация пользователей»; ¶295 «Защита от
  несанкционированного доступа»; ¶279 «Защиту персональных данных обучающегося»; Q&A L775–779
  «Многоуровневая аутентификация, значит, три уровня, администратор, преподаватель, обучаемый… каждым
  своими логинами и паролями, все. Больше ничего не нужно. Просто двухфакторка, да».
- Code: uvicorn HTTP (`backend/Dockerfile:60`), Vite dev server HTTP, LiveKit `ws://`
  (`.env.example:46`), PostgreSQL URL without sslmode; no TLS configuration in `infra/`; argon2
  password hashes, JWT; three account roles; redis published on host 16379 without `requirepass`;
  postgres on 15432 with default credentials unless `.env` changes them; no encryption at rest.
- Docs: SPEC §41; RUNBOOK.
- Gap: no TLS on any channel; one authentication factor (the organizer's «двухфакторка» is
  ambiguous, §8); unauthenticated redis port; no consent/personal-data document.

**F-25 — Backup, fault tolerance, recovery, monitoring.**
IDs: REQ-2126, REQ-2235 [не соблюдено]; REQ-2140, REQ-2143, REQ-2233, REQ-2236, REQ-2237, REQ-2238,
REQ-2253 [частично].
- Requirement: ТЗ ¶143/¶286 «Резервное копирование данных с периодичностью не реже 1 раза в сутки»;
  ¶287 «Отказоустойчивость компонентов при выходе из строя отдельных узлов»; ¶288 «Автоматическое
  восстановление сервисов после сбоев»; ¶289 monitoring; ¶308 «Инструменты диагностики проблем и
  система оповещения администратора об ошибках»; ¶162 «Работоспособность при кратковременных сбоях
  сети (до 30 секунд) с автоматическим восстановлением сессий без потери данных»; ¶166 buffering.
- Code: grep `backup|pg_dump|резерв`: none; `restart: unless-stopped` only on llama-server, backend,
  frontend, voice-agent, tts-qwen3 (not postgres, redis, livekit); backend re-adopts ACTIVE sessions
  on start (test passed); voice reconnect grace 30 s (`voice/config.py:116`) and WS resume
  (`ws-client.ts:8-15`) tested with fakes; FATAL latch needs ADMIN `clear-fatal`; readiness badge
  polled every 5 s; no host CPU/RAM/disk monitoring; no write buffering when PostgreSQL is down.
- Docs: SPEC §37–§39; RUNBOOK «Preflight», «A component is latched FATAL».
- Gap: no backup or restore; single instances; three services without restart policy; no push
  notification; database outages not covered.

**F-26 — Audit and security logs.**
IDs: REQ-2245 [не соблюдено]; REQ-2114, REQ-2180, REQ-2239, REQ-2244, REQ-2308 [частично].
- Requirement: ТЗ ¶128 «Ведение учета всех действий пользователей»; ¶296 «Аудит всех действий
  пользователей»; ¶297 «Хранение журналов безопасности не менее 6 месяцев»; ¶372 «JSON для логов и
  журналов».
- Code: immutable `session_events` with actor (append-only triggers, tests); login, `listUsers`,
  scenario import and report release write no event (`release_report.py:10-13` «It emits no event»);
  process logs plain text (`voice_agent/main.py:910`, `livekit.yaml` `json: false`); no retention
  setting.
- Docs: SPEC §8; AUDIT §8.
- Gap: actions outside a session are not audited; no security log; no 6-month retention; process
  logs not JSON.

### 7.11 Performance, scalability, hardware, platforms

**F-27 — GPU required; the organizer's minimum has no GPU.**
IDs: REQ-2054, REQ-2112, REQ-2152, REQ-4003 [не соблюдено]; REQ-2113 [частично]. Quotes in §4.7.
- Code: all profiles `backend/app/config/profiles/*.yaml` target NVIDIA (`gpu_name_contains`); LLM
  `device: cuda` even in `DEV_3060TI_SHARED`; preflight check #1 FAIL without CUDA.
- Docs: SPEC §26, §38; AUDIT §3 item 2 (FINAL profiles unmeasured).
- Gap: no CPU-only operation; no run on the ТЗ server minimum; PostgreSQL 16 does meet «PostgreSQL
  версии 12 и выше».

**F-28 — Scalability and concurrency.**
IDs: REQ-2056, REQ-2086, REQ-2111, REQ-2144, REQ-2145, REQ-2250, REQ-2251, REQ-4062, REQ-5903,
REQ-6040 [частично].
- Requirement: ТЗ ¶56/¶92/¶125 «Масштабируемость под различные группы пользователей»; ¶168/¶304
  vertical scaling; ¶169/¶305 horizontal scaling; Q&A L811–818 «если отваливается при 10
  одновременных, то это будет печально… в классе, 20-30 человек… оно нужно тоже работать» (recording:
  the **mentor**, 56:28, «99 вместо 100… закроем глаза», REQ-6040); chat 23.09.2026 13:48 (Str1fe, to the
  training-organisation question): «Да, все в классе», «форматы разные, в группах может быть разное
  количество участников» (REQ-5903, 5904); no repository document describes classroom use from several
  workstations.
- Code: MULTI_TRAINEE mode; single-host compose; one uvicorn process; runner lock/adoption across
  backend instances (test passed); `parallel_slots: 2` on DEV profiles; Qwen3-TTS serial.
- Docs: AUDIT §3 item 8 «Multi-session VRAM concurrency is untested»; `docs/benchmarks/vram.md`
  open TODO; `infra/livekit/livekit.yaml:8-9` «A multi-node deployment is not in scope».
- Gap: concurrency at 10–30 users unmeasured; no user-group concept; no multi-node deployment.

**F-29 — Operating systems.**
ID: REQ-2246 [частично].
- Requirement: ТЗ ¶299 «Операционные системы: Windows 10/11, Linux Ubuntu 20.04 и выше».
- Code: Linux containers; `Makefile` uses bash; llama-server `runtime: nvidia`.
- Docs: no Windows instructions; `docs/DOD_WALK.md` does not name the distribution.
- Gap: no Windows run or instructions; Ubuntu version not stated.

### 7.12 Integration

**F-30 — Integration with system-112 and "any other systems".**
IDs: REQ-2053 [не соблюдено]; REQ-2349, REQ-2359 [частично].
- Requirement: ТЗ ¶53 «Интеграцию с существующей инфраструктурой системы-112»; criteria ¶434/¶454
  «Возможность интеграции в любые другие системы». Q&A L538–543: «все локалка без интеграции»
  (REQ-4036).
- Code: REST/JSON API (`docs/hld/openapi.yaml`); `CallTransport` port; no XML, no SIP, no
  system-112 connector.
- Docs: SPEC §34, §41.
- Gap: no connector to system-112 infrastructure. The ТЗ's integration clause conflicts with its
  isolation clauses and the Q&A answer (REQ-2434, §8).

### 7.13 Data formats

**F-31 — Required file formats absent.**
IDs: REQ-2298, REQ-2299, REQ-2301, REQ-2302, REQ-2303, REQ-2305, REQ-2307, REQ-2309, REQ-2312,
REQ-2313, REQ-2314, REQ-2316, REQ-2318, REQ-2319, REQ-2321 [не соблюдено]; REQ-2308, REQ-2320
[частично].
- Requirement: ТЗ «Форматы данных» ¶358–392: «XML для хранения конфигурационных файлов»; «CSV для
  выгрузки отчетов и статистики»; «JSON для хранения профилей пользователей»; «XML для конфигураций
  рабочих мест»; «PDF для формирования сертификатов»; «XML для структурирования методических
  материалов»; «PDF для документации»; «XML для конфигурационных настроек»; «XML для совместимости с
  legacy-системами»; «CSV для статистической отчетности»; «PDF для формирования документов»; «MP3 для
  записи голосовых вызовов»; «PDF для официальных документов»; «DOCX для методических материалов»;
  «Поддержка сжатия данных»; «JSON для логов и журналов»; «Совместимость с основными СУБД».
- Code: configuration `.env` + YAML; CSV only in `benchmarks/_common.py`; relational user profile;
  WAV only; grep gzip/compress/zstd/brotli: none; PostgreSQL-specific schema.
- Docs: SPEC §30, §40; docs are Markdown only.
- Gap: no XML, report CSV, PDF, MP3, DOCX, compression; profiles relational; one DBMS.

### 7.14 UI

**F-32 — Mobile / adaptive interface.**
IDs: REQ-2135, REQ-2157, REQ-2342 [частично].
- Requirement: ТЗ ¶154 (optional) «Адаптивный веб-интерфейс: поддержка работы с мобильных устройств»;
  ¶185 «Адаптивность под различные устройства»; ¶422 «…как в десктопной, так и в мобильной версии».
- Code: viewport meta (`frontend/index.html:5`); `sm:`/`lg:grid-cols-*` breakpoints (single column
  below `lg`).
- Docs: no mention of mobile.
- Gap: no mobile test or run. (Optional vs mandatory wording: REQ-2433, §8.)

### 7.15 Deliverables and submission

**F-33 — Presentation, prototype link, screencast, repository access.**
IDs: REQ-1013, REQ-2338, REQ-2373, REQ-2374, REQ-4052, REQ-5004, REQ-5007, REQ-5008, REQ-5015–REQ-5031,
REQ-5930, REQ-5932, REQ-5933, REQ-5945, REQ-6034 [не соблюдено]; REQ-1015, REQ-2334, REQ-2372, REQ-4053,
REQ-5939, REQ-6035 [частично].
- Requirement: msg201 «Слайды с 7 по 11 являются строго обязательными и должны быть сохранены именно
  в том дизайне и структуре, в которых представлены в шаблоне»; ТЗ ¶414 «Презентация представляется в
  формате pptx или pdf»; ¶475–478 links to repository, presentation, «прототип для проверки
  выполненной работы», documentation; msg700 «Репозиторий — ссылка на публичный Git-репозиторий.
  Убедитесь, что репозиторий открыт для просмотра или предоставлен гостевой доступ. В корне
  обязательно добавьте README.md с инструкцией по локальному запуску… Прототип — ссылка на
  развернутый и работающий сервис… Если задача чисто алгоритмическая / бэкендовая, сюда можно
  прикрепить скринкаст»; Q&A L740–750 «записать видеопрезентацию вашего продукта… или просто запись с
  экрана… не более пяти минут… очень сильно рекомендую»; ТЗ ¶406 «открытый и не откомпилированный
  исходный код»; Q&A L752–757 «минимальные требования к самому пакету… в ТЗ указаны» (recording: the
  **mentor**, 50:14, REQ-6035; the ≤5-min video request is also the mentor's, 48:46, REQ-6034). Round 2:
  the template is archived — slide 3 labels slide 7 («Титульный слайд: название команды / название
  задачи / логотип / логотипы постановщика задачи») and slides 8–11 («описание сути и уникальности
  решения; план по дальнейшему развитию решения; ФИО и контактные данные всех участников; роли в
  команде; сложности и вызовы…») as «Обязательный блок» (REQ-5007, 5008, 5015–5031); channel post
  23.09.2026 18:20: «Презентацию сдают все команды, но формат зависит от требований вашего ТЗ»; «Если по
  ТЗ презентация требуется: Вы готовите полную презентацию проекта, в которую обязательно входят слайды
  7–11, а также описательная часть вашего решения»; «слайды с 7 по 11 должны быть сохранены строго в
  исходном дизайне и структуре. Менять сетку, расположение блоков или форматирование нельзя»;
  «Исключение — слайд 10 (состав команды)» (in the template the 5-card roster is slide 9); «30 сентября
  – 14 октября — Предварительная техническая экспертиза… код, репозитории, документацию и презентации»;
  «проверьте работоспособность ссылок на репозиторий, открытый доступ к материалам и корректность
  слайдов 7–11 заранее» (REQ-5930–5945).
- Code/repo: `git ls-files` outside `requirements/sources`: no .pptx/.pdf/video; the template is not
  archived; `README.md` at the root with local-run steps; `gh repo view` (2026-09-23):
  `"visibility":"PRIVATE"`; no LICENSE file; source is plain Python/TypeScript.
- Docs: SPEC is silent on submission.
- Gap: no presentation, no deployed-prototype link, no screencast/video; repository private (guest
  access not verifiable). The deadline (29.09.2026 23:59 MSK) had not passed on 2026-09-23.

**F-34 — Documentation deliverable.**
IDs: REQ-2252, REQ-2324, REQ-2325, REQ-2329, REQ-2375 [частично]; REQ-2353 [частично].
- Requirement: ТЗ ¶307 «Наличие документированных процедур установки, настройки и восстановления»;
  ¶396 «Все необходимые для использования решения методы должны быть доступны и подробно описаны, а
  также предоставлен перечень всех использованных библиотек и компонентов»; ¶400 «Обязательным
  условием является наличие сопроводительной документации»; ¶478 «Ссылка на сопроводительную
  документацию (.docx/.pdf)». msg700 accepts «…или файл в самом репозитории».
- Code/repo: `README.md`, `docs/RUNBOOK.md`, `docs/hld/*.md`, `docs/hld/openapi.yaml` (54 operations),
  `docs/AUDIT.md`, `docs/DOD_WALK.md`; dependencies only in manifests/lock files.
- Gap: Markdown in English only, no .docx/.pdf; no data-recovery procedure; no single list of
  libraries/components; no end-user guide for the instructor/trainee UI.

**F-35 — The build is not traced to the ТЗ.**
IDs: REQ-2130 [не соблюдено]; REQ-1010, REQ-1021, REQ-1022 [частично].
- Requirement: msg64 «Требования к итоговому проекту будут прописаны детально ТЗ»; msg625
  «Ориентируемся на ТЗ, как первоисточник»; msg637 «надо смотреть совокупность ТЗ и ответов на
  вопросы»; ТЗ ¶149 «Все обязательные функции должны быть реализованы в полном объеме.»
- Code/docs: `docs/AUDIT.md` traces SPEC §1–§47; grep «ТЗ» in AUDIT, HLD decisions, README: 0; the
  ТЗ-based matrices exist only under `requirements/traceability/` (created 2026-09-23).
- Gap: mandatory ТЗ items are `частично` or `не соблюдено` (this section); the build contract does
  not reference the ТЗ.

### 7.16 Evaluation criteria with no product counterpart

**F-36 — Forecasting, service «рекомендации» vs real ones, diagrams.**
IDs: REQ-2352, REQ-2361, REQ-2362, REQ-2363, REQ-2365, REQ-2369, REQ-2370 [не соблюдено]. (The ТЗ PDF
words REQ-2365's basis as «визуальной наглядности» instead of the docx's «визуальной восприимчивости»,
SRC-005 D15.)
- Requirement: ТЗ ¶439 «Проверка прогнозирования (оценка достоверности)»; ¶458 «Реализация
  прогнозирования и расчетов сравнением реальных значений»; ¶460 «Проверка рекомендаций сервиса и
  реальных рекомендаций в соответствии с реальными условиями»; ¶462 «Проверка объективности
  диаграмм…»; ¶468 «Соответствие прогнозов реальному поведению инфраструктуры»; ¶469.
- Code: no forecasting function; ETA module only (`backend/app/domain/world/eta.py`); no chart
  library; the only advice-type output is the LLM explanation.
- Docs: SPEC silent.
- Gap: absent. The ТЗ's requirement sections define no forecasting or calculation function
  (REQ-2435, §8).

### 7.17 The РТУ Т16Р IP phone

**F-37 — The datasheet's device functions have no counterpart.**
IDs: REQ-2416, REQ-2417, REQ-2418, REQ-2419, REQ-2420, REQ-2421, REQ-2423, REQ-2424, REQ-2427,
REQ-2428, REQ-2429, REQ-2430 [не соблюдено]; REQ-2415, REQ-2422, REQ-2425, REQ-2426 [частично].
- Requirement (datasheet): «РТУ Т16Р корпоративный IP телефон»; «Функциональный телефон РТУ Т16Р сделан
  для обработки большого количества вызовов»; «20 SIP линий»; «Нативная поддержка основных функций
  вызова…: перевод вызова, удержание, перехват, АОН, переадресация, многостороння конференция, «не
  беспокоить»»; «Функции вызова: Исходящие / Ответ / Отклонить; Включить / Выключить микрофон;
  Удержание вызова…». No source states why it was provided (REQ-2431); the ТЗ names no phone model.
- Code: browser widget with answer, hang-up, local mute, timer, level meter; RINGING offers only
  `answer` (`operator112.py:71`); display text constant «Входящий вызов 112» (`call_flow.py:86`);
  server-side VAD (`silero_vad.py`); HTTP; one call per session.
- Docs: SPEC §15.
- Gap: matches — IP-based telephony, answer, end, mute, VAD, HTTP. Absent — SIP lines, codecs
  configuration, reject, hold, transfer, conference, caller ID number, outgoing calls, keypad, DSS
  keys, phonebook, call log, video, network/provisioning features.

### 7.18 Round 2: the ДДС memo, the card stream, the tickets, the evaluation list

**F-38 — Cards as a concurrent stream; the 30-second acknowledgement and the 3-minute fill.**
IDs: REQ-5909, REQ-5910 [не соблюдено]; REQ-5254, REQ-5283, REQ-5298, REQ-6020, REQ-6021 [частично].
(Related round-1 items: REQ-2201, REQ-4033 in F-17; REQ-2287 in F-16; REQ-4034 in F-20.)
- Requirement: chat 23.09.2026 14:31 (Str1fe, to a participant asking «По одной… Потоком, как в
  реальной работе…?»): «Одновременно, как в текущей работе. В этом ещё доп мотивация - когда
  работаешь с карточкой, тайминг идёт и для этой работы и для тех карточек, что в очереди» (the
  participant's figures — one card per minute, at most three waiting, 30 s each — were not confirmed);
  ДДС memo p.5: «3. Диспетчер службы должен подтвердить получение сообщения… через 30 секунд после его
  направления в службу», p.21: without «Принята» in time the card gets «Не оповещено»; Q&A, recording:
  mentor reads the lifecycle question («Принято, не принято, начало реагирования, прибытие, проведение
  работ»), mentor tile 34:34 «Полностью моделирование полное должно быть», **room** 34:47–35:46: «в
  строке состояния сообщений оператор должен среагировать на неё в течение тридцати секунд. То есть это
  норматив, который определён… давайте установим в течение трёх минут»; 35:48–36:24 (REQ-6021, the
  passage round 1's transcript omitted): «Да, появится новая карточка, которая генерируется… Норматив
  по-прежнему работает. Многозадач[ность]… не на одну три минуты залипал…».
- Code: one incident per session (`uq_incidents_session`); one work item in the DDS console, no list,
  no queue, no timer in the DDS console; acknowledgement exists (RECEIVED→ACKNOWLEDGED «Принять к
  исполнению»); the only DEADLINE rule is 240 000 ms CALL_ANSWERED→HANDOFF_CREATED
  (`scenarios/examples/apartment-fire/v1.yaml:289-300`); the DEADLINE evaluator can time any event pair
  (`backend/app/domain/scoring/evaluators/deadline.py:23-35`); no «не принято» transition.
- Docs: SPEC §1 «A simulation is one persistent incident»; §11 «acknowledgment» without a time limit.
- Gap: no concurrent cards, no queued-card timers, no 30-s acknowledgement rule or display, no
  3-minute fill rule, no «Не оповещено» consequence, no decline.

**F-39 — ДДС response statuses and card statuses of the real system (memo «Работа на АРМ-112»).**
IDs: REQ-5260, REQ-5261, REQ-5262, REQ-5264, REQ-5265, REQ-5266, REQ-5275, REQ-5276, REQ-5279,
REQ-5280, REQ-5284, REQ-5289, REQ-5290, REQ-5294, REQ-5296, REQ-5297, REQ-5303, REQ-5307, REQ-5308,
REQ-5309, REQ-5310, REQ-5312, REQ-5313, REQ-5327, REQ-5328, REQ-5362 [не соблюдено]; REQ-2290,
REQ-5247, REQ-5248, REQ-5250, REQ-5253, REQ-5256, REQ-5257, REQ-5259, REQ-5270, REQ-5277, REQ-5278,
REQ-5281, REQ-5282, REQ-5285, REQ-5286, REQ-5287, REQ-5288, REQ-5292, REQ-5293, REQ-5295, REQ-5299,
REQ-5300, REQ-5301, REQ-5302, REQ-5305, REQ-5306, REQ-5311, REQ-5324, REQ-5361 [частично].
- Requirement: the ТЗ names the memo as primary data («Работа на АРМ-112. Памятка для
  дежурно-диспетчерских служб», REQ-2290); the memo (ГБУ «Система 112», Отдел контроля реагирования):
  response statuses «Добавлена», «Получена службой», «Принята», «Не принята», «Начало реагирования»,
  «Прибытие», «Проведение работ», «Работы завершены» («сохранение статуса закрывает карточку для
  редактирования»), «Отказ от выполнения работ» (comment mandatory); p.25 «Карандаш» opens the status
  dropdown; statuses only in sequence («Принята»/«Не принята» first); p.26 status must match reality and
  the specific service; card statuses p.27 «Зарегистрирована», «Отработана», «Проверена», «Не
  оповещено», «Отказ», «Не завершено» (48 h), «Завершена»; p.28 red cards routed to a control section;
  p.7–10 ЕКП routing and ВИС/ЭРА-ГЛОНАСС cards; p.14 «может добавить службу вручную. Удалить службу из
  списка оповещения он не может»; p.18 map; p.19 «Очень важно внимательно читать все поля карточки».
- Code: DDS stages RECEIVED «Получено» → ACKNOWLEDGED «Принято к исполнению» → resource selection →
  DISPATCHED «Силы направлены» → EN_ROUTE / ARRIVED / WORKING / RESOLVED set by SIMULATION → CLOSED by
  the trainee (`transitions.py:230-336`, `ru.ts:204-212`); status updates: 6 kinds with mandatory text,
  offered in every state, «moves nothing» (`send_status_update.py:1-14`); closure reasons
  RESOLVED/FALSE_CALL/TRANSFERRED/CANCELLED_BY_CALLER; one stage-wide work item for all recipient
  services; the operator trainee can deselect a service; no ЕКП, ВИС, map or control section.
- Docs: SPEC §7, §11 (generic «status changes»); no doc references the memo.
- Gap: equivalents exist under other names for acceptance, dispatch, arrival, works and completion,
  and the stage machine is sequential; absent are «Не принята», «Отказ от выполнения работ», the 103
  variant, per-service status blocks with time and history, the pencil control, the card statuses
  Проверена / Не оповещено / Отказ / Не завершено, red flags, refusal-legitimacy checks, automatic
  ЕКП routing, ВИС cards and markers, the map; deselecting a service is possible although the memo
  forbids removal.

**F-40 — Support contact, problem form, control-department procedures, violation examples.**
IDs: REQ-5268, REQ-5269, REQ-5314, REQ-5315, REQ-5316, REQ-5317, REQ-5319, REQ-5320, REQ-5321,
REQ-5322, REQ-5323, REQ-5329–REQ-5341 [не соблюдено].
- Requirement: memo p.11 contact of the support service (СТП) below «Войти»; «?» → «Сообщить о
  проблеме»; pp.28–31 examples of wrong statuses (road damage, lift entrapment, fire alarm, wasp nest,
  basement, attic, snow clearing) and missing/incomplete comments; p.32–34 what to do: wrong status →
  set the right one or phone the control department; changed situation → «Позвонить по номеру «112»,
  представиться (ФИО, должность, служба), назвать адрес… сообщить, что служба проводит работы по ранее
  направленной… карточке»; formal requests, outages, account requests via МосЭДО.
- Code: one login page with no contact; no problem-report function; no scenario or scoring rule with
  these violation cases; no DDS→112 call (the nearest is a status update of kind «Запрос
  дополнительных сил», which calls nobody); accounts only from `seed_users.py`.
- Docs: none. No organizer statement asks the simulator to reproduce the control-department
  procedures, and none excludes them (TRC-SRC-005).
- Gap: absent.

**F-41 — Incident list and search in the ДДС workstation.**
IDs: REQ-5271, REQ-5272, REQ-5343, REQ-5345, REQ-5347–REQ-5357 [не соблюдено]. (Round 1: REQ-3034,
REQ-3039 in F-11/F-13.)
- Requirement: memo p.11 main screen = list of cards received by the service, «Поиск происшествий»
  panel; pp.35–40 search by type/features, address (full or partial), округ, «название одного (!)
  района», descriptive address, region, service, description, channel, source, operator, status.
- Code: the DDS console shows one work item per session; no list, no search, no округ/район fields
  (`frontend/src/features/dds/console-page.tsx:162-177`; grep «search|поиск»: no hit).
- Docs: SPEC §11 names no list or search.
- Gap: absent.

**F-42 — The 96 ticket calls are not used as scenarios.**
IDs: REQ-1049, REQ-2292, REQ-5206, REQ-5209–REQ-5242 [не соблюдено]; REQ-5202, REQ-5203, REQ-5205,
REQ-4054, REQ-6036 [частично]. (REQ-5204 `соблюдено`, §6 S-16.)
- Requirement: ТЗ ¶349 primary data «Билеты и задачи»; the tickets file: 32 pages «БИЛЕТ N /
  Отработайте вызовы от заявителя», 3 calls each (situation, caller, phone, address; e.g. БИЛЕТ 1:
  «Возгорание мусорного контейнера…», «Дерутся 10-15 человек, 5 пострадавших…», «Ребенок 11 лет… упал с
  велосипеда…»); Q&A, recording: **mentor** 50:52 «основа для генерации новых, но можно использовать и
  эталонные»; **room** 51:11 «хотите — генерируйте новые, да, исходя из жизненного опыта… либо уже взять…
  которые наработаны нами в учебном процессе. Тут и то, и то приветствуется» (round 1's «основу от
  регенерации» was a mis-hearing).
- Code: `scenarios/examples/` holds one scenario (kitchen fire, Smolensk); none reproduces a ticket
  call (grep for ticket addresses: no hit); scenarios load only from YAML/JSON import; no generator.
  The scenario format has equivalents for a ticket's situation, caller and address, and separates
  world truth from the caller's belief (used for the floor in the shipped scenario).
- Docs: SPEC §4–§6 generic scenario format; no doc references the tickets.
- Gap: 0 of 96 ticket calls exist as scenarios; no grouping of three calls into a ticket; no second
  call in a session. The tickets contain caller names and phone numbers; whether they are synthetic is
  not determinable from the file (REQ-4048; the room said «они уже обезличены», REQ-6031).

**F-43 — The mentor's evaluation list and arbitrary scenarios.**
IDs: REQ-4027, REQ-4055, REQ-6014, REQ-6037 [частично].
- Requirement: **mentor** 28:14 (REQ-4027/6014): «похож интерфейс, не похож… Карточка заполняется…
  вопросы генерируются?… Похожи ли они на настоящие запросы?»; **mentor** 51:33 (REQ-4055/6037):
  experts «скорее всего, произвольный сценарий… будем оценивать… творческий подход… правильно
  генерирует… интерпретирует… подсвечивает правильные-неправильные истории»; reference tickets with
  correct answers may also be used.
- Code: interface resemblance — no (F-12); card filled — yes; caller speech generated from scenario
  facts — yes (`docs/DOD_WALK.md:124-128`); an arbitrary scenario can be added only as a YAML/JSON
  file via the INSTRUCTOR/ADMIN import API or CLI (`backend/app/api/routers/scenarios.py:115-164`), no
  UI; interpretation of operator speech and per-rule evidence exist; no ticket scenario (F-42).
- Docs: SPEC §4 (validation before start), §20, §29.
- Gap: no UI to add a scenario; resemblance to real requests and to the interface is not shown by the
  shipped content.

---

## 8. Ambiguities and open questions in the sources

Each entry quotes the wording and states the readings the wording allows; this report resolves none
of them. The last column records what round 2 found: where an archived document or the recording
settles an entry, it says so and why.

| # | IDs | Wording (verbatim) | Reading 1 | Reading 2 | Round 2 (2026-09-23) |
|---|---|---|---|---|---|
| 8.1 | REQ-2123, REQ-2240, REQ-4056 | ТЗ ¶140 «Многоуровневую систему аутентификации пользователей»; Q&A L775–779 «три уровня, администратор, преподаватель, обучаемый… каждым своими логинами и паролями, все. Больше ничего не нужно. Просто двухфакторка, да. То есть никаких там многоуровневых. Заморочек ничего не нужно, да.» | Three role levels with own login/password are the whole requirement | Two-factor authentication is expected («двухфакторка») | Open. Recording: «Просто двухфакторка, да…» sits on the mentor's tile (52:47–52:53), with the room partly highlighted; the room's list of three levels is 52:35–52:47. |
| 8.2 | REQ-2432 (REQ-2100, 2044, 2118, 2249, 2139) | ¶111 «через виртуальную IP-телефонию или текстовые сообщения» vs ¶134 «через виртуальную IP-телефонию (VoIP)» and ¶302 «через локальный SIP-сервер» | Text messages are an accepted alternative channel | IP telephony (via a local SIP server) is required | Open. The ТЗ PDF keeps ¶111's «или текстовые сообщения» (SRC-005 D5). |
| 8.3 | REQ-2433 (REQ-2135, 2157, 2342) | ¶154 under «Рекомендуется реализовать»: «Адаптивный веб-интерфейс: поддержка работы с мобильных устройств» vs ¶422 «Решение должно быть доступно и удобно… как в десктопной, так и в мобильной версии» | Mobile support is optional | Mobile support is mandatory | Open; the PDF wording is the same. |
| 8.4 | REQ-2434 (REQ-2053, 2127, 2082, 2106, 2136, 2349, 2359); Q&A REQ-4035, REQ-4036 | ¶53 «Интеграцию с существующей инфраструктурой системы-112» vs ¶88 «без доступа к внешним сетям», ¶119 «Содержать функционал основной системы-112 (только имитация)» (under «НЕ должен»), ¶155 «без взаимодействия с внешними системами»; Q&A: integration «с форматами данных и визуальными стандартами» means «Те поля, которые там отображаются» (L530–536) and «все локалка без интеграции» (L538–543) | "Integration" means reproducing the fields/formats of system-112 inside an isolated product | A connection to the existing system-112 infrastructure is expected | Open. Recording confirms the room's «всё локально без интеграции» (37:19, REQ-6022). Chat 23.09: internal API «без взаимодействия с внешними системами», the demo may use an external model, the solution must allow a configurable local endpoint (REQ-5912–5927). |
| 8.5 | REQ-2435 (REQ-2351, 2352, 2361–2363, 2365, 2369, 2370); chat REQ-1033 | Criteria ¶458 «Реализация прогнозирования и расчетов сравнением реальных значений», ¶468 «Соответствие прогнозов реальному поведению инфраструктуры»; msg643 «Критерии стандартные и указаны в из» (text ends there) | The criteria are generic ЛЦТ criteria not specific to task 9 | Task 9 is expected to contain forecasting/calculation functions; the ТЗ requirement sections define none | Open. The PDF rewords the diagram criterion to «визуальной наглядности» (D15). The room at 45:23 asks back «что конкретно означает требование прогнозирования?». |
| 8.6 | REQ-2436 (REQ-2002, 2005, 2268, 2269, 2217); chat REQ-1027–1030 | Title «подготовки оператора ДДС»; ¶326 «Система имитирует звонок участника событий»; ¶327 «Обучающиеся заполняют карточки событий (имитация интерфейса системы АРМ-112)»; msg624 «это разные службы, но в контексте имитации обучения - да… две мини роли» | The trainee who takes the call and fills the card is the 112 operator | The trainee is the ДДС operator throughout | Open. Memo: ДДС on АРМ-112 read cards routed to them and set response statuses; cards are filled by the specialist-112 (pp.8, 14, 21–25). ТЗ PDF: «Заполнение Обучающимся карточки событий» (singular, D9). No organizer statement names the trainee's role. |
| 8.7 | REQ-1028, REQ-1029 | msg638 «Вот как распределяются задачи согласно обсуждению телефонии, но не всего ТЗ. - Роль «Оператор 112» (Точка А): Система «поставляет» обучаемому уже заполненную карточку.»; msg642 «Оператор должен заполнить карточку исходя из вводной информации (если он получил инфо голосовое)» | At the 112 stage the system provides a filled card | At the 112 stage the operator fills the card from (voice) input; msg638 covers only the telephony topic | The 23.09 «Ответ заказчика» describes the ДДС: receive, accept (reject with comment per the confirmed definition), select statuses with comments, no fill-in check, phone the claimant, contact the brigade (§9.3). msg638's «Точка А» sentence is not repeated. |
| 8.8 | REQ-1041, REQ-1040, REQ-1043 (participants) | msg703 (22.09.2026 22:29, last message): «полномочия и алгоритм действий диспетчера ДДС, к сожалению, до сих пор не разъяснены»; msg702 training organisation; msg650 ДДС access to call audio | — | No organizer answer exists in the export (it ends at msg703) | Answered 23.09.2026: REQ-1040 at 13:48 («Да, все в классе»; group sizes vary); REQ-1041 at 15:46 («Да. Соответствует» with exceptions, §9.3). REQ-1043 Q1 (ДДС access to the call audio) is still unanswered (REQ-5360). |
| 8.9 | REQ-2437 | msg637 «Все ответы на вопросы в списке вопросов и ответов + ТЗ»; the only archived «Ответы на вопросы.pdf» is a generic ЛЦТ FAQ of 29.06.2026 | The "list" is the chat and the Q&A session | The "list" is a document not in the archive | Open. |
| 8.10 | REQ-2431 | Datasheet posted without caption (msg482); msg485 «многие просили, многие ждали и теперь направляю вам» | The phone model is to be imitated | Background material only; the ТЗ names no phone model (¶176 «IP-телефон с гарнитурой») | Open. The recording adds: the VoIP-documentation question («версия SIP, топология сети, модели АТС») was answered «тогда документы мы предоставим» (mentor tile) and sheet D3 «предоставим локи» (REQ-6006). |
| 8.11 | REQ-2193 | ¶231 «Просматривать результаты выполнения заданий (автоматическая оценка И + экспертная оценка)» | «И» = "and" (automatic and expert assessment) | «И» = "ИИ" (AI assessment + expert assessment) | **Resolved by the ТЗ PDF**: «автоматическая оценка ИИ + экспертная оценка» (D6). |
| 8.12 | REQ-2259 | ¶316 «…только профильные события (например? Мосводоканал, Москоллектор, Управы, службы газа и пр.)» | The services are examples of trainee profiles | The question mark marks the list as uncertain | **Resolved by the ТЗ PDF**: «(например, от Мосводоканала, Москоллектора, управ, служб газа и пр.)» (D7). |
| 8.13 | REQ-1030 | msg628 «Заполняет поле "Добавить тип происшествия" и появляющуюся ниже карту» | «карту» = map | «карту» = опросная карта (questionnaire card) | Open. |
| 8.14 | REQ-1045 | msg680 «Карточка и реестр обращений 100% должны быть похожи» | «реестр обращений» = the ДДС incident list («Поиск/Список происшествий» in the screenshots) | A register screen not shown in the archived files (the term does not occur in their text) | Open. The memo (p.11) calls the ДДС main screen a list of received cards with «Поиск происшествий»; «реестр» does not occur in the memo or the ТЗ PDF (pdftotext + grep). |
| 8.15 | REQ-4005, REQ-4007, REQ-4010 | L149–150 «Обязательно не на защите демонстрируйте реальные сим-вызовы через локальные сим-всервера и недопустимо программная эмуляция» followed by «…реальных вызовов не будет, и только симуляция»; «с несоединительной генерацией»; «чтобы меньше было инвестиционации» | Transcription artefacts; the resolved answer is "simulation only" | The first sentence states a requirement for real calls | **Resolved by the recording**: the first sentence is sheet question C3 read aloud by the mentor («…или допустима программная эмуляция?»); answers: mentor «симуляция вполне достаточно», room «только симуляция» (REQ-6005). «несоединительной генерацией» = «самостоятельную генерацию» (REQ-6007); «инвестиционации» = «галлюцинаций» (REQ-6009). |
| 8.16 | REQ-4009, REQ-4062, REQ-4053, REQ-4089 | «как раз было в ФТЗ указано… преподаватель является… фактическим подтверждающим те или иные итоги» | «ФТЗ» = the archived ТЗ docx (which has ¶315 teacher confirmation of reference answers) | Another document | **Resolved by the recording**: the mentor says «в ТЗ» (REQ-6008). |
| 8.17 | REQ-4054, REQ-1049, REQ-2292 | «что предоставляет собой 96 билетов?… основу от регенерации новых, но можно использовать эти эталонные» (the number is in the question only); ТЗ ¶349 «Билеты и задачи» | The tickets are in the «Датасет» link (participant msg655–656 «это в датасете всё есть») | — (not in the archive either way) | Tickets now archived: 32 «БИЛЕТ» pages × 3 = 96 call rows (extractor's count; no organizer statement equates «96» with these rows). Recording: «основа для генерации новых» (mentor), confirmed by the room (REQ-6036). |
| 8.18 | REQ-3049 | File name «…_искл_пожар_задымление.xlsx»; the file contains the full fire/smoke category (271 rows) | «искл» = excluding | «искл» = extract / other tag | Open; the v_046_24 diff does not resolve it (REQ-5721). |
| 8.19 | REQ-3037 | Manual hotkey table: «Alt+O» listed for «к блоку описания» (create mode) and «к блоку отработок» (view mode) | Mode-dependent key | Documentation clash | Open. |
| 8.20 | REQ-4001, REQ-4093 | Q&A L11–12 «…чрезвычайным ситуациям и природной безопасности» vs video/chat «пожарной безопасности» | Transcription error | — | **Resolved by the recording**: «пожарной безопасности» (REQ-6001). |
| 8.21 | REQ-1035 | msg684 answers «1.1. Да. 1.2… 1.5. Нет, только оператор ДДС 2. Да, но только по обычному айпи телефону» | — | The numbered questions are not in the chat; 1.1, 1.4, 1.5 and 2 cannot be matched to questions | Open. |
| 8.22 | REQ-2374 vs REQ-2082/2104 | ТЗ ¶477 «Ссылка на прототип для проверки выполненной работы»; msg700 «ссылка на развернутый и работающий сервис… Если задача чисто алгоритмическая / бэкендовая… скринкаст» vs ¶88 «без доступа к внешним сетям» | A deployed, reachable prototype is expected | A screencast suffices for an isolated product | Open. Chat 23.09 18:20: the preliminary review uses «код, репозитории, документацию и презентации»; 14:41/15:58: the demo may use an external model. |
| 8.23 | REQ-6030 | Mentor 43:20 «Да. Ну, если коллеги сделают, будет здорово», right after the room's «Точку А мы пока исключаем. Заявителя… и 112 мы пока убираем»; both tiles 43:22 «шикарно будет… на будущее задел будет» | «сделают» refers to point A (the caller) | «сделают» refers to the B↔C dialogue | New in round 2; the recording does not settle it. |
| 8.24 | REQ-5907, REQ-5919, REQ-5920 | Question (participant, 23.09 14:09): «когда перезванивает служба 103, называют ли они, по какой карточке…»; «Ответ заказчика» 15:46: «Как правило диспетчер ДДС номер карточки при дозвоне заявителю номер карты не называют…» | The answer describes the ДДС calling the claimant | The answer is meant for the 103 call-back asked about | New; as printed, the answer and the question concern different calls. |
| 8.25 | REQ-5934, REQ-5024 | Channel 23.09 18:20: «Исключение — слайд 10 (состав команды)»; the template's 5-card roster is on slide 9, slide 10 holds blocks 01/02/03 (python-pptx) | The exception applies to slide 9 (the roster) | The exception applies to slide 10 as numbered | New. |
| 8.26 | REQ-5720 | File name «…_корректировка_МВД_+_Департамент (1).xlsx»; 90 of 94 changed rows are МВД; no «Департамент*» column changed | «Департамент» names a department whose columns changed elsewhere | The name refers to something not visible in the rows | New. |
| 8.27 | REQ-5001–5003; ТЗ docx | docx file name «финал_01092026», posted 18.09 (msg587); PDF metadata 11.09.2026, linked 15.09 (msg201) | The PDF is the later text | The docx is the later text | New; the archive does not settle it. The requirement content is the same except 18 logged wording/format differences. |
| 8.28 | REQ-6004, 6007, 6035, 6044 and §9.1 row 7 | Audio not settled: «на CPU / на ГПУ» (08:53; the screen says CPU), «надо всё искусствовать / использовать» (13:00), «минимальная потребность / по требованиям» (40:22), «[О] нет, да?» (50:18), «до обучения / дообучение» (62:44) | — | — | New; each reading is given in `requirements/evidence/qna-transcripts-comparison.md` §8. |
| 8.29 | REQ-5911, REQ-5929 | Str1fe 23.09 14:41: «Уточню у заказчика, смогут ли они оперативно раздобыть данные машины для докалки»; participants (17:24): «говорили, что могут… какую - не сказали» | The customer will provide GPU machines | No GPU machines will be provided | New; no answer in the sources. |
| 8.30 | REQ-5928 | Participant 23.09 17:09: «будут ли запускаться системы командой экспертов, будет ли оцениваться качество работы, скорость работы на указанном в ТЗ железе» | — | — | New; unanswered in SRC-006. |
| 8.31 | REQ-6036, REQ-4054 | Room 51:11: «хотите — генерируйте новые, да, исходя из жизненного опыта… либо уже взять… наработаны нами» | «генерируйте» includes hand-authored new scenarios | «генерируйте» means automatic generation | New (TRC-SRC-007 note). |

---

## 9. Conflicts between sources and changes over time

Rewritten in round 2. Every Q&A statement below is taken from the recording-verified text
(`requirements/evidence/qna-transcripts-comparison.md` §4, §7; `requirements/normalized/SRC-007-qna-gigaam.md`)
with its time in the recording (mm:ss from the start) and the speaker shown by the video: **mentor** =
Станислав Галаган (tiles «Станислав Галаган» / «Станислав»); **room** = the customer's representatives'
tile «Александр Ш.» (four men, which of them speaks is not visible); **host** = «Михей Модератор». Where
the recording corrected round 1's wording or speaker, the row says "Corrected:". The session date
16.09.2026 comes from the chat (§1.3). None of the statements is resolved against another.

### 9.1 The caller-side AI voice — all dated organizer statements, in date order

| # | Date / time | Source, speaker | Verbatim (verified) | English |
|---|---|---|---|---|
| 1 | 06.08.2026 19:05 | chat msg34, channel account (task announcement, REQ-4075) | «Сервис должен с помощью искусственного интеллекта генерировать реалистичные сообщения о происшествиях, моделировать различные сценарии и помогать оценивать, насколько правильно специалист реагирует на ситуацию.» | The service must use AI to generate realistic incident messages, model scenarios and help assess the specialist's response. |
| 2 | 06.08.2026 (posted with msg34) | `IMG_2549.MP4` 80–100 s, Ащаулов В.К. (REQ-4081) | «…разработать учебный симулятор… который с помощью искусственного интеллекта генерировал бы сообщения о происшествиях.» | …a simulator that would generate incident messages with AI. |
| 3 | undated | `brief-from-user.md` «Описание задачи» (REQ-4069) | «-эмуляции вызов на гарнитуру IP телефона оператора 112 с использованием искусственного интеллекта» | Emulation of calls to the 112 operator's IP-phone headset using AI. |
| 4 | 01.09.2026 (docx file name); PDF metadata 11.09.2026; linked 15.09, docx posted 18.09 | ТЗ ¶326, scenario «…на АРМ-112 (карточки)» (REQ-2268) | docx: «Система имитирует звонок участника событий»; PDF: «Имитация системой звонка участника событий.» | The system imitates a call from a participant of the events (same meaning in both formats, SRC-005 D8). |
| 5 | same | ТЗ ¶111 (REQ-2100), ¶42 (REQ-2044), ¶260 (REQ-2216), ¶313 (REQ-2256) | «Обеспечить имитацию входящих вызовов (через виртуальную IP-телефонию или текстовые сообщения)»; «Система эмуляции вызовов с использованием IP-телефонии и технологий VoIP»; «Принимать входящие вызовы/сообщения в режиме обучения»; «настройка нейросети на генерацию конкретных типов происшествий» | No ТЗ clause says the caller's words or voice are AI-generated; both formats keep «или текстовые сообщения». |
| 6 | 16.09.2026, 21:41–22:54 | Q&A, **room** (REQ-4017; speaker confirmed) | «Соответственно, на первом этапе, вот на данном этапе хакатона, вот всего вот этого, мы 112 убираем, убираем и заменяем вот этот элемент 112, заменяем преподавателем и искусственным интеллектом. То есть забиваем туда шаблоны какие-то… либо даёт команду аппаратной части на генерацию сообщений, либо пересылку на рабочие места обучаемых… И вторая часть наиболее сложная — это чтобы искусственный интеллект или машина оценивала, да, действия обучаемых.» | At this stage "112" is removed and replaced by the teacher and AI (templates, message generation); the hardest part is AI evaluating the trainees. |
| 7 | 16.09.2026, 24:16–24:34 | Q&A, **mentor** (REQ-6010; round 1 attributed REQ-4020 to the customer) | «То есть у нас, допустим, есть история о том, что генерируется звонок якобы голосовой о каком-то событии. Дальше, соответственно, человек заносит в карточку сведения, которые должны в итоге система проверить…» | A supposedly voiced call about an event is generated; the person enters the information into the card, which the system checks. |
| 8 | 16.09.2026, 38:54–39:09 | Q&A, mentor reads sheet row 10 (participant question, context) | «Кто должен озвучивать заявителя в учебном вызове: ИИ, преподаватель или заранее подготовленная запись? Требуется ли интерактив[ный]…» | Corrected: round 1 read «и преподаватель»; the recording and the sheet say «ИИ, преподаватель». |
| 9 | 16.09.2026, 39:07–40:08 | Q&A, **room** (REQ-4040; confirmed) | «Значит, на этапе разработки программного обеспечения, значит, заявителя мы исключаем, то есть никаких заранее подготовленных записей, голосов нет… Это карточка, и дальше IP-телефония… набирает там мышкой кнопки какие-то, какой-то номер… и ему в ответ уже слышно: «Слушаю вас». Вот, оператор что-то произносит, ну и достаточно хотя бы на конкурсной основе говорить: «Я вас понял, информация принята». Всё, на этом закончено.» | The caller is excluded at this stage: no recordings, no voices. Card, then IP telephony: dial a number, hear «Слушаю вас», speak, «Я вас понял, информация принята» is enough. |
| 10 | 16.09.2026, 40:05–40:42 | Q&A, **room** (REQ-4041, REQ-4042; 40:19–40:27 both tiles) | «В зависимости от категории, там женские голоса, мужской голос должен быть… кому она там звонит… обратная сторона… должна… быть не со стороны заявителя об опасности, а мы делаем наоборот, когда оператор ДДС информирует уже руководящий состав о той информации, которую он получил. Вот здесь как бы поиграться с IP-телефонией будет достаточно очень интересно.» | Voices by category of the person called; the other side is not the caller but the leadership the ДДС operator informs. |
| 11 | 16.09.2026, 40:42–40:58 | Q&A, **mentor** (REQ-6026) — Corrected: round 1 attributed this to the customer | «А если, соответственно, вы сделаете генерацию всех историй там, например, входящими звонками тоже голосовыми, да… как будто человек там звонит, говорит: «Я попал в ДТП и прочее», это будет… Ну, это будет дополнительная история, это будет хорошо оценено тоже.» | If you generate the stories as voiced incoming calls too, that is an additional feature and will be well assessed too. |
| 12 | 16.09.2026, 40:58–41:49 | Q&A, **room** (REQ-6027; round-1 REQ-4043's customer part) | «Ну, хорошо. Нет, дело в том, что реально… давайте мы, если на следующий год вот эту идею пусть они проработают, потому что вот мы первый раз… участвуем… мы взяли маленькую задачку… А в будущем… это предусматривает уже работа именно системы 112. И вот здесь как раз вот генерация голоса, происшествия, какого-то заявления, она будет очень нам интересна. Поэтому вопрос остаётся на, скажем так, мы сделаем, снимаем как бы этот вопрос. Но он будет возник[ать] как раз именно в следующем конкурсе… соответственно, он там должен быть реализован, этот момент.» | Let that idea be worked on next year; voice generation of a report will be very interesting then; the question is removed for now and will arise in the next competition. No sentence prohibits it. |
| 13 | 16.09.2026, 41:49–42:06 | Q&A, **mentor** (REQ-6028 first part) — Corrected: round 1 attributed «достаточно прослушанных сообщений» to the customer | «…требуется ли интерактивный двусторонний голосовой диалог с ответами на уточняющие вопросы и ветвлением сценария или достаточно прослушивания сообщений? Ну, как вы уже сказали, да, достаточно, в принципе, прослушанных сообщений. То есть это для минимального объёма более чем достаточно.» | Listening to messages is enough for the minimum. |
| 14 | 16.09.2026, 42:06–42:28 | Q&A, **room** (REQ-6028; round-1 REQ-4044) | «Не-не, требуется ли … двусторонний голосовой [диалог]? Нет, пока. Давайте мы здесь вообще снимем, то есть никаких голосовых диалогов, ну, реально они не ведут. То есть голосовой диалог только, скажем так, ДДС — руководитель, которому они будут звонить. Вот и всё. Вот здесь вот можно как-то пообщаться интерактивно.» | No two-way voice dialogue for now; the only voice dialogue is ДДС ↔ the head they call; there it can be interactive. |
| 15 | 16.09.2026, 42:28–43:19 | Q&A, **room** (REQ-6029; round-1 REQ-4045) | «…есть точка А, генерация вызова, это работа 112 и вместе с тем, кто оказался в беде. Дальше информация уходит в точку Б… и точка С… Так вот здесь… нас интересует диалог между Б и С. Вот здесь, когда будут звониться по вот этому симулятору IP-телефонии. Понятно? Точку А мы пока исключаем. Заявителя. Заявителя, да, и 112 мы пока убираем.» | Point A (call generation, 112 + person in distress) is excluded for now; the B↔C dialogue over the IP-telephony simulator is of interest. |
| 16 | 16.09.2026, 43:19–43:29 | Q&A, **mentor** 43:20–43:22, then both tiles (REQ-6030) — Corrected: round 1 attributed both to the customer | mentor: «Да. Ну, если коллеги сделают, будет здорово.»; both tiles (not settled): «Да, это будет здорово. Да, это, конечно, шикарно будет… на будущее задел будет.» | "If the colleagues do it, great" — whether «сделают» means point A or B↔C is not settled (§8.23). |
| 17 | 16.09.2026, 63:21–64:29 | Q&A, **mentor** (REQ-6043) | «…вы можете сгенерировать вопросы-ответы до того… А если она будет каждый раз индивидуально оценивать в моменте… скорее всего, не взлетит, и мы в тайминг в 30 секунд не попадём… Если коллеги их обойдут… и смогут пробить каналы там с локального сервера вовне, это будет хорошо.» | On evaluation load, not the caller voice; listed because round 1 put it into this sequence. |
| 18 | 16.09.2026, 64:30–65:10 | Q&A, participant «Вадим Золотарев» asks; **mentor** answers (REQ-6046) — Corrected: round 1 did not identify the speakers | participant: «…наши коллеги… которые под аккаунтом Александр Ш. сидят, опровергли. То есть телефония должна генерироваться автоматически… у неё есть тема… наша модель должна подстраиваться под диалог»; mentor: «Мы пояснили. То есть коллеги как раз сказали, что нет, не надо, потому что это сложно, и это будет, скорее всего, на втором-третьем этапе там, и может быть, там в следующем.» | Automatically generated, dialogue-adapting telephony: "no, not needed, it is complex; probably at the second or third stage, maybe the next one". |
| 19 | 18.09.2026 11:22:03 | chat msg570, Str1fe «Ответ:» (REQ-1024) | «Конкретно звонок участника событий мы исключаем. Мы генерируем сообщение которое формируется карточкой системы 112 и направляется в конкретную службу ДДС исходя из сценария происшествия и алгоритмов подключаемых служб на это происшествие согласно ЕКП. То есть имитировать голос живого человека оказавшегося на происшествии или попавшего в беду не надо» | The event participant's call is excluded; a card-generated message goes to a specific ДДС per ЕКП; imitating a live person's voice is not needed. |
| 20 | 18.09.2026 11:30:05 | msg576, Str1fe (REQ-1025) | «Только имитация звонков в базе. Если сделают виртуальную телефонию с реальным звонком - это будет круто, но для mvp достаточно имитации» | Only simulated calls in the database; real virtual telephony would be great; simulation is enough for the MVP. |
| 21 | 18.09.2026 11:30:16 | msg577, Str1fe (REQ-1020), after participant msg571 «Классно тз поменялось» | «тз не менялось, оно одно» | The ТЗ has not changed. (Participant msg578–579, 11:31: «этот ответ буквально противоречит одному из сценариев использования из тз».) |
| 22 | 18.09.2026 11:52:49 | msg624, Str1fe (REQ-1026, REQ-1027) | «Один интерфейс, одна учетка, две мини роли - либо пользователь заносит данные от потерпевшего (которые или генерируются ИИ текстом или, если получится, генерируются голосом якобы от телефонии), либо пользователь передает карточку в ДДС и там её уже принимают и распределяют далее.» | Two mini-roles: enter the victim's data (AI-generated text or, if feasible, voice "from telephony"), or pass the card to ДДС. |
| 23 | 18.09.2026 11:53:04 | msg625, Str1fe (REQ-1021) | «По поводу противоречий в ТЗ - Заказчик впервые участвует в ЛЦТ и впервые взаимодействует с живыми командами. Ориентируемся на ТЗ, как первоисточник» | On contradictions: the ТЗ is the primary source. |
| 24 | 18.09.2026 16:37:06 | msg638, Str1fe (REQ-1028) | «Вот как распределяются задачи согласно обсуждению телефонии, но не всего ТЗ. - Роль «Оператор 112» (Точка А): Система «поставляет» обучаемому уже заполненную карточку…» | Per the telephony discussion: at point A the system supplies an already-filled card. |
| 25 | 18.09.2026 20:19:10 | msg642, Str1fe (REQ-1031, REQ-1032) | «Оператор должен заполнить карточку исходя из вводной информации (если он получил инфо голосовое) и проверяется соответствие того, что было сообщено голосом с тем, что он заполнил в карточке, какие службы выбрал.» | The operator fills the card from the input (if received by voice); voice vs card and services are checked. |
| 26 | 19.09–23.09.2026 | chat to 23.09 18:20 (SRC-001 to msg703, SRC-006) | No further organizer message addresses the caller voice. The 23.09 answers concern the ДДС (§9.2–§9.3) and the AI endpoint (§9.8). | — |

**What the product implements for each leg (facts):**

| Leg | Product state | Evidence |
|---|---|---|
| Caller → 112 operator, AI voice («точка А») | Built and walked on the real stack | SPEC §1, §15–§25; `docs/AUDIT.md` §15–§25 IMPLEMENTED/PARTIAL; §2 items 2–3 PASS (Qwen3-TTS «Serena»); `workers/voice_agent/`, `backend/app/application/dialogue/` |
| Caller data as AI-generated text (msg624 alternative) | Absent; the caller is voice only and the trainee's transcript view withholds caller text | `docs/DOD_WALK.md:117-119, 175` |
| System supplies an already-filled card at the 112 stage (msg638) | Absent at the 112 stage (empty card, manual entry). A system card (`prefab_handoff`) exists for a DDS-only role chain; tested; no shipped scenario uses it | `backend/app/application/handoff/prefab_handoff.py`; `backend/tests/api/modes/test_single_role_dds_prefab.py` (passed); `v1.yaml:16` |
| Card → ДДС (point B) | Built | `backend/app/application/handoff/create_handoff.py`; AUDIT §2 items 8–10 PASS |
| ДДС → service head, voice / IP telephony (B↔C) | Absent; DDS has a scenario radio log and REST status forms only | grep voice/phone in DDS code: no functional hit; TRC-SRC-007 REQ-6028/6029; TRC-SRC-002-003-video REQ-4042 |
| Scripted exchange «слушаю вас» / «я вас понял, информация принята» after dialling a number | Absent; no dial pad, no outgoing call | `frontend/src/features/operator/phone-widget.tsx` (answer, hang-up, mute only); RINGING offers only `answer` (`operator112.py:71`) |

What the recording changed in this sequence: the two statements that welcome voiced incoming calls
(rows 11 and 16) and the "listening is enough" line (row 13) and the closing "нет, не надо" (row 18)
are the **mentor's**, not the customer room's; the room's own statements (rows 6, 9, 10, 12, 14, 15)
exclude the caller at this stage, name ДДС → руководитель as the only voice dialogue, and defer caller
voice generation «в следующем конкурсе» without a prohibiting sentence. REQ-4043 is therefore
`не обработано` (§1.7); REQ-4040/4044/4045/6028/6029 stay `не соблюдено`.

### 9.2 Does the ДДС check the card's correctness? — a dated reversal

| Date / time | Source, speaker | Verbatim | English |
|---|---|---|---|
| 18.09.2026 12:11 | msg628, participant Mathew (context) | «2. Оператор ДДС, который: … б) Принимает либо отклоняет её в) В случае принятия проверяет корректность заполненных данных …» | ДДС: accept or reject; if accepted, check the data. |
| 18.09.2026 16:23 | msg635, Str1fe (REQ-1029) | «1. Да, в том числе 2. Да, в том числе …» | Confirms both lists "among other things". |
| 18.09.2026 16:37 | msg638, Str1fe (REQ-1028) | «Роль «Диспетчер ДДС» (Точка B). Его задачи … 2 - Проверка/Валидация: Проверяет корректность данных в карточке (потому что «оператор 112» мог допустить ошибки, например, в адресе, и диспетчер должен это заметить)» | The ДДС checks the card's data (e.g. an address error by the 112 operator). |
| 16.09.2026 (earlier, Q&A) | room 35:46–36:24 (REQ-6021) | «мы их должны проверять именно с точки зрения того, чтобы особенно критических не было ошибок в адресах» | Said of new cards generally; the speaker's subject («мы») is not a role. |
| 22.09.2026 22:29 | participant Mathew (REQ-5901 = REQ-1041) | «3) После принятия карты: a. Просмотреть содержимое на ошибки (грамматические, заполнение блока "Адрес" и другое.)» | The participant's definition includes checking for errors. |
| 23.09.2026 15:46 | Str1fe «Ответ заказчика» (REQ-5914, REQ-5915) | «Ответ. Да. Соответствует. Однако диспетчер ДДС правильность заполнения карты от заявителя не контролирует. Это прерогатива оператора 112 и службы контроля 112.» | The definition matches, except: the ДДС does not control the fill-in; that is the 112 operator's and the 112 control service's prerogative. |
| (memo, 2025) | ДДС memo p.19 (REQ-5278, 5361) | «Очень важно внимательно читать все поля карточки… В описании могут содержаться детали… очень важны» | Read every field carefully (reading, not validating). |

Facts: the 18.09 moderator statement (msg638) and the 23.09 relayed customer answer contradict each
other on this point; the later one is labelled «Ответ заказчика», the earlier one is not. The product
has no DDS validation, flag or correction action (`transitions.py:230-336`; DDS API has no such
endpoint): a gap against msg638 (REQ-1028 `частично`), a match against the 23.09 answer (REQ-5915
`соблюдено`). Both statuses stand; this report does not choose between the statements.

### 9.3 The customer's answer on the ДДС role (23.09.2026 15:46), point by point

The question (participant Mathew, 22.09.2026 22:29, repeated as REQ-5901) and the answer
(«Ответ заказчика», relayed by Str1fe, REQ-5914–REQ-5920):

| Point of the participant's definition (verbatim) | Customer's answer (verbatim) | Product (facts) | Status |
|---|---|---|---|
| Definition: «ДДС (дежурно-диспетчерская служба) это промежуточное звено между оператором 112 (который слушает заявителя и заполняет карту) и бригадой… "Гормост", "Мосгортранс", "Мосводоканал", "Поселение Преображениский (ДДС района…)" и другие - это всё ДДС.» | «Ответ. Да. Соответствует.» | One generic DDS role; 6 generic service types; no Гормост/Мосгортранс/Мосводоканал/district ДДС (F-03, F-14) | REQ-5914 частично |
| «1) Получить заполненную оператором 112 карту» | covered by «Соответствует» | DDS receives the handoff snapshot (RECEIVED) | (part of REQ-5914) |
| «2) Принять/отклонить её в соответствии с полномочиями своей службы ДДС… В случае отклонения карты пишется комментарий.» | covered by «Соответствует» | Accept only («Принять к исполнению»); no reject/decline transition; closure comment optional (F-13, F-39) | (part of REQ-5914) |
| «3a. Просмотреть содержимое на ошибки (грамматические, заполнение блока "Адрес" и другое.)» | «Однако диспетчер ДДС правильность заполнения карты от заявителя не контролирует. Это прерогатива оператора 112 и службы контроля 112.» | No validation action (§9.2) | REQ-5915 соблюдено |
| «3b. Через телефонию связаться с начальником бригады, которая выедет на место происшествия.» | «Общение с реагирующей на вызов бригадой тоже происходит либо по телефону или по другим каналам связи или через стороннее программное обеспечение, минуя 112.» | Inbound scenario radio log (unit → DDS); dispatch note; no phone; no DDS → unit message or query | REQ-5918 частично |
| «3c. Контролировать статус заявления до его окончания» | «Диспетчер ДДС только выбирает статусы ( в карте нижние поля см карту и добавляет статусы своими комментариями).» | Status dropdown with mandatory text (6 kinds); the trainee also selects and dispatches resources; EN_ROUTE…RESOLVED set by the simulation; no per-service status row at the bottom of the card | REQ-5916 частично |
| Example step 5: «при необходимости, контактирует с заявителем путём телефонии» | «При необходимости диспетчер ДДС может напрямую выйти на заявителя по обычному телефону, т.к. номер заявителя есть уже в карточке, и далее общаться с ним минуя 112.» | The caller's phone is shown on the DDS card if the operator entered it; no call function; no simulated claimant on the DDS side | REQ-5917 не соблюдено |
| (separate question, 14:09, about service 103 calling back) | «Как правило диспетчер ДДС номер карточки при дозвоне заявителю номер карты не называют. Общаются по сути заявления. Например. Вы звонили в 112 по поводу.... Что у вас случилось и т.д.» | No DDS → claimant call | REQ-5919, REQ-5920 не соблюдено |

Related dated statements on ДДС communication: msg691 (21.09.2026 15:17, «Ответ от заказчика»): «Мы
ограничивается только телефоном» and «старший группы звонит в ДДС… Или диспетчер сам… набирает по
телефону старшего»; msg701 (22.09.2026 19:38, «Ответ заказчика»): «В карточке ДДС службы не добавляются…
может с этой службой связаться если есть немер телефона»; 23.09.2026: phone, «другим каналам связи» or
«стороннее программное обеспечение». The ДДС memo describes the ДДС calling «112» and the control
department (pp.32–34), not service heads (TRC-SRC-005 REQ-5363). Q&A room 42:06: the only voice
dialogue is «ДДС — руководитель». The product has none of these calls.

### 9.4 GPU / hardware (replaces round-1 §9.2 row 20)

| Time | Speaker | Verified text |
|---|---|---|
| 08:41–09:20 | mentor reads sheet row 2 (participant question) | «…в минимальных требованиях к серверу не указан ГПУ. Будет ли он предоставлен или все функции [ИИ] должны работать на [CPU — screen; audio not settled]?» Sheet C2: «…все ИИ-функции (STT, LLM, TTS) должны работать на CPU?» |
| 09:20–10:09 | **room** (REQ-4003, confirmed) | «…никаких тут, скажем так, требований к видеокарте… сильных нет, поэтому… видеокарта там стандартно должна быть… никакая не навороченная. И в основном это будут все функции работы на центральном процессе. И, соответственно, проверка решений, ну, на стандартных бытовых компьютерах.» |
| 60:24–60:58 | participant «Вадим Золотарев» | «…в случае того, что у нас нет видеокарты, мы будем всё это делать на центральном процессоре, и это будет гораздо медленнее. Вот будут ли исключения по времени отклика…?» |
| 61:45–61:59 | **room** | «Ну, наверное, это Александр Сергеевич ответит техническую часть. … в принципе, если так будет критично, потому что… время — деньги…» |
| 61:59–62:03 | **room** (REQ-6042) | «Конечно, хотите, используйте видеокарту. Не вопрос.» |
| 62:06–62:16 | **room** | «Если мы используем видеокарту, если они предложат некое техническое решение, внедрить в наш сервер, мы можем внедрить видеокарту?» — Corrected: round 1's «Конечно, мы используем видеокарту» is not supported by the audio (a question inside the room). |
| 62:16–62:27 | **room** | «Ну, почему нет? Ну, соответственно, закупим новое оборудование… возможности закупки есть…» |
| 23.09.2026 14:41 | chat, Str1fe (REQ-5911) | «Уточню у заказчика, смогут ли они оперативно раздобыть данные машины для докалки» — no later answer in the sources. |

Facts: the same room tile first says there are no strong GPU requirements and that solutions are
checked on standard consumer computers, then permits a GPU and mentions purchase possibilities; which
of the four men spoke is not visible. The ТЗ server minimum lists no GPU (PDF and docx identical).
Product: every profile runs the LLM on the GPU (`n_gpu_layers: -1`); preflight fails without CUDA.
REQ-4003 `не соблюдено`, REQ-6042 `соблюдено`.

### 9.5 The 30-second norm and in-the-moment AI evaluation (replaces round-1 row 21)

- Mentor reads sheet row 8 (34:14–34:34): «нужно ли моделировать полный жизненный цикл карточки?
  Принято, не принято, начало реагирования, прибытие, проведение работ.» Mentor tile 34:34–34:45:
  «Полностью моделирование полное должно быть.» (first words unclear).
- **Room** 34:47–35:46: «в строке состояния сообщений оператор должен среагировать на неё в течение
  тридцати секунд. То есть это норматив, который определён. По времени исполнения карты… заполнения
  карты нет, но мы давайте установим в течение трёх минут… 30 секунд надо нажать для того, чтобы её
  открыть, и в течение трёх минут её заполнить.» (The speaker corrects «тридцати минут» to «тридцати
  секунд» and «трёх минут».)
- 35:48–36:24 (both tiles / room / mentor; missing from round 1's transcript): «Да, появится новая
  карточка, которая генерируется… Норматив по-прежнему работает. Многозадач[ность]…»
- **Mentor** 63:21–64:29 (REQ-6043): evaluating each answer «в моменте… скорее всего, не взлетит, и мы
  в тайминг в 30 секунд не попадём» — Corrected: round 1 attributed this to the customer; it is the
  mentor, and the 30-s / 3-min norm is the room's.
- ДДС memo p.5 (legal basis listed on p.4): «Диспетчер службы должен подтвердить получение сообщения…
  через 30 секунд после его направления в службу»; p.21: otherwise «Не оповещено».
- Chat 23.09.2026 14:31: cards arrive «Одновременно, как в текущей работе», the timing runs for queued
  cards too.
- ТЗ ¶240: default task time limit «По умолчанию значение - 30 сек.» (same in the PDF).
Product: no 30-s or 3-min rule, no DDS timer, one card per session (F-38, F-17).

### 9.6 Real vs de-identified data (replaces round-1 row 23)

- Video 100–120 s (Ащаулов В.К., REQ-4083): «От нас реальные данные.»
- Q&A, mentor reads sheet row 12 (44:46–45:04): «Являются ли данные о предоставленных билетах
  синтетическими или разрешено, и разрешено ли показывать их в прототипе и презентации, или
  [требуется…]?» (sheet: «…или требуется обезличивание?»). **Room** 45:04–45:28 (REQ-6031): «Да,
  пожалуйста, они уже обезличены, поэтому там… она в тех билетах, которые есть, она уже обезличена… можно
  использовать её без всяких без ограничений.» — Corrected: round 1 read «в предоставленных милициях»;
  «Да, пожалуйста» answers «разрешено ли показывать их в прототипе и презентации».
- The tickets file (archived in round 2) contains caller full names and phone numbers; whether they
  are synthetic cannot be determined from the file (TRC-SRC-005 REQ-4048). The product uses none of
  the tickets.

### 9.7 Speakers (replaces round-1 row 25)

The recording shows five speaking tiles: host «Михей Модератор»; the mentor on two tiles («Станислав
Галаган», «Станислав»); the customer room «Александр Ш.» (four men; the host names «Рушенков /
Варшунков / Паршенков Александр, Шкиперов Александр и Сергаков Александр Григорьевич»; at 61:46 a
speaker in the room says «это Александр Сергеевич ответит техническую часть», a patronymic none of the
three names carries); participants. Green-border seconds: room 1 874, mentor 1 724 + 38, participant
«Вадим Золотарев» 82, host 49 in the strip. Of round 1's REQ-4001–4063, 19 statements attributed to "a
company representative" are wholly the mentor's (REQ-4009, 4010, 4020, 4021, 4024, 4027–4030,
4037–4039, 4050, 4052, 4053, 4055, 4060–4062), 8 are split (REQ-4005, 4006, 4025, 4031, 4043, 4044,
4051, 4054), and REQ-4063 is the room's, not the mentor's. The promotional video's narrator is Ащаулов
В.К. (УМЦ ГОЧС); he is not among the names the host lists, and the sources do not state the relation
between «компания-постановщик» and the УМЦ.

### 9.8 Local-only operation vs an external model for the demo

| Date / time | Source, speaker | Verbatim |
|---|---|---|
| 01.09.2026 (ТЗ) | ТЗ ¶88, ¶115, ¶155 (REQ-2082, 2104, 2136) | «без доступа к внешним сетям (локальный контур)»; «Внутренний API: … (без взаимодействия с внешними системами)» |
| 16.09.2026 46:52 | Q&A, **mentor** (REQ-6032; round 1 attributed REQ-4050 to the customer) | «только локально… модель… может быть обучена… в облаках, но потом должна быть развёрнута локально… без выхода вовне» |
| 16.09.2026 47:21–48:35 | Q&A, **room** then both then **mentor** (REQ-6033) | room: the class can technically be connected to a server with internet, «но… и локально должно быть работать однозначно»; both: «локальный приоритет, а интернет — … дополнительно»; mentor: «приоритет именно на локалку… прибежит ДИП… по ИБ» |
| 23.09.2026 14:41 | chat, Str1fe (REQ-5912, 5913) | «на демонстрации можно показать работу без локалки (главное, чтобы решение не хардкодило только обращение во вне)» |
| 23.09.2026 15:53 | chat, Str1fe (REQ-5923, 5924) | «в ТЗ указано, что Внутренний API - решение для расширения функционала системы собственными модулями (без взаимодействия с внешними системами)»; «То есть API есть, но оно для взаимодействия без выхода во вне» |
| 23.09.2026 15:58 | chat, Str1fe (REQ-5925–5927) | «…если развернуть модель внутри (такая возможность должна быть), но раз это должно быть обеспечено мощностью самого заказчика, а он не совсем готов, то на ДЕМО можно показать во вне, но в самом решении должна быть возможность прописать, куда обращаться к модели…» |

Participants in the same chat (15:10–15:43) describe the demo permission as a change of the ТЗ's
local-only rule; no organizer message in the sources says a rule changed (SRC-006 §3.2). Product: local
only; the endpoint is configurable among loopback/internal hosts; an external host is refused, so the
demo permission cannot be used without a code change (§4.9).

### 9.9 Other conflicts and changes recorded by the extraction files

Rows 1–19, 24 and 26 are kept from round 1; round-1 rows 20–23 and 25 are replaced by §9.1 and
§9.4–§9.7; rows 27–33 are new in round 2.

| # | Subject | Statements (IDs, dates) | Extraction file |
|---|---|---|---|
| 1 | Has the ТЗ changed? | Participant msg571 (18.09 11:24) «Классно тз поменялось»; organizer msg577 (11:30) «тз не менялось, оно одно». No organizer message admits a revision. Round 2: the ТЗ PDF (msg201 link) and the docx differ in 18 logged places, none in a number, hardware minimum, deadline or legal citation; the requirement text is otherwise the same. | SRC-001-chat §Conflicts 2; SRC-005-tz-pdf §2, §5 |
| 2 | Scope of the A/B/C analogy | Participant msg628 read it as "B↔C only"; msg635 «в контексте телефонии, но не всего процесса»; msg638 «согласно обсуждению телефонии, но не всего ТЗ». | SRC-001-chat §Conflicts 3 |
| 3 | Are 112 and ДДС the same role? | msg624 «Вообще нет, это разные службы, но в контексте имитации обучения - да». | SRC-001-chat §Conflicts 4 |
| 4 | ДДС role still open | msg703 (22.09.2026) — answered 23.09.2026 15:46 (§9.3). | SRC-001-chat §Conflicts 5; SRC-006 |
| 5 | ТЗ internal: call channel | REQ-2100 vs REQ-2044/2118/2249/2139 (§8.2). | SRC-001-formal-docs §3.1.1 |
| 6 | ТЗ internal: mobile | REQ-2135 vs REQ-2157/2342 (§8.3). | §3.1.2 |
| 7 | ТЗ internal: integration vs isolation | REQ-2053/2127 vs REQ-2082/2104/2106/2136 (§8.4). | §3.1.3 |
| 8 | ТЗ internal: criteria without requirements | REQ-2351/2352/2361/2363/2369 (§8.5). | §3.1.4 |
| 9 | ТЗ internal: trainee role | Title/REQ-2005 vs REQ-2268/2269 (§8.6). | §3.1.5 |
| 10 | ТЗ verbatim repeats (no conflict) | REQ-2126 = 2235; 2144/2145 = 2250/2251; 2124 = 2242; 2123 = 2240; 2085 = 2109; 2056 = 2086 = 2111; 2087 = 2116; 2289 = 2271–2276. | §3.1.6 |
| 11 | ТЗ vs chat: imitated participant call | REQ-2268 vs msg570/576/624/625/638 (§9.1). | §3.2.1 |
| 12 | Deadline | The ТЗ has no date; chat msg6 (29.06), msg201 (15.09), msg700 (22.09), 23.09 18:20 (REQ-5936): 29 сентября 23:59 МСК; msg673 (20.09): presentation «К концу разработки, то есть 29 сентября». | §3.2.2; SRC-006 |
| 13 | Presentation | ТЗ «pptx или pdf» + link; msg201 adds the template with mandatory slides 7–11; msg700 accepts «PDF на облачном диске, Яндекс.Диске, Google Slides»; round 2: template archived (slide 3 «Обязательный блок» for slides 7 and 8–11); 23.09 18:20: every team submits a presentation, full when the ТЗ requires one; «Исключение — слайд 10 (состав команды)» while the template's roster is slide 9 (§8.25). | §3.2.3; SRC-005-tz-pdf §4; SRC-006 |
| 14 | Documentation form | ТЗ «(.docx/.pdf)»; msg700 also accepts «Google Docs, Notion, PDF на диске или файл в самом репозитории». | §3.2.4 |
| 15 | Repository | ТЗ «Ссылка на репозиторий»; msg700 adds «публичный… или предоставлен гостевой доступ» and README.md; 23.09 18:20 «открытый доступ к материалам». | §3.2.5; SRC-006 |
| 16 | Prototype vs isolation | §8.22; 23.09 demo permission (§9.8). | §3.2.6 |
| 17 | Criteria reply | msg643 truncated (§8.5); 23.09 18:20 names the evaluated materials, not criteria. | §3.2.7 |
| 18 | «Билеты и задачи» | Round 1: not in the archive. Round 2: archived («Датасет», msg201): 32 «БИЛЕТ» × 3 = 96 calls; two rows are verbatim duplicates (Билет 1 №3 = Билет 16 №2; Билет 1 №2 = Билет 21 №1). No organizer statement equates «96» with these rows. | §3.2.8; SRC-005-tickets §8 |
| 19 | Q&A session length | Guide «не более 1 часа 30 минут» vs msg216 «11:00-12:00»; host 03:55 «не более одного часа»; the recording lasts 01:05:45 incl. 2:27 of silence before the start. | §3.3.1; evidence §5.3 |
| 24 | Creativity vs originality | Video «Нам важен ваш творческий подход» (REQ-4083) vs Q&A **mentor** 55:37 «А оригинальность, неоригинальность, это уже второстепенно» (REQ-4061/6039) and **mentor** 51:33 «будем оценивать… творческий подход» (REQ-4055/6037); room 27:26 «чтобы была своя идея, какая-то изюминка» (REQ-4026). Corrected: round 1 attributed REQ-4055/4061 to the customer. | SRC-002-003-video §3.5; SRC-007 |
| 26 | Domain documents | No contradiction between the five domain documents; the manual's version tags (1.7 → 1.8 → 2.0 → 2.1) show features added over time. The ДДС memo is consistent with them (48 h «Не завершено», «Отработана», ВИС marker, card list, search). | SRC-001-domain-docs §3; TRC-SRC-005 Part 2 |
| 27 | Classifier versions | v_046_11 (90 columns, 1281 data rows, «Сценарий реагирования») vs v_046_24 (99 columns, 1283 rows, no «Сценарий реагирования»; 94 changed rows, 90 in МВД columns; fire content unchanged). | SRC-005-classifier |
| 28 | ДДС communication channels | msg638 (18.09): calls to service heads via IP-telephony simulator; msg691 (21.09): «ограничиваемся только телефоном»; 23.09: phone, other channels or third-party software; memo: ДДС calls «112» and the control department only. | SRC-001-chat; SRC-006; SRC-005-tickets §8.5 |
| 29 | Cards one by one or concurrently | Q&A 35:48 «появится новая карточка… Многозадач[ность]»; chat 23.09 14:31 «Одновременно, как в текущей работе»; the participant's numbers (1/min, ≤3, 30 s) not confirmed. No conflict between the organizer statements. | SRC-007; SRC-006 §3.4 |
| 30 | Who adds services | memo p.14: the specialist-112 may add a service, never remove; msg701 (22.09): services are not added on the ДДС card. Consistent. | SRC-005-tickets; SRC-001-chat |
| 31 | Which ТЗ file is later | docx file name 01.09, PDF metadata 11.09, PDF linked 15.09, docx posted 18.09 (§8.27). | SRC-005-tz-pdf §5 |
| 32 | 103 call-back question vs answer | §8.24. | SRC-006 §3.3 |
| 33 | Local-only vs demo with an external model | §9.8. | SRC-006 §3.2 |

### 9.10 Disagreements between extraction files and matrices

- `SRC-001-chat.md` §1 states that `video_files/IMG_2549.MP4` «is a sticker video, not the Q&A
  recording». `SRC-002-003-video.md` read the file: a 2:34 promotional video (narrator Ащаулов В.К.),
  forwarded as msg34 on 06.08.2026. Both agree it is not the Q&A recording; the "sticker" description
  is not correct (`grep IMG_2549 messages.html`: attached as `video_file` to msg34).
- `SRC-001-chat.md` §Conflicts 1 ends with a sentence giving "the most defensible reading" of the
  caller-voice statements. That sentence is the extractor's interpretation, not an organizer
  statement; §9.1 lists the statements without it.
- REQ-4054: `TRC-SRC-005.md` Part 2 → `не соблюдено`; `TRC-SRC-007.md` Part 2 → `частично` (§1.7).
- `SRC-005-tickets-and-dds-memo.md` REQ-5358 note says the memo «never uses "ДДС"»; this holds for
  p.14 only — the title, the p.23 caption and pp.28–34 use «ДДС» (TRC-SRC-005).
- Round 1 `Город 9.txt` quotes corrected by the recording are listed in `SRC-007-qna-gigaam.md` §3 (34
  of 63 items); the matrix `TRC-SRC-002-003-video.md` keeps the round-1 quotes in its rows, with the
  changed statuses marked «(re-judged by TRC-SRC-007 Part 2)».

---

## 10. Appendix — where the detail is

| File | Content |
|---|---|
| `requirements/normalized/SRC-001-chat.md` | 58 chat items (REQ-1001–1058), verbatim, speaker, message id and time; conflicts §5 |
| `requirements/normalized/SRC-001-formal-docs.md` | 437 items from the ТЗ, FAQ, Q&A guide, datasheet (REQ-2001–2437); citation by heading, TOC page, lead-in, bullet ordinal, ¶N; conflicts §3 |
| `requirements/normalized/SRC-001-domain-docs.md` | 49 items from the real card, manual, ДДС screenshots, services list, classifier (REQ-3001–3049), incl. the 51 incident types, 271 fire rows, 39 hotkeys |
| `requirements/normalized/SRC-002-003-video.md` | 94 items from `Город 9.txt`, `brief-from-user.md`, `IMG_2549.MP4` (REQ-4001–4094); conflicts §3 |
| `requirements/evidence/IMG_2549-transcript.md` | Full GigaAM transcript and frame descriptions of the video |
| `requirements/normalized/SRC-005-tz-pdf-and-template.md` | ТЗ PDF vs docx (D1–D18) and the presentation template (REQ-5001–5036) |
| `requirements/normalized/SRC-005-tickets-and-dds-memo.md` | 96 ticket calls and the ДДС memo (REQ-5201–5363) |
| `requirements/normalized/SRC-005-classifier-v046-24.md` | Classifier v_046_24 vs v_046_11 (REQ-5701–5721) |
| `requirements/normalized/SRC-006-chat-update.md` | Chat 22.09 21:29 – 23.09 18:20 (REQ-5901–5945) |
| `requirements/normalized/SRC-007-qna-gigaam.md` | Recording-verified Q&A items (REQ-6001–6047) and a verdict for each of REQ-4001–4063 |
| `requirements/evidence/qna-transcripts-comparison.md` | Three transcripts compared, recording re-check, speakers from the video, the on-screen question sheet |
| `requirements/evidence/tickets-ocr.md` | OCR of the 32 ticket pages |
| `requirements/traceability/TRC-SRC-001-chat.md` | Matrix for REQ-1001–1058 (SPEC coverage, evidence, status, gap) |
| `requirements/traceability/TRC-SRC-001-formal-docs-a.md` | Matrix for REQ-2001–2220, with repository facts F1–F13 |
| `requirements/traceability/TRC-SRC-001-formal-docs-b.md` | Matrix for REQ-2221–2437, evidence keys, §3 conflict positions |
| `requirements/traceability/TRC-SRC-001-domain-docs.md` | Matrix for REQ-3001–3049 |
| `requirements/traceability/TRC-SRC-002-003-video.md` | Matrix for REQ-4001–4094 (REQ-4022 corrected after review; round-2 re-judgements marked; REQ-4003 citation corrected) |
| `requirements/traceability/TRC-SRC-005.md` | Part 1: REQ-5001–5945 (265 rows); Part 2: re-judgement of earlier items |
| `requirements/traceability/TRC-SRC-007.md` | Part 1: REQ-6001–6047; Part 2: re-judgement of the 34 corrected REQ-40xx |
| `requirements/INDEX.md` | Document registry and one row per REQ with the status used in this report |
| `docs/SPEC.md`, `docs/AUDIT.md`, `docs/DOD_WALK.md` | Build contract, its §1–§47 audit, and the real-stack walk of 2026-09-22 |

Round-1 corrections: §1.6; round-2 re-judgements: §1.7. The matrices carry both.

---

## 11. Owner decisions recorded 2026-09-23

These are the product owner's scope decisions of 2026-09-23, recorded as facts. They are not
requirement statuses: no status in this report, in the matrices or in `requirements/INDEX.md` was
changed because of them, and the findings they touch stay as written above.

**Out of scope for now:**

| Decision | Findings and items it touches (status unchanged) |
|---|---|
| Submission deliverables: the presentation (incl. template slides 7–11), the prototype link and the video / screencast, repository access, documentation as .docx/.pdf | F-33, F-34 (REQ-1013, 1015, 2334, 2338, 2372–2375, 4052, 4053, 5004–5031, 5930–5945, 6034, 6035) |
| Everything that cannot be verified on this machine: the hardware IP phone РТУ Т16Р, runs on the ТЗ minimum hardware, Windows and tablets, integration with the real system-112, Яндекс.Браузер | F-08, F-29, F-30, F-37; B-list in §3.4 (REQ-2146–2149, 2153, 2154, 2247, 2343) |
| CPU-only operation: the customer's GPU is assumed to be at least an RTX 3060 Ti | F-27 (REQ-2054, 2112, 2113, 2152, 4003); §9.4 |
| ML-based assessment: the owner has a model to add later | F-19 (REQ-2063, 2090, 2091, 2102, 2121, 4067, …); §4.5 |

**Kept as built:** the AI caller voice and TTS (the caller → 112 operator leg), which the §9.1 statements
discuss (F-06; REQ-4017, 4040, 4044, 4045 remain `не соблюдено`, REQ-4043 `не обработано`).
