"""
main.py
-------
Entry point for the StorageTierIQ project.

Usage:
    python main.py                          # run with default settings
    python main.py --policy aggressive      # use aggressive tiering
    python main.py --records 50000          # larger dataset
    python main.py --hot-days 14            # custom hot-age threshold
    python main.py --no-dashboard           # skip chart generation
    python main.py --help
"""

import argparse
import sys
import os

from data_generator  import generate_dataset, summarize_dataset
from policy_engine   import PolicyEngine, POLICIES
from cost_estimator  import CostEstimator, PricingModel, sensitivity_analysis
from report_generator import generate_report


def parse_args():
    p = argparse.ArgumentParser(
        description="StorageTierIQ — Cost-Optimized Storage Tiering System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --policy aggressive --records 20000
  python main.py --hot-days 14 --warm-days 120 --cold-only-after 365
        """
    )
    p.add_argument("--records",    type=int, default=10_000,
                   help="Number of synthetic records to generate (default: 10000)")
    p.add_argument("--seed",       type=int, default=42,
                   help="Random seed for reproducibility")
    p.add_argument("--policy",     choices=["default","aggressive","conservative","custom"],
                   default="default",
                   help="Preset tiering policy (default: default)")

    # Custom policy overrides
    p.add_argument("--hot-days",   type=int,   default=None,
                   help="Override: max age (days) for HOT tier")
    p.add_argument("--warm-days",  type=int,   default=None,
                   help="Override: max age (days) for WARM tier")
    p.add_argument("--hot-access", type=int,   default=None,
                   help="Override: days-since-access threshold for HOT")
    p.add_argument("--hot-price",  type=float, default=None,
                   help="Override: hot storage $/GB/month")

    p.add_argument("--no-dashboard", action="store_true",
                   help="Skip dashboard PNG generation")
    p.add_argument("--output-dir", default=".",
                   help="Directory for output files (default: current dir)")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    print("\n" + "═" * 60)
    print("  StorageTierIQ — Storage Tiering Cost Analyser")
    print("═" * 60)

    # 1. Generate dataset ─────────────────────────────────────────────────
    print(f"\n[1/5] Generating {args.records:,} synthetic records …")
    df = generate_dataset(args.records, seed=args.seed)  # uses current date by default
    summarize_dataset(df)

    csv_path = os.path.join(args.output_dir, "storage_records.csv")
    df.to_csv(csv_path, index=False)
    print(f"      Saved raw dataset → {csv_path}")

    # 2. Build policy ─────────────────────────────────────────────────────
    print(f"\n[2/5] Building tiering policy  (preset: '{args.policy}') …")
    policy = POLICIES.get(args.policy, POLICIES["default"])

    # Apply CLI overrides
    if args.hot_days   is not None: policy.hot_age_days    = args.hot_days
    if args.warm_days  is not None: policy.warm_age_days   = args.warm_days
    if args.hot_access is not None: policy.hot_access_days = args.hot_access
    if args.policy == "custom":     policy.name = "custom"

    print(f"      {policy.describe()}")

    # 3. Classify records ─────────────────────────────────────────────────
    print("\n[3/5] Classifying records …")
    engine     = PolicyEngine(policy)
    classified = engine.classify(df)
    summary    = engine.tier_summary(classified)
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    classified_path = os.path.join(args.output_dir, "classified_records.csv")
    classified.to_csv(classified_path, index=False)
    print(f"\n      Saved classified dataset → {classified_path}")

    # 4. Estimate costs ───────────────────────────────────────────────────
    print("\n[4/5] Estimating costs …")
    pricing = PricingModel()
    if args.hot_price is not None:
        pricing.hot_storage_per_gb = args.hot_price
        pricing.baseline_per_gb    = args.hot_price

    estimator = CostEstimator(pricing)
    result    = estimator.estimate(classified)
    estimator.print_report(result)

    sens_df = sensitivity_analysis(classified, pricing)

    # 5. Generate outputs ─────────────────────────────────────────────────
    print("\n[5/5] Generating outputs …")

    # Text report
    report_path = os.path.join(args.output_dir, "tiering_report.txt")
    report = generate_report(classified, result, policy, pricing,
                             output_file=report_path)

    # Dashboard
    if not args.no_dashboard:
        try:
            from visualizer import build_dashboard
            dash_path = os.path.join(args.output_dir, "storage_tiering_dashboard.png")
            build_dashboard(classified, result, sens_df,
                            policy_name=policy.name,
                            output_path=dash_path)
            print(f"      Dashboard saved     → {dash_path}")
        except ImportError as e:
            print(f"      [WARNING] Dashboard skipped: {e}")
    else:
        print("      Dashboard skipped (--no-dashboard).")

    # Final summary
    print("\n" + "═" * 60)
    print("  ✓  Analysis complete!")
    print(f"  Total records   : {len(classified):,}")
    print(f"  Total data      : {result['total_gb']:.2f} GB")
    print(f"  Monthly saving  : ${result['monthly_savings']:,.2f}  "
          f"({result['savings_pct']:.1f}%)")
    print(f"  Annual saving   : ${result['annual_savings']:,.2f}")
    print("\n  Output files:")
    print(f"    {csv_path}")
    print(f"    {classified_path}")
    print(f"    {report_path}")
    if not args.no_dashboard:
        print(f"    {os.path.join(args.output_dir, 'storage_tiering_dashboard.png')}")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
