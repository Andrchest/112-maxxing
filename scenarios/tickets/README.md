# Ticket scenarios — «Билеты- задачи по C 112» (I3 E8)

One schema-2 scenario per call of the organizer's tickets: 32 tickets × 3 calls = 96 base
scenarios, `ticket-NN-call-M/v1.yaml`, on reference pack `v046_24-r1`. Every one carries
`provenance: {source: TICKET, ticket: NN, call: M, generation_candidate: true}` — **кандидат на
генерацию** (HLD 30 §30.13, rule R43). Source: `requirements/normalized/SRC-005-tickets-and-dds-memo.md`
(authoritative), cross-checked against `requirements/evidence/tickets-ocr.md` and the page images.

Lessons are composed by the instructor from these scenarios (a ticket's three calls are a lesson
plan of three entries); this directory holds no lesson files.

Every scenario: `variants` `card_source` [GENERATED_CARD (default), CALLER_VOICE (frozen, playable
from the facts)], `dds_mode` [MEMO_STATUSES] only — the tickets name no resources, so no resource
board is authored —, `dds_card_check` [OFF (default), ON], `dds_brigade_call` [OFF, ON (default —
the ДДС phone, owner decision 2026-09-25, D28)], `responders: DEFAULT`, default timers.
The prefab card is written in card-schema v2 paths and codes; fields a ticket does not state are
left out, and addresses outside Moscow keep their text with no okrug/district.

Validate: `uv run python -m app.tools.validate_scenarios scenarios/tickets`. Tests:
`backend/tests/unit/domain/scenario/test_ticket_scenarios.py` (load, variants, routing),
`backend/tests/api/test_ticket_scenarios.py` (import + generated card through handoff).

## Index: ticket → three scenarios (all «кандидат на генерацию»)

