"""
tests/test_storagetieriq.py
---------------------------
Unit tests for StorageTierIQ.

Run with:
    pytest tests/ -v
"""

from __future__ import annotations

import sys
import os

# Ensure project root is on path when tests are run from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
from datetime import datetime

from data_generator import generate_dataset, DATA_TYPES
from policy_engine import (
    PolicyEngine, TieringPolicy, POLICIES,
    HOT, WARM, COLD,
)
from cost_estimator import CostEstimator, PricingModel, sensitivity_analysis, compare_policies


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def small_df() -> pd.DataFrame:
    return generate_dataset(500, seed=0)


@pytest.fixture(scope="module")
def classified_df(small_df) -> pd.DataFrame:
    return PolicyEngine(POLICIES["default"]).classify(small_df)


@pytest.fixture
def default_policy() -> TieringPolicy:
    return TieringPolicy(name="test")


@pytest.fixture
def default_pricing() -> PricingModel:
    return PricingModel()


# ─────────────────────────────────────────────────────────────────────────────
# data_generator tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDataGenerator:
    def test_row_count(self):
        df = generate_dataset(200, seed=1)
        assert len(df) == 200

    def test_required_columns(self):
        df = generate_dataset(50, seed=2)
        expected = {
            "record_id", "data_type", "size_mb", "created_at",
            "last_accessed", "access_count", "age_days", "days_since_access",
        }
        assert expected.issubset(set(df.columns))

    def test_reproducible_with_seed(self):
        # Pin reference_date so timestamps are deterministic; exclude uuid4 record_id
        ref = datetime(2024, 1, 1)
        df1 = generate_dataset(100, seed=42, reference_date=ref)
        df2 = generate_dataset(100, seed=42, reference_date=ref)
        cols = [c for c in df1.columns if c != "record_id"]
        pd.testing.assert_frame_equal(df1[cols].reset_index(drop=True),
                                      df2[cols].reset_index(drop=True))

    def test_different_seeds_differ(self):
        df1 = generate_dataset(100, seed=1)
        df2 = generate_dataset(100, seed=2)
        assert not df1["size_mb"].equals(df2["size_mb"])

    def test_age_days_in_range(self):
        df = generate_dataset(1_000, seed=3)
        assert df["age_days"].min() >= 1
        assert df["age_days"].max() <= 1095

    def test_days_since_access_le_age(self):
        df = generate_dataset(500, seed=4)
        assert (df["days_since_access"] <= df["age_days"]).all()

    def test_no_negative_sizes(self):
        df = generate_dataset(500, seed=5)
        assert (df["size_mb"] > 0).all()

    def test_data_types_are_known(self):
        df = generate_dataset(500, seed=6)
        assert set(df["data_type"].unique()).issubset(set(DATA_TYPES))

    def test_unique_record_ids(self):
        df = generate_dataset(500, seed=7)
        assert df["record_id"].nunique() == len(df)

    def test_custom_reference_date(self):
        ref = datetime(2023, 1, 1)
        df = generate_dataset(100, seed=8, reference_date=ref)
        assert (df["created_at"] <= ref).all()

    def test_invalid_n_records_raises(self):
        with pytest.raises(ValueError):
            generate_dataset(0)


# ─────────────────────────────────────────────────────────────────────────────
# TieringPolicy tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTieringPolicy:
    def test_default_instantiates(self):
        p = TieringPolicy()
        assert p.name == "default"

    def test_invalid_hot_ge_warm_raises(self):
        with pytest.raises(ValueError):
            TieringPolicy(hot_age_days=200, warm_age_days=100)

    def test_invalid_accesses_raises(self):
        with pytest.raises(ValueError):
            TieringPolicy(hot_min_accesses=2, warm_min_accesses=5)

    def test_describe_returns_string(self, default_policy):
        desc = default_policy.describe()
        assert isinstance(desc, str)
        assert "HOT" in desc and "WARM" in desc and "COLD" in desc

    def test_preset_policies_exist(self):
        for name in ["default", "aggressive", "conservative"]:
            assert name in POLICIES
            assert isinstance(POLICIES[name], TieringPolicy)


