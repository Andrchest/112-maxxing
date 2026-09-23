# SRC-007: the 16.09.2026 Q&A session re-checked against the recording (new and corrected items, REQ-6001–REQ-6047)

## 1. Header

**What this file covers.** One recorded session, read three ways plus a fresh re-transcription:

- **W**: the old transcript `requirements/sources/02-original-requirement/Город 9.txt` and its twin
  `whisper-timestamps/Город 9.srt` (faster-whisper large-v3-turbo). `old L<n>` = line n of W.
- **G**: the new transcript `requirements/sources/07-qna-transcript-gigaam/` (GigaAM v3 e2e-CTC, fixed
  22-s windows).
- **L3**: the third transcript `requirements/sources/08-qna-transcript-whisper-large-v3/` (faster-whisper
  large-v3). `L3 line <n>` = line n of it.
- **The recording** `/home/andreipc/everything/Город 9. Департамент по делам гражданской обороны.mp4`
  (read only, not copied).

**How it was read.** Method, numbers and frame descriptions are in
`requirements/evidence/qna-transcripts-comparison.md`. In short:

- W, G and L3 were aligned on the 22-s G windows and read side by side.
- The recording was re-transcribed with the repository's `GigaAMProvider` (checkpoint `v3_e2e_ctc`) on
  windows cut at pauses: a whole-recording pass at ≤ 20 s and one at ≤ 8 s.
- Disputed windows were also transcribed by the second local checkpoint (`v3_ctc`).
- Speakers come from Telemost's green speaking border. Frames were taken at 1 fps, and the labels of
  highlighted tiles were OCR-read with tesseract `rus`.
- The on-screen question sheet was read from full-resolution frames.

**What could not be read.**

- 11:40–12:29 of the recording has no audio (all-zero samples). See REQ-6003.
- The session date is not shown anywhere in the recording.
- The four customer representatives share one room camera. The tile label is «Александр Ш.», and the
  video does not show which of them speaks.
- A few words are not settled by any reading (comparison §8).

**How organizers were identified.** By the video tile, with the evidence in comparison §5.1:

| Tile | Role |
|---|---|
| «Михей Модератор» | the session host |
| «Станислав Галаган» and «Станислав» (screen share) | the task **mentor** Галаган Станислав (two accounts, in his own words at 05:48) |
| «Александр Ш.» | the room of the **customer's representatives** («представители компании-постановщика»). A participant confirms it at 64:36: «наши коллеги, которые под аккаунтом Александр Ш. сидят» |
| «Вадим Золотарев» and other named tiles | **participants** (context only) |

The questions read from the sheet are participant questions. The mentor collected and normalised them
(08:17), so they are context, not organizer statements.

Speaker notation in this file: **mentor** = Станислав Галаган; **customer room** = the tile «Александр Ш.»;
**host** = «Михей Модератор». The previous extraction (`SRC-002-003-video.md`) labelled almost every speaker
"organizer (unnamed company representative)". Where the video shows the mentor instead, the item below
records it as a correction.

**Counts per Kind (REQ-6001–REQ-6047)**

| Kind | Count |
|---|---|
| REQUIREMENT | 10 |
| CLARIFICATION | 12 |
| CONSTRAINT | 8 |
| EVALUATION | 9 |
| DELIVERABLE | 2 |
| DATA-PROVIDED | 3 |
| DOMAIN-FACT | 2 |
| OPEN-QUESTION | 1 |
| **Total** | **47** (37 correct or extend a REQ-40xx item; 10 are new, and 5 of those re-attribute statements quoted in assessment §9.1/§9.2 or in the SRC-002-003-video conflicts) |

REQ-6048–REQ-6299 are unused.

---

## 2. Items

Each item states: time in the recording, the old line(s), the G window, and the L3 line(s).

### REQ-6001 · DOMAIN-FACT · corrects REQ-4001
- **Source:** 03:14.6–03:22.3; old L10–11; G window 03:18; L3 lines 10–11.
- **Speaker:** host «Михей Модератор» (green border, grid frames 200 s and 250 s).
- **Verbatim:** «Сегодня мы разберём задачу номер девять, направление — город, от департамента
  гражданской обороны, чрезвычайным ситуациям и пожарной безопасности. Учебный симулятор подготовки
  диспетчеров экстренных служб по вызовам от систем 112.»
- **English:** "Today we'll go through task number nine, track 'city', from the Department of Civil
  Defence, Emergency Situations and **Fire** Safety: a training simulator for preparing emergency-service
  dispatchers for calls from system 112."
- **Notes:** REQ-4001 quotes W «природной безопасности». L3 has «приоритетной безопасности». Every R
  window has «пожарной безопасности»: both checkpoints, 3 windows each.

### REQ-6002 · CLARIFICATION · new
- **Source:** 03:28–03:42 and 05:40–05:58 (old L14–17, L60–65); 64:36–64:43 (old L908; L3 line 658).
- **Speaker:** host; mentor; participant «Вадим Золотарев» (context).
- **Verbatim:**
  - host: «Вместе с нами на встрече ментор задачи Галаган Станислав и представители
    компании-постановщика: [Рушенков / Варшунков / Паршенков] Александр, Шкиперов Александр и Сергаков
    Александр Григорьевич.»
  - mentor: «Я буду с двух аккаунтов, то есть у меня на компьютере не работает камера, так что я буду
    вести трансляцию с телефона.»
  - participant: «наши коллеги, вот, которые под аккаунтом Александр Ш. сидят»
- **English:**
  - "With us are the task mentor Stanislav Galagan and the representatives of the task-setting company:
    [surname unsettled] Aleksandr, Aleksandr Shkiperov and Aleksandr Grigoryevich Sergakov."
  - "I'll be on two accounts: the camera on my computer doesn't work, so I'll stream from my phone."
  - "our colleagues who sit under the account 'Aleksandr Sh.'"
- **Notes:**
  - The video shows the tiles «Станислав Галаган» (camera) and «Станислав» (screen share).
  - The tile «Александр Ш.» is one room camera with four men.
  - The first surname is read four ways: W Рушенков, G Варшунков, L3 Паршенков, ctc Паршунков. Not
    settled.
  - At 61:46 a speaker in the room tile says «это Александр Сергеевич ответит техническую часть».

### REQ-6003 · OPEN-QUESTION · new
- **Source:** 11:39.7–12:29 (between old L160 and L161; G has no window 11:44–12:28; between L3 lines
  143 and 144).
- **Speaker:** the video shows the green border on «Александр Ш.» during the span (frame 721 s).
- **Verbatim:** the last words before the gap, by the mentor: «Следующий вопрос у нас — генерация
  сценариев и опросные карты по типам…». The first words after it: «…Высоких. Уже должен включаться
  искусственный интеллект…»
- **English:** "Next question: scenario generation and questionnaire cards by incident type…" … "…at
  higher [levels] AI should already come in…"
- **Notes:**
  - The recording's samples are exactly zero for about 50 s. The customer's reply to sheet row 4 («Должен
    ли ИИ самостоятельно генерировать новые сценарии или достаточно варьировать утверждённые шаблоны?…»)
    has lost its beginning in every transcript.
  - REQ-4007 starts mid-answer for this reason.

### REQ-6004 · CLARIFICATION · corrects the question context of REQ-4003
- **Source:** 08:47.8–09:03.6; old L118–122; G window 08:48; L3 lines 121–123; sheet cell C2.
- **Speaker:** mentor, reading a participant question.
- **Verbatim, on screen (C2):** «В минимальных требованиях к серверу не указан GPU. Будет ли он
  предоставлен, или все ИИ-функции (STT, LLM, TTS) должны работать на CPU? На какой конфигурации
  оборудования (CPU, RAM, видеокарты) планируется проверка решения?»
- **English:** "The minimum server requirements don't list a GPU. Will one be provided, or must all AI
  functions (STT, LLM, TTS) run on the CPU? On what hardware configuration will solutions be checked?"
- **Notes:**
  - W «должны работать на ГПУ» and L3 «на GPU» do not match the sheet. The audio is not settled: G «на на
    ГПУ», R8 «на на Cp», R20 «на на КПУ».
  - The customer room's answer (REQ-4003, 09:20–10:09) is confirmed by all readings.

### REQ-6005 · CONSTRAINT · corrects REQ-4005
- **Source:** 10:46–11:12; old L149–154; G windows 10:38 and 11:00; L3 lines 134–137; sheet C3.
- **Speakers and verbatim:**
  - mentor, reading (10:48–11:00): «Обязательно ли на защите демонстрировать реальные SIP-вызовы через
    локаль[ный SIP-]сервер[а] и[ли] недопустима программная эмуляция.»
  - mentor (11:00–11:06): «Ну, реальные вызовы либо симуляция. Я думаю, что симуляция вполне
    достаточно.»
  - customer room (11:07–11:12): «Конечно. Симуляция. Да, конечно. То есть симуляция, реальных вызовов
    не будет, и только симуляция. Да.»
