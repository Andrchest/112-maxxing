import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DdsWorkItemsSection } from './dds-work-items-section';
import { ru } from '@/shared/i18n/ru';
import { makeDdsWorkItem, makeEmergencyResource } from './test-fixtures';

describe('DdsWorkItemsSection — per-service dds_assignments rows + resources', () => {
  it('renders the empty states', () => {
    render(<DdsWorkItemsSection assignments={[]} resources={[]} />);
    expect(screen.getByText(ru.instructorDdsWorkItemsEmpty)).toBeInTheDocument();
    expect(screen.getByText(ru.instructorDdsResourcesEmpty)).toBeInTheDocument();
  });

  it('renders one leg per assignment with its own state and closure reason', () => {
    render(
      <DdsWorkItemsSection
        assignments={[
          makeDdsWorkItem({ service_type: 'AMBULANCE', state: 'CLOSED', closed_at_offset_ms: 9000, closure_reason: 'RESOLVED' }),
        ]}
        resources={[]}
      />,
    );
    expect(screen.getByText(ru.serviceTypeAmbulance)).toBeInTheDocument();
    expect(screen.getByText(ru.ddsStageClosed)).toBeInTheDocument();
    expect(screen.getByText(ru.closureReasonResolved)).toBeInTheDocument();
  });

  it('flags missing required fields per assignment', () => {
    render(<DdsWorkItemsSection assignments={[makeDdsWorkItem({ missing_field_paths: ['address.house'] })]} resources={[]} />);
    expect(screen.getByText(new RegExp(ru.instructorDdsMissingFieldsLabel))).toBeInTheDocument();
  });

  // I6 UX fix: a missing field used to render under its raw path (e.g. `address.locality`) even
  // though `field_specs` (I3 E3a) carries a Russian label for it — same lookup the live operator
  // card already uses.
  it('labels a missing field via field_specs, falling back to the raw path when no spec matches', () => {
    render(
      <DdsWorkItemsSection
        assignments={[
          makeDdsWorkItem({
            missing_field_paths: ['address.locality', 'address.house'],
            field_specs: [
              { field_path: 'address.locality', value_type: 'STRING', enum_name: null, label_ru: 'Locality', scoring_relevant: true, required_for_handoff: true },
            ],
          }),
        ]}
        resources={[]}
      />,
    );
    expect(screen.getByText(new RegExp('Locality'))).toBeInTheDocument();
    expect(screen.getByText(new RegExp('address\\.house'))).toBeInTheDocument();
    expect(screen.queryByText(new RegExp('address\\.locality'))).not.toBeInTheDocument();
  });

  it('renders each resource with its callsign, type and status', () => {
    render(<DdsWorkItemsSection assignments={[]} resources={[makeEmergencyResource({ callsign: 'UNIT-1', current_status: 'DISPATCHED' })]} />);
    expect(screen.getByText(new RegExp('UNIT-1'))).toBeInTheDocument();
    expect(screen.getByText(ru.resourceStatusDispatched)).toBeInTheDocument();
  });
});
