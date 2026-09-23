# SRC-005 — Classifier v_046_24 (МВД + Департамент correction) — extraction and diff vs v_046_11

Task: X5c (worker: i2). IDs REQ-5701–REQ-5899 (21 used: REQ-5701–REQ-5721).

## 1. Header

**Source(s) covered:**
1. `requirements/sources/05-organizer-materials/Классификатор_происшествий_v_046_24_корректировка_МВД_+_Департамент (1).xlsx`
   (NEW — this task's assigned file).
2. `requirements/sources/01-qna-session-telegram/files/Классификатор_происшествий_v_046_11_ДТУ_15_11_2024_искл_пожар_задымление.xlsx`
   (OLD — baseline, already normalized in `requirements/normalized/SRC-001-domain-docs.md` §REQ-3044–
   REQ-3049; read here again programmatically to compute the row-level diff. Not modified.)

**How read:** Both opened with `openpyxl` (`uv run --with openpyxl python ...`), `data_only=True`. Sheet
dimensions, merged-cell ranges (rows 1–4, to recover the 3-row header hierarchy exactly), all cell values
for rows 1–3 (headers) and rows 4–max (category-header rows + data rows) were read programmatically.
Category-header rows were distinguished from data rows by: column A ("Г", group code) is empty AND
column F (category name) is non-empty → category-header row; column E ("Номер") non-empty → data row.
A full row-level join was computed on column E ("Номер", the classifier's stable numeric incident code)
as the key, comparing per-key: columns G/H/I/J/K/L (Признак1/2/3, Доп.признаки, Итоговый тип, ЕКП35),
"Главная служба", the 3 "Классификатор МВД" sub-columns, and the 2 "Служба 101" sub-columns (see §2 for
exact column letters per file — they differ because column positions shifted between versions).

**What could NOT be read:** Nothing in-scope was unreadable; both `.xlsx` files opened cleanly with no
corrupt cells encountered. Per this task's scope, only rows 1–3 (headers), all category-header rows, and
the columns named above were read for every one of the 1281/1283 data rows; the remaining ~85 routing-
matrix columns per row (out of ~90–99 total) were NOT individually diffed cell-by-cell for every
organization for every row — only the МВД, Служба 101, "Главная служба", and all pre-existing
"Департамент*"-named columns were explicitly diffed row-by-row (chosen because the new filename names
"МВД" and "Департамент" as what changed; see REQ-5718–REQ-5720). This is a documented sampling scope,
not a silent omission.

**How organizers were identified:** Both files are organizer-supplied source documents (no chat/author
metadata attached); per this task's source-typing convention (used identically in SRC-001-domain-docs.md
for the same classifier family) they are treated as "organizer (document)" — content authored/issued by
the organizers as domain reference material, not by a participant.

**Counts per Kind:** DOMAIN-FACT: 19. OPEN-QUESTION: 2. Total: 21 (REQ-5701–REQ-5721).

---

## 2. Items

### REQ-5701 — File identity and sheet structure (NEW file)

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | `Классификатор_происшествий_v_046_24_корректировка_МВД_+_Департамент (1).xlsx` |
| Speaker | organizer (document) |

**Verbatim (RU):** Workbook contains a single sheet named "Лист1". `ws.dimensions` = `A1:CU1310`;
`max_row` = 1310; `max_column` = 99. Header rows 1–3 (merged group headers row 1, sub-headers row 2,
sub-sub-headers row 3, identical layout convention to the OLD file); category-header rows interleaved
with data rows from row 4 onward (row 4 = category 1 header: E=1, F="Пожары и задымления"; row 5 =
first data row).

**English:** Same overall sheet architecture as v_046_11 (single sheet, 3-row header, category-header
rows + data rows), but with 9 more columns (99 vs 90) and 2 more rows (1310 vs 1308 max_row).

**Notes:** Baseline structure documented in `SRC-001-domain-docs.md` REQ-3044 (OLD file: `A1:CL1308`,
90 cols × 1308 rows).

---

### REQ-5702 — Column-count change: 90 → 99 (+9), reconciled

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, row 1 merged ranges (via `ws.merged_cells.ranges`) |
| Speaker | organizer (document) |

**Verbatim (RU):** OLD `max_column`=90 (col `CL`). NEW `max_column`=99 (col `CU`). Reconciliation by
column-by-column alignment: −1 column ("Сценарий реагирования" removed, REQ-5703) + 1 column (ГУП МСР
group gains a second sub-column "пожары", REQ-5704) + 9 columns (new organizations appended at the tail,
REQ-5705) = net +9 (90 − 1 + 1 + 9 = 99).

**English:** The +9 net column growth is not simple appending — one field was deleted, one existing
organization's sub-column set grew by one, and 9 wholly new columns were added at the end.

---

### REQ-5703 — "Сценарий реагирования" (Response scenario) field removed

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | OLD file, merged range `M1:M3` (value present); NEW file, no equivalent merge or column found |
| Speaker | organizer (document) |

**Verbatim (RU):** OLD: `M1:M3 -> value='Сценарий реагирования'` (a single-column field, vertically
merged across all 3 header rows, positioned immediately after column L "ТИП происшествия ЕКП 35" and
before column N "Главная служба"). NEW: column M (same position after L) holds `row1='Главная служба'`
directly — no "Сценарий реагирования" column, merge, or label exists anywhere in the NEW file's header
rows 1–3.

**English:** The "Response scenario" field that existed as its own column in v_046_11 is absent from
v_046_24; "Главная служба" (Main/lead service) now occupies the position immediately after "ТИП
происшествия ЕКП 35" where "Сценарий реагирования" used to sit.

---

### REQ-5704 — "ГУП МСР" group gains a new "пожары" sub-column

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | OLD col `CI` (row2 `'(КУБ)'`); NEW cols `CH:CI` (row1 `'ГУП МСР'`, row2 `CH='(КУБ)'`, `CI='пожары'`) |
| Speaker | organizer (document) |

**Verbatim (RU):** OLD: `CI: row1='ГУП МСР' row2='(КУБ)' row3=None` — a single column. NEW: `CH:
row1='ГУП МСР' row2='(КУБ)'` (unchanged, same position after realignment) plus a new second column
`CI: row1=None row2='пожары' row3=None`. Sample value at NEW row 5 (Номер 1010101, "пожар: мусор", the
first fire-category data row) under the new "пожары" sub-column: `'пожар: мусор'`.

**English:** "ГУП МСР" (a receiving organization) previously had one routing sub-column, labeled "(КУБ)".
It now has a second sub-column labeled "пожары" (fires), which is populated for fire-category rows (the
row-5 sample shows the fire row now explicitly routes to ГУП МСР under this new "fires" flag).

---

### REQ-5705 — 9 new organization columns appended at the end of the routing matrix

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | NEW file, columns `CM`–`CU`, row 1 (plus row2/row3 sub-headers where present), via merged-range and raw-cell dump |
| Speaker | organizer (document) |

**Verbatim (RU), all 9, in column order (`—` = no row2/row3 sub-header, single-field column):**
`CM` "ЦУКБ Министерство обороны" (—); `CN` "ЦУКБ.БПЛА\nМинистерство обороны" (—); `CO:CP`
"ГКУ Организатор перевозок" (row3 sub-columns: `CO`="признак не выбран", `CP`="перекрытие движение");
`CQ` "ГПБУ Мосэкомониторинг" (—); `CR:CS` "Министерство обороны РХБЗ" (row2 sub-columns:
`CR`="События по полигонам", `CS`="Москва"); `CT` "ООО Ситиэнерго" (—); `CU`
"Депортамент гражданского строительства" (—, **note: spelled "Депортамент", not "Департамент", in the
source file — recorded verbatim as it appears**).

**English:** 9 new columns for 7 new receiving organizations/entities not present in v_046_11: two
Ministry-of-Defence-related columns (general + "БПЛА"/drones), a transport-organizer body (2
sub-columns: default / "road closure"), an ecological-monitoring body, a Ministry-of-Defence
RCBZ (radiation/chemical/biological defence) body (2 sub-columns: "events on polygons" / "Moscow"), an
energy company ("ООО Ситиэнерго"), and a "construction" department whose name is misspelled in the
source ("Депортамент" for "Департамент").

---

### REQ-5706 — Pre-existing "Департамент*"-named columns: zero row-value changes

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, row-value diff on all 1281 common `Номер` keys, restricted to columns: "Департамент РБиПК (ГКУ МОСБЕЗ)" (OLD `BF:BG`→NEW `BE:BF`), "Департамент образования" (OLD `BK`→NEW `BJ`), "Департамент строительства города Москвы" (OLD `CA:CB`→NEW `BZ:CA`), "Департамент культуры" (OLD `CE`→NEW `CD`), "ОД Департамент ТСЗН" (OLD `BQ`→NEW `BP`), "Деп. ЖКХ" (OLD `BE`→NEW `BD`), "ДГП (Департамент градостроительной политики)" (OLD `CK:CL`→NEW `CK:CL`) |
| Speaker | organizer (document) |

**Verbatim:** Programmatic diff of all 7 pre-existing "Департамент/Деп."-named column groups, for all
1281 `Номер` codes common to both files: `0 row-value diffs` for every one of the 7 groups.

**English:** None of the routing values in any column whose row-1 label already contained
"Департамент"/"Деп." changed between v_046_11 and v_046_24, for any classifier row. See REQ-5718–5720
for what "Департамент" in the new filename may instead refer to.

---

### REQ-5707 — Category list and total row counts: OLD vs NEW

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, column F category-header rows |
| Speaker | organizer (document) |

**Verbatim (RU):** Both files list the same 24 top-level categories, in the same order (see full names
in `SRC-001-domain-docs.md` REQ-3045). OLD: 1281 total data rows (24 category-header rows + 1281 data
rows = 1305 rows from row 4 to `max_row` 1308). NEW: 1283 total data rows (24 category-header rows +
1283 data rows = 1307 rows from row 4 to `max_row` 1310).

**English:** No category was added, removed, or renamed. Total data-row count grew by exactly 2
(1281 → 1283).

---

### REQ-5708 — Per-category row-count diff, full table

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, rows bucketed by owning category-header row |
| Speaker | organizer (document) |

**Verbatim (RU/EN category names), full 24-category table, OLD vs NEW row counts:**

| Category (RU) | OLD | NEW | Δ |
|---|---|---|---|
| Пожары и задымления | 271 | 271 | 0 |
| ДТП | 47 | 47 | 0 |
| Взрывы | 45 | 45 | 0 |
| Угрозы взрывов и террористических актов | 29 | 29 | 0 |
| Обрушения | 40 | 40 | 0 |
| Угрозы обрушений | 30 | 30 | 0 |
| Опасные геологические, гидрологические и метеорологические явления | 30 | 30 | 0 |
| Экологические происшествия | 15 | 15 | 0 |
| Аварии на гидротехнических сооружениях | 2 | 2 | 0 |
| Аварии на опасных и производственных объектах | 18 | 18 | 0 |
| Угрозы выброса опасных веществ | 32 | 32 | 0 |
| Аварии и происшествия на транспортных объектах | 63 | 63 | 0 |
| Запах газа | 32 | 32 | 0 |
| Аварии и происшествия в городском хозяйстве | 193 | 193 | 0 |
| Нарушение правопорядка | 174 | 174 | 0 |
| Проблемы на дороге | 30 | 30 | 0 |
| Человек в опасности | 85 | 85 | 0 |
| Ребенок в опасности | 16 | 16 | 0 |
| Смертельный исход человека | 31 | 31 | 0 |
| Социальная помощь | 8 | 8 | 0 |
| Происшествия с участием животных | 13 | 13 | 0 |
| Оказание медицинской скорой и неотложной помощи | 59 | 59 | 0 |
| Прочие происшествия | 6 | 7 | **+1** |
| БПЛА | 12 | 13 | **+1** |
| **TOTAL** | **1281** | **1283** | **+2** |

**English:** Only 2 of 24 categories changed row count, by +1 row each: "Прочие происшествия" (Other
incidents) and "БПЛА" (UAV/drones). The fire/smoke category ("Пожары и задымления") count is unchanged
(271 = 271) — see REQ-5715.

---

### REQ-5709 — The 2 added rows, verbatim

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | NEW file only, rows 1296 (Номер 23060001) and 1310 (Номер 24120200) |
| Speaker | organizer (document) |

**Verbatim (RU):**
Row 1296, category "Прочие происшествия": Номер=23060001; Признак1="Прочие происшествия (от 102)";
Признак2="Для простомотра операторов ОКр" [sic, as in source]; Итоговый тип="Прочие происшествия (от
102)"; ЕКП35=blank; Главная служба=blank; МВД/Служба101=blank.
Row 1310, category "БПЛА": Номер=24120200; Признак1="летит, готовят к запуску,упал/ столкнулся, нет
взрыва возгорания"; Признак2="Регион"; Итоговый тип="БВС Регион"; ЕКП35=blank; Главная служба="МСР";
МВД/Служба101=blank.

