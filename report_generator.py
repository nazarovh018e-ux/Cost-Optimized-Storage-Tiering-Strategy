"""
report_generator.py
-------------------
Generates a detailed text-based policy justification report.
Prints to console and optionally saves to a .txt file.
"""

import pandas as pd
from datetime import datetime
from policy_engine  import TieringPolicy, PolicyEngine
from cost_estimator import CostEstimator, PricingModel


LINE = "─" * 65
DLINE = "═" * 65


def generate_report(
    classified: pd.DataFrame,
    result: dict,
    policy: TieringPolicy,
    pricing: PricingModel = None,
    output_file: str = None,
) -> str:
    """
    Build a full markdown-style report string and optionally save it.
    Returns the report as a string.
    """
    pricing = pricing or PricingModel()
    engine  = PolicyEngine(policy)
    summary = engine.tier_summary(classified)

    lines = []
    w = lines.append   # shorthand

    w(DLINE)
    w("  StorageTierIQ — Policy Justification Report")
    w(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    w(f"  Policy    : '{policy.name}'")
    w(DLINE)
    w("")

    # 1. Executive summary ───────────────────────────────────────────────────
    w("1. EXECUTIVE SUMMARY")
    w(LINE)
    w(f"  Total records analysed : {len(classified):,}")
    w(f"  Total data volume      : {result['total_gb']:.2f} GB")
    w(f"  Flat-SSD baseline cost : ${result['baseline']:,.2f} / month")
    w(f"  Tiered policy cost     : ${result['tiered_total']:,.2f} / month")
    w(f"  Monthly savings        : ${result['monthly_savings']:,.2f}  "
      f"({result['savings_pct']:.1f}% reduction)")
    w(f"  Projected annual saving: ${result['annual_savings']:,.2f}")
    w("")
    w("  Recommendation: ADOPT tiered storage policy.")
    w(f"  The tiered policy reduces storage costs by {result['savings_pct']:.1f}%")
    w(f"  while maintaining sub-millisecond access to the {_hot_pct(summary):.1f}%")
    w("  of data that is actively used.")
    w("")

    # 2. Policy rules ────────────────────────────────────────────────────────
    w("2. TIERING POLICY RULES")
    w(LINE)
    w(f"  {policy.describe()}")
    w("")

    # 3. Data distribution ───────────────────────────────────────────────────
    w("3. DATA DISTRIBUTION BY TIER")
    w(LINE)
    _table(lines, summary[[
        "tier","records","pct_records","total_gb","pct_gb",
        "avg_age_days","avg_accesses"
    ]], fmt={
        "records":     ("{:>8,d}",  lambda x: int(x)),
        "pct_records": ("{:>6.1f}%", lambda x: x),
        "total_gb":    ("{:>9.2f}",  lambda x: x),
        "pct_gb":      ("{:>6.1f}%", lambda x: x),
        "avg_age_days":("{:>10.0f}", lambda x: x),
        "avg_accesses":("{:>12.1f}", lambda x: x),
    })
    w("")

    # 4. Cost breakdown ──────────────────────────────────────────────────────
    w("4. MONTHLY COST BREAKDOWN")
    w(LINE)
    pt = result["per_tier"]
    for _, row in pt.iterrows():
        w(f"  {row['tier']:<4}  {row['gb']:>8.2f} GB"
          f"  @ ${row['storage_$/gb']:.4f}/GB"
          f"  storage=${row['storage_cost_$']:>8.2f}"
          f"  retrieval=${row['retrieval_cost_$']:>7.2f}"
          f"  total=${row['total_cost_$']:>8.2f}")
    w(LINE)
    w(f"  {'TIERED TOTAL':<36}  ${result['tiered_total']:>8.2f}")
    w(f"  {'FLAT SSD BASELINE':<36}  ${result['baseline']:>8.2f}")
    w(f"  {'MONTHLY SAVING':<36}  ${result['monthly_savings']:>8.2f}")
    w("")

    # 5. Top migration candidates ────────────────────────────────────────────
    w("5. TOP MIGRATION CANDIDATES (Cold-tier savings)")
    w(LINE)
    cold = (classified[classified["tier"] == "cold"]
            .nlargest(10, "size_mb")[
                ["data_type","size_mb","age_days","days_since_access","access_count"]
            ])
    cold["monthly_saving_$"] = (cold["size_mb"] / 1024) * (
        pricing.baseline_per_gb - pricing.cold_storage_per_gb
    )
    w(cold.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    w("")

    # 6. Quantitative justification ──────────────────────────────────────────
    w("6. QUANTITATIVE JUSTIFICATION")
    w(LINE)

    hot_pct  = _hot_pct(summary)
    cold_pct = summary.loc[summary["tier"]=="COLD","pct_gb"].values[0]
    warm_pct = summary.loc[summary["tier"]=="WARM","pct_gb"].values[0]

    w(f"  a) Only {hot_pct:.1f}% of data (by count) requires hot-tier latency.")
    w(f"     Putting the remaining {100 - hot_pct:.1f}% on SSD wastes expensive")
    w(f"     IOPS capacity on data that is rarely or never accessed.")
    w("")
    w(f"  b) {cold_pct:.1f}% of stored data by volume qualifies for archive tier.")
    w(f"     At ${pricing.cold_storage_per_gb:.4f}/GB vs ${pricing.baseline_per_gb:.4f}/GB baseline,")
    cold_gb = summary.loc[summary["tier"]=="COLD","total_gb"].values[0]
    cold_saving = cold_gb * (pricing.baseline_per_gb - pricing.cold_storage_per_gb)
    w(f"     this segment alone saves ${cold_saving:,.2f}/month.")
    w("")
    w(f"  c) {warm_pct:.1f}% of data sits in warm (object storage).")
    w(f"     S3-IA class provides 99.9% durability at {pricing.warm_storage_per_gb/pricing.baseline_per_gb*100:.0f}% of SSD cost,")
    w(f"     with seconds-latency retrieval acceptable for batch and reporting workloads.")
    w("")
    w(f"  d) Break-even on migration tooling:")
    migration_tooling_estimate = 500  # $ one-time dev cost estimate
    months_to_break_even = migration_tooling_estimate / max(result["monthly_savings"], 0.01)
    w(f"     Assuming ~${migration_tooling_estimate} one-time engineering cost,")
    w(f"     break-even is reached in {months_to_break_even:.1f} months.")
    w("")

    # 7. Risk considerations ─────────────────────────────────────────────────
    w("7. RISK CONSIDERATIONS")
    w(LINE)
    w("  • Cold retrieval latency (hours): not suitable for SLA < 1 hr.")
    w("    Mitigate: tag business-critical records as 'hot-protected'.")
    w("  • Warm retrieval cost ($0.01/GB): monitor monthly egress for")
    w("    workloads that do full scans of warm data.")
    w("  • Policy drift: re-classify monthly as access patterns evolve.")
    w("  • Compliance: backup/audit data forced to COLD — verify regional")
    w("    data-residency requirements for chosen archive provider.")
    w("")

    w(DLINE)
    w("  End of Report")
    w(DLINE)

    report_str = "\n".join(lines)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report_str)
        print(f"  Report saved to: {output_file}")

    return report_str


def _hot_pct(summary: pd.DataFrame) -> float:
    row = summary[summary["tier"] == "HOT"]
    return row["pct_records"].values[0] if len(row) else 0.0


def _table(lines, df, fmt=None):
    """Minimal fixed-width table printer."""
    lines.append("  " + "  ".join(f"{c:<14}" for c in df.columns))
    lines.append("  " + "  ".join("─" * 14 for _ in df.columns))
    for _, row in df.iterrows():
        cells = []
        for col in df.columns:
            val = row[col]
            if fmt and col in fmt:
                tmpl, conv = fmt[col]
                try:
                    cells.append(tmpl.format(conv(val)))
                except Exception:
                    cells.append(str(val)[:14])
            else:
                cells.append(f"{val!s:<14}"[:14])
        lines.append("  " + "  ".join(cells))


if __name__ == "__main__":
    from data_generator import generate_dataset
    from policy_engine  import PolicyEngine, POLICIES
    from cost_estimator import CostEstimator

    df         = generate_dataset(10_000)
    policy     = POLICIES["default"]
    engine     = PolicyEngine(policy)
    classified = engine.classify(df)
    result     = CostEstimator().estimate(classified)

    report = generate_report(classified, result, policy,
                             output_file="tiering_report.txt")
    print(report)