- **English:**
  - mentor: "Is it mandatory at the defence to demonstrate real SIP calls through a local SIP server, or
    is software emulation acceptable? … Well, real calls or simulation. I think simulation is quite
    enough."
  - room: "Of course. Simulation. Yes, of course. That is, simulation; there will be no real calls, only
    simulation."
- **Notes:**
  - REQ-4005's first sentence (W «Обязательно не на защите демонстрируйте … и недопустимо программная
    эмуляция») is the question, mis-heard. C3 on screen: «…или допустима программная эмуляция?».
  - REQ-4005 flagged the passage as contradictory. With the question identified, the recording contains
    no statement requiring real SIP calls.

### REQ-6006 · DATA-PROVIDED · corrects REQ-4006
- **Source:** 11:12–11:34; old L155–159; G windows 11:00 and 11:22; L3 lines 138–142; sheet D3.
- **Speakers and verbatim:**
  - mentor (11:12–11:23): «И если [= есть ли] техническая документация по устройству VoIP на стороне
    заказчика… Я думаю, это коллегам поможет построить правильную симуляцию.»
  - customer room (11:23–11:29): «Конечно. [Документация…] Всё это… Нет, это всё, конечно, мы поможем и
    подскажем, как сделать это правильно и грамотно.»
  - mentor tile highlighted (11:28–11:34): «Всё, тогда документы мы предоставим.»
- **English:**
  - mentor: "And whether there is technical documentation on the VoIP setup on the customer's side… I
    think it would help colleagues build a correct simulation."
  - room: "Of course… No, all that, of course, we'll help and advise how to do it correctly and
    properly."
  - mentor tile: "Right, then we'll provide the documents."
- **Notes:**
  - W «выйдет на стороне заказчика» is not supported: G «VIP», L3 «веб», ctc «выип».
  - Sheet cell D3 (column «Ответ») shows the typed text «предоставим локи» from about 11:26 (frames 686–
    1066 s). It is the only answer cell typed during the session.
  - The sheet question also names «версия SIP, топология сети, модели АТС».

### REQ-6007 · REQUIREMENT · corrects REQ-4007
- **Source:** 12:46–13:16; old L164–175; G windows 12:28 and 12:50; L3 lines 145–149.
- **Speaker:** customer room.
- **Verbatim:** «Ответил? Ну, то есть и там, и там, то есть должен быть симбиоз. На низших уровнях
  преподаватель, на более высоких — искусственный интеллект, но под контролем [опять же / связи]
  преподавателей. Ну, то есть надо всё искусствовать [unsettled]. И искусственный интеллект тоже…
  Помимо, помимо шаблонов, да, предусмотреть самостоятельную генерацию. Ну, и так, и так, да, и шаблоны,
  и [генерацию].»
- **English:** "…both, there should be a symbiosis: at lower levels the teacher, at higher levels AI, but
  under the teachers' control… Besides templates, provide for **autonomous generation**. Both ways:
  templates and generation."
- **Notes:**
  - REQ-4007's «смотреть с несоединительной генерацией» (W) is not supported. Both checkpoints and G read
    «предусмотреть самостоятельную генерацию»; L3 reads «смотреть социальные генерации».
  - The start of this answer is lost (REQ-6003).

### REQ-6008 · REQUIREMENT · corrects REQ-4009 (text and speaker)
- **Source:** 14:43–15:18; old L200–208; G windows 14:40 and 15:02; L3 lines 159–162.
- **Speaker:** mentor (14:43–15:25 mentor tile).
- **Verbatim:** «И об этом, да, как раз было в ТЗ указано. То есть у нас, в принципе, преподаватель
  является, грубо говоря, фактическим подтверждающим те либо иные итоги. Возможно, мы в ТЗ об этом ещё
  дополнительно, может быть, там, ну, не в ТЗ, там ещё где-то упомянем, что да, искусственный интеллект
  выдал какие-то правильные ответы, все ответили на них, да, там, обучающиеся, но преподаватель сам
  подтверждает правильность ответа.»
- **English:** "This was stated in the ТЗ: the teacher is, roughly, the one who actually confirms the
  outcomes. Maybe we'll mention it additionally, not in the ТЗ but somewhere else: AI gave some correct
  answers, the trainees answered them, but the teacher himself confirms the correctness of the answer."
- **Notes:**
  - W «ФТЗ» is not supported; G, L3 and R read «ТЗ».
  - REQ-4009's speaker "company representative" is corrected to the mentor.

### REQ-6009 · CLARIFICATION · corrects REQ-4010
- **Source:** 15:12–15:27; old L208–211; L3 lines 161–163.
- **Speaker:** mentor.
- **Verbatim:** «То есть, и поэтому теоретически это должно дообучать саму модель, да, чтобы меньше было
  галлюцинаций. — Ну да, возможно [д]обучение, в принципе.»
- **English:** "…so in theory this should further train the model itself, so there are fewer
  hallucinations. — Well yes, possibly [further] training, in principle."
- **Notes:**
  - W «инвестиционации» and L3 «интеллигенции» are not supported; G and both checkpoints read
    «галлюцинаций».
  - «дообучение / обучение» in the second sentence is not settled (e2e «обучение», W/L3 «дообучение»).

### REQ-6010 · REQUIREMENT · corrects the speaker of REQ-4020 and extends its quote
- **Source:** 24:16–24:42; old L333–342; G windows 24:12 and 24:34; L3 lines 234–240.
- **Speaker:** mentor (mentor tile only, 24:16–24:42).
- **Verbatim:** «Ну, вроде да, да. То есть я поясню ещё разочек. То есть у нас, допустим, есть история о
  том, что генерируется звонок якобы голосовой о каком-то событии. Дальше, соответственно, человек заносит
  в карточку сведения, которые должны в итоге система проверить на то, насколько он всё учёл в момент
  занесения карточки. И фактически, исходя из этого, выставляются какие-то оценки. Система баллов пока не
  важна, какую придумаете, такую придумаете.»
- **English:** "I'll explain once more. Say we have a story where a supposedly voiced call about some
  event is generated. Then the person enters into the card information which the system must ultimately
  check for how completely he took everything into account when filling the card. Grades are given on
  that basis. The points system doesn't matter yet: whatever you invent."
- **Notes:**
  - The speaker of REQ-4020 was "company representative"; the video shows the mentor.
  - The phrase «генерируется звонок якобы голосовой» comes before REQ-4020's quote and is not in it.

### REQ-6011 · REQUIREMENT · corrects the speaker of REQ-4021
- **Source:** 24:42–25:03; old L343–347.
- **Speaker:** mentor.
- **Verbatim:** «И второй момент, грубо говоря, когда появилась уже вот эта вот разблюдовка, исходя из
  того звонка, уже как бы этот же человек или другой человек в роли того же оператора ДДС, он может
  распределить уже эту активность на конкретные службы фактически.»
- **English:** "Second: once this breakdown has appeared from that call, the same or another person in
  the role of the ДДС operator can distribute this activity to specific services."
- **Notes:** Text confirmed by W, G and L3. Speaker changed from company representative to mentor.

### REQ-6012 · CONSTRAINT · corrects the speaker of REQ-4024
- **Source:** 26:36–27:05; old L376–387; L3 lines 268–276.
- **Speaker:** mentor (the mentor tile is highlighted 26:16–27:25).
- **Verbatim:** «Значит, будут ли предоставлены скриншоты, да? Тестовый стенд, код фронтенда, UI-kit или
  демонстрационный доступ? Смотрите, по поводу демонстрационного доступа, наверное, нет, потому что он
  локальный. Тестовый стенд — такая же история, он всё локальный. Вот. Код фронтенда вряд ли. Вот. Надо
  будет просто попробовать повторить то, что вы будете видеть на скриншоте.»
- **English:** "Will screenshots be provided? Test stand, frontend code, UI-kit or demo access? Demo
  access, probably not, since it's local. Test stand, same story, all local. Frontend code, unlikely.
  You'll just have to try to reproduce what you see in the screenshots."
- **Notes:** Text confirmed. Speaker changed to mentor. The screenshots offer itself («Конечно. Ну, если
  опять же под запросом, мы его предоставим. То есть у нас всё есть в виде скриншотов», 26:02–26:12) is
  the customer room (REQ-4023).

### REQ-6013 · CLARIFICATION · corrects REQ-4025 (speakers, wording)
- **Source:** 26:12–27:25; old L369–391; L3 lines 264–280.
- **Speakers and verbatim:**
  - customer room (26:12–26:16): «Да, он довольно несложный.»
  - mentor (26:16–27:25): «Да, там ничего сложного нет, то есть фактически там карточка, возможность
    выбрать, условно, так назовём, теги … и цветовая гамма там тоже не сильно цветастая … Потому что сама
    цель этой всей системы, да, АРМ 112, не в том, что там наплодить кучу разных там непонятных сущностей,
    а чтобы как можно быстрее забивать данные и переходить к следующему звонку, следующему пострадавшему,
    вне зависимости от того, что случилось.»
