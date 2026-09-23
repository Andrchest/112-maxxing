# Evidence: IMG_2549.MP4 — transcript and frame descriptions

Source file: `requirements/sources/01-qna-session-telegram/video_files/IMG_2549.MP4` (59 MB, portrait
720x1280, h264/aac, duration 00:02:34.43, 25 fps).

## Provenance (from `requirements/sources/01-qna-session-telegram/messages.html`)

- The chat export's title (page header) is: "Задача #9 | Департамент по делам гражданской обороны,
  чрезвычайным ситуациям и пожарной безопасности | ЛЦТ 26" — i.e. this whole `messages.html` is the
  Telegram group chat for Task #9.
- `message34` (`id="message34"`) in that chat contains the video. It is a **forwarded** message:
  - Forwarded from: "ЛЦТ 2026 | Хакатон", originally posted 06.08.2026 17:54:55 (UTC+03:00).
  - Posted into the Task #9 chat by "Задача #9 | Департамент по делам гражданской обороны,
    чрезвычайным ситуациям и пожарной безопасности | ЛЦТ 26" (the task-channel account itself) at
    06.08.2026 19:05:10 (UTC+03:00).
  - The message was then pinned in the chat (`message35`: "... pinned this message").
  - Video duration shown in the export: `02:34`, thumbnail `IMG_2549.MP4_thumb.jpg` — matches the
    file (`00:02:34.43`).
