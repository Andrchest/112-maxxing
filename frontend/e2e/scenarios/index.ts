// I6 SCENARIOS: every scenario, in run and document order.
import type { Scenario } from './dsl';
import { S01 } from './s01-login-logout';
import { S02 } from './s02-full-lesson';
import { S03 } from './s03-dds-validation';
import { S04 } from './s04-report-release';
import { S05 } from './s05-pass-criteria';
import { S06 } from './s06-text-quality';
import { S07 } from './s07-abort';
import { S08 } from './s08-timer';
import { S09 } from './s09-ownership';
import { S10 } from './s10-admin';
import { S11 } from './s11-export';
import { S12 } from './s12-materials';
import { S13 } from './s13-statistics';
import { S14 } from './s14-scenarios';
import { S15 } from './s15-layout';
import { S16 } from './s16-demo-limits';
import { S17 } from './s17-tutorial';

export const ALL_SCENARIOS: Scenario[] = [S01, S02, S03, S04, S05, S06, S07, S08, S09, S10, S11, S12, S13, S14, S15, S16, S17];
