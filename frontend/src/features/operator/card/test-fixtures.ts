// Shared v2 fixtures for `features/operator/card/**`'s component tests (not a test file itself —
// no `.test.` in the name, so vitest does not collect it, and `.ts` rather than `.tsx` so the
// no-Cyrillic-literal guard (`src/app/no-cyrillic-guard.test.ts`, D12) — which scans every `.tsx`
// under `src/features` for a hard-coded Russian string — never looks at it; these `label_ru`
// values are fixture data standing in for the server's `CardFieldSpec.label_ru`, not
// trainee-facing UI text authored in this repo, exactly like `../test-fixtures.ts`'s v1 table).
import type { CardFieldSpec, OperatorCardView } from '@/entities/card';

export const V2_CARD_FIELD_SPECS: CardFieldSpec[] = [
  { field_path: 'caller.phone_aon', value_type: 'STRING', enum_name: null, label_ru: 'АОН', scoring_relevant: false, required_for_handoff: false, group: 'header', order: 0, control: 'PHONE' },
  { field_path: 'caller.full_name', value_type: 'STRING', enum_name: null, label_ru: 'Фамилия и имя заявителя', scoring_relevant: true, required_for_handoff: false, group: 'applicant', order: 0, control: 'TEXT' },
  { field_path: 'address.street', value_type: 'STRING', enum_name: null, label_ru: 'Улица', scoring_relevant: true, required_for_handoff: false, group: 'address', order: 0, control: 'TEXT' },
  { field_path: 'description.text', value_type: 'STRING', enum_name: null, label_ru: 'Описание со слов заявителя', scoring_relevant: true, required_for_handoff: true, group: 'description', order: 0, control: 'TEXTAREA' },
  {
    field_path: 'flags.no_contact',
    value_type: 'BOOLEAN',
    enum_name: null,
    label_ru: 'нет контакта',
    scoring_relevant: false,
    required_for_handoff: false,
    group: 'flags',
    order: 0,
    control: 'CHECKBOX',
  },
  {
    field_path: 'incident.types',
    value_type: 'STRING_LIST',
    enum_name: null,
    label_ru: 'Что случилось?',
    scoring_relevant: true,
    required_for_handoff: true,
    group: 'incident',
    order: 0,
    control: 'CHIPS',
    options: [
      { code: '1', label_ru: '101' },
      { code: '13', label_ru: '104' },
    ],
    routing_relevant: true,
  },
  {
    field_path: 'q.fire.where',
    value_type: 'STRING_LIST',
    enum_name: null,
    label_ru: 'Где',
    scoring_relevant: true,
    required_for_handoff: false,
    group: 'q_fire',
    order: 0,
    control: 'TOGGLE_SET',
    options: [
      { code: 'на улице', label_ru: 'Улица' },
      { code: 'жилой дом', label_ru: 'Дом' },
    ],
    visible_when: { field_path: 'incident.types', op: 'CONTAINS', value: '1' },
    routing_relevant: true,
  },
  { field_path: 'recipients.services', value_type: 'STRING_LIST', enum_name: null, label_ru: 'Службы', scoring_relevant: true, required_for_handoff: true, group: 'services', order: 0, control: 'CHIPS' },
  { field_path: 'recipients.comment', value_type: 'STRING', enum_name: null, label_ru: 'Комментарий для служб', scoring_relevant: false, required_for_handoff: false, group: 'services', order: 1, control: 'TEXTAREA' },
];

// Named so `.tsx` test files never need to spell a Cyrillic literal themselves (the no-Cyrillic
// guard scans every `.tsx` under `src/features`, tests included).
export const V2_LABELS = {
  phoneAon: 'АОН',
  fullName: 'Фамилия и имя заявителя',
  street: 'Улица',
  incidentTypesGroup: 'Что случилось?',
  addIncidentTypeButton: 'добавить тип происшествия',
  incidentType101: '101',
  // The reference's own chip wording for code '1' (ui-check D-5), what `chips-control.tsx`'s
  // `CHIP_LABEL_OVERRIDE` renders instead of the bare option label «101» — must stay equal to
  // `ru.ts`'s `operatorGroupQFire` (both name the same reference text, from different tables).
  incidentType101ChipText: 'Происшествие 101',
  qFireWhere: 'Где',
  qFireWhereOnStreet: 'на улице',
  services: 'Службы',
};

