"""Unit tests for src/data/preprocess.py."""

import os
import pickle
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.preprocess import build_vocab, encode_texts, tokenize


# ── Tests: tokenize ───────────────────────────────────────────────────────────

def test_tokenize_lowercases():
    """Tokenizer converts text to lowercase."""
    assert tokenize("Zomato Payment") == ["zomato", "payment"]


def test_tokenize_strips_punctuation():
    """Tokenizer removes non-alphanumeric characters."""
    assert "₹" not in tokenize("Zomato ₹350 payment")
    assert "payment" in tokenize("Zomato ₹350 payment")


def test_tokenize_empty_string():
    """Empty string returns empty list."""
    assert tokenize("") == []


def test_tokenize_only_punctuation():
    """String of only punctuation returns empty list."""
    result = tokenize("!!!@@@###")
    assert all(t.strip() == "" or t == "" for t in result) or result == []


# ── Tests: build_vocab ────────────────────────────────────────────────────────

def test_build_vocab_contains_pad_unk():
    """Vocabulary always contains <PAD> at index 0 and <UNK> at index 1."""
    vocab = build_vocab(["hello world", "foo bar"], max_vocab_size=100, min_freq=1)
    assert vocab["<PAD>"] == 0
    assert vocab["<UNK>"] == 1


def test_build_vocab_respects_min_freq():
    """Words below min_freq threshold are excluded."""
    texts = ["apple apple apple", "banana", "cherry"]
    vocab = build_vocab(texts, max_vocab_size=100, min_freq=2)
    assert "apple" in vocab
    assert "banana" not in vocab
    assert "cherry" not in vocab


def test_build_vocab_respects_max_size():
    """Vocabulary size does not exceed max_vocab_size + 2 (PAD + UNK)."""
    texts = [f"word{i}" for i in range(200)]
    vocab = build_vocab(texts, max_vocab_size=50, min_freq=1)
    assert len(vocab) <= 52  # 50 words + PAD + UNK


# ── Tests: encode_texts ───────────────────────────────────────────────────────

def test_encode_texts_output_shape():
    """Encoded array has shape (n_texts, max_seq_len)."""
    vocab = {"<PAD>": 0, "<UNK>": 1, "zomato": 2, "payment": 3}
    texts = ["zomato payment", "unknown word"]
    encoded = encode_texts(texts, vocab, max_seq_len=10)
    assert encoded.shape == (2, 10)


def test_encode_texts_pads_short_sequences():
    """Short sequences are right-padded with the PAD index."""
    vocab = {"<PAD>": 0, "<UNK>": 1, "hello": 2}
    encoded = encode_texts(["hello"], vocab, max_seq_len=5)
    assert encoded[0, 0] == 2
    assert list(encoded[0, 1:]) == [0, 0, 0, 0]


def test_encode_texts_truncates_long_sequences():
    """Long sequences are truncated to max_seq_len."""
    vocab = {f"w{i}": i for i in range(100)}
    vocab["<PAD>"] = 100
    vocab["<UNK>"] = 101
    texts = ["w1 w2 w3 w4 w5 w6 w7 w8 w9 w10"]
    encoded = encode_texts(texts, vocab, max_seq_len=5)
    assert encoded.shape == (1, 5)


def test_encode_texts_unknown_words_use_unk():
    """Unknown words are mapped to the <UNK> index."""
    vocab = {"<PAD>": 0, "<UNK>": 1, "known": 2}
    encoded = encode_texts(["known unknown"], vocab, max_seq_len=5)
    assert encoded[0, 0] == 2
    assert encoded[0, 1] == 1


# ── Integration: preprocess pipeline ─────────────────────────────────────────

def test_preprocess_creates_all_artefacts():
    """End-to-end preprocess creates all expected output files."""
    from src.data.preprocess import preprocess  # noqa: PLC0415

    categories = [
        "Food & Dining", "Transport", "Utilities", "Entertainment", "Shopping",
        "Healthcare", "Education", "Travel", "Housing", "Finance",
    ]
    records = []
    for i, cat in enumerate(categories * 10):
        records.append({"description": f"transaction {i} for {cat}", "amount": 100.0,
                        "category": cat})
    df = pd.DataFrame(records)

    with tempfile.TemporaryDirectory() as tmpdir:
        ingested_path = os.path.join(tmpdir, "transactions.csv")
        processed_dir = os.path.join(tmpdir, "processed")
        df.to_csv(ingested_path, index=False)

        params = {
            "preprocess": {
                "max_vocab_size": 500, "max_seq_len": 10, "test_size": 0.15,
                "val_size": 0.15, "min_freq": 1, "seed": 42,
            },
            "data": {"ingested_path": ingested_path, "processed_dir": processed_dir},
        }
        preprocess(ingested_path=ingested_path, output_dir=processed_dir, params=params)

        expected = [
            "X_train.npy", "X_val.npy", "X_test.npy",
            "y_train.npy", "y_val.npy", "y_test.npy",
            "vocab.pkl", "label_encoder.pkl", "feature_baseline.json",
        ]
        for fname in expected:
            assert os.path.exists(os.path.join(processed_dir, fname)), f"Missing: {fname}"

        X_train = np.load(os.path.join(processed_dir, "X_train.npy"))
        assert X_train.shape[1] == 10
