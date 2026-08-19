- Canonical ramp baseline (GAE-via-LB at 100/0, captured at the Stage 8 DNS cutover)
  committed to `docs/migration/baselines/`; ramp runbook holds cut to ~4h with a
  peak-window carve-out; rollback runbook records the at-cutover GAE certificate
  expiry and the verified 5-minute DNS TTL.