**English:** Two brand-new classifier codes with no v_046_11 counterpart: one flags "прочие происшествия
(от 102)" as visible only "для просмотра операторов ОКр" [for OKr-operator viewing only]; the other
extends the БПЛА (UAV) category for a drone "in flight / preparing for launch / crashed or collided, no
explosion or fire" scenario in a "Регион" (region, i.e. outside central Moscow) context, routed to "МСР"
as главная служба. Neither is fire/smoke-related.

---

### REQ-5710 — Zero rows removed

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, full key-set diff on column E ("Номер") |
| Speaker | organizer (document) |

**Verbatim:** All 1281 `Номер` codes present in v_046_11 are present in v_046_24 (`removed = []`,
programmatic diff output).

**English:** No classifier code was deleted between v_046_11 and v_046_24.

---

### REQ-5711 — Row-level changed-field summary (94 of 1281 common rows)

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, per-row diff on columns G/H/I/J/K/L, "Главная служба", "Классификатор МВД" (3 sub-cols), "Служба 101" (2 sub-cols), for all 1281 common `Номер` keys |
| Speaker | organizer (document) |

**Verbatim:** `94` of `1281` common-key rows have ≥1 changed field among the columns diffed. Field-level
breakdown (a row can have more than one changed field): "Классификатор МВД" sub-columns changed on `90`
rows; "Служба 101" sub-columns changed on `5` rows; "Итоговый тип происшествия" (column K) changed on
`1` row. `0` rows changed in Признак1/Признак2/Признак3/Дополнительные признаки (columns G/H/I/J) or in
"Главная служба".

