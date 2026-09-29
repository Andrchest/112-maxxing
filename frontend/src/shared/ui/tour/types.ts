// I7 E56: the in-app tutorial's step shape. The tours themselves are plain data, one file per role
// under `./tours/` (so the Russian texts are easy to edit without touching the component).

/** One step of a guided tour. */
export interface TourStep {
  /** Stable id (tests, screenshots). */
  id: string;
  /** Russian: the popover's heading. */
  title: string;
  /** Russian: 1–3 short sentences naming the real on-screen labels. */
  text: string;
  /** Open this address first when the browser is elsewhere (a tour spans pages). */
  route?: string;
  /**
   * The page the step's target lives on when the step has no `route` of its own (e.g. a live
   * console `/dds/<id>` the tour cannot open by itself). Defaults to `route`, else any page.
   */
  page?: RegExp;
  /** The element to highlight: `[data-tour="<target>"]`. Omitted — a centred text-only step. */
  target?: string;
  /**
   * When the target is not on screen (no live lesson, an empty list), show the step as centred
   * text instead of skipping it. Default: a step with a missing target is skipped.
   */
  explainIfMissing?: boolean;
  /** `[data-tour="<activate>"]` is clicked before the target is looked up (e.g. a tab). */
  activate?: string;
  /** «Далее» clicks the target itself (a link: the tour follows it to the next page). */
  clickOnNext?: boolean;
}