- **English:** "It's fairly simple… nothing complicated: a card, the option to pick tags… the colour
  scheme isn't very colourful either… because the whole purpose of the АРМ 112 system is not to spawn
  lots of obscure entities, but to enter data as fast as possible and move on to the next call, the next
  victim, whatever happened."
- **Notes:** W «цветовская» and «самооценит и все системы» are corrected by G and L3 («цветастая», «само
  цель этой всей системы» / «самооценитая вся система»).

### REQ-6014 · EVALUATION · corrects the speaker of REQ-4027
- **Source:** 28:14–29:02; old L405–418.
- **Speaker:** mentor (28:18–29:02).
- **Verbatim:** «Смотрите, значит, здесь я могу пояснить. То есть оценка происходит на момент уже
  сформированного вами MVP… и оценивается всё в целом. То есть элементарно там: похож интерфейс, не похож
  интерфейс? Да, похож. Карточка заполняется, не заполняется? Заполняется. Значит, вопросы генерируются?
  Генерируются. Похожи ли они на настоящие запросы?…»
- **English:** "Evaluation takes place on the MVP you've formed, and everything is evaluated as a whole:
  does the interface resemble [the real one]; is the card filled; are questions generated; do they
  resemble real requests…"
- **Notes:** Text confirmed. Speaker changed to mentor.

### REQ-6015 · EVALUATION · corrects the speaker of REQ-4028
- **Source:** 29:04–29:42; old L420–429.
- **Speaker:** mentor.
- **Verbatim:** «Но суть в том, что, так как это всё настраиваемая тема, да, то есть мы можем эту точность
  поднастроить, исходя из качества тех данных, которые предоставят сами коллеги на конкурс… мы прекрасно
  понимаем, что там сильной точности мы можем и не ожидать, да? Но она просто должна соответствовать тем
  параметрам, которые выставляются в самой настройке самой системы. По умолчанию там всё было указано,
  да, какие у нас веса стоят по умолчанию, но их можем менять.»
- **English:** "Since this is all configurable, we can tune the accuracy depending on the quality of the
  data the teams provide; we don't expect high accuracy; it just has to match the parameters set in the
  system's own configuration; default weights are given but we can change them."
- **Notes:** Text confirmed. Speaker changed to mentor.

### REQ-6016 · EVALUATION · corrects the speaker of REQ-4029
- **Source:** 29:42–30:14; old L430–436.
- **Speaker:** mentor.
- **Verbatim:** «То есть, если модель имеет потенциал, но в настоящий момент не раскрывает его полностью,
  это лучше, чем модель, которая изначально показывает отсутствие какого-либо потенциала.»
- **English:** "A model that has potential but doesn't fully show it yet is better than a model that
  shows no potential at all."
- **Notes:** Text confirmed. Speaker changed to mentor.

### REQ-6017 · EVALUATION · corrects the speaker of REQ-4030
- **Source:** 30:14–31:31; old L437–454.
- **Speaker:** mentor. The room then interrupts him at 31:31: «Станислав, Станислав, можно ремарочку
  одну?»
- **Verbatim:** «По поводу грамматики сильно заморачиваться не нужно… И вот эта проверка грамматики нужна
  только в момент оценки работы самого оператора, насколько грамотно он заносит эти сведения, чтобы они в
  первую очередь были понятны следующему … оператору … ДДС … и насколько критичны какие-то, может быть,
  опечатки в названиях улиц или ещё где-то, чтобы он не направил … службы ехать на другой адрес.»
- **English:** "No need to fuss much about grammar… the grammar check matters only when assessing the
  operator's own work: how correctly he enters the information so that the next ДДС operator
  understands it, and how critical typos in street names are, so that services aren't sent to the wrong
  address."
- **Notes:** Text confirmed. Speaker changed to mentor.

### REQ-6018 · DOMAIN-FACT · corrects REQ-4031
- **Source:** 31:31–31:48; old L455–461; G window 31:32; L3 lines 312–316.
- **Speaker:** customer room.
- **Verbatim:** «Станислав, Станислав, можно ремарочку одну? — Конечно. — Просто из опыта вот был случай
  у нас в Москве, например, улица есть Дубнинская, а есть Дубининская. Вот, да. Был случай, когда высылка
  пошла не туда. Вот такие вот варианты.»
- **English:** "Just from experience: there was a case in Moscow, there is Dubninskaya street and there
  is Dubininskaya street. There was a case when a dispatch went to the wrong place."
- **Notes:** W «В тот случай, когда выставка пошла» is not supported. G reads «высылка пошла не туда»,
  L3 «высылка пошла, не то», ctc «высылка пошла».

### REQ-6019 · EVALUATION · corrects REQ-4032
- **Source:** 31:53–32:13; old L463–467; G window 31:54; L3 line 322.
- **Speaker:** customer room.
- **Verbatim:** «В настоящее время такой методики не существует. Мы даём на откуп, скажем так, это
  участникам.»
- **English:** "At present no such [evaluation] methodology exists. We leave it, so to speak, to the
  participants."
- **Notes:** W «Мы даем наоборот» is not supported. G reads «на откуп»; ctc «мы даем н откуп»; L3 «науку».

### REQ-6020 · REQUIREMENT · corrects the speakers of REQ-4033
- **Source:** 34:14–35:46; old L497–521; G windows 34:06–35:34; L3 lines 339–359; sheet C8.
- **Speakers and verbatim:**
  - mentor reads: «…нужно ли моделировать полный жизненный цикл карточки? Принято, не принято, начало
    реагирования, прибытие, проведение работ.»
  - mentor tile (34:34–34:45): «Конечно. Да, здесь… Полностью моделирование полное должно быть.»
  - customer room (34:47–35:46): «…в строке состояния сообщений оператор должен среагировать на неё в
    течение тридцати секунд. То есть это норматив, который определён. По времени исполнения карты, к
    сожалению, здесь заполнения карты нет, но мы давайте установим в течение трёх минут… То есть 30 секунд
    надо нажать для того, чтобы её открыть, и в течение трёх минут её заполнить.»
- **English:** "…the operator must react to it in the message-status row within thirty seconds; that is a
  defined norm. For card completion there is none, but let's set three minutes… 30 seconds to click to
  open it, and fill it in within three minutes."
- **Notes:** Text confirmed by all readings. The speaker who says the lifecycle must be modelled in full
  is not settled: the mentor tile is highlighted alone until 34:45. Sheet C8 asks: «Что означает норматив
  30 секунд — время на установку первичного статуса или выполнение всего задания?»

### REQ-6021 · REQUIREMENT · extends REQ-4034 (content missing from W)
- **Source:** 35:46–36:24; old L522–524 (L522 is a 31-s cue that omits ≈ 29 s of speech); G windows 35:34–
  36:18; L3 lines 359–368.
- **Speakers:** both tiles 35:48–35:59; customer room 36:00–36:11; mentor 36:12–36:15; customer room/
  mentor 36:16–36:24.
- **Verbatim:** «Да, при этом мы понимаем, что может появиться новая карточка, да, событий. — Да,
  появится новая карточка, которая генерируется, да-да. Норматив по-прежнему работает. Многозадач[ность],
  здесь будет интересно решение. Понятно, что не на одну три минуты залипал, а уже стремился для того,
  чтобы другую, другую, другую. — Именно. И вот здесь как раз возникают ошибки и грамматики, и всего на
  свете. — Да-да-да-да. Когда появляется скорость, то появляются и ошибки, да? — Да-да. И мы их должны
  проверять именно с точки зрения того, чтобы особенно критических не было ошибок в адресах и прочих.»
- **English:** "We understand a new card may appear. — Yes, a new card that is generated. The norm still
  applies. Multitasking: an interesting solution is wanted here. He shouldn't get stuck for three minutes
  on one but strive to handle another, and another. — Exactly. And that's where grammar errors and all
  sorts of errors arise. — When speed appears, errors appear. — And we must check them specifically so
  that there are no critical errors, especially in addresses and the like."
- **Notes:** Confirmed by G, L3, R20 and R8.

### REQ-6022 · CONSTRAINT · corrects REQ-4036
- **Source:** 37:14–37:34; old L537–543; G windows 37:02 and 37:24; L3 lines 377–381; sheet C9.
- **Speakers and verbatim:**
  - mentor reads: «Да, какие интеграции с другими системами предполагаются в закрытом контуре без выхода
    в интернет, и е[сть ли] документация?»
  - answer (37:19–37:34, both tiles): «Никаких систем, да, то есть это локалка, всё чисто. Да, всё
    локально без интеграции, то есть, грубо говоря, мы загружаем данные для обучения, вот вы загрузили
    [некий] сервер, и дальше с ним работаем. Всё.»