| Билет | Вызов 1 | Вызов 2 | Вызов 3 |
|:--|:--|:--|:--|
| 1 | `ticket-01-call-1` — Возгорание мусорного контейнера, пострадавших нет | `ticket-01-call-2` — Дерутся 10-15 человек, 5 пострадавших с различными травмами, дерутся п… | `ticket-01-call-3` — Ребенок 11 лет, Смирнов Илья упал с велосипеда, упал сам, отек руки и … |
| 2 | `ticket-02-call-1` — Задымление мусоропровода в жилом доме, в доме 17 этажей, заявитель нах… | `ticket-02-call-2` — Поругался с продавцом «Мегафон», бросил трубку | `ticket-02-call-3` — Падение автомашины в воду |
| 3 | `ticket-03-call-1` — Горит крыша частного дома, пострадавших нет, дом не газифицирован | `ticket-03-call-2` — Громко играет музыка во дворе | `ticket-03-call-3` — На машину упало бревно с грузовика |
| 4 | `ticket-04-call-1` — Горит балкон и два окна рядом на 13-м этаже, открытое пламя, пострадав… | `ticket-04-call-2` — Плохо женщине на автомобильной парковке | `ticket-04-call-3` — Открыть дверь в квартиру |
| 5 | `ticket-05-call-1` — Горит одно окно на 9 этаже, открытое пламя, рядом на балконе 2-е людей… | `ticket-05-call-2` — Женщина выпила случайно не те лекарственные препараты, потеряла сознан… | `ticket-05-call-3` — На стройке жилого дома, рабочий упал в котлован |
| 6 | `ticket-06-call-1` — Горит а/м фольксваген цвет красный Х 863 МН 199, пострадавших нет | `ticket-06-call-2` — Мужчина 40 лет, плохо | `ticket-06-call-3` — Трое мужчин плывут на льдине |
| 7 | `ticket-07-call-1` — Горит а/м Тойота цвет бежевый Р 254 ТС 99, пострадал водитель, 54 года… | `ticket-07-call-2` — Сильная головная, А/Д 150/80, д/р 30 | `ticket-07-call-3` — 85 лет, Марков Илья Кузьмич, страдает потерей памяти, 6 часов назад уш… |
| 8 | `ticket-08-call-1` — Задымление на минус первом этаже в торговом центре, источник не устано… | `ticket-08-call-2` — Лежит мужчина неизвестный, около 50 лет, без сознания, видимых травм и… | `ticket-08-call-3` — Тонет человек в настоящее время |
| 9 | `ticket-09-call-1` — Задымление на платформе, пострадавших людей нет | `ticket-09-call-2` — Минина Ольга Петровна, 36 лет, беременность 39 недель, отошли воды, вы… | `ticket-09-call-3` — Мужчина упал с моста в воду, кричит, что не умеет плавать |
| 10 | `ticket-10-call-1` — Горит помещение кассы, открытый огонь, пострадала кассир 45 л, Гвоздик… | `ticket-10-call-2` — Пожилая женщина, неизвестная, около 70 лет, сильные головные боли, сто… | `ticket-10-call-3` — Женщина просит о помощи из-за двери квартиры, дверь в квартиру закрыта… |
| 11 | `ticket-11-call-1` — Горит кабина автобуса, № маршрута 63, бортовой № 15477, гос | `ticket-11-call-2` — Легкодушев Дмитрий Константинович, д/р 31 | `ticket-11-call-3` — Женщина собирала грибы, заблудилась |
| 12 | `ticket-12-call-1` — Сильное задымление в зале ресторана, о пострадавших точной информации … | `ticket-12-call-2` — Сильные боли в сердце, женщина Сергеева Наталья Петрова 55 лет | `ticket-12-call-3` — Мужчины на ограждении моста в крови |
| 13 | `ticket-13-call-1` — Горят деревья в парке, площадь возгорания 10 м х 10 м, пострадавших лю… | `ticket-13-call-2` — Рожает жена, 40 недель, кровотечения нет, воды отошли 2 мин назад, Сок… | `ticket-13-call-3` — На обочине лежит мужчина в крови |
| 14 | `ticket-14-call-1` — Горит сухая трава рядом с АЗС Роснефть, огонь подходит к территории АЗ… | `ticket-14-call-2` — Подросток 12 лет задыхается, астма, Ковалев Иван Сергеевич, вызывает б… | `ticket-14-call-3` — Неизвестные затащили жену в машину у метро Комсомольская, скрылись в с… |
| 15 | `ticket-15-call-1` — Горит лес за деревней Варварино, пострадавших нет | `ticket-15-call-2` — Мужчина 30 лет нырнул в воду, ударился о камень, рассек голову, кровот… | `ticket-15-call-3` — Сожитель ударил ножом в ногу |
| 16 | `ticket-16-call-1` — Видит столб черного дыма со стороны жилых домов поселка, информации о … | `ticket-16-call-2` — Ребенок 11 лет, Смирнов Илья упал с велосипеда, упал сам, отек руки и … | `ticket-16-call-3` — Петрова Светлана Павловна 35 лет, выпила упаковку снотворного «Донорми… |
| 17 | `ticket-17-call-1` — В жилом доме сработала пожарная сигнализация | `ticket-17-call-2` — У покупателя в магазине судороги, пена изо рта | `ticket-17-call-3` — Избита женщина, около 30 лет, неизвестная, травма головы, кровотечение |
| 18 | `ticket-18-call-1` — Видит пожар, что горит не знает | `ticket-18-call-2` — Не может разбудить мужа | `ticket-18-call-3` — С улицы слышны крики о помощи, кричит мужчина |
| 19 | `ticket-19-call-1` — Горит поле, пострадавших нет | `ticket-19-call-2` — Прихожанина укусила змея | `ticket-19-call-3` — Мужчину сбила электричка, на ж/д переходе |
| 20 | `ticket-20-call-1` — Дерутся 3 человека, без пострадавших, без оружия | `ticket-20-call-2` — Женщина, речь невнятная, лицо перекошено | `ticket-20-call-3` — Изнасиловали женщину, около 30 лет, травмы, просит вызвать полицию |
| 21 | `ticket-21-call-1` — Дерутся 10-15 человек, 5 пострадавших с различными травмами, дерутся п… | `ticket-21-call-2` — Рубила дрова и ударила топором себя по руке, случайно, кровотечение | `ticket-21-call-3` — Ребенок 4 года один в а/м, двери заблокировались |
| 22 | `ticket-22-call-1` — Дерутся в квартире, 2 мужчин, без пострадавших, без оружия | `ticket-22-call-2` — Ребенок 4 года Соловьев Максим, боль в животе, рвота с кровью | `ticket-22-call-3` — Знакомый отправил СМС – хочет повеситься |
| 23 | `ticket-23-call-1` — Скандал с пьяным мужем, требуется скорая для женщины, 28 лет, Петровой… | `ticket-23-call-2` — Чистила ухо, повредила барабанную перепонку, кровотечение | `ticket-23-call-3` — Потерялся ребенок 30 минут назад- 5 лет, Степанов Гриша, одет в синюю … |
| 24 | `ticket-24-call-1` — Ссора во дворе из-за парковки | `ticket-24-call-2` — Касанов Константин Константинович, 8 лет, упал сам с горки, высота 1,5… | `ticket-24-call-3` — Женщина с младенцем на руках, попрошайничает, пристает к гражданам |
| 25 | `ticket-25-call-1` — На улице, на остановке трамвая мужчина нетрезвый сильно ругается и хва… | `ticket-25-call-2` — ДТП, Б/П, Б/Р, пежо + фольксваген | `ticket-25-call-3` — Заявитель пришел в квартиру бывшей супруги, т |
| 26 | `ticket-26-call-1` — У входа на стадион – группа молодых людей, 10-12 человек, пытаются сло… | `ticket-26-call-2` — ДТП, Б/П, Б/Р, пежо + фольксваген | `ticket-26-call-3` — В доме престарелых скончалась женщина, после инсульта |
| 27 | `ticket-27-call-1` — Подозрительный автомобиль ваз2110 черная, очень грязная, гос | `ticket-27-call-2` — ДТП, Б/П, Б/Р, пежо + фольксваген | `ticket-27-call-3` — Соседи делают ремонт, со стены в ванной комнаты отлетела плитка и обра… |
| 28 | `ticket-28-call-1` — У подъезда молодой человек, лет 20, в синей джинсовой куртке в синих д… | `ticket-28-call-2` — ДТП, Б/П, Б/Р, пежо + фольксваген | `ticket-28-call-3` — На Ярославском вокзале нет одного крепления на табло с указанием распи… |
| 29 | `ticket-29-call-1` — На дорожке в парке лежит большая коробка, замотана скотчем, внутри что… | `ticket-29-call-2` — ДТП, Б/П, Б/Р, драка между водителями, без пострадавших, без оружия | `ticket-29-call-3` — Муж угрожает взорвать квартиру бывшей супруги |
| 30 | `ticket-30-call-1` — Угон машины, видели в последний раз вчера вечером, тойота синяя А128НА… | `ticket-30-call-2` — Наезд на пешехода, мужчина, без сознания, на месте ваз2110 красный а12… | `ticket-30-call-3` — В частном доме запах газа от трубы на вводе в дом, слышит шум в трубе |
| 31 | `ticket-31-call-1` — Угон машины мерседес черный А128АА 177, на глазах владельца, уехала в … | `ticket-31-call-2` — Наезд на пешехода, мужчина в сознании, травма головы, с места скрылась… | `ticket-31-call-3` — Свист от газовой трубы в квартире, на кухне |
| 32 | `ticket-32-call-1` — Завладение автотранспортом, остановили (перегородили проезд) машиной в… | `ticket-32-call-2` — ДТП, 3 пострадавших в троллейбусе, не блокированы, троллейбус маршрут … | `ticket-32-call-3` — На МКАД (внутренняя и внешняя сторона) на протяжении от Ленинградского… |

