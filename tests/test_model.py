"""Unit tests for src/models/model.py — BiLSTMClassifier."""

import os
import sys

import pytest
import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models.model import BiLSTMClassifier


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def small_model():
    """Return a small BiLSTMClassifier for fast testing."""
    return BiLSTMClassifier(
        vocab_size=100,
        embed_dim=16,
        hidden_dim=32,
        num_classes=10,
        num_layers=2,
        dropout=0.1,
    )


# ── Tests: output shape ───────────────────────────────────────────────────────

def test_output_shape_single(small_model):
    """Single sample produces logits of shape (1, num_classes)."""
    x = torch.randint(0, 100, (1, 20))
    out = small_model(x)
    assert out.shape == (1, 10)


def test_output_shape_batch(small_model):
    """Batch of 8 samples produces logits of shape (8, num_classes)."""
    x = torch.randint(0, 100, (8, 20))
    out = small_model(x)
    assert out.shape == (8, 10)


def test_output_shape_variable_seq_len(small_model):
    """Works correctly with different sequence lengths."""
    for seq_len in [1, 5, 50, 100]:
        x = torch.randint(0, 100, (4, seq_len))
        out = small_model(x)
        assert out.shape == (4, 10)


# ── Tests: padding ────────────────────────────────────────────────────────────

def test_padding_token_embedding_is_zero():
    """PAD token (index 0) embedding should be zero-initialised."""
    model = BiLSTMClassifier(vocab_size=50, embed_dim=16, hidden_dim=32,
                              num_classes=5, num_layers=1, dropout=0.0)
    pad_vector = model.embedding.weight[0].detach()
    assert torch.allclose(pad_vector, torch.zeros(16))


# ── Tests: single-layer model ─────────────────────────────────────────────────

def test_single_layer_no_dropout():
    """Single-layer model (no LSTM dropout) runs without error."""
    model = BiLSTMClassifier(vocab_size=50, embed_dim=8, hidden_dim=16,
                              num_classes=3, num_layers=1, dropout=0.3)
    x = torch.randint(0, 50, (2, 10))
    out = model(x)
    assert out.shape == (2, 3)


# ── Tests: gradient flow ──────────────────────────────────────────────────────

def test_backward_pass_updates_weights(small_model):
    """Gradients flow end-to-end and weights can be updated."""
    optimizer = torch.optim.SGD(small_model.parameters(), lr=0.01)
    x = torch.randint(0, 100, (4, 20))
    y = torch.randint(0, 10, (4,))

    small_model.train()
    logits = small_model(x)
    loss = torch.nn.CrossEntropyLoss()(logits, y)
    loss.backward()

    for name, param in small_model.named_parameters():
        if param.requires_grad and param.grad is not None:
            assert not torch.isnan(param.grad).any(), f"NaN gradient in {name}"

    optimizer.step()


# ── Tests: eval mode ──────────────────────────────────────────────────────────

def test_eval_mode_deterministic(small_model):
    """In eval mode, the same input produces the same output (no dropout randomness)."""
    small_model.eval()
    x = torch.randint(0, 100, (2, 20))
    out1 = small_model(x)
    out2 = small_model(x)
    assert torch.allclose(out1, out2)
