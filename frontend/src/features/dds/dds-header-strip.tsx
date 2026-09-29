// I3 E5c (manager review): the memo workstation's header strip — the reference's phone-row strip
// (`ref/screenshot-dds/image6.png`) plus the card's identity, read-only (the ДДС never edits the
// 112 card, D3) and with no fill-timer (the ДДС has none — only the 112 operator does). Renders
// only the schema's own `group: header` fields (`field_specs`, E3c's rule: nothing hard-coded)
// plus the session's `display_number`; renders nothing when neither is available.
import { t } from '@/shared/i18n';
import type { DdsWorkItem } from '@/entities/work-item';
import { formatCardValueRu, groupVisibleCardFields, isCardValueFilled } from './card-schema-render';
import { useDdsDisplayNumber } from './use-dds-display-number';

interface DdsHeaderStripProps {
  sessionId: string;
  workItem: DdsWorkItem;
}

export function DdsHeaderStrip({ sessionId, workItem }: DdsHeaderStripProps) {
  const displayNumber = useDdsDisplayNumber(sessionId);
  const fieldSpecs = workItem.field_specs ?? [];
  const groups = groupVisibleCardFields(fieldSpecs, workItem.card_values, (spec) => isCardValueFilled(workItem.card_values[spec.field_path]));
  const headerFields = groups.find((group) => group.key === 'header')?.fields ?? [];

  if (headerFields.length === 0 && displayNumber === null) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3" data-slot="dds-header-strip" data-tour="dds-header">
      <div className="flex flex-wrap gap-4">
        {headerFields.map((spec) => (
          <span key={spec.field_path} className="text-sm">
            <span className="text-muted-foreground">{spec.label_ru}: </span>
            {formatCardValueRu(spec, workItem.card_values[spec.field_path])}
          </span>
        ))}
      </div>
      {displayNumber !== null ? (
        <span className="text-sm font-semibold" data-slot="dds-card-number">
          {t('operatorCardNumberLabel')} {displayNumber}
        </span>
      ) : null}
    </div>
  );
}