- Accompanying text (verbatim, from the `text` div of `message34`):
  > **Создай ИИ-тренажёр для диспетчеров системы 112** ⭐️
  >
  > Задача от города №9 от Департамента по делам гражданской обороны, чрезвычайным ситуациям и
  > пожарной безопасности города Москвы.
  >
  > ➡️ **Что нужно сделать?**
  >
  > Разработать учебный симулятор для подготовки диспетчеров экстренных служб системы 112. Сервис
  > должен с помощью искусственного интеллекта генерировать реалистичные сообщения о происшествиях,
  > моделировать различные сценарии и помогать оценивать, насколько правильно специалист реагирует на
  > ситуацию.
  >
  > ➡️ **Почему это важно?**
  >
  > > От работы диспетчера часто зависят здоровье и жизнь людей. Москве нужен инструмент, который
  > > позволит обучать специалистов в условиях, максимально приближенных к реальным, и делать это
  > > системно и безопасно. У задачи высокий потенциал внедрения: аналогичных решений такого уровня
  > > практически нет, а сам продукт может стать уникальным ИИ-симулятором для экстренных служб.
  >
  > Призовой фонд задачи:
  > 🥇 1 000 000 ₽ — 1 место
  > 🥈 600 000 ₽ — 2 место
  > 🥉 400 000 ₽ — 3 место
  >
  > [Подавай заявку на хакатон «Лидеры цифровой трансформации»](https://i.moscow/lct?utm_source=smm&utm_medium=social&utm_campaign=lc)
  > и попробуй создать решение, которое поможет готовить специалистов для одной из самых важных
  > городских систем!
  >
  > 📎 ЛЦТ в [VK](https://vk.com/leaders_hack)
  >
  > #Задачи

  English (faithful rendering): "Create an AI trainer for 112-system dispatchers. Task from city
  challenge #9, from the Moscow Department for Civil Defense, Emergency Situations and Fire Safety.
  What needs to be done? Develop a training simulator for preparing dispatchers of the 112 system's
  emergency services. The service must, using artificial intelligence, generate realistic incident
  messages, simulate various scenarios, and help assess how correctly a specialist responds to a
  situation. Why does it matter? A dispatcher's work often determines people's health and life.
  Moscow needs a tool that trains specialists under conditions as close to real as possible, and does
  so systematically and safely. The task has high deployment potential: there are practically no
  analogous solutions of this caliber, and the product itself could become a unique AI simulator for
  emergency services. Prize fund: 1,000,000 RUB — 1st place; 600,000 RUB — 2nd place; 400,000 RUB —
  3rd place. [Apply to the hackathon "Leaders of Digital Transformation"] and try to create a
  solution that will help train specialists for one of the city's most important systems! LCT on VK.
  #Tasks"

Conclusion: the video is **not** a recording of the Q&A session referenced elsewhere (that session
is a separate meeting, transcribed in `Город 9.txt`). It is a short promotional/recruitment video for
Task #9, produced and distributed by the organizer's own hackathon channel ("ЛЦТ 2026 | Хакатон") and
re-posted/pinned by the Task #9 channel.

## Method

- Audio extracted with `ffmpeg -i IMG_2549.MP4 -ar 16000 -ac 1 audio.wav` (16 kHz mono PCM).
- Audio split into ≤20 s windows with `ffmpeg -f segment -segment_time 20 -c copy` (8 chunks,
  0.0–154.4 s).
- Transcribed on CPU (GPU lock not taken — CPU sufficed for this short clip) with the repo's real
  GigaAM provider: `backend/app/inference/asr/gigaam_provider.py` `GigaAMProvider`, checkpoint
  `models/gigaam-v3-e2e_ctc`, `model_version="v3_e2e_ctc"`, `device="cpu"`, run via
  `cd /home/andreipc/112-maxxing && uv run python <script using GigaAMProvider>`. Confidence is the
  provider's own `ctc_confidence` (mean per-frame max-softmax probability over non-blank CTC frames).
- Frames sampled every ~10 s with `ffmpeg -vf fps=0.1` (15 frames, 10 s–150 s) and viewed directly.

## Audio transcript (per ≤20 s chunk, GigaAM v3 e2e_ctc, CPU, greedy CTC decode)

| Window | Chunk file | Confidence | Text (ru, as decoded — GigaAM's plain-punctuation output) |
|---|---|---|---|
| 0.0s–20.1s | chunk_000.wav | 0.970 | Ежедневно в Москве происходит много ситуаций, где требуется оперативная помощь людям, от которой зависит их здоровье и жизнь. Здравствуйте. Я старший преподаватель кафедры гражданского. |
| 20.1s–40.1s | chunk_001.wav | 0.971 | Гражданской обороны учебно-методического центра ГОЧС города Москвы Ощаулов Виктор Кимович. В соответствии с Федеральным законодательством, постановлениями Правительства Российской Федерации, помощь людям в происшествиях и чрезвычайных ситуациях должна оказываться максимально оперативно. Чтобы сохранить им жизнь |
| 40.1s–60.0s | chunk_002.wav | 0.978 | ...жизнь и здоровье, а также их имущество. Наш учебно-методический центр ГО ЧС является единственным учебным заведением в городе Москве, которое готовит специалистов-диспетчеров для всех экстренных оперативных служб города. Это люди, которые высылают необходимые службы и специ... |
| 60.0s–80.0s | chunk_003.wav | 0.981 | Специалистов на место происшествий, контролируют качество оказания помощи, информируют руководство о происшествиях в чрезвычайных ситуациях и передают необходимую информацию в другие службы и организации. Для реализации задач по подготовке таких специалистов нам |
| 80.0s–100.1s | chunk_004.wav | 0.990 | Необходимо с вашей помощью разработать учебный симулятор подготовки диспетчеров экстренных служб города по вызовам системы 112, который позволял бы учить специалистов диспетчерских служб действовать самостоятельно, который с помощью искусственного интеллекта генерировал бы сообщения о происшествиях. |
| 100.1s–120.1s | chunk_005.wav | 0.978 | А также производил независимую оценку действий обучаемого и качества его обучения. От нас реальные данные. От вас решение этой непростой, но очень важной задачи, которая позволит улучшить жизнь города и жителей Москвы. Нам важен ваш творческий подход… |
| 120.1s–140.0s | chunk_006.wav | 0.991 | Решение такой задачи, как обучение специалистов диспетчерских экстренных служб города. Аналогов таких продуктов нет, потому он будет уникальным для вас и для нас. А опыт, полученный в разработке такого симулятора, можно распространить на все регионы страны. Это отличный шанс стать лидерами в направлении развития оперативных экстренных служб. |
| 140.0s–154.4s | chunk_007.wav | 0.987 | Приглашаю всех вас стать участниками Хокатона. Встретимся и вместе выполним эту задачу. Покажите Москве, на что вы способны. |

Note: GigaAM `v3_e2e_ctc` renders the speaker's self-introduced name as "Ощаулов Виктор Кимович"
(ASR homophone confusion О/А); frame 3's on-screen caption (see below) spells it "**Ащаулов Виктор
Кимович**" — treated as authoritative for the name since it is burned-in text, not ASR output.

English gist of the narration: daily incidents in Moscow require prompt emergency response; the
speaker introduces himself as senior instructor, Civil Defense department, Moscow's GO ChS training
and methodology center ("УМЦ ГО ЧС"), Viktor Kimovich Ashchaulov; by federal law/government decree,
help in incidents/emergencies must be rendered as promptly as possible to preserve life, health and
property; their center is the only educational institution in Moscow training dispatcher specialists
for all of the city's emergency operational services; those specialists dispatch services/personnel
to incident sites, control quality of aid rendered, inform leadership, and relay information to other
services/organizations; to train such specialists, the center needs help developing a training
simulator for city emergency-service dispatchers handling 112-system calls, one that lets specialists
learn to act independently, that uses AI to generate incident messages and independently assess the
trainee's actions and quality of training; "real data" is provided by the organizer, the "solution"
is expected from participants; a creative approach is valued; no analogous product exists, so it will
be unique; the experience gained could be rolled out to all Russian regions; framed as a chance to
become leaders in emergency-service development; closes with an invitation to join the hackathon.

## Frame descriptions (fps=0.1, ≈10 s spacing, 15 frames)

| Frame | ~Time | Description |
|---|---|---|
| frame_001.jpg | ~10s | Animated dark purple/blue particle-and-circuit-line motion-graphics background (stock intro style). Overlaid: the department's emblem/coat-of-arms (a griffin/eagle-like crest) and white caption text "ДЕПАРТАМЕНТ ПО ДЕЛАМ ГРАЖДАНСКОЙ ОБОРОНЫ, ЧРЕЗВЫЧАЙНЫМ СИТУАЦИЯМ И ПОЖАРНОЙ БЕЗОПАСНОСТИ ГОРОДА МОСКВЫ" ("Moscow Department for Civil Defense, Emergency Situations and Fire Safety"). Not a software screen — a title/branding card. |
| frame_002.jpg | ~20s | Close-up, motion-blurred shot of a young woman wearing a blue polo shirt printed "112 МОСКВА" and a headset boom mic, with a name badge partially readable ("...КБА 112", "...ЛЕКСАНДРОВНА", "...ного отдела Службы 112"). Burned-in caption: "от которой зависят их здоровье и жизнь." Depicts what is presented as a real (or reenacted) Moscow "112" service operator; no computer screen visible in frame. |
| frame_003.jpg | ~30s | Talking-head shot: bald man in a striped shirt with a lapel mic, standing in a classroom/training room with wall posters (visible poster titles include "СИСТЕМА ОБЕСПЕЧЕНИЯ ВЫЗОВА ЭКСТРЕННЫХ ОПЕРАТИВНЫХ СЛУЖБ ПО ЕДИНОМУ НОМЕРУ 112" — "system for calling emergency operational services via the single number 112" — and an "алгоритм действий диспетчера" style chart) and rows of desks with monitors behind him. Burned-in caption identifies him: "Ащаулов Виктор Кимович — Старший преподаватель кафедры гражданской обороны ГБУ ДПО «УМЦ ГО ЧС»". This is a talk/presenter shot, not a software screen, but the room is the actual dispatcher-training classroom (workstations visible in the background, unfocused). |
| frame_004.jpg | ~40s | B-roll stock/promotional footage: a red-and-white rescue helicopter and a rescuer in a red suit rappelling down the side of a bare concrete high-rise under construction. Caption: "помощь людям в происшествиях и чрезвычайных ситуациях". Generic emergency-response B-roll, unrelated to dispatcher software. |
| frame_005.jpg | ~50s | Title card, same particle background style as frame 1, white text "О НАС" ("About us"). |
| frame_006.jpg | ~60s | Shot from behind of a man wearing a blue polo with a Russian-flag sleeve patch, headset on, seated at a workstation with **two monitors and a desk phone/handset console visible**. The near (upper-left) monitor shows an application window with an orange-red header bar and a form/list layout typical of a call-record/ticket application; the on-screen field labels are too small/blurred to read at this resolution, but the layout (top banner, left-hand list panel, form area) is legible as a real ticketing/CRM-style dispatcher application, not a generic desktop. This is the one frame in the sample that shows an actual software screen in the background of a real (or reenacted) dispatcher workstation. Caption: "экстренных оперативных служб города." |
| frame_007.jpg | ~70s | B-roll: a rescuer in red jacket, yellow helmet/ear protection and harness gesturing/directing on a rooftop, with rigging/cable equipment and a red-and-white helicopter visible in the distant background. Caption: "контролируют качество оказания помощи, информируют". Generic rescue B-roll. |
| frame_008.jpg | ~80s | Title card: "О ЗАДАЧЕ" ("About the task"). |
| frame_009.jpg | ~90s | Same presenter (Ащаулов В.К.) as frame_003, same classroom, mid-speech. Caption: "учебный симулятор подготовки диспетчеров". |
| frame_010.jpg | ~100s | B-roll: a red rescue basket/stretcher suspended on cables in front of the same bare-concrete high-rise. Caption: "действовать самостоятельно." |
| frame_011.jpg | ~110s | Presenter (Ащаулов В.К.), same classroom. Caption: "оценку действий обучаемого и качество его обучения." |
| frame_012.jpg | ~120s | Title card: "ПОЧЕМУ ЭТО ИНТЕРЕСНО?" ("Why is this interesting?"). |
| frame_013.jpg | ~130s | Presenter (Ащаулов В.К.), same classroom, different wall-poster area visible (a flow-chart-style poster) in background. Caption: "Аналогов таких продуктов нет, потому он будет уникальным". |
| frame_014.jpg | ~140s | Presenter (Ащаулов В.К.), same classroom. Caption: "Это отличный шанс". |
| frame_015.jpg | ~150s | Presenter (Ащаулов В.К.), close-up, same classroom (blurred background). Caption: "Встретимся и вместе выполним эту задачу." Closing shot. |

### Overall visual characterization

The video is a professionally edited ~2.5-minute recruitment/promotional piece: motion-graphics
title cards ("О НАС" / "О ЗАДАЧЕ" / "ПОЧЕМУ ЭТО ИНТЕРЕСНО?"), a single talking-head presenter
(Ащаулов В.К., filmed in the training center's classroom, real workstations visible unfocused in the
background), and generic stock/B-roll emergency-rescue footage (helicopter, rooftop rescue rigging)
that illustrates "emergency response" in general — it is not 112-specific footage. It is **not** a
screen-recorded software demo and **not** the Q&A session; the only glimpse of an actual dispatcher
software screen is the blurred, small, orange-banner ticket/CRM-style window visible over the
shoulder of the operator in frame_006 (~60s) — legible as a real application layout, not legible as
to field content.
