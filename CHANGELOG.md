# Changelog

All notable changes to the HAVI ETL pipeline are recorded here.
Entries cover data corrections, export scope changes, and pipeline behaviour changes
that affect what partners receive or how data is processed.

---

## [Unreleased]

---

## 2026-06-01

### Export
- Export scope set to `n_collections = 2` (first visit = 2 consecutive nights per HH).
- Export filename format: `havi_visit{n}_export_{date}.zip`.
- Confirmed 17 sites × 6 HHs × 2 nights clean and complete.

### Data corrections
- **ento_mosquito** — H26-KM2-0310 (HH 362030228, Kigandalo, 2026-05-06): moved outdoor → indoor (clocation 1 → 2).
- **ento_mosquito** — H26-NT-0311 through H26-NT-0323 (HH 370020624, Nagongera, 2026-05-20): moved indoor → outdoor (clocation 2 → 1).
- **ento_collection** — HH 362030228, 2026-05-06, outdoor: numfanoph corrected 76 → 75.
- **ento_collection** — HH 362030228, 2026-05-06, indoor: numfanoph corrected 25 → 26.
- **hbo_person** — HH 337030120 (Aboke), 2026-05-26: individuals 4, 5, 6 excluded (exact duplicates of 1, 2, 3 — data entry repeated).

### Pending
- Padibe sleeprooms inconsistency: field query sent to team for HHs 329010047, 329020059, 329030104. Awaiting response.

---

## 2026-05-29

### Schema
- Added V1.0 app columns: `aspirations_method`, `rain`, `windforce` (ento_collection); `aspirations_method` (ento_mosquito).
- Old records missing these fields are filled with `-6` (Not applicable) in silver.

### Download policy
- Unversioned archives (`havi_entomology_*`): all timestamps downloaded.
- Versioned archives (`havi_entomology_v*`): latest per device only.
