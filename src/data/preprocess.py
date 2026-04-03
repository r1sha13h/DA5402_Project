"""DVC Stage 2 — Text preprocessing, vocabulary building, and train/val/test splitting.

Reads validated data, builds a word-level vocabulary, tokenises descriptions,
encodes labels, creates fixed-length padded sequences, and saves split arrays
plus the vocabulary and label encoder for use at inference time.
"""

import json
import logging
import os
import pickle
import re
import sys
from collections import Counter

import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_params(path: str = "params.yaml") -> dict:
    """Load pipeline parameters from params.yaml."""
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def tokenize(text: str) -> list:
    """Lowercase and split text into word tokens, stripping punctuation.

    Args:
        text: Raw transaction description string.

    Returns:
        List of lowercase word tokens.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text.split()


def build_vocab(texts: list, max_vocab_size: int, min_freq: int) -> dict:
    """Build word → index vocabulary from a list of tokenised texts.

    Index 0 is reserved for padding; index 1 for unknown words.

    Args:
        texts: List of raw description strings.
        max_vocab_size: Maximum vocabulary size (excluding PAD and UNK).
        min_freq: Minimum word frequency to be included in vocabulary.

    Returns:
        Dictionary mapping word strings to integer indices.
    """
    counter: Counter = Counter()
    for text in texts:
        counter.update(tokenize(text))

    # Sort by frequency descending, take top max_vocab_size
    most_common = [w for w, c in counter.most_common() if c >= min_freq]
    most_common = most_common[:max_vocab_size]

    vocab = {"<PAD>": 0, "<UNK>": 1}
    for idx, word in enumerate(most_common, start=2):
        vocab[word] = idx

    logger.info("Vocabulary size: %d (including PAD + UNK)", len(vocab))
    return vocab


def encode_texts(texts: list, vocab: dict, max_seq_len: int) -> np.ndarray:
    """Convert list of description strings to padded integer sequences.

    Args:
        texts: List of raw description strings.
        vocab: Word → index mapping.
        max_seq_len: Fixed sequence length (truncate or pad).

    Returns:
        Array of shape (n_samples, max_seq_len).
    """
    unk_idx = vocab["<UNK>"]
    pad_idx = vocab["<PAD>"]
    encoded = []
    for text in texts:
        tokens = tokenize(text)
        indices = [vocab.get(t, unk_idx) for t in tokens]
        if len(indices) < max_seq_len:
            indices = indices + [pad_idx] * (max_seq_len - len(indices))
        else:
            indices = indices[:max_seq_len]
        encoded.append(indices)
    return np.array(encoded, dtype=np.int32)


def save_baseline(X: np.ndarray, y: np.ndarray, output_dir: str) -> None:
    """Persist baseline feature statistics for downstream drift detection.

    Args:
        X: Encoded training sequences.
        y: Encoded training labels.
        output_dir: Directory to save the JSON file.
    """
    stats = {
        "seq_nonzero_mean": float(np.mean(np.count_nonzero(X, axis=1))),
        "seq_nonzero_std": float(np.std(np.count_nonzero(X, axis=1))),
        "label_distribution": {str(k): int(v) for k, v in zip(*np.unique(y, return_counts=True))},
    }
    path = os.path.join(output_dir, "feature_baseline.json")
    with open(path, "w") as fh:
        json.dump(stats, fh, indent=2)
    logger.info("Feature baseline saved → %s", path)


def preprocess(ingested_path: str, output_dir: str, params: dict) -> None:
    """Full preprocessing pipeline.

    Args:
        ingested_path: Path to validated ingested CSV.
        output_dir: Directory to write processed splits and artefacts.
        params: Preprocessing hyperparameters from params.yaml.
    """
    if not os.path.exists(ingested_path):
        logger.error("Ingested data not found: %s", ingested_path)
        sys.exit(1)

    df = pd.read_csv(ingested_path)
    logger.info("Loaded %d rows for preprocessing.", len(df))

    # Label encoding
    le = LabelEncoder()
    y = le.fit_transform(df["category"].values)
    logger.info("Classes: %s", list(le.classes_))

    # Train / val / test stratified split
    seed = params["preprocess"]["seed"]
    test_size = params["preprocess"]["test_size"]
    val_size = params["preprocess"]["val_size"]

    X_texts = df["description"].values

    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X_texts, y, test_size=test_size, stratify=y, random_state=seed
    )
    relative_val = val_size / (1.0 - test_size)
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=relative_val, stratify=y_trainval, random_state=seed
    )
    logger.info("Split sizes — train: %d, val: %d, test: %d", len(X_train), len(X_val), len(X_test))

    # Build vocabulary on training data only (no leakage)
    vocab = build_vocab(
        X_train.tolist(),
        max_vocab_size=params["preprocess"]["max_vocab_size"],
        min_freq=params["preprocess"]["min_freq"],
    )

    max_seq_len = params["preprocess"]["max_seq_len"]
    X_train_enc = encode_texts(X_train.tolist(), vocab, max_seq_len)
    X_val_enc = encode_texts(X_val.tolist(), vocab, max_seq_len)
    X_test_enc = encode_texts(X_test.tolist(), vocab, max_seq_len)

    os.makedirs(output_dir, exist_ok=True)

    # Save arrays
    np.save(os.path.join(output_dir, "X_train.npy"), X_train_enc)
    np.save(os.path.join(output_dir, "X_val.npy"), X_val_enc)
    np.save(os.path.join(output_dir, "X_test.npy"), X_test_enc)
    np.save(os.path.join(output_dir, "y_train.npy"), y_train)
    np.save(os.path.join(output_dir, "y_val.npy"), y_val)
    np.save(os.path.join(output_dir, "y_test.npy"), y_test)

    # Save artefacts needed at inference
    with open(os.path.join(output_dir, "vocab.pkl"), "wb") as fh:
        pickle.dump(vocab, fh)
    with open(os.path.join(output_dir, "label_encoder.pkl"), "wb") as fh:
        pickle.dump(le, fh)

    save_baseline(X_train_enc, y_train, output_dir)
    logger.info("Preprocessing complete. Artefacts written to %s", output_dir)


if __name__ == "__main__":
    params = load_params()
    preprocess(
        ingested_path=params["data"]["ingested_path"],
        output_dir=params["data"]["processed_dir"],
        params=params,
    )