**English:** Every detected content difference in the columns checked is either a МВД-routing change, a
Служба-101-routing change, or one single-row spelling fix — never a change to which "Признак" features
define a row or to its "Итоговый тип" derivation (except the one typo, REQ-5712), and never to which
service is "Главная служба".

---

### REQ-5712 — The one "Итоговый тип" change is a spelling fix

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, row for Номер 13010200 (category "Запах газа") |
| Speaker | organizer (document) |

**Verbatim (RU):** OLD "Итоговый тип" = `'Запах бытового газа в метро (тонелле)'`. NEW = `'Запах
бытового газа в метро (тоннеле)'`.

**English:** Spelling correction only ("тонелле" → "тоннеле", i.e. "tunnel" misspelling fixed). No
meaning change.

---

### REQ-5713 — Dominant МВД-column change pattern: flag-column reassignment

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, "Классификатор МВД" 3 sub-columns (OLD `V,W,X` = "признак не выбран" / "выбран признак Правонарушение" / "выбран признак Пострадавшие"; NEW `U,V,W`, same 3 labels in the same order) |
| Speaker | organizer (document) |

**Verbatim (RU):** Most frequent single change pattern across the 90 МВД-changed rows: OLD tuple
`(None, 'пожар', 'пожар')` → NEW tuple `('пожар', None, None)`, occurring on 17 rows (all in the
"Пожары и задымления" category — see REQ-5716). I.e. the routing value moves from the 2nd+3rd
sub-columns ("выбран признак Правонарушение" / "выбран признак Пострадавшие") to the 1st sub-column
("признак не выбран" — no flag selected / default) of the same МВД group.

