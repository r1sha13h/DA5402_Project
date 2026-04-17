"""DVC Stage 1 — Data ingestion and schema/quality validation.

Reads the raw CSV, validates schema, checks for nulls and duplicates,
logs baseline statistics, and writes the validated dataset to data/ingested/.
"""

import json
import logging
import os
import sys

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"description", "category"}
EXPECTED_CATEGORIES = {
    "Food & Dining", "Transportation", "Shopping & Retail",
    "Entertainment & Recreation", "Healthcare & Medical",
    "Utilities & Services", "Financial Services", "Income",
    "Government & Legal", "Charity & Donations",
}


def load_params(path: str = "params.yaml") -> dict:
    """Load pipeline parameters from params.yaml."""
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def validate_schema(df: pd.DataFrame) -> None:
    """Assert required columns are present with correct types.

    Args:
        df: Raw transaction DataFrame.

    Raises:
        ValueError: If required columns are missing or types are invalid.
    """
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if not pd.api.types.is_string_dtype(df["description"]):
        raise ValueError("Column 'description' must be string type.")

    if not pd.api.types.is_string_dtype(df["category"]):
        raise ValueError("Column 'category' must be string type.")

    logger.info("Schema validation passed.")


def validate_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Log and drop rows with null values in critical columns.

    Args:
        df: Input DataFrame.

    Returns:
        DataFrame with null rows removed.
    """
    null_counts = df[list(REQUIRED_COLUMNS)].isnull().sum()
    if null_counts.sum() > 0:
        logger.warning("Null values found:\n%s", null_counts[null_counts > 0].to_string())
        df = df.dropna(subset=list(REQUIRED_COLUMNS))
        logger.info("Dropped null rows. Remaining: %d", len(df))
    else:
        logger.info("Null check passed — no nulls in required columns.")
    return df


def validate_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Filter rows to only known categories.

    Args:
        df: Input DataFrame.

    Returns:
        Filtered DataFrame with only valid categories.
    """
    unknown = set(df["category"].unique()) - EXPECTED_CATEGORIES
    if unknown:
        logger.warning("Unknown categories found (will be dropped): %s", unknown)
        df = df[df["category"].isin(EXPECTED_CATEGORIES)]
        logger.info("After category filter: %d rows", len(df))
    else:
        logger.info("Category validation passed — all categories are known.")
    return df


def log_baseline_statistics(df: pd.DataFrame, output_dir: str) -> None:
    """Compute and save baseline statistics for drift detection.

    Args:
        df: Validated DataFrame.
        output_dir: Directory to write baseline stats JSON.
    """
    stats = {
        "total_rows": int(len(df)),
        "category_distribution": df["category"].value_counts().to_dict(),
        "description_avg_length": float(df["description"].str.len().mean()),
    }
    os.makedirs(output_dir, exist_ok=True)
    stats_path = os.path.join(output_dir, "baseline_stats.json")
    with open(stats_path, "w") as fh:
        json.dump(stats, fh, indent=2)
    logger.info("Baseline statistics saved → %s", stats_path)


def ingest(raw_path: str, output_path: str) -> None:
    """Full ingestion pipeline: load → validate → save.

    Args:
        raw_path: Path to the raw CSV file.
        output_path: Path to write the validated CSV.
    """
    if not os.path.exists(raw_path):
        logger.error("Raw data file not found: %s", raw_path)
        sys.exit(1)

    logger.info("Loading raw data from %s ...", raw_path)
    df = pd.read_csv(raw_path)
    logger.info("Loaded %d rows, %d columns.", len(df), len(df.columns))

    validate_schema(df)
    df = validate_nulls(df)
    df = validate_categories(df)

    df = df.drop_duplicates(subset=["description", "category"])
    logger.info("After deduplication: %d rows.", len(df))

    if len(df) == 0:
        logger.error("No valid rows after ingestion validation.")
        sys.exit(1)

    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("Validated dataset written → %s", output_path)

    log_baseline_statistics(df, output_dir)


if __name__ == "__main__":
    params = load_params()
    ingest(
        raw_path=params["data"]["raw_path"],
        output_path=params["data"]["ingested_path"],
    )
