// Enum label tables exhaustive (this task's CHECK). Each `Record<Enum, ...>` in `dds-labels.ts`
// already fails `tsc` if a generated union grows a member without a matching row (D12 design
// decision #5) — this test additionally proves every member resolves to a non-empty, distinct
// Russian string at runtime, mirroring `shared/api/client.test.ts`'s `problemMessageRu` suite.
import { describe, expect, it } from 'vitest';
import {
  serviceTypeLabelRu,
  ddsStageStateLabelRu,
  resourceTypeLabelRu,
  resourceStatusLabelRu,
  resourceCapabilityLabelRu,
  notificationSeverityLabelRu,
  statusUpdateKindLabelRu,
  closureReasonLabelRu,
} from './dds-labels';
import type {
  ServiceType,
  DDSStageState,
  ResourceType,
  ResourceStatus,
  ResourceCapability,
  NotificationSeverity,
  StatusUpdateKind,
  ClosureReason,
} from '@/shared/api';

const SERVICE_TYPES: readonly ServiceType[] = ['FIRE_RESCUE', 'POLICE', 'AMBULANCE', 'GAS_SERVICE', 'UTILITY_EMERGENCY', 'EDDS'];
const DDS_STAGE_STATES: readonly DDSStageState[] = ['RECEIVED', 'ACKNOWLEDGED', 'RESOURCE_SELECTION', 'DISPATCHED', 'EN_ROUTE', 'ARRIVED', 'WORKING', 'RESOLVED', 'CLOSED'];
const RESOURCE_TYPES: readonly ResourceType[] = ['FIRE_ENGINE', 'LADDER_TRUCK', 'RESCUE_UNIT', 'AMBULANCE_UNIT', 'RESUSCITATION_UNIT', 'POLICE_PATROL', 'GAS_EMERGENCY_UNIT', 'UTILITY_CREW', 'FIRE_CHIEF_CAR'];
const RESOURCE_STATUSES: readonly ResourceStatus[] = ['AVAILABLE', 'SELECTED', 'DISPATCHED', 'EN_ROUTE', 'ON_SCENE', 'WORKING', 'RETURNING', 'OUT_OF_SERVICE', 'UNAVAILABLE'];
const RESOURCE_CAPABILITIES: readonly ResourceCapability[] = [
  'FIRE_SUPPRESSION', 'HIGH_RISE_ACCESS', 'LADDER_RESCUE', 'TECHNICAL_RESCUE', 'SMOKE_DIVING',
  'BASIC_LIFE_SUPPORT', 'ADVANCED_LIFE_SUPPORT', 'BURN_CARE', 'PUBLIC_ORDER', 'TRAFFIC_CONTROL',
  'AREA_CORDON', 'GAS_SHUTOFF', 'GAS_LEAK_DETECTION', 'POWER_SHUTOFF', 'WATER_SUPPLY', 'COMMAND_AND_CONTROL',
];
const NOTIFICATION_SEVERITIES: readonly NotificationSeverity[] = ['INFO', 'WARNING', 'CRITICAL'];
const STATUS_UPDATE_KINDS: readonly StatusUpdateKind[] = ['ACKNOWLEDGEMENT', 'EN_ROUTE_REPORT', 'ON_SCENE_REPORT', 'SITUATION_UPDATE', 'ADDITIONAL_FORCES_REQUESTED', 'RESOLUTION_REPORT'];
const CLOSURE_REASONS: readonly ClosureReason[] = ['RESOLVED', 'FALSE_CALL', 'TRANSFERRED', 'CANCELLED_BY_CALLER'];

function assertExhaustive<T extends string>(members: readonly T[], labelFn: (value: T) => string): void {
  const labels = members.map(labelFn);
  for (const label of labels) {
    expect(label).toBeTypeOf('string');
    expect(label.length).toBeGreaterThan(0);
  }
  expect(new Set(labels).size).toBe(members.length);
}

describe('DDS console enum label tables', () => {
  it('ServiceType', () => assertExhaustive(SERVICE_TYPES, serviceTypeLabelRu));
  it('DDSStageState', () => assertExhaustive(DDS_STAGE_STATES, ddsStageStateLabelRu));
  it('ResourceType', () => assertExhaustive(RESOURCE_TYPES, resourceTypeLabelRu));
  it('ResourceStatus', () => assertExhaustive(RESOURCE_STATUSES, resourceStatusLabelRu));
  it('ResourceCapability', () => assertExhaustive(RESOURCE_CAPABILITIES, resourceCapabilityLabelRu));
  it('NotificationSeverity', () => assertExhaustive(NOTIFICATION_SEVERITIES, notificationSeverityLabelRu));
  it('StatusUpdateKind', () => assertExhaustive(STATUS_UPDATE_KINDS, statusUpdateKindLabelRu));
  it('ClosureReason', () => assertExhaustive(CLOSURE_REASONS, closureReasonLabelRu));
});
