"""Unit tests for src/data/ingest.py."""

import os
import sys
import tempfile

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.ingest import validate_categories, validate_nulls, validate_schema


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_df():
    return pd.DataFrame({
        "description": ["Zomato payment", "Uber ride", "Netflix subscription"],
        "amount": [350.0, 120.0, 499.0],
        "category": ["Food & Dining", "Transport", "Entertainment"],
    })


@pytest.fixture
def df_missing_column():
    return pd.DataFrame({
        "description": ["Zomato payment"],
        "amount": [350.0],
    })


@pytest.fixture
def df_with_nulls():
    return pd.DataFrame({
        "description": ["Zomato payment", None, "Uber ride"],
        "amount": [350.0, 120.0, None],
        "category": ["Food & Dining", "Transport", "Transport"],
    })


@pytest.fixture
def df_unknown_category():
    return pd.DataFrame({
        "description": ["Some transaction"],
        "amount": [100.0],
        "category": ["Unknown Category"],
    })


# ── Tests: validate_schema ────────────────────────────────────────────────────

def test_validate_schema_passes_on_valid_df(valid_df):
    """No exception raised for a valid DataFrame."""
    validate_schema(valid_df)


def test_validate_schema_raises_on_missing_column(df_missing_column):
    """ValueError raised when required column is absent."""
    with pytest.raises(ValueError, match="Missing required columns"):
        validate_schema(df_missing_column)


def test_validate_schema_raises_on_wrong_amount_type():
    """ValueError raised when amount column contains non-numeric data."""
    df = pd.DataFrame({
        "description": ["Zomato"], "amount": ["not_a_number"], "category": ["Food & Dining"]
    })
    with pytest.raises((ValueError, TypeError)):
        validate_schema(df)


# ── Tests: validate_nulls ─────────────────────────────────────────────────────

def test_validate_nulls_no_change_on_clean_df(valid_df):
    """DataFrame is unchanged when there are no nulls."""
    result = validate_nulls(valid_df)
    assert len(result) == len(valid_df)


def test_validate_nulls_drops_null_rows(df_with_nulls):
    """Rows with nulls in required columns are dropped."""
    result = validate_nulls(df_with_nulls)
    assert result.isnull().sum().sum() == 0
    assert len(result) < len(df_with_nulls)


# ── Tests: validate_categories ────────────────────────────────────────────────

def test_validate_categories_passes_known(valid_df):
    """Known categories pass without filtering."""
    result = validate_categories(valid_df)
    assert len(result) == len(valid_df)


def test_validate_categories_drops_unknown(df_unknown_category):
    """Unknown categories are removed from the DataFrame."""
    result = validate_categories(df_unknown_category)
    assert len(result) == 0


# ── Integration: ingest function ─────────────────────────────────────────────

def test_ingest_writes_output():
    """End-to-end ingest: valid input CSV produces a non-empty output CSV."""
    from src.data.ingest import ingest  # noqa: PLC0415

    df = pd.DataFrame({
        "description": ["Zomato payment", "Uber trip", "BESCOM bill"],
        "amount": [200.0, 100.0, 500.0],
        "category": ["Food & Dining", "Transport", "Utilities"],
    })

    with tempfile.TemporaryDirectory() as tmpdir:
        raw_path = os.path.join(tmpdir, "raw", "transactions.csv")
        out_path = os.path.join(tmpdir, "ingested", "transactions.csv")
        os.makedirs(os.path.dirname(raw_path))
        df.to_csv(raw_path, index=False)

        ingest(raw_path=raw_path, output_path=out_path)

        assert os.path.exists(out_path)
        result = pd.read_csv(out_path)
        assert len(result) == 3
        assert set(result.columns) >= {"description", "amount", "category"}
