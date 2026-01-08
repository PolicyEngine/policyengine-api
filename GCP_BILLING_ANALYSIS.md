# GCP Billing Analysis

**Analysis Period:** October 2025 – January 2026
**Currency:** USD ($)

> **Note:** Original billing data was in GBP (£). Converted to USD using rate of £1 = $1.34 (January 2026).

## Service Context

| Project | GCP Service | Description |
|---------|-------------|-------------|
| API v1 | App Engine | API v1 deployment |
| Simulation API | Cloud Run | Simulation API |
| Dataset Calibration | Compute Engine | Mostly one-off dataset calibration costs |

---

## Monthly Cost Breakdown by Service

### October 2025

| Project | GCP Service | Cost ($) | % of Total |
|---------|-------------|----------|------------|
| Simulation API | Cloud Run | 9,229.08 | 84.0% |
| API v1 | App Engine | 1,050.49 | 9.6% |
| Various | Cloud SQL | 403.88 | 3.7% |
| Dataset Calibration | Compute Engine | 154.68 | 1.4% |
| Various | Artifact Registry | 85.40 | 0.8% |
| Various | Networking | 36.02 | 0.3% |
| API v1 | Cloud Storage | 21.60 | 0.2% |
| — | Other | 0.66 | 0.0% |
| | **TOTAL** | **10,981.79** | **100%** |

### November 2025

| Project | GCP Service | Cost ($) | % of Total |
|---------|-------------|----------|------------|
| Simulation API | Cloud Run | 10,643.38 | 84.9% |
| API v1 | App Engine | 1,024.98 | 8.2% |
| Various | Cloud SQL | 397.40 | 3.2% |
| Dataset Calibration | Compute Engine | 317.07 | 2.5% |
| Various | Artifact Registry | 90.73 | 0.7% |
| Various | Networking | 33.19 | 0.3% |
| API v1 | Cloud Storage | 22.20 | 0.2% |
| — | Other | 2.57 | 0.0% |
| | **TOTAL** | **12,531.53** | **100%** |

### December 2025

| Project | GCP Service | Cost ($) | % of Total |
|---------|-------------|----------|------------|
| Simulation API | Cloud Run | 7,716.52 | 73.2% |
| Dataset Calibration | Compute Engine | 1,247.96 | 11.8% |
| API v1 | App Engine | 997.36 | 9.5% |
| Various | Cloud SQL | 409.60 | 3.9% |
| Various | Artifact Registry | 95.01 | 0.9% |
| Various | Networking | 46.24 | 0.4% |
| API v1 | Cloud Storage | 22.61 | 0.2% |
| — | Other | 0.13 | 0.0% |
| | **TOTAL** | **10,535.43** | **100%** |

### January 2026 (Partial: Jan 1–7)

| Project | GCP Service | Cost ($) | % of Total |
|---------|-------------|----------|------------|
| Simulation API | Cloud Run | 387.15 | 50.7% |
| API v1 | App Engine | 214.53 | 28.1% |
| Various | Cloud SQL | 88.82 | 11.6% |
| Dataset Calibration | Compute Engine | 44.21 | 5.8% |
| Various | Artifact Registry | 21.01 | 2.8% |
| API v1 | Cloud Storage | 4.25 | 0.6% |
| Various | Networking | 4.01 | 0.5% |
| | **TOTAL** | **763.97** | **100%** |

---

## January 2026 Projection

Based on daily averages from December 20, 2025 onward (post-optimization stable period):

| Project | GCP Service | Estimated Monthly Cost ($) | % of Total |
|---------|-------------|---------------------------|------------|
| Simulation API | Cloud Run | 1,764.94 | 50.2% |
| API v1 | App Engine | 948.12 | 27.0% |
| Various | Cloud SQL | 403.59 | 11.5% |
| Dataset Calibration | Compute Engine | 260.25 | 7.4% |
| Various | Artifact Registry | 95.15 | 2.7% |
| API v1 | Cloud Storage | 20.73 | 0.6% |
| Various | Networking | 19.98 | 0.6% |
| — | Other | 0.38 | 0.0% |
| | **TOTAL** | **3,513.16** | **100%** |

**Note:** The Compute Engine estimate ($260.25) is elevated due to one-off calibration costs during the Dec 20+ period. Excluding spikes, baseline Compute Engine is approximately $201/month.

---

## Savings from Container Reduction (Dec 16–17)

On December 16–17, 2025, the number of always-on containers for the Simulation API (Cloud Run) was significantly reduced.

### Cloud Run Cost Transition

| Date | Daily Cost ($) |
|------|---------------|
| 2025-12-14 | 446.69 |
| 2025-12-15 | 446.94 |
| 2025-12-16 | 419.49 |
| **2025-12-17** | **104.71** ← Change deployed |
| 2025-12-18 | 57.77 |
| 2025-12-19 | 55.98 |
| 2025-12-20 | 54.97 |
| 2025-12-21 | 55.30 |
| 2025-12-22 | 55.36 |

### Savings Summary

| Metric | Value |
|--------|-------|
| Pre-change daily average (Dec 1–16) | $425.22 |
| Post-change daily average (Dec 20+) | $56.94 |
| **Daily savings** | **$368.29** |
| **Monthly savings** | **$11,048.70** |
| **Annual savings** | **$134,424.34** |

The container reduction achieved an **87% cost reduction** in Cloud Run spending.

---

## Summary

| Period | Total Cost ($) |
|--------|---------------|
| October 2025 | 10,981.79 |
| November 2025 | 12,531.53 |
| December 2025 | 10,535.43 |
| January 2026 (projected) | ~3,513.16 |

**Key Takeaway:** The December 16–17 container optimization reduced monthly costs by approximately **$11,049**, bringing projected January 2026 costs to **$3,513** — a **~70% reduction** from pre-optimization months.
