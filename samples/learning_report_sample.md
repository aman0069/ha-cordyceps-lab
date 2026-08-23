# Cordyceps Lab v2 — Weekly Learning Report

Input: `/home/user/workspace/cordyceps-lab-v2/samples/cordyceps_demo.db`

This report describes associations only. Hypotheses are unconfirmed, and missing values remain missing.

## Data inventory

| Table | Rows | Date range |
|---|---:|---|
| `batch_master` | 12 | 2026-03-01T09:00:00+05:30 → 2026-05-06T09:00:00+05:30 |
| `env_stage_summary` | 23 | 2026-03-02T09:00:00+05:30 → 2026-06-22T18:30:03+05:30 |
| `harvest_yield` | 10 | 2026-04-07T18:21:07+05:30 → 2026-06-13T00:12:37+05:30 |
| `interventions` | 2 | 2026-04-08T18:28:21+05:30 → 2026-05-07T16:37:02+05:30 |
| `jar_master` | 240 | 2026-03-01T09:00:00+05:30 → 2026-05-06T09:00:00+05:30 |
| `observations` | 12 | 2026-03-20T18:21:07+05:30 → 2026-05-30T18:30:03+05:30 |
| `photos` | 6 | 2026-03-23T18:21:07+05:30 → 2026-05-27T00:12:37+05:30 |
| `stage_events` | 56 | 2026-03-01T09:00:00+05:30 → 2026-06-13T00:12:37+05:30 |

## Data completeness per batch

| Batch ID | Observed / assessed fields | Completeness |
|---|---:|---:|
| `AC-20260301-01` | 192 / 206 | 93.2% |
| `AC-20260307-01` | 165 / 179 | 92.2% |
| `AC-20260313-01` | 194 / 206 | 94.2% |
| `AC-20260319-01` | 167 / 181 | 92.3% |
| `AC-20260325-01` | 178 / 193 | 92.2% |
| `AC-20260331-01` | 192 / 205 | 93.7% |
| `AC-20260406-01` | 171 / 185 | 92.4% |
| `AC-20260412-01` | 193 / 205 | 94.1% |
| `AC-20260418-01` | 168 / 182 | 92.3% |
| `AC-20260424-01` | 160 / 170 | 94.1% |
| `AC-20260430-01` | 162 / 175 | 92.6% |
| `AC-20260506-01` | 150 / 162 | 92.6% |

## Correlation scan

All scan p-values are unadjusted. Each row is observational.

### dark-incubation average temperature (°C) ↔ dry weight (g)
`n=8`; Spearman rho = +0.228; p = 0.5878; missing dark-incubation average temperature (°C): 16.7%; missing dry weight (g): 16.7%.
Possible confounders: strain; recipe version; transfer timing; dark-incubation RH. The association is not established beyond these records.

### dark-incubation average RH (%) ↔ dry weight (g)
`n=8`; Spearman rho = -0.071; p = 0.8665; missing dark-incubation average RH (%): 25.0%; missing dry weight (g): 16.7%.
Possible confounders: strain; recipe version; transfer timing; sensor completeness. The association is not established beyond these records.

### inoculation-to-transfer duration (h) ↔ dry weight (g)
`n=9`; Spearman rho = +0.243; p = 0.5292; missing inoculation-to-transfer duration (h): 8.3%; missing dry weight (g): 16.7%.
Possible confounders: strain; recipe version; dark-incubation temperature; colonization score. The association is not established beyond these records.

### dark-incubation average temperature (°C) ↔ contaminated jars (%)
`n=8`; Spearman rho = +0.209; p = 0.6200; missing dark-incubation average temperature (°C): 16.7%; missing contaminated jars (%): 16.7%.
Possible confounders: strain; recipe version; handling sequence; sensor completeness. The association is not established beyond these records.

## Suppressed findings (n<5)

- light-stage average CO₂ (ppm) ↔ dry weight (g): `n=4`; suppressed and not presented as a correlation.

## Low-confidence findings

- dark-incubation average temperature (°C) ↔ dry weight (g) (`n=8`): **insufficient for inference**.
- dark-incubation average RH (%) ↔ dry weight (g) (`n=8`): **insufficient for inference**.
- inoculation-to-transfer duration (h) ↔ dry weight (g) (`n=9`): **insufficient for inference**.
- dark-incubation average temperature (°C) ↔ contaminated jars (%) (`n=8`): **insufficient for inference**.

## Hypotheses

- **Hypothesis:** inoculation-to-transfer duration (h) may be associated with dry weight (g) in a controlled follow-up; this is not established.
- **Hypothesis:** dark-incubation average temperature (°C) may be associated with dry weight (g) in a controlled follow-up; this is not established.
- **Hypothesis:** dark-incubation average temperature (°C) may be associated with contaminated jars (%) in a controlled follow-up; this is not established.

## Proposed experiments

### Proposed experiment card — association follow-up
- **Hypothesis:** The observed association between inoculation-to-transfer duration (h) and dry weight (g) merits a controlled test; it is not established.
- **one_variable_changed:** inoculation-to-transfer duration (h)
- **control_batch_requirement:** Concurrent control batches with the same strain, recipe version, jar type, planned jar count, and chamber allocation.
- **minimum_sample_size:** 25 batches per arm (50 total), simple two-arm estimate with α=0.05, 80% power, and standardized difference=0.80.
- **success_metric:** Batch-level dry weight (g), recorded without zero-filling missing values.
- **duration_estimate:** 6 weeks per arm, based on the median observed inoculation-to-harvest duration.
- **risks:** Between-batch variation, contamination, incomplete sensor coverage, and unbalanced chamber allocation.
- **approved_by_aman:** false
- **Requires Aman's approval:** false

No setpoints have been changed. Nothing in this report is applied automatically.