**English:** For these 17 fire rows, v_046_11 notified МВД (police) only under the "Правонарушение"
(offence) or "Пострадавшие" (casualties) flag columns; v_046_24 instead notifies МВД under the default
"no flag selected" column — i.e. unconditionally for these incident types, rather than only when an
offence/casualty flag was set. The same reassignment logic (value moving between the 3 МВД sub-columns,
without changing which incident types are covered) recurs, with different specific flag pairs, across
most of the other 73 МВД-changed rows (full list in REQ-5714).

---

### REQ-5714 — Full row-level changed-field table (all 94 rows)

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, complete diff output for all 94 rows with ≥1 changed field among G/H/I/J/K/L, Главная служба, МВД (3 sub-cols), Служба101 (2 sub-cols) |
| Speaker | organizer (document) |

**Verbatim (RU), full table, `Номер` (classifier code) | category | old "Итоговый тип" (for
identification) | exact changed field(s), old → new:**

| Номер | Category | Итоговый тип (old) | Changed field(s), old → new |
|---|---|---|---|
| 1010201 | Пожары и задымления | пожар: трава | mvd: ('пожар','пожар','пожар') → (None,'пожар','пожар') |
| 1010501 | Пожары и задымления | пожар: лес | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1010701 | Пожары и задымления | пожар: мачта освещения | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1010801 | Пожары и задымления | пожар: опора контактной сети | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1010901 | Пожары и задымления | пожар: ЛЭП | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1011100 | Пожары и задымления | запах гари на улице | s101: ('пожар',None) → ('пожар: другое',None) |
| 1021201 | Пожары и задымления | пожар: эстакада | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1021302 | Пожары и задымления | задымление: тоннель | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1021401 | Пожары и задымления | пожар: переход | mvd: (None,'пожар','пожар') → ('пожар',None,None); s101: ('пожар',None) → ('пожар: Другое',None) |
| 1021402 | Пожары и задымления | задымление: переход | mvd: (None,'пожар','пожар') → ('пожар',None,None); s101: ('пожар',None) → ('пожар: Другое',None) |
| 1040002 | Пожары и задымления | задымление: МЦК | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1050002 | Пожары и задымления | задымление: жилой дом | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1050502 | Пожары и задымления | задымление: лифт | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1050602 | Пожары и задымления | задымление: мусоропровод | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1050702 | Пожары и задымления | задымление: подъезд | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1051202 | Пожары и задымления | задымление: лестничная клетка | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1051302 | Пожары и задымления | задымление: подвал | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1051502 | Пожары и задымления | задымление: жилой дом (прочие) | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 1060600 | Пожары и задымления | пожар: газопровод | s101: ('пожар',None) → ('пожар: Другое',None) |
| 1060700 | Пожары и задымления | пожар: газохранилище | s101: ('пожар',None) → ('пожар: Другое',None) |
| 1061102 | Пожары и задымления | задымление: подземные коммуникации | mvd: (None,'пожар','пожар') → ('пожар',None,None) |
| 2020200 | ДТП | ДТП с пострадавшими (автомашина скрылась) | mvd: ('ДТП с пострадавшими (автомашина скрылась)',None,None) → ('ДТП с пострадавшими (транспортное средство скрылось)',None,None) |
| 2020600 | ДТП | ДТП с пострадавшими - служебный | mvd: ('ДТП со служебным транспортом',None,None) → ('ДТП со служебным транспортом полиции, ФСБ, Росгвардии, "101", "103"',None,None) |
| 2020601 | ДТП | ДТП с пострадавшими - служебный 104 | mvd: ('ДТП со служебным транспортом',None,None) → ('ДТП со служебным транспортом полиции, ФСБ, Росгвардии, "101", "103"',None,None) |
| 3030000 | Взрывы | Звуки похожие на взрыв | mvd: (None,'Взрыв','Взрыв') → ('Взрыв',None,None) |
| 6150200 | Угрозы обрушений | Мост эстакада тоннель подземный переход угроза обрушения вызов ОТ СПЕЦИАЛИСТА | mvd: (None,'Аварии в городском хозяйстве','Аварии в городском хозяйстве') → ('Аварии в городском хозяйстве',None,None) |
| 12090200 | Аварии и происшествия на транспортных объектах | Происшестве с водителем общественного наземного транспорта | mvd: (None,'прочее','Прочее') → ('прочее',None,None) |
| 13010200 | Запах газа | Запах бытового газа в метро (тонелле) | K: 'Запах бытового газа в метро (тонелле)' → 'Запах бытового газа в метро (тоннеле)' |
| 13020600 | Запах газа | Запах бытового газа (прочее, в помещении) | mvd: (None,'Прочее','Прочее') → (None,'Запах газа','Запах газа') |
| 14060201 | Аварии и происшествия в городском хозяйстве | Провал на тротуаре | mvd: ('Аварии в городском хозяйстве',None,'Аварии в городском хозяйстве') → (None,None,'Аварии в городском хозяйстве') |
| 14060302 | Аварии и происшествия в городском хозяйстве | Провал более 2*2 метров | mvd: (None,None,'Аварии в городском хозяйстве') → ('Аварии в городском хозяйстве',None,None) |
| 14060304 | Аварии и происшествия в городском хозяйстве | Провал фонтан воды | mvd: (None,None,'Аварии в городском хозяйстве') → ('Аварии в городском хозяйстве',None,None) |
| 14060305 | Аварии и происшествия в городском хозяйстве | Провал утечка воды | mvd: (None,None,'Аварии в городском хозяйстве') → ('Аварии в городском хозяйстве',None,None) |
| 14080104 | Аварии и происшествия в городском хозяйстве | Дерево упало на машину | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14080105 | Аварии и происшествия в городском хозяйстве | Дерево упало на машину (есть пострадавшие) | mvd: (None,None,'Аварии в городском хозяйстве') → ('Аварии в городском хозяйстве',None,None) |
| 14080107 | Аварии и происшествия в городском хозяйстве | Дерево упало на животное | mvd: (None,None,'Аварии в городском хозяйстве') → (None,'Аварии в городском хозяйстве','Аварии в городском хозяйстве') |
| 14090104 | Аварии и происшествия в городском хозяйстве | Сосульки, наледь, снег, свисающие с крыши и карнизов | mvd: (None,None,'Аварии в городском хозяйстве') → (None,'Аварии в городском хозяйстве',None) |
| 14090202 | Аварии и происшествия в городском хозяйстве | Падение объектов на машину | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14090303 | Аварии и происшествия в городском хозяйстве | Падение объектов на машину - пострадавшие | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14090403 | Аварии и происшествия в городском хозяйстве | Падение (детали кровли, крыши, балкона, фасада) на автомашину (есть пострадавшие) | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14090404 | Аварии и происшествия в городском хозяйстве | Угроза падения (детали кровли, крыши, балкона, фасада) | mvd: (None,None,'Аварии в городском хозяйстве') → (None,'Аварии в городском хозяйстве',None) |
| 14101800 | Аварии и происшествия в городском хозяйстве | Порча кабины лифта | mvd: (None,'Хулиганство мелкое',None) → ('Хулиганство мелкое',None,None) |
| 14101900 | Аварии и происшествия в городском хозяйстве | Проникновение в шахту | mvd: (None,'Хулиганство мелкое',None) → ('Хулиганство мелкое',None,None) |
| 14110301 | Аварии и происшествия в городском хозяйстве | Обрыв проводов (двор) | mvd: (None,None,'Аварии в городском хозяйстве') → (None,'Аварии в городском хозяйстве','Аварии в городском хозяйстве') |
| 14110302 | Аварии и происшествия в городском хозяйстве | Обрыв проводов (проезжая часть) | mvd: (None,None,'Аварии в городском хозяйстве') → ('Аварии в городском хозяйстве',None,'Аварии в городском хозяйстве') |
| 14110303 | Аварии и происшествия в городском хозяйстве | Обрыв проводов на автомашину | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14110304 | Аварии и происшествия в городском хозяйстве | Обрыв проводов на автомашину (пострадавшие) | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14120302 | Аварии и происшествия в городском хозяйстве | Обрыв контактных проводов на автомашину | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14120303 | Аварии и происшествия в городском хозяйстве | Обрыв контактных проводов на автомашину (пострадавшие) | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 14120503 | Аварии и происшествия в городском хозяйстве | Опора контактной сети падение на человека | mvd: (None,None,'Аварии в городском хозяйстве') → ('Аварии в городском хозяйстве',None,None) |
| 14120504 | Аварии и происшествия в городском хозяйстве | Опора контактной сети падение на животное | mvd: (None,None,'Аварии в городском хозяйстве') → (None,'Аварии в городском хозяйстве',None) |
| 15010200 | Нарушение правопорядка | Повреждение автомашины (не ДТП) | mvd: ('Повреждение автомобиля в результате падения предмета либо действий людей',None,None) → ('Повреждение автотранспортного средства в результате падения предмета, либо действия людей',None,None) |
| 15010300 | Нарушение правопорядка | Брошеная автомашина | mvd: ('Брошенная автомашина',None,None) → ('Брошенное автотранспортное средство',None,None) |
| 15010700 | Нарушение правопорядка | Автомашина подозрительная | mvd: ('Подозрительная автомашина',None,None) → ('Подозрительное автотранспортное средство',None,None) |
| 15020100 | Нарушение правопорядка | Вскрыта квартира, помещение | mvd: ('Вскрыта квартира, помещение',None,None) → ('Вскрыто жилое помещение, организация',None,None) |
| 15020500 | Нарушение правопорядка | Вскрыт объект (прочее) | mvd: ('Вскрыта квартира, помещение',None,None) → ('Вскрыто жилое помещение, организация',None,None) |
| 15050300 | Нарушение правопорядка | Кража | mvd: ('Кража (из гаража, из организации, из автомашины, личного имущества, документов)',None,None) → ('Кража личного имущества, документов',None,None) |
| 15050400 | Нарушение правопорядка | Кража кабелей связи | mvd: ('Кража (из гаража, из организации, из автомашины, личного имущества, документов)',None,None) → ('Кража личного имущества, документов',None,None) |
| 15050500 | Нарушение правопорядка | Кража кабели, трубы и т.п. оборудование с улицы | mvd: ('Кража (из гаража, из организации, из автомашины, личного имущества, документов)',None,None) → ('Кража личного имущества, документов',None,None) |
| 15050702 | Нарушение правопорядка | Грабеж (завладели автомашиной) | mvd: ('Грабеж',None,None) → ('Грабеж с завладением автотранспорта',None,None) |
| 15050802 | Нарушение правопорядка | Разбой (завладели автомашиной) | mvd: ('Разбой',None,None) → ('Грабеж с завладением автотранспорта',None,None) |
| 15060100 | Нарушение правопорядка | Драка в квартире | mvd: ('Драка в квартире',None,None) → (' Драка в жилом помещении',None,None) |
| 15090200 | Нарушение правопорядка | Нападение на военного | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15090300 | Нарушение правопорядка | Нападение на депутата | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15090400 | Нарушение правопорядка | Нападение на правозащитника | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15090500 | Нарушение правопорядка | Нападение на представителя духовенства | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15090600 | Нарушение правопорядка | Нападение на судью | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15091000 | Нарушение правопорядка | Нападение на здание полиции | mvd: ('Нападение на сотрудников МВД, ФСБ, Росгвардии, 101,103, и иных служб',None,None) → ('Нападение на сотрудников МВД, ФСБ, Росгвардии, 101,103, и иных спецслужб',None,None) |
| 15091500 | Нарушение правопорядка | Нападение | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15110700 | Нарушение правопорядка | Скандал в магазине | mvd: ('Скандал/конфликт',None,None) → ('Скандал/конфликтная ситуация',None,None) |
| 15130700 | Нарушение правопорядка | Подозрительная автомашина | mvd: ('Подозрительная автомашина',None,None) → ('Подозрительное автотранспортное средство',None,None) |
| 15140100 | Нарушение правопорядка | Посторонние выносят вещи | mvd: ('Посторонние выносят вещи из квартиры, подъезда',None,None) → ('Посторонние выносят вещи из жилого помещения, организации',None,None) |
| 15140200 | Нарушение правопорядка | Посторонние в квартире или только что вышли | mvd: ('Посторонние в квартире или только что вышли',None,None) → ('Посторонние в жилом помещении или только вышли',None,None) |
| 15140400 | Нарушение правопорядка | Рвутся в квартиру (огранизацию) | mvd: ('Посторонние рвутся в квартиру магазин, организацию и др',None,None) → ('Посторонние рвутся в жилое помещение, магазин, организацию и т.п.',None,None) |
| 15150100 | Нарушение правопорядка | Пьяный в общественном месте | mvd: ('Гражданин (-не) в состоянии алкогольного опьянения в общественном месте',None,None) → ('Гражданин(-не) в состоянии опьянения в общественном месте',None,None) |
| 15150200 | Нарушение правопорядка | Распитие в неположенном месте | mvd: ('Распитие спиртных напитков/курение в общественном месте',None,None) → ('Распитие спиртных напитков в общественном месте',None,None) |
| 15150300 | Нарушение правопорядка | Курение в неположенном месте | mvd: ('Распитие спиртных напитков/курение в общественном месте',None,None) → ('Распитие спиртных напитков в общественном месте',None,None) |
| 15190000 | Нарушение правопорядка | Скандал | mvd: ('Скандал/конфликт',None,None) → ('Скандал/конфликтная ситуация',None,None) |
| 15211400 | Нарушение правопорядка | Угон (грабеж) | mvd: ('Грабеж с завладением автотранспортного средства',None,None) → ('Грабеж с завладением автотранспорта',None,None) |
| 15211500 | Нарушение правопорядка | Угон (разбой) | mvd: ('Разбой с завладением автотранспортного средства',None,None) → ('Разбой с завладением автотранспортом',None,None) |
| 15220000 | Нарушение правопорядка | Мелкое хулиганство | mvd: ('Хулиганство мелкое',None,None) → ('Хулиганство',None,None) |
| 15220100 | Нарушение правопорядка | Хулиганство - пьяный | mvd: ('Гражданин (-не) в состоянии алкогольного опьянения в общественном месте',None,None) → ('Гражданин(-не) в состоянии опьянения в общественном месте',None,None) |
| 15220200 | Нарушение правопорядка | Распитие (курение) в неположенном месте | mvd: ('Распитие спиртных напитков/курение в общественном месте',None,None) → ('Распитие спиртных напитков в общественном месте',None,None) |
| 15220400 | Нарушение правопорядка | Попрошайки | mvd: ('Хулиганство мелкое',None,None) → ('Хулиганство',None,None) |
| 15220600 | Нарушение правопорядка | Хулиганство (с оружием или предметами) | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15220601 | Нарушение правопорядка | Хулиганство - угрожают | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15220602 | Нарушение правопорядка | Хулиганство - применяют оружие | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15220603 | Нарушение правопорядка | Ломают остановку общественного транспорта | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15220700 | Нарушение правопорядка | Хулиганство | mvd: ('Хулиганство (с оружием или предметами)',None,None) → ('Хулиганство (с оружием или предметом)',None,None) |
| 15230300 | Нарушение правопорядка | Употребление наркотиков в общественном месте | mvd: ('Гражданин (-не) в состоянии алкогольного опьянения в общественном месте',None,None) → ('Гражданин(-не) в состоянии опьянения в общественном месте',None,None) |
| 16030000 | Проблемы на дороге | Брошенная автомашина | mvd: ('Брошенная автомашина',None,None) → ('Брошенное автотранспортное средство',None,None) |
| 18030000 | Ребенок в опасности | Жестокое обращение с ребенком в семье | mvd: (None,'Прочее','Прочее') → ('Прочее',None,None) |
| 19020200 | Смертельный исход человека | Труп на жд станции (у жд полотна) | mvd: ('Труп на ж/д станции или у ж/д полотна',None,None) → ('Труп на ж/д станции, вокзале или у ж/д полотна',None,None) |
| 19020201 | Смертельный исход человека | Труп на жд станции (у жд полотна) - причина неизвестна | mvd: ('Труп на ж/д станции или у ж/д полотна',None,None) → ('Труп на ж/д станции, вокзале или у ж/д полотна',None,None) |

