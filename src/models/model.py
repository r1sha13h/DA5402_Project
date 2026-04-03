"""BiLSTM text classifier model definition."""

import torch
import torch.nn as nn


class BiLSTMClassifier(nn.Module):
    """Bidirectional LSTM classifier for transaction description categorisation.

    Architecture:
        Embedding → BiLSTM (stacked) → Dropout → Linear → ReLU → Dropout → Linear

    Args:
        vocab_size: Total vocabulary size (including PAD and UNK tokens).
        embed_dim: Dimensionality of the word embedding vectors.
        hidden_dim: Number of features in the LSTM hidden state (per direction).
        num_classes: Number of output categories.
        num_layers: Number of stacked LSTM layers.
        dropout: Dropout probability applied between layers.
    """

    def __init__(
        self,
        vocab_size: int,
        embed_dim: int,
        hidden_dim: int,
        num_classes: int,
        num_layers: int = 2,
        dropout: float = 0.3,
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm = nn.LSTM(
            input_size=embed_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_classes),
        )
        self._init_weights()

    def _init_weights(self) -> None:
        """Initialise embedding weights with uniform distribution."""
        nn.init.uniform_(self.embedding.weight, -0.1, 0.1)
        nn.init.constant_(self.embedding.weight[0], 0)  # PAD token stays zero

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: LongTensor of shape (batch_size, seq_len) with token indices.

        Returns:
            Logit tensor of shape (batch_size, num_classes).
        """
        embedded = self.embedding(x)                          # (B, T, E)
        _, (hidden, _) = self.lstm(embedded)                  # hidden: (2*L, B, H)
        # Concatenate last-layer forward and backward hidden states
        forward_hidden = hidden[-2]                           # (B, H)
        backward_hidden = hidden[-1]                          # (B, H)
        context = torch.cat([forward_hidden, backward_hidden], dim=1)  # (B, 2H)
        return self.classifier(context)                       # (B, C)
