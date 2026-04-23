"""Model loading and inference logic for the SpendSense backend."""

import logging
import os
import pickle
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import mlflow
import numpy as np
import torch

logger = logging.getLogger(__name__)

# Paths to artefacts (can be overridden by environment variables)
_MODEL_PATH = os.environ.get("MODEL_PATH", "models/latest_model.pt")
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
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.current_run_id: Optional[str] = None

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
            ).to(self.device)
            self.model.load_state_dict(
                torch.load(_MODEL_PATH, map_location=self.device, weights_only=True)
            )
            self.model.eval()
            if self.device.type == "cpu":
                self.model = torch.quantization.quantize_dynamic(
                    self.model, {torch.nn.LSTM, torch.nn.Linear}, dtype=torch.qint8
                )
                logger.info("Dynamic INT8 quantization applied (CPU mode).")
            logger.info("Model loaded on %s from %s", self.device, _MODEL_PATH)
            return True
        except Exception as exc:
            logger.exception("Failed to load model: %s", exc)
            return False

    @property
    def is_ready(self) -> bool:
        """Return True if the model is loaded and ready for inference."""
        return self.model is not None

    def load_from_mlflow(self, run_id: str) -> bool:
        """Load model artefacts from an MLflow run.

        Args:
            run_id: The MLflow run ID to load artefacts from.

        Returns:
            True if loading succeeded, False otherwise.
        """
        try:
            import yaml
            sys.path.insert(0, os.path.abspath("."))
            from src.models.model import BiLSTMClassifier  # noqa: PLC0415

            tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "mlruns")
            mlflow.set_tracking_uri(tracking_uri)

            with tempfile.TemporaryDirectory() as tmpdir:
                # Download artefacts from the MLflow run
                art_path = mlflow.artifacts.download_artifacts(
                    run_id=run_id, dst_path=tmpdir
                )

                params_file = os.path.join(art_path, "params.yaml")
                vocab_file = os.path.join(art_path, "vocab.pkl")
                le_file = os.path.join(art_path, "label_encoder.pkl")
                model_dir = os.path.join(art_path, "model")

                with open(params_file, "r") as fh:
                    params = yaml.safe_load(fh)
                tp = params["train"]

                with open(vocab_file, "rb") as fh:
                    self.vocab = pickle.load(fh)
                with open(le_file, "rb") as fh:
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
                ).to(self.device)

                # MLflow stores pytorch model; load state_dict from data/model.pth
                model_pth = os.path.join(model_dir, "data", "model.pth")
                self.model.load_state_dict(
                    torch.load(model_pth, map_location=self.device, weights_only=True)
                )
                self.model.eval()
                if self.device.type == "cpu":
                    self.model = torch.quantization.quantize_dynamic(
                        self.model, {torch.nn.LSTM, torch.nn.Linear}, dtype=torch.qint8
                    )
                    logger.info("Dynamic INT8 quantization applied (CPU mode).")

            self.current_run_id = run_id
            logger.info("Model loaded from MLflow run_id=%s on %s", run_id, self.device)
            return True
        except Exception as exc:
            logger.exception("Failed to load model from MLflow run %s: %s", run_id, exc)
            return False

    @staticmethod
    def list_mlflow_runs(max_results: int = 20) -> List[Dict[str, Any]]:
        """List recent MLflow runs for the SpendSense experiment.

        Args:
            max_results: Maximum number of runs to return.

        Returns:
            List of dicts with run_id, metrics, start_time, status.
        """
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "mlruns")
        mlflow.set_tracking_uri(tracking_uri)

        try:
            experiment = mlflow.get_experiment_by_name("SpendSense")
            if experiment is None:
                return []

            runs = mlflow.search_runs(
                experiment_ids=[experiment.experiment_id],
                order_by=["start_time DESC"],
                max_results=max_results,
            )

            result = []
            for _, row in runs.iterrows():
                result.append({
                    "run_id": row["run_id"],
                    "status": row.get("status", ""),
                    "start_time": str(row.get("start_time", "")),
                    "best_val_f1": row.get("metrics.best_val_f1_macro", None),
                    "val_acc": row.get("metrics.val_acc", None),
                    "max_epochs": row.get("params.max_epochs", None),
                    "batch_size": row.get("params.batch_size", None),
                })
            return result
        except Exception as exc:
            logger.exception("Failed to list MLflow runs: %s", exc)
            return []

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
        x = torch.tensor([indices], dtype=torch.long).to(self.device)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1).squeeze().cpu().numpy()

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
        x = torch.tensor(encoded, dtype=torch.long).to(self.device)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1).cpu().numpy()

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