**English:** `mvd` = the 3-tuple (признак не выбран, выбран Правонарушение, выбран Пострадавшие);
`s101` = the 2-tuple (Служба 101: НД не выбран, Служба 101: выбран НД); `K` = "Итоговый тип
происшествия". 34 of the 94 rows are in category "Нарушение правопорядка" (Public-order violations —
МВД's primary domain); 21 are in "Пожары и задымления" (fire/smoke, see REQ-5716); the remainder are
scattered across "ДТП", "Взрывы", "Угрозы обрушений", transport, gas-smell, city-services, "Ребенок в
опасности" and "Смертельный исход человека". Recurring non-МВД-flag-shuffle edits are terminology
normalizations: "автомашина" → "автотранспортное средство" (car → motor vehicle); "квартира" →
"жилое помещение" (apartment → residential premises); "с оружием или предметами" → "с оружием или
предметом" (singular "object"); "Грабеж"/"Разбой" (robbery/assault-robbery with vehicle theft) unified
to a single "Грабеж с завладением автотранспорта" wording.

---

### REQ-5715 — Fire/smoke category (category 1): content columns unchanged for all 271 rows

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, rows 5–275 (category 1, "Пожары и задымления"), columns E (Номер), G/H/I/J/K/L |
| Speaker | organizer (document) |

