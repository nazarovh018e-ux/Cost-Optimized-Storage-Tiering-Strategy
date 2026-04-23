"""
data_generator.py
-----------------
Generates a synthetic dataset of storage records with realistic
access patterns, sizes, and timestamps.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd


# ── Configuration ─────────────────────────────────────────────────────────────

DATA_TYPES: list[str] = ["log", "transaction", "media", "backup", "analytics", "user_data"]

# Weighted so logs and transactions dominate (like real systems)
TYPE_WEIGHTS: list[float] = [0.30, 0.25, 0.20, 0.10, 0.10, 0.05]

# Typical size ranges per data type (MB)
SIZE_RANGES: dict[str, tuple[float, float]] = {
    "log":         (0.1,   50),
    "transaction": (0.01,  5),
    "media":       (1,     500),
    "backup":      (100,   5000),
    "analytics":   (10,    200),
    "user_data":   (0.5,   20),
}


# ── Generator ──────────────────────────────────────────────────────────────────

def generate_dataset(
    n_records: int = 10_000,
    seed: int = 42,
    reference_date: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    Generate *n_records* synthetic storage records.

    Parameters
    ----------
    n_records:
        How many records to generate.
    seed:
        Random seed for reproducibility.
    reference_date:
        The "today" date used to compute age_days and days_since_access.
        Defaults to the current date so output is always fresh.

    Returns
    -------
    DataFrame with columns:
        record_id, data_type, size_mb, created_at, last_accessed,
        access_count, age_days, days_since_access
    """
    if n_records < 1:
        raise ValueError(f"n_records must be ≥ 1, got {n_records}")

    random.seed(seed)
    np.random.seed(seed)

    now: datetime = reference_date or datetime.utcnow()

    records: list[dict] = []
    for _ in range(n_records):
        dtype: str = random.choices(DATA_TYPES, weights=TYPE_WEIGHTS, k=1)[0]

        # Age: skewed so most data is 0–365 days, long tail to 3 years
        age_days: int = int(np.random.exponential(scale=180))
        age_days = max(1, min(age_days, 1095))  # clamp 1..1095

        created_at: datetime = now - timedelta(days=age_days)

        # Last access: recent data accessed more recently on average
        if age_days <= 30:
            days_since_access = random.randint(0, age_days)
        elif age_days <= 180:
            days_since_access = int(np.random.exponential(30))
            days_since_access = min(days_since_access, age_days)
        else:
            days_since_access = int(np.random.exponential(120))
            days_since_access = min(days_since_access, age_days)

        last_accessed: datetime = now - timedelta(days=days_since_access)

        # Access count: hot data has many accesses, cold has few
        if days_since_access <= 7:
            access_count = random.randint(10, 500)
        elif days_since_access <= 30:
            access_count = random.randint(2, 50)
        elif days_since_access <= 180:
            access_count = random.randint(1, 15)
        else:
            access_count = random.randint(0, 3)

        lo, hi = SIZE_RANGES[dtype]
        # Log-normal distribution for file sizes
        size_mb: float = round(
            np.random.lognormal(mean=np.log((lo + hi) / 2), sigma=0.6), 3
        )
        size_mb = max(lo, min(size_mb, hi * 2))

        records.append({
            "record_id":          str(uuid.uuid4()),
            "data_type":          dtype,
            "size_mb":            size_mb,
            "created_at":         created_at,
            "last_accessed":      last_accessed,
            "access_count":       access_count,
            "age_days":           age_days,
            "days_since_access":  days_since_access,
        })

    return pd.DataFrame(records)


def summarize_dataset(df: pd.DataFrame) -> None:
    """Print a quick summary of the generated dataset."""
    print("=" * 55)
    print("  Dataset Summary")
    print("=" * 55)
    print(f"  Total records : {len(df):,}")
    print(f"  Total size    : {df['size_mb'].sum() / 1024:.2f} GB")
    print()
    print("  By data type:")
    for dtype in DATA_TYPES:
        sub = df[df["data_type"] == dtype]
        print(
            f"    {dtype:<12} {len(sub):>6,} records  "
            f"{sub['size_mb'].sum() / 1024:>7.2f} GB"
        )
    print()
    print(f"  Age range     : {df['age_days'].min()}–{df['age_days'].max()} days")
    print(f"  Access range  : {df['access_count'].min()}–{df['access_count'].max()}")
    print("=" * 55)


if __name__ == "__main__":
    df = generate_dataset(10_000)
    summarize_dataset(df)
    df.to_csv("storage_records.csv", index=False)
    print("\n  Saved to storage_records.csv")