- **English:** "What integrations with other systems are expected in the closed contour with no internet,
  and is there documentation? — No systems; it's all local, clean. All local, no integration: we load the
  data for training, you've loaded [some] server, and then work with it."
- **Notes:** W «И если документация никаких систем» joins the question and the answer. Sheet C9 ends
  «Есть ли документация по инфраструктуре?». No answer about documentation is given in this exchange.

### REQ-6023 · REQUIREMENT · corrects the speaker of REQ-4037
- **Source:** 37:34–38:13; old L544–553.
- **Speaker:** mentor.
- **Verbatim:** «Да, если мы хотим её дообучить, то это либо от действий самого, допустим, преподавателя,
  то есть он помечает, какие ответы, например, ИИшка пометил как правильные, он считает их неправильными.
  Это как бы тоже локально делается. И если нужно какие-то дополнительные загрузить материалы, новые
  билеты, например, или какую-то методику … это тоже делается локально, и тогда модель дообучается…»
- **English:** "If we want to further train it, that comes either from the teacher's actions (he marks
  answers the AI marked correct as wrong), done locally; or from loading additional materials (new
  tickets, a methodology…), also locally, and then the model is further trained…"
- **Notes:** Text confirmed. Speaker changed to mentor.

### REQ-6024 · REQUIREMENT · corrects REQ-4038 (text and speaker)
- **Source:** 38:08–38:35; old L553–560; G windows 38:08 and 38:30; L3 lines 386–389.
- **Speaker:** mentor.
- **Verbatim:** «…учитывая предыдущий контекст и особенно действия преподавателей, то есть очень важно не
  забывать о них. То есть, если вдруг какая-то история конфликтная, да, там, то преподаватель, он более
  как бы приоритетен и он точно знает, как надо действовать в той либо иной ситуации. Если он отметил это
  неправильным ответом, да, ИИшка всё равно там настаивает на правильности, такого быть не должно.»
- **English:** "…especially the teachers' actions; it is very important not to forget them. If a
  conflicting case arises, the teacher has priority and knows exactly how to act. If he has marked an
  answer wrong and the AI still insists it is right, that must not happen."
- **Notes:** W «очень важно, нет, взбывательных» and «такого не быть не должно» are not supported. G and
  R read «не забывать о них» and «такого быть не должно».

### REQ-6025 · DATA-PROVIDED · corrects the speaker of REQ-4039
- **Source:** 38:34–38:54; old L560–564.
- **Speaker:** mentor (38:34–38:51); then «Полностью подтверждаю, Станислав, правильно» (38:51–38:54).
  That second phrase is spoken while the mentor tile is highlighted but is addressed to «Станислав», so its
  speaker is not settled.
- **Verbatim:** «Документация, соответственно, да, как мы уже говорили, есть руководство, там, методика,
  довольно понятный документ с большим количеством скриншотов и действий самого оператора. Там всё
  расписано по всем действиям. — Полностью подтверждаю, Станислав, правильно.»
- **English:** "Documentation: as we said, there is a manual, a methodology, a fairly clear document
  with many screenshots and the operator's actions, everything spelled out. — I fully confirm, Stanislav,
  correct."
- **Notes:** Text confirmed (W «подтверждаем», G and R «подтверждаю»).

### REQ-6026 · EVALUATION · new attribution (assessment §9.1 row 9 said "speaker not labelled")
- **Source:** 40:42–40:58; old L599–605; G window 40:42; L3 line 418.
- **Speaker:** mentor (mentor tile only, 40:43–40:57).
- **Verbatim:** «Да. А если, соответственно, вы сделаете генерацию всех историй там, например, входящими
  звонками тоже голосовыми, да, там, исходя из каких-то сценариев, да, как будто человек там звонит,
  говорит: «Я попал в ДТП и прочее», это будет… Ну, это будет дополнительная история, это будет хорошо
  оценено тоже.»
- **English:** "And if you generate all the stories as, for example, incoming calls, voiced too, based on
  some scenarios, as if a person calls and says 'I've been in a road accident', that will be an additional
  feature, and it will be rated well too."
- **Notes:** The last words read «хорошо оценено тоже» in e2e (4 windows) and G. W has «хорошо
  оцениваться», L3 «хорошо оценивать».

### REQ-6027 · CLARIFICATION · corrects REQ-4043 (split of speakers)
- **Source:** 40:58–41:49; old L606–620; G windows 41:04 and 41:26; L3 lines 418–424.
- **Speaker:** customer room (40:58–41:49). The first part of REQ-4043's range (old L600–605) is the
  mentor's REQ-6026.
- **Verbatim:** «Ну, хорошо. Нет, дело в том, что реально, реально, да, давайте мы, если на следующий год
  вот эту идею пусть они проработают, потому что вот мы первый раз, как мы первый раз участвуем, да, мы
  взяли маленькую задачку… А в будущем, в будущем или в следующем этапе, или [в] следующе[м нашего
  участия] программы, это предусматривает уже работа именно системы 112. И вот здесь как раз вот генерация
  голоса, происшествия, какого-то заявления, она будет очень нам интересна. Поэтому вопрос остаётся на,
  скажем так, мы сделаем, снимаем как бы этот вопрос. Но он будет возник[ать] как раз именно в следующем
  конкурсе, если вы будете это представлять, будет представляться, да, соответственно, он там должен быть
  реализован, этот момент.»
- **English:** "Well, fine. No, the thing is, really, let them work that idea out next year, because
  this is our first time taking part, we took a small task… In future (the next stage, or our next
  participation) that involves the actual 112 system's work. And there, voice generation of an incident
  report will be very interesting to us. So we'll drop this question for now, but it will come up in the
  next competition, and there it must be implemented."
- **Notes:**
  - «генерация голоса» is confirmed by R20, R8 and L3; the G boundary reads «генерация. / …голосом».
  - L3's «в следующем этапе. В следующем конкурсе» (line 423) has no counterpart in R.

### REQ-6028 · REQUIREMENT · corrects REQ-4044 (speaker split, text)
- **Source:** 41:49–42:28; old L621–633; G windows 41:48 and 42:10; L3 lines 424–428; sheet C10.
- **Speakers and verbatim:**
  - mentor (41:49–42:06): «Также, соответственно, ну, собственно, вопрос продолжается: требуется ли
    интерактивный двусторонний голосовой диалог с ответами на уточняющие вопросы и ветвлением сценария
    или достаточно прослушивания сообщений? Ну, как вы уже сказали, да, достаточно, в принципе,
    прослушанных сообщений. То есть это для минимального объёма более чем достаточно.»
  - customer room (42:06–42:28; the mentor also highlighted 42:06–42:10): «[Ну,] если будут ещё… —
    Не-не, требуется ли … двусторонний голосовой [диалог]? Нет, пока. Давайте мы здесь вообще снимем, то
    есть никаких голосовых диалогов, ну, реально они не ведут. То есть голосовой диалог только, скажем
    так, ДДС — руководитель, которому они будут звонить. Вот и всё. Вот здесь вот можно как-то
    пообщаться интерактивно. То есть это вот первая часть.»
- **English:**
  - mentor: "Is an interactive two-way voice dialogue with clarifying answers and scenario branching
    required, or is listening to messages enough? As you already said, listening to messages is in
    principle enough; for the minimum scope, more than enough."
  - room: "No, no: is a two-way voice [dialogue] required? No, for now. Let's drop that entirely: no
    voice dialogues, they don't really hold them. The only voice dialogue is ДДС to the head they will
    call. That's all. Here you can talk interactively. That's the first part."
- **Notes:** REQ-4044 attributed all of it to the company representative. The sentence «достаточно,
  в принципе, прослушанных сообщений» is the mentor's.

### REQ-6029 · CLARIFICATION · confirms REQ-4045 and settles the L3 variant
- **Source:** 42:28–43:19; old L634–643; G windows 42:10–43:16; L3 lines 429–435.
- **Speaker:** customer room.
- **Verbatim:** «…есть точка А, генерация вызова, это работа 112 и вместе с тем, кто оказался в беде.
  Дальше информация уходит в точку Б, это где работает дежурно-диспетчерская служба, и точка С — это
  конкретно та служба, которая может реагировать на те или иные вызовы … Так вот здесь, [если] в рамках
  вот этой задачи, нас интересует диалог между Б и С. Вот здесь, когда будут звониться по вот этому
  симулятору IP-телефонии. Понятно? Точку А мы пока исключаем. Заявителя. Заявителя, да, и 112 мы пока
  убираем.»
- **English:** "Point A, call generation, is the work of 112 together with the person in trouble; then
  information goes to point B, the dispatch service, and point C, the specific responding service…
  Within this task we are interested in the dialogue between B and C, when they call over this
  IP-telephony simulator. Understood? We exclude point A for now. The caller, yes, and 112 we remove for
  now."