**Verbatim:** All 271 `Номер` codes in category 1 are identical between OLD and NEW (no additions, no
removals — category row count 271 = 271, per REQ-5708). Of these 271 rows, `0` have any difference in
columns G, H, I, J, K, or L (Признак1/2/3, Дополнительные признаки, Итоговый тип происшествия, ТИП
происшествия ЕКП 35).

**English:** The fire/smoke category's substantive classification content — which features define each
row and what final incident-type string and ЕКП35 mapping it produces — is byte-for-byte identical
between v_046_11 and v_046_24. The only changes inside this category are routing-only (REQ-5716).

---

### REQ-5716 — Fire/smoke category: 21 of 271 rows have МВД/Служба-101 routing-only changes

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, category 1 subset of the REQ-5714 diff table |
| Speaker | organizer (document) |

**Verbatim:** 21 of the 271 fire/smoke rows appear in REQ-5714 (Номер: 1010201, 1010501, 1010701,
1010801, 1010901, 1011100, 1021201, 1021302, 1021401, 1021402, 1040002, 1050002, 1050502, 1050602,
1050702, 1051202, 1051302, 1051502, 1060600, 1060700, 1061102). All 21 changes are confined to the
"Классификатор МВД" and/or "Служба 101" sub-columns; see REQ-5714 for the exact old→new values per row.

