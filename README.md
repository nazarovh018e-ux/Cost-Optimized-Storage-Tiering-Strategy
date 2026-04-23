# StorageTierIQ — Cost-Optimized Storage Tiering System

![CI](https://github.com/nazarovh018e-ux/Cost-Optimized-Storage-Tiering-Strategy/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A complete Python toolkit that simulates a real-world **Hot / Warm / Cold**
storage tiering strategy, estimates costs, and produces a quantitative policy
justification report.

For companies managing large datasets, storage costs can be substantial.
StorageTierIQ analyzes data characteristics and recommends a cost-optimized
tiering strategy that balances performance and expense.

---

## Project structure

```
storage_tiering_project/
├── main.py               ← entry point / CLI
├── data_generator.py     ← synthetic dataset generation
├── policy_engine.py      ← rule-based tiering classifier
├── cost_estimator.py     ← cost calculations, sensitivity & policy comparison
├── visualizer.py         ← charts & dashboard (PNG)
├── report_generator.py   ← text-based policy report
├── requirements.txt
├── requirements-dev.txt  ← pytest, coverage
├── conftest.py
├── tests/
│   └── test_storagetieriq.py
└── .github/
    └── workflows/
        └── ci.yml        ← CI: test on Python 3.10, 3.11, 3.12 + lint
```

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run with defaults (10,000 records, default policy)
python main.py

# 3. Try an aggressive tiering policy
python main.py --policy aggressive

# 4. Larger dataset with custom hot-age threshold
python main.py --records 50000 --hot-days 14

# 5. Skip dashboard (no matplotlib needed)
python main.py --no-dashboard

# 6. Save all outputs to a specific folder
python main.py --output-dir results/
```

---

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Output files

| File | Description |
|---|---|
| `storage_records.csv` | Raw synthetic dataset |
| `classified_records.csv` | Dataset with `tier` column added |
| `tiering_report.txt` | Full policy justification report |
| `storage_tiering_dashboard.png` | 7-panel visual dashboard |

---

## Storage tiers

| Tier | Storage type | Default price | Use case |
|---|---|---|---|
| **HOT** | SSD / NVMe | $0.092 /GB/mo | Last 30 days, frequently accessed |
| **WARM** | Object storage (S3-IA) | $0.0125 /GB/mo | 30–180 days, occasional access |
| **COLD** | Glacier / Archive | $0.004 /GB/mo | 180+ days, compliance / backup |

---

## Policy presets

| Policy | Hot age | Warm age | Behaviour |
|---|---|---|---|
| `aggressive` | 14 days | 90 days | Move data to cheaper tiers quickly |
| `default` | 30 days | 180 days | Balanced cost vs availability |
| `conservative` | 60 days | 365 days | Keep data hot/warm longer |

---

## CLI options

```
  --records N         Number of synthetic records (default: 10000)
  --seed N            Random seed (default: 42)
  --policy NAME       Preset: default | aggressive | conservative
  --hot-days N        Override max age for HOT tier
  --warm-days N       Override max age for WARM tier
  --hot-access N      Override days-since-access threshold for HOT
  --hot-price FLOAT   Override hot-tier $/GB/month
  --no-dashboard      Skip PNG generation
  --output-dir PATH   Output directory
```

---

## Module usage (as a library)

```python
from data_generator  import generate_dataset
from policy_engine   import PolicyEngine, TieringPolicy
from cost_estimator  import CostEstimator, PricingModel, compare_policies

# Generate data
df = generate_dataset(n_records=10_000)

# Define a custom policy
policy = TieringPolicy(
    name="my_policy",
    hot_age_days=21,
    warm_age_days=120,
    hot_min_accesses=30,
)

# Classify
engine     = PolicyEngine(policy)
classified = engine.classify(df)   # returns a copy — original is not modified

# Estimate costs
pricing = PricingModel(hot_storage_per_gb=0.10)
result  = CostEstimator(pricing).estimate(classified)

print(f"Monthly saving: ${result['monthly_savings']:.2f}")
print(f"Annual saving : ${result['annual_savings']:.2f}")

# Compare all presets side-by-side
from policy_engine import POLICIES
classified_map = {
    name: PolicyEngine(pol).classify(df)
    for name, pol in POLICIES.items()
}
print(compare_policies(classified_map))
```

---

## Dashboard panels

1. **Donut chart** — Record distribution by tier
2. **Horizontal bar** — Storage volume (GB) per tier
3. **Waterfall chart** — Baseline vs tiered cost with savings callout
4. **Grouped bar** — Storage + retrieval cost breakdown per tier
5. **Scatter plot** — Age vs access count, colored by assigned tier
6. **Stacked bar** — Tier distribution by data type
7. **Line chart** — Annual savings sensitivity to hot-tier price

---

## Extending the project

- **Real data**: Replace `data_generator.py` with a reader that pulls from
  your actual storage inventory (AWS S3 inventory reports, GCS object
  listing, or a SQL query against your metadata store).
- **Custom pricing**: Edit `PricingModel` in `cost_estimator.py` with your
  cloud provider's actual prices.
- **ML classifier**: Replace the rule-based `PolicyEngine` with a trained
  classifier (e.g. XGBoost) using access patterns as features and
  manually-labelled tiers as targets.
- **Automated migration**: Feed `classified_records.csv` into a migration
  script that calls `aws s3 cp` / `gsutil` to physically move objects.