Tickets 1 №3 and 16 №2, and 1 №2 and 21 №1, are verbatim duplicates in the source (REQ-5207,
REQ-5208); each keeps its own scenario. Ticket 18 №3's printed house «15/19» is corrected by hand
to «12» (REQ-5212); the base scenario uses «12».

## Special variants (each a separate scenario next to its base)

**Competence decline** (`…-decline`): one notified service answers «Не принята» with a reason,
scripted in `expected_response.responders` (`RECEIVED` at 0 ms, `NOT_ACCEPTED` at 20 s). The script
plays when no ДДС participant is bound to that service (HLD 70 §70.4.5 — e.g. a MULTI_TRAINEE
session with the trainee bound to another service); when a trainee plays the leg, the rule
`memo_competence_decline` rewards declining it.

| Scenario | Declining service | Why it is natural |
|:--|:--|:--|
| `ticket-01-call-1-decline` | ОАТИ (`OATI`) | The burning container is in a depot on Moscow Railway (МЖД) land, not city territory the city inspection covers. |
| `ticket-02-call-1-decline` | Мособлгаз (`MOSOBLGAZ`) | The classifier notifies the Moscow Oblast gas company for a building fire; the address is in Moscow (СЗАО), outside its service area — «not its district». |
| `ticket-09-call-3-decline` | Гормост (`GORMOST`) | A man fell from Бережковский мост; the bridge itself is intact, the bridge owner has nothing to do. |
| `ticket-14-call-1-decline` | ЦОДД (`TSODD`) | The grass fire is by the federal М-2 highway in Moscow Oblast, outside Moscow's road network. |
| `ticket-27-call-3-decline` | Пожарно-спасательная служба (`FIRE_RESCUE`) | A 1 m crack after the neighbours' renovation, no victims, no collapse threat: a housing-inspection matter (Мосжилинспекция is scored as the main service). |
| `ticket-28-call-3-decline` | ФСБ (`FSB`) | A loose timetable-board bracket at Ярославский вокзал is a technical hazard with no sign of a terrorist threat. |

