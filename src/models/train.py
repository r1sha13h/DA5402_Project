"""DVC Stage 3 — Model training with MLflow experiment tracking.

Loads preprocessed splits, trains a BiLSTMClassifier, logs all metrics/
parameters/artefacts to MLflow, registers the best model in the MLflow
Model Registry, and writes a summary metrics JSON for DVC.
"""

import json
import logging
import os
import pickle
import sys
import time

import mlflow
import mlflow.pytorch
import numpy as np
import torch
import torch.nn as nn
import yaml
from sklearn.metrics import accuracy_score, f1_score
from torch.utils.data import DataLoader, TensorDataset
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
    """Load training parameters from params.yaml."""
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def load_processed_data(processed_dir: str):
    """Load all preprocessed arrays and artefacts from disk.

    Args:
        processed_dir: Directory containing .npy arrays, vocab.pkl, label_encoder.pkl.

    Returns:
        Tuple of (X_train, X_val, y_train, y_val, vocab, label_encoder).
    """
    X_train = np.load(os.path.join(processed_dir, "X_train.npy"))
    X_val = np.load(os.path.join(processed_dir, "X_val.npy"))
    y_train = np.load(os.path.join(processed_dir, "y_train.npy"))
    y_val = np.load(os.path.join(processed_dir, "y_val.npy"))

    with open(os.path.join(processed_dir, "vocab.pkl"), "rb") as fh:
        vocab = pickle.load(fh)
    with open(os.path.join(processed_dir, "label_encoder.pkl"), "rb") as fh:
        label_encoder = pickle.load(fh)

    return X_train, X_val, y_train, y_val, vocab, label_encoder


def run_epoch(model, loader, optimizer, criterion, device, training: bool):
    """Execute one training or validation epoch.

    Args:
        model: BiLSTMClassifier instance.
        loader: DataLoader for the split.
        optimizer: Torch optimiser (used only when training=True).
        criterion: Loss function.
        device: torch.device.
        training: If True, runs backward pass and updates weights.

    Returns:
        Tuple of (avg_loss, accuracy, macro_f1).
    """
    model.train(training)
    total_loss = 0.0
    all_preds: list = []
    all_labels: list = []

    phase = "Train" if training else "Val"
    ctx = torch.enable_grad() if training else torch.no_grad()
    with ctx:
        for X_batch, y_batch in tqdm(loader, desc=f"  {phase}", leave=False):
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            if training:
                optimizer.zero_grad()
            logits = model(X_batch)
            loss = criterion(logits, y_batch)
            if training:
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * len(y_batch)
            preds = logits.argmax(dim=1).cpu().numpy()
            all_preds.extend(preds)
            all_labels.extend(y_batch.cpu().numpy())

    avg_loss = total_loss / len(loader.dataset)
    acc = accuracy_score(all_labels, all_preds)
    f1 = f1_score(all_labels, all_preds, average="macro", zero_division=0)
    return avg_loss, acc, f1