**English:** ~7.7% of fire/smoke rows had their МВД and/or Служба-101 routing adjusted; the dominant
pattern (17 of the 21) is the flag-column reassignment described in REQ-5713.

---

### REQ-5717 — REQ-3048's 13 fire-relevant rows outside category 1 are unchanged

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Both files, the 13 rows listed in `SRC-001-domain-docs.md` REQ-3048 (Номер: 2010800, 2021000, 10010300, 12010300, 12020300, 12030300, 12040200, 12060200, 12050300, 12070700, 12080700, 13020203, 13030301) |
| Speaker | organizer (document) |

**Verbatim:** None of these 13 Номер codes appear in the REQ-5714 changed-row list. `0` diffs found for
all 13 across the columns checked.

**English:** The 13 fire/smoke-relevant rows that live outside the main "Пожары и задымления" category
(e.g. "ДТП ... с пожаром", airport/port/rail/metro "горит" rows, the two "Запах газа" rows referencing
fire) are unchanged between v_046_11 and v_046_24.

---

### REQ-5718 — Both classifier filenames, verbatim

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Filenames as stored in `requirements/sources/01-qna-session-telegram/files/` and `requirements/sources/05-organizer-materials/` |
| Speaker | organizer (document, filename only) |

**Verbatim (RU):** OLD: `Классификатор_происшествий_v_046_11_ДТУ_15_11_2024_искл_пожар_задымление.xlsx`.
NEW: `Классификатор_происшествий_v_046_24_корректировка_МВД_+_Департамент (1).xlsx`.

**English:** OLD literally: "Incident classifier v_046_11, ДТУ [likely a department/directorate
abbreviation], 15.11.2024, excl./exception_fire_smoke". NEW literally: "Incident classifier v_046_24,
correction: MVD [Ministry of Internal Affairs] + Department". Both filenames are the only source of
these facts — no accompanying text/email/chat explains either fragment further within this task's
source set.