// I7 E55: the card-instruction fields (`reference/card-schema/v2.yaml`, labels verbatim from
// «Инструкция_по_заведению_карточки_2507ГСИ.docx»), with the two fields their `visible_when` reads.
export const E55_CARD_FIELD_SPECS: CardFieldSpec[] = [
  {
    field_path: 'caller.status',
    value_type: 'ENUM',
    enum_name: null,
    label_ru: 'Статус заявителя',
    scoring_relevant: false,
    required_for_handoff: false,
    group: 'applicant',
    order: 1,
    control: 'SELECT',
    options: [
      { code: 'EYEWITNESS', label_ru: 'очевидец' },
      { code: 'VICTIM', label_ru: 'пострадавший' },
      { code: 'RELATIVE', label_ru: 'родственник' },
      { code: 'ACQUAINTANCE', label_ru: 'знакомый' },
      { code: 'CHILD', label_ru: 'ребенок' },
      { code: 'PARTICIPANT', label_ru: 'участник' },
    ],
  },
  {
    field_path: 'applicant.channel',
    value_type: 'ENUM',
    enum_name: null,
    label_ru: 'Канал связи',
    scoring_relevant: false,
    required_for_handoff: false,
    group: 'applicant',
    order: 2,
    control: 'SELECT',
    options: [
      { code: 'MOBILE_APP', label_ru: 'Мобильное приложение' },
      { code: 'MTS', label_ru: 'МТС' },
    ],
  },
  {
    field_path: 'description.text',
    value_type: 'STRING',
    enum_name: null,
    label_ru: 'Описание со слов заявителя',
    scoring_relevant: true,
    required_for_handoff: true,
    group: 'description',
    order: 0,
    control: 'TEXTAREA',
    max_length: 1999,
  },
  {
    field_path: 'flags.casualties',
    value_type: 'BOOLEAN',
    enum_name: null,
    label_ru: 'Пострадавшие',
    scoring_relevant: true,
    required_for_handoff: false,
    group: 'flags',
    order: 0,
    control: 'CHECKBOX',
    options: [{ code: 'casualties', label_ru: 'Пострадавшие' }],
    routing_relevant: true,
  },
  {
    field_path: 'flags.casualties_count',
    value_type: 'INTEGER',
    enum_name: null,
    label_ru: 'Количество',
    scoring_relevant: false,
    required_for_handoff: false,
    group: 'flags',
    order: 1,
    control: 'NUMBER',
    visible_when: { field_path: 'flags.casualties', op: 'EQ', value: true },
  },
  {
    field_path: 'incident.types',
    value_type: 'STRING_LIST',
    enum_name: null,
    label_ru: 'Что случилось?',
    scoring_relevant: true,
    required_for_handoff: true,
    group: 'incident',
    order: 0,
    control: 'CHIPS',
    options: [
      { code: '1', label_ru: '101' },
      { code: '22', label_ru: '103' },
    ],
    routing_relevant: true,
  },
  {
    field_path: 'flags.response_refused',
    value_type: 'BOOLEAN',
    enum_name: null,
    label_ru: 'Отказ от реагирования',
    scoring_relevant: false,
    required_for_handoff: false,
    group: 'q_ambulance',
    order: 0,
    control: 'CHECKBOX',
    options: [{ code: 'RESPONSE_REFUSED', label_ru: 'Отказ от реагирования Скорой', routing: 'none' }],
    visible_when: { field_path: 'incident.types', op: 'CONTAINS', value: '22' },
  },
];

export const E55_LABELS = {
  callerStatus: 'Статус заявителя',
  callerStatuses: ['очевидец', 'пострадавший', 'родственник', 'знакомый', 'ребенок', 'участник'],
  channel: 'Канал связи',
  channelMts: 'МТС',
  description: 'Описание со слов заявителя',
  casualties: 'Пострадавшие',
  casualtiesCount: 'Количество',
  // Must stay equal to `ru.ts`'s `operatorGroupQAmbulance` (instr fig. 16's block title).
  ambulanceBlock: 'Происшествие 103',
  responseRefusedButton: 'Отказ от реагирования Скорой',
};

export function makeE55Card(overrides: Partial<OperatorCardView> = {}): OperatorCardView {
  return {
    card_id: 'card-v2-e55',
    incident_id: 'inc-v2-e55',
    values: {},
    revision_counter: 0,
    field_specs: E55_CARD_FIELD_SPECS,
    card_schema: 'v2',
    ...overrides,
  };
}

export function makeV2Card(overrides: Partial<OperatorCardView> = {}): OperatorCardView {
  return {
    card_id: 'card-v2-1',
    incident_id: 'inc-v2-1',
    values: {},
    revision_counter: 0,
    field_specs: V2_CARD_FIELD_SPECS,
    card_schema: 'v2',
    ...overrides,
  };
}