def main() -> None:
    """Main training entry point."""
    params = load_params()
    tp = params["train"]
    dp = params["data"]

    seed = tp["seed"]
    torch.manual_seed(seed)
    np.random.seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Using device: %s", device)

    logger.info("Loading preprocessed data from %s ...", dp["processed_dir"])
    X_train, X_val, y_train, y_val, vocab, label_encoder = load_processed_data(
        dp["processed_dir"]
    )

    train_loader = DataLoader(
        TensorDataset(torch.tensor(X_train, dtype=torch.long),
                      torch.tensor(y_train, dtype=torch.long)),
        batch_size=tp["batch_size"],
        shuffle=True,
    )
    val_loader = DataLoader(
        TensorDataset(torch.tensor(X_val, dtype=torch.long),
                      torch.tensor(y_val, dtype=torch.long)),
        batch_size=tp["batch_size"],
    )

    num_classes = len(label_encoder.classes_)
    vocab_size = len(vocab)

    model = BiLSTMClassifier(
        vocab_size=vocab_size,
        embed_dim=tp["embed_dim"],
        hidden_dim=tp["hidden_dim"],
        num_classes=num_classes,
        num_layers=tp["num_layers"],
        dropout=tp["dropout"],
    ).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=tp["learning_rate"])
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=2)

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "mlruns"))
    mlflow.set_experiment("SpendSense")

    with mlflow.start_run(run_name="bilstm_training") as run:
        mlflow.log_params({
            "embed_dim": tp["embed_dim"],
            "hidden_dim": tp["hidden_dim"],
            "num_layers": tp["num_layers"],
            "dropout": tp["dropout"],
            "batch_size": tp["batch_size"],
            "learning_rate": tp["learning_rate"],
            "max_epochs": tp["epochs"],
            "vocab_size": vocab_size,
            "num_classes": num_classes,
            "seed": seed,
        })

        best_val_f1 = 0.0
        patience_counter = 0
        os.makedirs("models", exist_ok=True)
        best_model_path = os.path.join("models", "latest_model.pt")

        training_start = time.time()
        epoch_bar = tqdm(range(1, tp["epochs"] + 1), desc="Epochs", unit="epoch")
        for epoch in epoch_bar:
            tr_loss, tr_acc, tr_f1 = run_epoch(
                model, train_loader, optimizer, criterion, device, training=True
            )
            val_loss, val_acc, val_f1 = run_epoch(
                model, val_loader, optimizer, criterion, device, training=False
            )
            scheduler.step(val_loss)

            mlflow.log_metrics({
                "train_loss": tr_loss, "train_acc": tr_acc, "train_f1_macro": tr_f1,
                "val_loss": val_loss, "val_acc": val_acc, "val_f1_macro": val_f1,
            }, step=epoch)

            logger.info(
                "Epoch %02d | tr_loss=%.4f tr_acc=%.4f | val_loss=%.4f val_acc=%.4f val_f1=%.4f",
                epoch, tr_loss, tr_acc, val_loss, val_acc, val_f1,
            )

            if val_f1 > best_val_f1:
                best_val_f1 = val_f1
                patience_counter = 0
                torch.save(model.state_dict(), best_model_path)
                logger.info("  ✓ Best model checkpoint saved (val_f1=%.4f)", best_val_f1)
            else:
                patience_counter += 1
                if patience_counter >= tp["early_stopping_patience"]:
                    logger.info("Early stopping triggered at epoch %d.", epoch)
                    break

        # Load best weights, log model and artefacts
        model.load_state_dict(torch.load(best_model_path, map_location=device, weights_only=True))
        mlflow.log_metric("best_val_f1_macro", best_val_f1)

        mlflow.pytorch.log_model(
            model,
            artifact_path="model",
            registered_model_name="SpendSense",
        )
        mlflow.log_artifact(os.path.join(dp["processed_dir"], "vocab.pkl"))
        mlflow.log_artifact(os.path.join(dp["processed_dir"], "label_encoder.pkl"))
        mlflow.log_artifact("params.yaml")

        run_id = run.info.run_id
        logger.info("MLflow run_id: %s", run_id)

        # Automatically transition the newly registered model version to Staging
        try:
            client = mlflow.MlflowClient()
            versions = client.search_model_versions("name='SpendSense'")
            if versions:
                latest = sorted(versions, key=lambda v: int(v.version))[-1]
                client.transition_model_version_stage(
                    name="SpendSense",
                    version=latest.version,
                    stage="Staging",
                )
                logger.info("Model version %s transitioned to Staging.", latest.version)
        except Exception as exc:
            logger.warning("Could not auto-transition model to Staging: %s", exc)

    # Write DVC metrics file
    os.makedirs("metrics", exist_ok=True)
    metrics_path = os.path.join("metrics", "train_metrics.json")
    with open(metrics_path, "w") as fh:
        json.dump({"best_val_f1_macro": best_val_f1, "mlflow_run_id": run_id}, fh, indent=2)
    logger.info("Training complete. Best val F1: %.4f", best_val_f1)

    # Push training metrics to Prometheus Pushgateway
    training_duration = time.time() - training_start
    pushgateway_url = os.environ.get("PUSHGATEWAY_URL", "http://localhost:9091")
    if _PUSHGATEWAY_AVAILABLE:
        try:
            registry = CollectorRegistry()
            Gauge("spendsense_training_val_f1", "Best validation F1 from training run",
                  registry=registry).set(best_val_f1)
            Gauge("spendsense_training_duration_seconds",
                  "Total training wall-clock time in seconds",
                  registry=registry).set(training_duration)
            push_to_gateway(pushgateway_url, job="spendsense_training", registry=registry)
            logger.info("Training metrics pushed to Pushgateway at %s", pushgateway_url)
        except Exception as exc:
            logger.warning("Could not push metrics to Pushgateway: %s", exc)


if __name__ == "__main__":
    main()