- **Notes:** L3 line 434 «…или по ней понятно . она пока исключаем» is not supported. Both checkpoints
  read «Понятно? Точку А мы пока исключаем» in 5 windows (ctc «точку а мы пока исключаем»). L3 line 400
  («На этапе разработки программного обеспечения заявителя мы исключаем», 39:14) agrees with W, G and R.

### REQ-6030 · CLARIFICATION · new attribution (REQ-4045 range, assessment §9.1 row 12)
- **Source:** 43:19–43:29; old L644–648; G window 43:16; L3 lines 435–436.
- **Speakers and verbatim:**
  - mentor (mentor tile only, 43:20–43:22): «Да. Ну, если коллеги сделают, будет здорово.»
  - both tiles highlighted (43:22–43:29; not settled): «Да, это будет здорово. Да, это, конечно, шикарно
    будет. Это прямо будет [такой вариант], на будущее задел будет. — Да-да.»
- **English:** mentor: "Well, if the colleagues do it, that'll be great." Then either speaker: "Yes, that'll
  be great. Yes, of course, it'll be superb. It will be a groundwork for the future."
- **Notes:** The assessment §9.1 row 12 quotes these sentences as part of the company representative's
  answer. The video shows the first sentence on the mentor's tile.

### REQ-6031 · DATA-PROVIDED · corrects REQ-4048
- **Source:** 44:46–45:23; old L678–685; G windows 44:44 and 45:06; L3 lines 447–451; sheet C12.
- **Speakers and verbatim:**
  - mentor reads: «Следующий вопрос по поводу данных: синтетические данные, обезличивание,
    прогнозирование. Являются ли данные о предоставленных билетах синтетическими или разрешено, и
    разрешено ли показывать их в прототипе и презентации, или [требуется…]?»
  - customer room (45:04–45:23): «Да, пожалуйста, они уже обезличены, поэтому там, значит, информация,
    то есть она в тех билетах, которые есть, она уже обезличена. То есть фактически, да, она уже, то есть
    можно использовать её без всяких без ограничений.»
- **English:** "Are the data in the provided tickets synthetic, and is it allowed to show them in the
  prototype and presentation, or [is de-identification required]? — Yes, please: they are already
  de-identified; the information in the existing tickets is already de-identified; it can be used without
  any restrictions."
- **Notes:**
  - W «предоставленных милициях» is not supported (G «билетах»; sheet C12 «в предоставленных билетах»).
  - Sheet C12 in full: «…и разрешено ли показывать их в прототипе и презентации, или требуется
    обезличивание?».
  - «Да, пожалуйста» is the first reply after the permission question.

### REQ-6032 · CONSTRAINT · corrects the speaker of REQ-4050
- **Source:** 46:34–47:21; old L702–712; G windows 46:34 and 46:56; L3 lines 461–467; sheet C13.
- **Speaker:** mentor (46:52–47:21).
- **Verbatim:** «Здесь только локально у нас, к сожалению, коллеги. То есть сама модель должна быть, может
  быть обучена, например, в облаках, но потом должна быть развёрнута локально, то есть как угодно, но, к
  сожалению, ограничение такое, что у коллег, да, непосредственно в том здании, в том помещении, в тех
  помещениях, где проводится обучение, там всё локально, без выхода вовне. И поэтому эту историю надо
  будет коллегам эксплуатировать только на локальном [сервере].»
- **English:** "Here it's local only, unfortunately. The model may be trained, e.g., in the cloud, but
  must then be deployed locally; the constraint is that at the colleagues' premises where training takes
  place, everything is local with no outside access. So colleagues will have to run it only on a local
  [server]."
- **Notes:** The speaker was "company representative"; the video shows the mentor. The wording «у коллег»
  refers to the customer.

### REQ-6033 · CONSTRAINT · corrects REQ-4051 (split of speakers, missing text)
- **Source:** 47:21–48:35; old L712–735; G windows 47:18–48:24; L3 lines 468–478 (degraded block,
  comparison §3.4).
- **Speakers and verbatim:**
  - customer room (47:21–48:03): «[Сервер] мы можем наш класс подключать к серверу нашему? Или нет? …
    связаться [со] 112 сервер[ом] и подключить, Саш. … К серверу мы можем наш класс подключить к серверу,
    который подключён к Интернету? Можем. … Потому что вот коллега технической подготовки, технической,
    скажем так, нашей части, да, он, в принципе, не вопрос. Мы можем наш класс взять и сделать подключение
    к Интернету. То есть тоже техническая возможность есть. Поэтому тут, как бы, давайте вариант такой,
    что обучаться она может и с помощью интернета, но, соответственно, и локально должно быть работать
    однозначно.»
  - both tiles (48:03–48:11): «Да, но тогда мы понимаем, да, что локальный приоритет, а интернет — это
    уже дополнительно, да.»
  - mentor (48:11–48:35): «Да, и конкурсанты, мы должны понимать, что сейчас всё сделано локально, то есть
    вот та возможность, она гипотетическая, может она не получиться. Так что, да, приоритет именно на
    локалку всё-таки. … Потому что вдруг там какое-то согласование, вдруг какой-нибудь прибежит ДИП с
    какими-нибудь требованиями по ИБ. Всё что угодно может быть, и запретят выходить в интернет. … Так что
    лучше локально.»
- **English:**
  - room: "Can we connect our classroom to our server… the 112 server… to a server that is connected to
    the Internet? We can… Our technical colleague says it's no problem: we can connect our classroom to
    the Internet; the technical possibility exists. So let's say it can train with the help of the
    internet, but it must definitely also work locally."
  - both: "local is the priority, internet is extra."
  - mentor: "contestants should understand that everything is done locally now; that possibility is
    hypothetical and may not work out; priority on local, because an approval or information-security
    requirement could come and internet access could be banned; so better local."
- **Notes:** REQ-4051 attributed all of it to the company representative and began at old L722. W old
  L712–717 is garbled («Отвязаться 112 сервера… Ничего себе»).

### REQ-6034 · DELIVERABLE · corrects the speaker of REQ-4052
- **Source:** 48:46–50:14; old L736–751; G windows 48:46–49:52.
- **Speaker:** mentor (48:46–50:11).
- **Verbatim:** «Ну, короче, это общие вопросы в части конкурса… А я поясню ещё дополнительную такую
  историю, что помимо тех требований, которые у нас указаны в ТЗ в части прототипа, как оно должно быть
  упаковано … отдельная просьба … записать видеопрезентацию вашего продукта, да, там, или просто запись
  с экрана … со звуком … не более пяти минут … Это прямо вот очень сильно рекомендую.»
- **English:** "Defence format is a general contest question… Beyond the ТЗ requirements on packaging,
  a separate request: record a video presentation of your product or a screen recording with sound, no
  longer than five minutes. I very strongly recommend it."
- **Notes:** Text confirmed (W «ТСЗ» = «ТЗ» in G and L3). Speaker changed to mentor. Sheet C14 is the
  question.

### REQ-6035 · DELIVERABLE · corrects the speaker of REQ-4053
- **Source:** 50:14–50:52; old L751–757; G windows 50:14 and 50:36; L3 lines 490–495.
- **Speaker:** mentor.
- **Verbatim:** «…все требования указаны в ТЗ, в принципе. Есть вот там вопрос: допустима ли отдельная
  интернет-демо-версия на синтетических данных? [О] нет, да? То есть вы просто предоставите ссылочку, мы
  там потыкаемся с удовольствием, да, там. Но минимальные требования к самому пакету, да, там, к MVP, как
  он должен быть упакован, в ТЗ указаны, это должно быть соблюдено, это обязательное требование самого
  ЛЦТ. Всё, что допом вы сделаете, будет здорово, классно. Любые возможности потыкать заказчику в разные
  форматы, там хоть видео запустить, хоть демо-версию, приветствуется однозначно.»
- **English:** "Is a separate internet demo on synthetic data allowed? … You just provide a link, we'll
  gladly click around. But the minimum package requirements for the MVP in the ТЗ must be met; that is a
  mandatory requirement of the LCT itself. Anything extra is great; any way for the customer to try it in
  different formats (video, demo) is definitely welcome."
- **Notes:** Speaker changed to mentor. The first word of «[О] нет, да?» is not settled (W and L3 «О,
  нет, да», G «Впо нет», e2e «О нет / Внет», ctc «помоу нет»).

### REQ-6036 · CLARIFICATION · corrects REQ-4054
- **Source:** 50:52–51:34; old L758–766; G windows 50:58 and 51:20; L3 lines 498–506; sheet C15.
- **Speakers and verbatim:**
  - mentor (50:52–51:10): «Назначение и использование билетов. Значит, что представляет собой 96
    билетов: готовые эталонные учебные сценарии или основу для генерации новых? Ну, основа для генерации
    новых, но можно использовать и эталонные, то есть как [и] захотите. Здесь вопрос, в принципе.»
  - customer room (51:11–51:34): «Ну, в принципе, да, подтверждаем. То есть тут поле деятельности
    широкое. То есть хотите — генерируйте новые, да, исходя из жизненного опыта, исходя из жизненных,
    скажем так, ситуаций, в которых встречаетесь вы, ваши родственники какие-нибудь, знакомые, либо уже
    взять … которые наработаны нами в учебном процессе. Тут и то, и то приветствуется.»