---

### REQ-5719 — Filename claim "корректировка МВД" matches the observed diff's dominant content

| Field | Value |
|---|---|
| Kind | DOMAIN-FACT |
| Source | Derived from REQ-5711/REQ-5713/REQ-5714 (row-level diff) and REQ-5718 (filename) |
| Speaker | organizer (document) |

**Verbatim:** 90 of the 94 changed rows (96%) have a "Классификатор МВД" sub-column change; the single
largest concentration is in category "Нарушение правопорядка" (Public-order violations — МВД's primary
domain, 34 rows), with a further 17 concentrated in "Пожары и задымления" (REQ-5716). No column
structurally named "МВД" was added or removed (REQ-5702–5705 show the structural additions/removal are
"Сценарий реагирования", "ГУП МСР", and 7 new non-МВД organizations) — the МВД correction is a data-value
correction within the pre-existing 3-column "Классификатор МВД" block, not a structural one.

**English:** The filename's "МВД" claim is corroborated by the diff: the correction is real, large
(90 rows), concentrated in МВД's own subject-matter category, and confined to routing-flag values and
terminology wording — not to the ontology (Признак/Итоговый тип) itself.

---

### REQ-5720 — Filename claim "Департамент": no corroborating row-level change found (OPEN)

| Field | Value |
|---|---|
| Kind | OPEN-QUESTION |
| Source | Filename fragment "..._Департамент (1).xlsx" (REQ-5718) vs. REQ-5706 (0 diffs in all pre-existing "Департамент*" columns) and REQ-5705 (1 new column named "Депортамент гражданского строительства", misspelled) |
| Speaker | organizer (document, filename only — no accompanying text explains it) |

**Verbatim (RU):** Filename fragment: "..._Департамент (1).xlsx". No pre-existing column whose row-1
label contains "Департамент" or "Деп." shows any row-value difference (REQ-5706: 0 diffs across 7 such
column groups, all 1281 common rows). The only structural change containing that word is the addition of
a single new column literally spelled "Депортамент гражданского строительства" (REQ-5705).

**English:** It is ambiguous, without further organizer clarification, which "Департамент" the filename
refers to: (a) the newly added "Депортамент гражданского строительства" column (a structural addition,
not a corrected value, and misspelled in the source), (b) one of the other 6 new non-МВД organizations
added at the tail (Министерство обороны ×2, ГКУ Организатор перевозок, ГПБУ Мосэкомониторинг, ООО
Ситиэнерго) loosely characterized as "Департамент"-type additions, or (c) something not captured by
either the structural or row-value diff performed in this task. Flagged here rather than guessed at.

---

### REQ-5721 — Cross-reference to REQ-3049: this diff does not resolve "искл_пожар_задымление" (OPEN)

| Field | Value |
|---|---|
| Kind | OPEN-QUESTION |
| Source | `SRC-001-domain-docs.md` REQ-3049 (open question) vs. this task's v_046_11→v_046_24 diff (REQ-5715–5717) |
| Speaker | organizer (document, filename only) |

**Verbatim (RU):** REQ-3049 asks what "...искл_пожар_задымление" (in the OLD, v_046_11, filename) means,
given that file already contains a full 271-row "Пожары и задымления" category. This task's diff shows:
the fire/smoke category in v_046_24 (the NEXT version after v_046_11) has the identical 271 rows with
identical classification content to v_046_11 (REQ-5715); only 21 of those rows changed, and only in
МВД/Служба-101 routing (REQ-5716); the 13 fire-relevant rows outside the category are also unchanged
(REQ-5717).

**English:** This diff establishes that whatever "искл_пожар_задымление" meant in v_046_11's own
filename, it did not correspond to a fire/smoke-content difference between v_046_11 and v_046_24 — the
fire/smoke category is stable across this version transition. This does not resolve REQ-3049 itself:
that question is about v_046_11's filename relative to some other/earlier, unseen version, and no such
earlier version is in this task's or SRC-001's source scope. REQ-3049 therefore remains open; this item
records only what the v_046_11→v_046_24 diff does and does not show about it.

---

## 3. Conflicts and changes over time

No direct contradiction was found between the two classifier versions — v_046_24 is a superset/successor
of v_046_11 (same 24 categories, same order, 0 rows removed, 2 rows added, 94 rows with routing-only or
single-typo content changes; REQ-5707–REQ-5717). The filename's own two claims are only partially
corroborated by the diff:
- "корректировка МВД" (МВД correction): strongly corroborated (REQ-5719) — 90/94 changed rows touch the
  МВД block, concentrated in МВД's own subject category.
- "+ Департамент" (+ Department): NOT corroborated by any row-value diff in a pre-existing
  "Департамент"-named column (REQ-5706); left open which "Департамент" is meant (REQ-5720).

Two points carried over from `SRC-001-domain-docs.md` remain open and are not resolved by this task's
sources:
1. REQ-3049 (v_046_11 filename's "искл_пожар_задымление" fragment) — this task's diff narrows nothing
   beyond REQ-5721: the fire/smoke category is stable v_046_11→v_046_24, so this diff offers no evidence
   about what an even earlier/unseen version might have excluded.
2. REQ-5720 (v_046_24 filename's "Департамент" fragment) — newly opened by this task, same category of
   ambiguity (a filename tag with no accompanying explanatory text in scope).
