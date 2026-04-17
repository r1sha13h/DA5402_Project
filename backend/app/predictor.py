"""Model loading and inference logic for the SpendSense backend."""

import logging
import os
import pickle
import re
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)

# Paths to artefacts (can be overridden by environment variables)
_MODEL_PATH = os.environ.get("MODEL_PATH", "models/best_model.pt")
_VOCAB_PATH = os.environ.get("VOCAB_PATH", "data/processed/vocab.pkl")
_LABEL_ENCODER_PATH = os.environ.get(
    "LABEL_ENCODER_PATH", "data/processed/label_encoder.pkl"
)
_PARAMS_PATH = os.environ.get("PARAMS_PATH", "params.yaml")
_MAX_SEQ_LEN = int(os.environ.get("MAX_SEQ_LEN", "50"))


class SpendSensePredictor:
    """Loads model artefacts once and serves predictions.

    Attributes:
        model: BiLSTMClassifier in eval mode (or None if not yet loaded).
        vocab: Word → index dictionary.
        label_encoder: Scikit-learn LabelEncoder with category names.
        max_seq_len: Fixed sequence length used during preprocessing.
    """

    def __init__(self) -> None:
        self.model = None
        self.vocab: Optional[dict] = None
        self.label_encoder = None
        self.max_seq_len: int = _MAX_SEQ_LEN

    def load(self) -> bool:
        """Load all artefacts from disk.

        Returns:
            True if loading succeeded, False otherwise.
        """
        try:
            import yaml
            sys.path.insert(0, os.path.abspath("."))
            from src.models.model import BiLSTMClassifier  # noqa: PLC0415

            with open(_PARAMS_PATH, "r") as fh:
                params = yaml.safe_load(fh)
            tp = params["train"]

            with open(_VOCAB_PATH, "rb") as fh:
                self.vocab = pickle.load(fh)
            with open(_LABEL_ENCODER_PATH, "rb") as fh:
                self.label_encoder = pickle.load(fh)

            self.max_seq_len = params["preprocess"]["max_seq_len"]
            num_classes = len(self.label_encoder.classes_)
            vocab_size = len(self.vocab)

            self.model = BiLSTMClassifier(
                vocab_size=vocab_size,
                embed_dim=tp["embed_dim"],
                hidden_dim=tp["hidden_dim"],
                num_classes=num_classes,
                num_layers=tp["num_layers"],
                dropout=tp["dropout"],
            )
            self.model.load_state_dict(
                torch.load(_MODEL_PATH, map_location="cpu", weights_only=True)
            )
            self.model.eval()
            logger.info("Model loaded successfully from %s", _MODEL_PATH)
            return True
        except Exception as exc:
            logger.exception("Failed to load model: %s", exc)
            return False

    @property
    def is_ready(self) -> bool:
        """Return True if the model is loaded and ready for inference."""
        return self.model is not None

    def _tokenize(self, text: str) -> List[int]:
        """Tokenise and encode a single description.

        Args:
            text: Raw transaction description string.

        Returns:
            Padded list of token indices of length max_seq_len.
        """
        text = text.lower()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        tokens = text.split()
        unk = self.vocab.get("<UNK>", 1)
        pad = self.vocab.get("<PAD>", 0)
        indices = [self.vocab.get(t, unk) for t in tokens]
        if len(indices) < self.max_seq_len:
            indices += [pad] * (self.max_seq_len - len(indices))
        else:
            indices = indices[: self.max_seq_len]
        return indices

    def predict(self, description: str) -> Tuple[str, float, Dict[str, float]]:
        """Predict the expense category for a single description.

        Args:
            description: Raw transaction description string.

        Returns:
            Tuple of (predicted_category, confidence, all_scores).

        Raises:
            RuntimeError: If the model is not loaded.
        """
        if not self.is_ready:
            raise RuntimeError("Model is not loaded.")

        indices = self._tokenize(description)
        x = torch.tensor([indices], dtype=torch.long)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1).squeeze().numpy()

        pred_idx = int(np.argmax(probs))
        predicted_category = self.label_encoder.classes_[pred_idx]
        confidence = float(probs[pred_idx])
        all_scores = {
            cls: float(probs[i])
            for i, cls in enumerate(self.label_encoder.classes_)
        }
        return predicted_category, confidence, all_scores

    def predict_batch(
        self, descriptions: List[str]
    ) -> List[Tuple[str, float, Dict[str, float]]]:
        """Predict categories for a batch of descriptions.

        Args:
            descriptions: List of raw transaction description strings.

        Returns:
            List of (predicted_category, confidence, all_scores) tuples.

        Raises:
            RuntimeError: If the model is not loaded.
        """
        if not self.is_ready:
            raise RuntimeError("Model is not loaded.")

        encoded = [self._tokenize(d) for d in descriptions]
        x = torch.tensor(encoded, dtype=torch.long)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1).numpy()

        results = []
        for i, row in enumerate(probs):
            pred_idx = int(np.argmax(row))
            predicted_category = self.label_encoder.classes_[pred_idx]
            confidence = float(row[pred_idx])
            all_scores = {
                cls: float(row[j])
                for j, cls in enumerate(self.label_encoder.classes_)
            }
            results.append((predicted_category, confidence, all_scores))
        return results


# Module-level singleton — shared across all requests
predictor = SpendSensePredictor()