- **English:**
  - mentor: "What are the 96 tickets: ready reference scenarios or a base for generating new ones? A base
    for generating new ones, but you can also use the reference ones, as you like."
  - room: "In principle, yes, we confirm: a wide field of action; generate new ones from life experience
    and situations you or your relatives meet, or take the ones we have developed in the training process.
    Both are welcome."
- **Notes:** W «основу от регенерации» and «не рыпите новые» are not supported. The proposed answer is
  the mentor's; the customer room confirms it. The number 96 is in the question as read and on the sheet.

### REQ-6037 · EVALUATION · corrects the speaker of REQ-4055
- **Source:** 51:33–52:26; old L766–772; G windows 51:20–52:04; L3 lines 506–514.
- **Speaker:** mentor (the host interrupts at 51:41: «Коллеги, осталось 10 минут, поэтому чуть-чуть
  нужно ускориться»).
- **Verbatim:** «Да, будут ли эксперты проверять систему на заранее подготовленных билетах или смогут
  создавать произвольные сценарии? … Да, давайте тогда на этом вопросе, на пятнадцатом, остановимся, не
  успели до двадцати. … Здесь, короче, скорее всего, произвольный сценарий, потому что, в принципе, по
  заготовленным как бы, конечно, проще и так далее, да, но мы будем оценивать именно творческий подход и
  насколько система, как я уже говорил выше, в принципе, и правильно генерирует, да, правильно
  интерпретирует, и правильно подсвечивает правильные-неправильные истории. … Хотя, конечно же, в
  качестве эталонных историй мы сможем проверить на заранее подготовленных билетах, которые у вас также
  будут в наличии, то есть у вас там есть правильные ответы.»
- **English:** "Will experts test on the prepared tickets or create arbitrary scenarios? … Most likely
  arbitrary scenarios, because prepared ones are easier; we will evaluate precisely the creative approach
  and how correctly the system generates, interprets and highlights right and wrong stories… though as
  reference stories we can check on the prepared tickets, which you will also have, with correct answers."
- **Notes:** Text confirmed (W «сморческий подход» = «творческий»). Speaker changed to mentor.

### REQ-6038 · CLARIFICATION · corrects the speaker of REQ-4060
- **Source:** 55:06–55:37; old L795–798.
- **Speaker:** mentor.
- **Verbatim:** «Да, MVP: собственная ML-модель или готовые инструменты. В целом всё равно, коллеги, как
  вы сделаете, то есть сами обучите или там будете использовать что-то своё, но понимайте, что в целом вам
  потом, скорее всего, придётся развернуть её локально. Если у коллег получится там сделать доступ в
  Интернет, это будет вообще здорово, да, но скорее всего, всё равно ориентируйтесь на то, что эту модель
  вам придётся … развернуть … локально.»
- **English:** "Own ML model or ready tools: it doesn't matter how you do it… but you'll most likely have
  to deploy it locally. If the colleagues manage internet access, great, but plan on deploying locally."
- **Notes:** Text confirmed. Speaker changed to mentor.

### REQ-6039 · EVALUATION · corrects the speaker of REQ-4061
- **Source:** 55:37–56:30; old L799–809; sheet C19.
- **Speaker:** mentor.
- **Verbatim:** «А при оценке решений, да, чему эксперты придают больший вес? Вопрос: оригинальности
  концепции или глубине технической реализации? Коллеги будут воспринимать это решение как, насколько это
  похоже тому, вот что они озвучивали в качестве видения. То есть оригинально или технически проработано,
  всё равно, если просто модель похожа, выдаёт правильные ответы, помогает преподавателю, это хорошо. …
  А оригинальность, неоригинальность — это уже второстепенно.»
- **English:** "When evaluating, what do experts weight more: originality or technical depth? The
  colleagues [the customer] will judge how close it is to what they described as their vision… original
  or technically deep doesn't matter; if the model resembles it, gives correct answers and helps the
  teacher, that's good… Originality is secondary."
- **Notes:** Text confirmed. Speaker changed to mentor; «Коллеги будут воспринимать» refers to the
  customer.

### REQ-6040 · CONSTRAINT · corrects the speaker of REQ-4062 and settles a number
- **Source:** 56:28–57:44; old L809–819; G windows 56:28–57:34; L3 lines 558–569; sheet C20.
- **Speaker:** mentor.
- **Verbatim:** «Там, в принципе, ТЗ всё указано точно … Проверять их, скорее всего, вряд ли будут прямо
  сильно на высокой нагрузке. Но вы должны понимать, что как только там … если 10 человек подключилось …
  и вдруг она отваливается … это печально. Когда мы её будем запускать там на учебном процессе, там в
  классе там 20–30 человек, да, она должна тоже работать. … если будет, допустим, 99 вместо 100, ну,
  скорее всего, немного на это закроем глаза. Но если отваливаться при 10 одновременных, то это будет
  печально.»
- **English:** "The ТЗ states it precisely… load is unlikely to be tested hard, but if 10 people connect
  and it falls over, that's sad; in class with 20–30 people it must work; 99 instead of 100 we'll probably
  overlook, but falling over at 10 concurrent would be sad."
- **Notes:**
  - «99 вместо 100»: W, L3 and R (both checkpoints) agree. G's «99 вместо 10» is a 22-s boundary cut.
  - Speaker changed to mentor. Sheet C20 names «100 пользователей, 20 одновременных сессий».

### REQ-6041 · REQUIREMENT · corrects REQ-4063
- **Source:** 57:53–59:27; old L821–836; G windows 57:56–59:24; L3 lines 573–587; sheet C21.
- **Speaker:** customer room from 57:59 («Станислав, я отвечу на этот вопрос»). The preceding «В общем, здесь уже детали» (57:56) is the mentor.
- **Verbatim:** «…то искусственный интеллект должен предложить преподавателю, ну, скажем, предложить, что
  это вот то, что он сгенерировал, будет касаться там, стоить десять баллов там, да? Или пять баллов, или
  шесть — это вот этого предложения. Ну и последняя часть: допустимо ли реализовать обучение только для
  некоторых приоритетных с возможностью масштабирования? Ну, я думаю, здесь, да…»
- **English:** "…the AI should propose to the teacher that what it generated is worth, say, ten points,
  or five, or six… And the last part: is it permissible to implement training only for some priority
  [services] with scalability? Well, I think, yes…"
- **Notes:** W «100 и 10 баллов» is not supported; G, L3, e2e and ctc read «стоить 10 баллов». «допустимо ли
  реализовать…» is the question being read (sheet C21), not a statement.

### REQ-6042 · CONSTRAINT · new; corrects the wording in assessment §9.2 row 20 and SRC-002-003-video Conflicts §1
- **Source:** 61:45–62:27; old L870–882; G windows 61:36–62:20; L3 lines 616–631.
- **Speakers and verbatim:**
  - customer room (61:45–62:03): «Ну, наверное, это Александр Сергеевич ответит техническую часть. …
    [Можно], в принципе, если так будет критично, потому что, ну, как бы время — деньги, да, и ждать там
    минуту, да… Конечно, хотите, используйте видеокарту. Не вопрос.»
  - participant «Вадим Золотарев» (62:03–62:06): «Нет, здесь вопрос про то, что сможете ли вы
    поставить…»
  - customer room (62:06–62:27): «Если мы используем видеокарту, если они предложат некое техническое
    решение, внедрить в наш сервер, мы можем внедрить видеокарту? — Ну, не видеокарты именно. — Ну,
    почему нет? Ну, соответственно, закупим новое оборудование. Ну вот, то есть возможности закупки есть,
    такое, да? [Новое оборудование] будет соответствовать вашим возможностям.»
- **English:**
  - room: "…if it's that critical (time is money, waiting a minute…), of course, use a GPU if you want.
    No problem."
  - participant: "No, the question is whether you can install one…"
  - room: "If we use a GPU, if they propose some technical solution to put into our server, can we fit a
    GPU? — Well, not GPUs as such. — Why not? We'll buy new equipment then. There is the possibility to
    purchase. It will match your capabilities."
- **Notes:** W and L3 «Конечно, мы используем видеокарту…» are not supported. Both checkpoints read
  «[е]сли мы использ…», the ctc checkpoint in 4 windows. W «на вопрос» reads «Не вопрос» (e2e, ctc).