**Card error** (`…-card-error`): the generated card carries one deliberately wrong value;
`dds_card_check` defaults to `ON`, and the rule `dds_card_issue_flagged` (`WORKFLOW_ACTION` on
`DDS_CARD_ISSUE_FLAGGED` with the wrong field's `field_path`, applicable only under card check
`ON`) rewards flagging it.

| Scenario | Wrong field | Why it is natural |
|:--|:--|:--|
| `ticket-01-call-2-card-error` | `incident.classifier_code` | «Драка до 10 человек» (15060201) for a 10–15-person fight with five injured — the ticket makes it a mass fight (15060202). |
| `ticket-03-call-1-card-error` | `address.region` | The address omits the town; only on clarification is it г. Королёв, МО. The card keeps the unclarified Moscow reading. |
| `ticket-09-call-1-card-error` | `address.object` | Two Moscow stations are called Арбатская; the ticket clarifies the Филевская line, the card names the Арбатско-Покровская. |
| `ticket-17-call-1-card-error` | `q.fire.sign_house` | A fire alarm with no smoke and no fire, but the chip says «Открытое пламя / Дым» (row 1050002 «задымление: жилой дом»). |
| `ticket-18-call-3-card-error` | `address.house` | The printed house «15/19» is struck through and corrected by hand to «12» (REQ-5212); the card carries the printed number. |
| `ticket-23-call-2-card-error` | `address.district` | «ул. Лесная, дом 5» is, on clarification, Зеленоград, пос. Малино; the card places it on central Moscow's ул. Лесная (ЦАО, Тверской). |

## Routing

Every base scenario's prefab card resolves through the routing resolver (HLD 70 §70.6.4) to a
non-empty automatic notification list, except the two below (the classifier yields nothing for
them; the prefab's `recipient_services` adds the service by hand):

| Scenario | Why the classifier notifies nobody |
|:--|:--|
| `ticket-18-call-1` | «Видит пожар, что горит не знает»: «Что горит неизвестно» is bound to no признак (routing: none) and v046_24 has no street-fire row for an unknown object; Служба 101 is added by hand. |
| `ticket-32-call-3` | Row 14030203 «Горит уличное освещение в дневное время» counts only «Территориальные ОИВ», and МКАД 68–74 км (both sides) names no single district or okrug; ОЭК (the row's main service) is added by hand. |

`recipient_services` (the manual part) is the resolver's non-territorial list; only the two cases
above add a service by hand. The resolver reads the classifier's feature sub-columns as «base plus
flags» (reading R2, I3 E8): an org's base column always applies and a selected flag (ПП, «Нет
доступа», …) only adds, so e.g. 15060202 «Массовая драка» with five injured notifies the police and
103 both.