# ─────────────────────────────────────────────────────────────────────────────
# PolicyEngine tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyEngine:
    def test_classify_returns_copy(self, small_df):
        engine = PolicyEngine()
        result = engine.classify(small_df)
        assert "tier" not in small_df.columns, "classify() must not mutate the input"
        assert "tier" in result.columns

    def test_tier_values_are_valid(self, classified_df):
        assert set(classified_df["tier"].unique()).issubset({HOT, WARM, COLD})

    def test_all_records_get_a_tier(self, small_df, classified_df):
        assert len(classified_df) == len(small_df)
        assert classified_df["tier"].notna().all()

    def test_backup_always_cold(self, classified_df):
        backup_rows = classified_df[classified_df["data_type"] == "backup"]
        assert (backup_rows["tier"] == COLD).all()

    def test_very_recent_data_is_hot(self):
        """Records created yesterday with many accesses must be HOT."""
        df = pd.DataFrame([{
            "record_id": "abc",
            "data_type": "log",
            "size_mb": 1.0,
            "created_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
            "access_count": 100,
            "age_days": 1,
            "days_since_access": 0,
        }])
        result = PolicyEngine().classify(df)
        assert result.iloc[0]["tier"] == HOT

    def test_large_file_not_in_hot(self):
        """Files > large_file_threshold_mb must not land in HOT."""
        df = pd.DataFrame([{
            "record_id": "xyz",
            "data_type": "media",
            "size_mb": 2000.0,   # > 1000 MB threshold
            "created_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
            "access_count": 999,
            "age_days": 1,
            "days_since_access": 0,
        }])
        result = PolicyEngine().classify(df)
        assert result.iloc[0]["tier"] != HOT

    def test_old_infrequent_data_is_cold(self):
        """Ancient, rarely-accessed data must be COLD."""
        df = pd.DataFrame([{
            "record_id": "old",
            "data_type": "log",
            "size_mb": 5.0,
            "created_at": datetime(2020, 1, 1),
            "last_accessed": datetime(2020, 6, 1),
            "access_count": 1,
            "age_days": 1000,
            "days_since_access": 900,
        }])
        result = PolicyEngine().classify(df)
        assert result.iloc[0]["tier"] == COLD

    def test_missing_column_raises(self):
        bad_df = pd.DataFrame([{"age_days": 10, "size_mb": 5.0}])
        with pytest.raises(ValueError, match="missing required columns"):
            PolicyEngine().classify(bad_df)

    def test_tier_summary_has_all_tiers(self, classified_df):
        engine  = PolicyEngine()
        summary = engine.tier_summary(classified_df)
        assert set(summary["tier"].str.lower()) == {HOT, WARM, COLD}

    def test_tier_summary_pct_sums_to_100(self, classified_df):
        engine  = PolicyEngine()
        summary = engine.tier_summary(classified_df)
        assert abs(summary["pct_records"].sum() - 100.0) < 1e-6
        assert abs(summary["pct_gb"].sum() - 100.0) < 1e-6

    def test_preset_policies_produce_different_distributions(self, small_df):
        distributions = {}
        for name, policy in POLICIES.items():
            classified = PolicyEngine(policy).classify(small_df)
            distributions[name] = classified["tier"].value_counts(normalize=True).to_dict()
        # aggressive should push more data to COLD than conservative
        assert (
            distributions["aggressive"].get(COLD, 0)
            >= distributions["conservative"].get(COLD, 0)
        )