### REQ-6043 · EVALUATION · new attribution (SRC-002-003-video Conflicts §2; assessment §9.2 row 21)
- **Source:** 63:21–64:02; old L892–900; G windows 63:04–63:48; L3 lines 642–650.
- **Speaker:** mentor (the participant spoke at 62:54–63:21).
- **Verbatim:** «Это понятно. Я имею в виду, что, смотрите, то есть вы можете сгенерировать вопросы-ответы
  до того, как, то есть не в онлайне это делать, а на основе материалов сгенерировать вопросы-ответы и
  всё. И обучающиеся будут выбирать там ответы из предоставленных, ну, в смысле, не выбирать ответы, да,
  там выбирать действия, а модель[ка] уже потом будет это оценивать исходя из предзаполненных некоторых
  критериев. Вот это как бы нормальная история. А если она будет каждый раз индивидуально оценивать в
  моменте, то да, это высоконагруженная будет история, и, скорее всего, не взлетит, и мы в тайминг в 30
  секунд не попадём. Я про это.»
- **English:** "I mean you can generate question-answer sets beforehand, not online, from the materials;
  trainees choose actions, and the model then evaluates them against pre-filled criteria. That's a normal
  approach. If it evaluates each one individually in the moment, that's a high-load story, most likely
  won't fly, and we won't meet the 30-second timing. That's what I mean."
- **Notes:** The earlier files give the speaker as "organizer". The video shows the mentor. The 30-second
  norm itself (REQ-4033/REQ-6020) was stated by the customer room.

### REQ-6044 · CLARIFICATION · new
- **Source:** 62:28–62:54; old L883–887; G windows 62:20 and 62:42; L3 lines 632–636.
- **Speaker:** mentor (the participant interjects at 62:34–62:37: «[Не обучение, это] инференс — это
  использование»).
- **Verbatim:** «Да, смотри, если вы модель обучили, да, вы её можете обучить там у себя где-то, а потом,
  допустим, загрузить. А вот до обучения [sic; «дообучение» not settled], если оно будет длиться минуты,
  это нормально, потому что, ну, это преподаватель по результатам обучения там обучает эту модель, да, и
  она там [пере…].»
- **English:** "If you've trained the model, you can train it at your place and then load it. But the
  further training, if it takes minutes, is fine, because it's the teacher training this model on the
  results of the training [sessions]."
- **Notes:** All readings write «до обучения».

### REQ-6045 · CONSTRAINT · new
- **Source:** 64:02–64:29; old L900–905; G windows 63:48 and 64:10; L3 lines 650–655.
- **Speaker:** mentor.
- **Verbatim:** «То есть, грубо говоря, надо понимать, что да, есть некоторые ограничения. Если коллеги их
  обойдут с точки зрения техники и смогут пробить каналы там с локального сервера вовне, это будет
  хорошо. Но пока на текущий момент … текущее состояние дел. Вот. Если вдруг получится, будет здорово, но,
  скорее всего, это всё равно затянется на какое-то время.»
- **English:** "There are some constraints. If the colleagues get around them technically and manage to
  open channels from the local server to the outside, that'd be good. But for now, as things stand… if it
  works out, great, but most likely it will take some time anyway."

### REQ-6046 · CLARIFICATION · new attribution (assessment §9.1 row 13)
- **Source:** 64:30–65:18; old L906–917; G windows 64:32 and 64:54; L3 lines 656–664.
- **Speakers and verbatim:**
  - participant «Вадим Золотарев» (context), 64:30–64:58: «Вот вы расписали сценарий, которому мы заранее
    генерируем. И этот сценарий уже наши коллеги, вот, которые под аккаунтом Александр Ш. сидят,
    опровергли. То есть телефония должна генерироваться автоматически …, то есть у неё есть тема, как они
    сказали. И благодаря этой теме наша модель должна подстраиваться под диалог.»
  - **mentor**, 65:00–65:10: «Мы пояснили. То есть коллеги как раз сказали, что нет, не надо, потому что
    это сложно, и это будет, скорее всего, на втором-третьем этапе там, и может быть, там в следующем.»
- **English:**
  - participant: "You described a scenario we generate in advance, and our colleagues under the account
    'Aleksandr Sh.' refuted it: telephony must be generated automatically, it has a topic, and our model
    must adapt to the dialogue."
  - mentor: "We explained: the colleagues said precisely that no, it's not needed, because it's complex,
    and it will most likely be at the second or third stage, maybe the next one."
- **Notes:** W «коллеги как раз вам сказали» adds «вам»; G, L3 and R omit it. The answer is on the mentor's
  tile (65:01–65:12); the participant's tile is highlighted before and after.

### REQ-6047 · CLARIFICATION · new
- **Source:** 65:28–65:43; old L918–921; G windows 65:16 and 65:38; L3 lines 664–667.
- **Speaker:** host «Михей Модератор».
- **Verbatim:** «Вопрос, на который не хватило, мы зафиксировали и передадим компании-постановщику, ответ
  опубликуем в общем чате. Всем спасибо, всем удачных решений. Сессия завершена.»
- **English:** "The question[s] we didn't have time for, we have recorded and will pass to the task-setting
  company; the answer will be published in the general chat. Thank you all, good solutions to everyone.
  The session is over."
- **Notes:** L3's final «Спасибо вам огромное.» has no counterpart in R.

---

## 3. All REQ-4001–REQ-4063 against the recording

Verdicts:

- **confirmed**: the quote matches the best-supported reading, apart from filler words.
- **corrected**: the text or the speaker differs materially; see the REQ-6xxx item.
- **not locatable**: not used; every item was located.

Times come from W's timestamps for the cited lines (`whisper-timestamps/Город 9.srt`). Speaker notation is
as in §1 ("room" = customer room).

