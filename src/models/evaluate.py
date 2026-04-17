"""DVC Stage 4 — Model evaluation on the held-out test set.

Loads the best model checkpoint and test split, computes accuracy, macro F1,
per-class F1, and confusion matrix. Writes results to metrics/eval_metrics.json
for DVC tracking and MLflow logging.
"""

import json
import logging
import os
import pickle
import sys

import mlflow
import numpy as np
import torch
import yaml
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from src.models.model import BiLSTMClassifier  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_params(path: str = "params.yaml") -> dict:
    """Load pipeline parameters from params.yaml."""
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def evaluate(processed_dir: str, params: dict) -> dict:
    """Run evaluation on the test split and return a metrics dictionary.

    Args:
        processed_dir: Directory containing test arrays and artefacts.
        params: Pipeline parameters from params.yaml.

    Returns:
        Dictionary of evaluation metrics.
    """
    X_test = np.load(os.path.join(processed_dir, "X_test.npy"))
    y_test = np.load(os.path.join(processed_dir, "y_test.npy"))

    with open(os.path.join(processed_dir, "vocab.pkl"), "rb") as fh:
        vocab = pickle.load(fh)
    with open(os.path.join(processed_dir, "label_encoder.pkl"), "rb") as fh:
        label_encoder = pickle.load(fh)

    tp = params["train"]
    num_classes = len(label_encoder.classes_)
    vocab_size = len(vocab)

    model = BiLSTMClassifier(
        vocab_size=vocab_size,
        embed_dim=tp["embed_dim"],
        hidden_dim=tp["hidden_dim"],
        num_classes=num_classes,
        num_layers=tp["num_layers"],
        dropout=tp["dropout"],
    )

    model_path = os.path.join("models", "best_model.pt")
    if not os.path.exists(model_path):
        logger.error("Trained model not found at %s. Run training first.", model_path)
        sys.exit(1)

    model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
    model.eval()

    X_tensor = torch.tensor(X_test, dtype=torch.long)
    with torch.no_grad():
        logits = model(X_tensor)
        probs = torch.softmax(logits, dim=1).numpy()
        y_pred = np.argmax(probs, axis=1)

    acc = accuracy_score(y_test, y_pred)
    f1_macro = f1_score(y_test, y_pred, average="macro", zero_division=0)
    f1_weighted = f1_score(y_test, y_pred, average="weighted", zero_division=0)

    report = classification_report(
        y_test, y_pred, target_names=label_encoder.classes_, output_dict=True, zero_division=0
    )
    cm = confusion_matrix(y_test, y_pred).tolist()

    metrics = {
        "test_accuracy": float(acc),
        "test_f1_macro": float(f1_macro),
        "test_f1_weighted": float(f1_weighted),
        "per_class_f1": {cls: float(report[cls]["f1-score"]) for cls in label_encoder.classes_},
        "confusion_matrix": cm,
    }

    logger.info("Test accuracy: %.4f", acc)
    logger.info("Test macro F1: %.4f", f1_macro)
    logger.info("Classification report:\n%s",
                classification_report(y_test, y_pred, target_names=label_encoder.classes_,
                                      zero_division=0))

    # Log to MLflow (attaches to the last active run or creates a new child run)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "mlruns"))
    mlflow.set_experiment("SpendSense")
    with mlflow.start_run(run_name="evaluation"):
        mlflow.log_metrics({
            "test_accuracy": acc,
            "test_f1_macro": f1_macro,
            "test_f1_weighted": f1_weighted,
        })
        for cls in label_encoder.classes_:
            mlflow.log_metric(f"f1_{cls.replace(' & ', '_').replace(' ', '_').lower()}",
                              report[cls]["f1-score"])

    return metrics


def main() -> None:
    """Main evaluation entry point."""
    params = load_params()
    metrics = evaluate(
        processed_dir=params["data"]["processed_dir"],
        params=params,
    )

    os.makedirs("metrics", exist_ok=True)
    out_path = os.path.join("metrics", "eval_metrics.json")
    with open(out_path, "w") as fh:
        json.dump(metrics, fh, indent=2)
    logger.info("Evaluation metrics written → %s", out_path)

    # Fail the DVC stage if test F1 is below acceptance threshold
    threshold = 0.70
    if metrics["test_f1_macro"] < threshold:
        logger.error(
            "Test macro F1 %.4f is below acceptance threshold %.2f. "
            "Improve the model before deploying.",
            metrics["test_f1_macro"], threshold,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