# ─────────────────────────────────────────────────────────────────────────────
# CostEstimator tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCostEstimator:
    def test_estimate_returns_expected_keys(self, classified_df, default_pricing):
        result = CostEstimator(default_pricing).estimate(classified_df)
        for key in ["per_tier", "tiered_total", "baseline", "monthly_savings",
                    "savings_pct", "annual_savings", "total_gb"]:
            assert key in result

    def test_tiered_total_lt_baseline(self, classified_df, default_pricing):
        result = CostEstimator(default_pricing).estimate(classified_df)
        assert result["tiered_total"] < result["baseline"]

    def test_savings_positive(self, classified_df, default_pricing):
        result = CostEstimator(default_pricing).estimate(classified_df)
        assert result["monthly_savings"] > 0
        assert result["annual_savings"] == pytest.approx(result["monthly_savings"] * 12)

    def test_savings_pct_in_range(self, classified_df, default_pricing):
        result = CostEstimator(default_pricing).estimate(classified_df)
        assert 0 < result["savings_pct"] < 100

    def test_per_tier_has_three_rows(self, classified_df, default_pricing):
        result = CostEstimator(default_pricing).estimate(classified_df)
        assert len(result["per_tier"]) == 3

    def test_total_gb_matches_data(self, classified_df, default_pricing):
        result = CostEstimator(default_pricing).estimate(classified_df)
        expected_gb = classified_df["size_mb"].sum() / 1024
        assert result["total_gb"] == pytest.approx(expected_gb)

    def test_aggressive_policy_saves_more(self, small_df, default_pricing):
        """Aggressive tiering should yield higher savings than conservative."""
        results = {}
        for name, policy in POLICIES.items():
            classified = PolicyEngine(policy).classify(small_df)
            results[name] = CostEstimator(default_pricing).estimate(classified)

        assert (
            results["aggressive"]["monthly_savings"]
            >= results["conservative"]["monthly_savings"]
        )

    def test_sensitivity_analysis_returns_dataframe(self, classified_df, default_pricing):
        df = sensitivity_analysis(classified_df, default_pricing)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert "hot_$/gb" in df.columns
        assert "annual_saving" in df.columns

    def test_sensitivity_savings_increase_with_hot_price(self, classified_df, default_pricing):
        """Higher hot-tier price → higher savings from tiering."""
        df = sensitivity_analysis(classified_df, default_pricing).sort_values("hot_$/gb")
        savings = df["annual_saving"].tolist()
        assert savings == sorted(savings), "Annual savings should grow as hot price rises"


# ─────────────────────────────────────────────────────────────────────────────
# PricingModel validation tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPricingModel:
    def test_default_instantiates(self):
        p = PricingModel()
        assert p.hot_storage_per_gb > p.warm_storage_per_gb > p.cold_storage_per_gb

    def test_zero_price_raises(self):
        with pytest.raises(ValueError):
            PricingModel(hot_storage_per_gb=0)

    def test_inverted_prices_raise(self):
        with pytest.raises(ValueError):
            PricingModel(cold_storage_per_gb=1.0, warm_storage_per_gb=0.5,
                         hot_storage_per_gb=0.1)

    def test_missing_tier_column_raises(self, small_df):
        with pytest.raises(ValueError, match="'tier' column"):
            CostEstimator().estimate(small_df)


# ─────────────────────────────────────────────────────────────────────────────
# compare_policies tests
# ─────────────────────────────────────────────────────────────────────────────

class TestComparePolicies:
    def test_returns_one_row_per_policy(self, small_df):
        classified_map = {
            name: PolicyEngine(policy).classify(small_df)
            for name, policy in POLICIES.items()
        }
        result = compare_policies(classified_map)
        assert len(result) == len(POLICIES)

    def test_sorted_by_annual_savings(self, small_df):
        classified_map = {
            name: PolicyEngine(policy).classify(small_df)
            for name, policy in POLICIES.items()
        }
        result = compare_policies(classified_map)
        savings = result["annual_saving_$"].tolist()
        assert savings == sorted(savings, reverse=True)

    def test_aggressive_tops_comparison(self, small_df):
        classified_map = {
            name: PolicyEngine(policy).classify(small_df)
            for name, policy in POLICIES.items()
        }
        result = compare_policies(classified_map)
        assert result.iloc[0]["policy"] == "aggressive"