| REQ | Verdict | Time | Speaker (video) |
|---|---|---|---|
| REQ-4001 | corrected → REQ-6001 («пожарной безопасности») | 03:14–03:28 | host «Михей Модератор» |
| REQ-4002 | confirmed | 04:52–05:03 | host |
| REQ-4003 | confirmed (answer); question context corrected → REQ-6004 | 08:48–10:08 | question read by mentor 08:48–09:20; answer room 09:20–10:08 |
| REQ-4004 | confirmed | 10:35–10:46 | room |
| REQ-4005 | corrected → REQ-6005 | 10:48–11:11 | mentor reads question and says «симуляция вполне достаточно»; room «только симуляция» |
| REQ-4006 | corrected → REQ-6006 | 11:12–11:34 | mentor / room / mentor tile |
| REQ-4007 | corrected → REQ-6007 (start lost, REQ-6003) | 12:46–13:14 | room |
| REQ-4008 | confirmed | 14:06–14:43 | room |
| REQ-4009 | corrected → REQ-6008 | 14:43–15:13 | **mentor** |
| REQ-4010 | corrected → REQ-6009 | 15:13–15:26 | **mentor** |
| REQ-4011 | confirmed | 15:28–15:47 | question read by mentor; answer room 15:35–15:47 |
| REQ-4012 | confirmed | 16:01–16:34 | room |
| REQ-4013 | confirmed (speaker refined) | 16:38–17:22 | mentor 16:37–16:52 («это даёт некоторую свободу… материалы, которые вы предоставляете»), room 16:54–17:22 |
| REQ-4014 | confirmed (speaker refined) | 17:47–18:23 | room 17:46–18:06; mentor 18:06–18:29 (incl. reading «требуется реализовать оба режима…»); room 18:29–18:48 |
| REQ-4015 | confirmed | 19:00–20:34 | room |
| REQ-4016 | confirmed | 20:31–21:42 | room |
| REQ-4017 | confirmed (L3's «на втором этапе хакатона» rejected) | 21:42–22:54 | room |
| REQ-4018 | confirmed | 23:01–23:45 | room |
| REQ-4019 | confirmed | 23:51–24:11 | room |
| REQ-4020 | corrected (speaker, quote extended) → REQ-6010 | 24:16–24:42 | **mentor** |
| REQ-4021 | corrected (speaker) → REQ-6011 | 24:43–25:03 | **mentor** |
| REQ-4022 | confirmed | 25:21–25:53 | room |
| REQ-4023 | confirmed (speaker refined) | 25:54–26:12 | mentor 25:53–26:02; room 26:02–26:12 |
| REQ-4024 | corrected (speaker) → REQ-6012 | 26:39–27:05 | **mentor** |
| REQ-4025 | corrected (speakers, wording) → REQ-6013 | 26:13–27:34 | room 26:12–26:16; **mentor** 26:16–27:25 |
| REQ-4026 | confirmed | 27:26–27:47 | room |
| REQ-4027 | corrected (speaker) → REQ-6014 | 28:19–29:03 | **mentor** |
| REQ-4028 | corrected (speaker) → REQ-6015 | 29:04–29:42 | **mentor** |
| REQ-4029 | corrected (speaker) → REQ-6016 | 29:46–30:14 | **mentor** |
| REQ-4030 | corrected (speaker) → REQ-6017 | 30:14–31:13 | **mentor** |
| REQ-4031 | corrected → REQ-6018 | 31:13–31:48 | mentor 31:13–31:31 (lead-in); room 31:31–31:48 (the anecdote) |
| REQ-4032 | corrected → REQ-6019 | 32:06–34:14 | room |
| REQ-4033 | confirmed text; speakers → REQ-6020 | 34:24–35:45 | mentor reads question and mentor tile 34:34–34:45; room 34:47–35:46 |
| REQ-4034 | corrected (W omission) → REQ-6021 | 35:46–36:23 | both tiles / room / mentor |
| REQ-4035 | confirmed («формат 112», W «по 12») | 36:45–37:14 | room |
| REQ-4036 | corrected → REQ-6022 | 37:18–37:34 | mentor reads; answer both tiles |
| REQ-4037 | corrected (speaker) → REQ-6023 | 37:34–38:13 | **mentor** |
| REQ-4038 | corrected → REQ-6024 | 38:13–38:39 | **mentor** |
| REQ-4039 | corrected (speaker) → REQ-6025 | 38:34–38:51 | **mentor** |
| REQ-4040 | confirmed | 39:13–40:19 | room (question read by mentor 38:54–39:09) |
| REQ-4041 | confirmed («кому она там звонит»; W «бы») | 40:06–40:19 | room |
| REQ-4042 | confirmed (except «минимальная потребность», not settled) | 40:24–40:41 | room (40:19–40:23 both tiles) |
| REQ-4043 | corrected (speaker split) → REQ-6026, REQ-6027 | 40:42–41:49 | **mentor** 40:42–40:58; room 40:58–41:49 |
| REQ-4044 | corrected → REQ-6028 | 41:54–42:25 | **mentor** 41:49–42:06; room 42:06–42:28 |
| REQ-4045 | confirmed → REQ-6029; the following lines → REQ-6030 | 42:27–43:18 | room |
| REQ-4046 | confirmed | 43:40–43:46 | mentor reads; «Ну, конечно же, офлайн» 43:40 both tiles; «Только офлайн… в центре обучения» room |
| REQ-4047 | confirmed | 43:55–44:46 | room |
| REQ-4048 | corrected → REQ-6031 | 44:56–45:22 | mentor reads; answer room 45:04–45:23 |
| REQ-4049 | confirmed | 45:28–46:27 | room |
| REQ-4050 | corrected (speaker) → REQ-6032 | 46:53–47:23 | **mentor** |
| REQ-4051 | corrected (speakers, missing lead-in) → REQ-6033 | 47:53–48:36 | room 47:21–48:03; both 48:03–48:11; **mentor** 48:11–48:35 |
| REQ-4052 | corrected (speaker) → REQ-6034 | 48:55–50:11 | **mentor** |
| REQ-4053 | corrected (speaker) → REQ-6035 | 50:15–50:50 | **mentor** |
| REQ-4054 | corrected → REQ-6036 | 51:00–51:34 | **mentor** (answer proposed); room (confirmation) |
| REQ-4055 | corrected (speaker) → REQ-6037 | 51:33–52:26 | **mentor** |
| REQ-4056 | confirmed (speaker refined) | 52:35–52:53 | room 52:35–52:47; mentor tile highlighted 52:47–52:53 («Просто двухфакторка, да…», with the room partly) |
| REQ-4057 | confirmed (speaker refined) | 53:11–53:58 | mentor 53:10–53:21 («по отчётности… кто в лидерах…»); room 53:21–53:58 («Ну, как мы и сказали, да, Станислав, значит, критерии должны быть…») |
| REQ-4058 | confirmed (speaker refined) | 53:59–54:55 | mentor 53:58–54:04 («удалённый контроль — это просто фактически преподаватель сидит и в онлайне видит»); room 54:04–54:55 («нет, не онлайн…») |
| REQ-4059 | confirmed | 54:22–54:55 | room |
| REQ-4060 | corrected (speaker) → REQ-6038 | 55:12–55:37 | **mentor** |
| REQ-4061 | corrected (speaker) → REQ-6039 | 55:38–56:28 | **mentor** |
| REQ-4062 | corrected (speaker) → REQ-6040 | 56:43–57:43 | **mentor** |
| REQ-4063 | corrected → REQ-6041 | 58:00–60:09 | room from 57:59 (question read by mentor to 57:58) |

Totals:

| Verdict | Items | Notes |
|---|---|---|
| confirmed | 29 | 6 marked "speaker refined": the speaker is split into mentor and room parts |
| corrected | 34 | 19 of them wholly or partly for the speaker |
| not locatable | 0 | — |

---

## 4. Conflicts and changes over time

All statements below are from the same session. The recording shows no date; the chat dates the session
16.09.2026, 11:00 MSK (assessment §1.3). "Earlier/later" means position in the recording.

1. **GPU.**
   - REQ-4003, 09:20–10:08, room: «никаких тут, скажем так, требований к видеокарте, ну, скажем, сильных
     нет… проверка решений, ну, на стандартных бытовых компьютерах».
   - REQ-6042, 61:59–62:27, same room tile: «Конечно, хотите, используйте видеокарту. Не вопрос.» and
     «закупим новое оборудование… возможности закупки есть».
   - The later exchange also contains the room's question «Если мы используем видеокарту… мы можем
     внедрить видеокарту?», not the affirmation «Конечно, мы используем» found in W and L3.
2. **The 30-second norm vs real-time AI evaluation.**
   - REQ-6020 (= REQ-4033 text), 34:47–35:46, room: 30 s to react, 3 min to fill the card.
   - REQ-6043, 63:21–64:02, **mentor**: individual evaluation «в моменте» «скорее всего, не взлетит, и мы
     в тайминг в 30 секунд не попадём»; pre-generated question-answer sets are described as «нормальная
     история».
   - The two statements come from different speakers.
3. **Caller voice / point A.** In order:
   - 24:16, mentor: «генерируется звонок якобы голосовой о каком-то событии» (REQ-6010).
   - 39:07–39:22, room: «заявителя мы исключаем… никаких заранее подготовленных записей, голосов нет»
     (REQ-4040).
   - 40:42–40:58, **mentor**: incoming voice calls «будет дополнительная история, это будет хорошо оценено
     тоже» (REQ-6026).
   - 40:58–41:49, room: «на следующий год… снимаем как бы этот вопрос… в следующем конкурсе… он там должен
     быть реализован» (REQ-6027).
   - 41:58–42:06, **mentor**: «достаточно, в принципе, прослушанных сообщений».
   - 42:06–42:28, room: «Нет, пока. Давайте мы здесь вообще снимем, то есть никаких голосовых диалогов…
     голосовой диалог только… ДДС — руководитель» (REQ-6028).
   - 43:10–43:19, room: «Точку А мы пока исключаем… и 112 мы пока убираем» (REQ-6029).
   - 43:20–43:22, **mentor**: «Ну, если коллеги сделают, будет здорово»; 43:22–43:29, both tiles: «шикарно
     будет… на будущее задел» (REQ-6030).
   - 65:00–65:10, **mentor**: «коллеги как раз сказали, что нет, не надо, потому что это сложно… на
     втором-третьем этапе… может быть, в следующем» (REQ-6046).
   - The room's statements exclude point A. The mentor's statements at 40:42 and 43:20 describe it as a
     well-rated extra.
4. **Internet.**
   - REQ-6032, 46:52–47:21, mentor: «Здесь только локально у нас, к сожалению».
   - REQ-6033, 47:21–48:03, room: «Мы можем наш класс взять и сделать подключение к Интернету… техническая
     возможность есть… обучаться она может и с помощью интернета, но… и локально должно быть работать
     однозначно».
   - REQ-6033, 48:11–48:35, mentor: «та возможность она гипотетическая… приоритет именно на локалку».
   - REQ-6038, 55:21–55:37, mentor: «Если у коллег получится там сделать доступ в Интернет, это будет
     вообще здорово… всё равно ориентируйтесь… локально».
   - REQ-6045, 64:02–64:29, mentor: «смогут пробить каналы… вовне, это будет хорошо… затянется».
5. **Creativity vs originality** (both statements are the mentor's).
   - REQ-6037, 51:59–52:06: «мы будем оценивать именно творческий подход».
   - REQ-6039, 56:24: «оригинальность, неоригинальность — это уже второстепенно».
   - The room at 27:34–27:47 (REQ-4026): «чтобы была своя идея, какая-то изюминка».
   - Outside this recording, `IMG_2549.MP4` (REQ-4083): «Нам важен ваш творческий подход».
6. **Real vs de-identified data.** REQ-6031, 45:04, room: «Да, пожалуйста, они уже обезличены… можно
   использовать её без всяких без ограничений». This is unchanged against REQ-4083 (`IMG_2549.MP4` «От нас
   реальные данные»).
7. **Contradictions that came from the transcripts, not the speakers.**
   - REQ-4005's self-contradiction («Обязательно не на защите демонстрируйте… недопустимо программная
     эмуляция» followed by «только симуляция») is W's mis-transcription of the question being read
     (REQ-6005).
   - L3's «на втором этапе хакатона» (21:47) and «мы уложились в два вопроса» (60:09) are not in the
     audio.
