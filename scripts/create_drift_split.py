"""Create the 90-10 drift split from data/raw/transactions.csv.

Outputs
-------
data/raw/transactions_90.csv   — stratified 90% used as base training data
data/drift/transactions_drift.csv — skewed 10% used to mock real-world drift

The 10% split is built by oversampling the top-3 categories from the
remaining rows, so the distribution deviates >10 pp from the 90% baseline.
All rows are genuine — no synthetic data is introduced.

Usage
-----
    python scripts/create_drift_split.py          # uses default paths
    python scripts/create_drift_split.py --verify # verify drift flags fire
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

RAW_PATH = "data/raw/transactions.csv"
OUT_90 = "data/raw/transactions_90.csv"
OUT_DRIFT = "data/drift/transactions_drift.csv"
SEED = 42
DRIFT_THRESHOLD = 0.10  # must match Airflow check_drift threshold


def create_split(raw_path: str = RAW_PATH, seed: int = SEED) -> dict:
    np.random.seed(seed)

    df = pd.read_csv(raw_path)
    df = df.dropna(subset=["description", "category"])
    df = df[df["description"].str.strip() != ""]
    df = df.reset_index(drop=True)

    print(f"Loaded {len(df):,} rows from {raw_path}")
    print(f"Full distribution:\n{df['category'].value_counts(normalize=True).round(3).to_string()}\n")

    # ── 90%: stratified sample (proportional to full distribution) ────────────
    df_90 = (
        df.groupby("category", group_keys=False)
        .apply(lambda x: x.sample(frac=0.90, random_state=seed))
        .reset_index(drop=True)
    )

    # ── Remaining rows (natural 10%) ──────────────────────────────────────────
    remaining_idx = df.index.difference(df_90.index)
    df_remaining = df.loc[remaining_idx].reset_index(drop=True)

    # ── Build drifted 10%: oversample top-3 categories from remaining ─────────
    top_cats = df["category"].value_counts().index[:3].tolist()
    top_rows = df_remaining[df_remaining["category"].isin(top_cats)]
    other_rows = df_remaining[~df_remaining["category"].isin(top_cats)]

    n_total = len(df_remaining)
    n_top = int(n_total * 0.75)
    n_other = n_total - n_top

    df_top = top_rows.sample(
        n=min(n_top, len(top_rows)),
        random_state=seed,
        replace=(len(top_rows) < n_top),
    )
    df_other = other_rows.sample(
        n=min(n_other, len(other_rows)),
        random_state=seed,
        replace=(len(other_rows) < n_other),
    )

    df_drift = (
        pd.concat([df_top, df_other], ignore_index=True)
        .sample(frac=1, random_state=seed)
        .reset_index(drop=True)
    )

    # ── Verify drift is large enough to fire Airflow check ────────────────────
    dist_90 = df_90["category"].value_counts(normalize=True)
    dist_drift = df_drift["category"].value_counts(normalize=True)

    drift_flags = {}
    for cat in set(list(dist_90.index) + list(dist_drift.index)):
        base = float(dist_90.get(cat, 0.0))
        curr = float(dist_drift.get(cat, 0.0))
        shift = abs(curr - base)
        if shift > DRIFT_THRESHOLD:
            drift_flags[cat] = {
                "baseline": round(base, 4),
                "current": round(curr, 4),
                "shift": round(shift, 4),
            }

    print(f"90%% split : {len(df_90):,} rows")
    print(f"Drift split: {len(df_drift):,} rows")
    print(f"Drift flags detected (>{DRIFT_THRESHOLD*100:.0f}pp shift):")
    if drift_flags:
        for cat, v in drift_flags.items():
            print(f"  {cat}: baseline={v['baseline']:.3f} → current={v['current']:.3f}  Δ={v['shift']:.3f}")
    else:
        print("  NONE — no categories exceeded the threshold!")

    # ── Save ──────────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUT_90), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_DRIFT), exist_ok=True)

    df_90.to_csv(OUT_90, index=False)
    df_drift.to_csv(OUT_DRIFT, index=False)

    print(f"\nSaved: {OUT_90}")
    print(f"Saved: {OUT_DRIFT}")

    return {"drift_flags": drift_flags, "n_90": len(df_90), "n_drift": len(df_drift)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="Exit 1 if no drift flags fired")
    parser.add_argument("--raw", default=RAW_PATH, help="Path to raw transactions CSV")
    args = parser.parse_args()

    result = create_split(raw_path=args.raw)

    if args.verify and not result["drift_flags"]:
        print("ERROR: No drift flags detected — split needs adjustment.", file=sys.stderr)
        sys.exit(1)

    print("\nDrift split created successfully.")


if __name__ == "__main__":
    main()
