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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
from tqdm import tqdm

try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
    _PUSHGATEWAY_AVAILABLE = True
except ImportError:
    _PUSHGATEWAY_AVAILABLE = False

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

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Using device: %s", device)

    model = BiLSTMClassifier(
        vocab_size=vocab_size,
        embed_dim=tp["embed_dim"],
        hidden_dim=tp["hidden_dim"],
        num_classes=num_classes,
        num_layers=tp["num_layers"],
        dropout=tp["dropout"],
    ).to(device)

    model_path = os.path.join("models", "latest_model.pt")
    if not os.path.exists(model_path):
        logger.error("Trained model not found at %s. Run training first.", model_path)
        sys.exit(1)

    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.eval()

    X_tensor = torch.tensor(X_test, dtype=torch.long)
    batch_size = params["train"].get("batch_size", 64)
    all_probs = []
    with torch.no_grad():
        for i in tqdm(range(0, len(X_tensor), batch_size), desc="Evaluating", unit="batch"):
            batch = X_tensor[i:i + batch_size].to(device)
            logits = model(batch)
            all_probs.append(torch.softmax(logits, dim=1).cpu().numpy())
    probs = np.concatenate(all_probs, axis=0)
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
        mlflow.log_dict(metrics["per_class_f1"], "per_class_f1.json")
        mlflow.log_dict(
            {"classes": label_encoder.classes_.tolist(), "matrix": cm},
            "confusion_matrix.json",
        )

        # Log confusion matrix as a heatmap PNG
        try:
            import tempfile
            cm_array = np.array(cm)
            fig, ax = plt.subplots(figsize=(12, 10))
            im = ax.imshow(cm_array, interpolation="nearest", cmap="Blues")
            plt.colorbar(im, ax=ax)
            ax.set_xticks(range(len(label_encoder.classes_)))
            ax.set_yticks(range(len(label_encoder.classes_)))
            ax.set_xticklabels(label_encoder.classes_, rotation=45, ha="right", fontsize=9)
            ax.set_yticklabels(label_encoder.classes_, fontsize=9)
            ax.set_xlabel("Predicted Label", fontsize=11)
            ax.set_ylabel("True Label", fontsize=11)
            ax.set_title("Confusion Matrix", fontsize=13)
            thresh = cm_array.max() / 2.0
            for i in range(cm_array.shape[0]):
                for j in range(cm_array.shape[1]):
                    ax.text(j, i, str(cm_array[i, j]),
                            ha="center", va="center", fontsize=7,
                            color="white" if cm_array[i, j] > thresh else "black")
            plt.tight_layout()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                fig.savefig(tmp.name, dpi=120, bbox_inches="tight")
                mlflow.log_artifact(tmp.name, artifact_path="confusion_matrix")
            plt.close(fig)
            logger.info("Confusion matrix heatmap logged to MLflow.")
        except Exception as exc:
            logger.warning("Could not log confusion matrix heatmap: %s", exc)

    # Push evaluation metrics to Prometheus Pushgateway
    pushgateway_url = os.environ.get("PUSHGATEWAY_URL", "http://localhost:9091")
    if _PUSHGATEWAY_AVAILABLE:
        try:
            registry = CollectorRegistry()
            Gauge("spendsense_test_f1_macro", "Test macro F1 from latest DVC run",
                  registry=registry).set(f1_macro)
            Gauge("spendsense_test_accuracy", "Test accuracy from latest DVC run",
                  registry=registry).set(acc)
            push_to_gateway(pushgateway_url, job="spendsense_evaluate", registry=registry)
            logger.info("Evaluation metrics pushed to Pushgateway at %s", pushgateway_url)
        except Exception as exc:
            logger.warning("Could not push metrics to Pushgateway: %s", exc)

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
