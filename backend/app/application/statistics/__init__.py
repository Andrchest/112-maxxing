"""Per-trainee statistics, the trainee's own history and their CSV (I4 E33, HLD 71 §71.10).

* `ports` — `StatisticsReader`, the read model over stored scores, participants and a few events;
* `trainee_statistics` — `getTraineeStatistics`, `getMyHistory`: aggregates of stored rows, never
  re-scored (D11);
* `statistics_csv` — `getTraineeStatisticsCsv`: the same view as a file.
"""
