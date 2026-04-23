"""
policy_engine.py
----------------
Rule-based tiering policy engine.
Classifies each record into HOT / WARM / COLD based on
configurable age, access frequency, and size thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


# ── Tier labels ───────────────────────────────────────────────────────────────

HOT  = "hot"
WARM = "warm"
COLD = "cold"

TIER_ORDER: list[str] = [HOT, WARM, COLD]

_REQUIRED_COLUMNS: set[str] = {
    "age_days", "days_since_access", "access_count", "data_type", "size_mb"
}


# ── Policy configuration ──────────────────────────────────────────────────────

@dataclass
class TieringPolicy:
    """
    All thresholds are user-tunable.  The engine applies rules in priority
    order: HOT criteria first, then WARM, everything else → COLD.

    HOT criteria  (any one must be true):
        • age_days             ≤ hot_age_days
        • days_since_access    ≤ hot_access_days
        • access_count         ≥ hot_min_accesses

    WARM criteria  (any one must be true, after excluding HOT):
        • age_days             ≤ warm_age_days
        • days_since_access    ≤ warm_access_days
        • access_count         ≥ warm_min_accesses

    COLD  : everything else.

    Override rules:
        • Records with compliance tags (backup) always go to COLD
          regardless of age (if force_backup_cold is True).
        • Records larger than large_file_threshold_mb bypass HOT
          (huge files are rarely accessed quickly enough to justify SSD).
    """
    # HOT thresholds
    hot_age_days:      int   = 30
    hot_access_days:   int   = 7
    hot_min_accesses:  int   = 20

    # WARM thresholds
    warm_age_days:     int   = 180
    warm_access_days:  int   = 60
    warm_min_accesses: int   = 3

    # Overrides
    force_backup_cold:       bool  = True
    large_file_threshold_mb: float = 1000.0  # files > 1 GB skip HOT

    # Label
    name: str = "default"

    def __post_init__(self) -> None:
        if self.hot_age_days >= self.warm_age_days:
            raise ValueError(
                f"hot_age_days ({self.hot_age_days}) must be < "
                f"warm_age_days ({self.warm_age_days})"
            )
        if self.hot_min_accesses <= self.warm_min_accesses:
            raise ValueError(
                f"hot_min_accesses ({self.hot_min_accesses}) must be > "
                f"warm_min_accesses ({self.warm_min_accesses})"
            )

    def describe(self) -> str:
        lines = [
            f"Policy: '{self.name}'",
            f"  HOT  → age ≤ {self.hot_age_days}d  OR  "
            f"last-access ≤ {self.hot_access_days}d  OR  accesses ≥ {self.hot_min_accesses}",
            f"  WARM → age ≤ {self.warm_age_days}d  OR  "
            f"last-access ≤ {self.warm_access_days}d  OR  accesses ≥ {self.warm_min_accesses}",
            "  COLD → everything else",
            f"  Overrides: backup→COLD={self.force_backup_cold}, "
            f"large-file>{self.large_file_threshold_mb:.0f}MB→skip HOT",
        ]
        return "\n".join(lines)


# ── Engine ────────────────────────────────────────────────────────────────────

class PolicyEngine:
    """Apply a :class:`TieringPolicy` to a DataFrame of storage records."""

    def __init__(self, policy: Optional[TieringPolicy] = None) -> None:
        self.policy: TieringPolicy = policy or TieringPolicy()

    # ------------------------------------------------------------------
    def _validate(self, df: pd.DataFrame) -> None:
        missing = _REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame is missing required columns: {missing}")

    # ------------------------------------------------------------------
    def classify(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Return a copy of *df* with a new ``'tier'`` column.

        The original DataFrame is **not** modified.
        """
        self._validate(df)
        p   = self.policy
        out = df.copy()

        age   = out["age_days"]
        since = out["days_since_access"]
        count = out["access_count"]
        dtype = out["data_type"]
        size  = out["size_mb"]

        # Default everything to COLD
        out["tier"] = COLD

        # WARM (applied first so HOT can overwrite)
        warm_mask = (
            (age   <= p.warm_age_days)    |
            (since <= p.warm_access_days) |
            (count >= p.warm_min_accesses)
        )
        out.loc[warm_mask, "tier"] = WARM

        # HOT (overwrites WARM where criteria met)
        hot_mask = (
            (age   <= p.hot_age_days)    |
            (since <= p.hot_access_days) |
            (count >= p.hot_min_accesses)
        )
        # Large files skip HOT → at most WARM
        large_file_mask = size > p.large_file_threshold_mb
        hot_mask = hot_mask & ~large_file_mask
        out.loc[hot_mask, "tier"] = HOT

        # Override: backup data always cold
        if p.force_backup_cold:
            out.loc[dtype == "backup", "tier"] = COLD

        return out

    # ------------------------------------------------------------------
    def tier_summary(self, classified: pd.DataFrame) -> pd.DataFrame:
        """Return a per-tier summary DataFrame."""
        total_records = len(classified)
        total_mb      = classified["size_mb"].sum()

        rows = []
        for tier in TIER_ORDER:
            sub = classified[classified["tier"] == tier]
            rows.append({
                "tier":          tier.upper(),
                "records":       len(sub),
                "pct_records":   len(sub) / total_records * 100,
                "total_gb":      sub["size_mb"].sum() / 1024,
                "pct_gb":        sub["size_mb"].sum() / total_mb * 100 if total_mb else 0,
                "avg_age_days":  sub["age_days"].mean()     if len(sub) else 0.0,
                "avg_accesses":  sub["access_count"].mean() if len(sub) else 0.0,
            })
        return pd.DataFrame(rows)


# ── Preset policies ───────────────────────────────────────────────────────────

POLICIES: dict[str, TieringPolicy] = {
    "aggressive": TieringPolicy(
        name="aggressive",
        hot_age_days=14,  hot_access_days=3,   hot_min_accesses=50,
        warm_age_days=90, warm_access_days=30,  warm_min_accesses=5,
    ),
    "default": TieringPolicy(name="default"),
    "conservative": TieringPolicy(
        name="conservative",
        hot_age_days=60,   hot_access_days=30,  hot_min_accesses=10,
        warm_age_days=365, warm_access_days=180, warm_min_accesses=2,
    ),
}


if __name__ == "__main__":
    from data_generator import generate_dataset, summarize_dataset

    df = generate_dataset(10_000)
    summarize_dataset(df)

    for name, policy in POLICIES.items():
        engine     = PolicyEngine(policy)
        classified = engine.classify(df)
        summary    = engine.tier_summary(classified)

        print(f"\n{'─' * 55}")
        print(policy.describe())
        print()
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
