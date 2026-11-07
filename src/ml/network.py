"""A small MLP predicting bounded normalized European call prices, C/K."""

import torch
from torch import nn

ARCHITECTURE = {"hidden_sizes": [96, 96, 64], "activation": "silu", "output": "bounded_call_v1"}


class PricingMLP(nn.Module):
    def __init__(self, mean: list[float], scale: list[float]):
        super().__init__()
        self.register_buffer("feature_mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("feature_scale", torch.tensor(scale, dtype=torch.float32))
        self.layers = nn.Sequential(
            nn.Linear(4, 96),
            nn.SiLU(),
            nn.Linear(96, 96),
            nn.SiLU(),
            nn.Linear(96, 64),
            nn.SiLU(),
            nn.Linear(64, 1),
        )

    def forward(self, raw: torch.Tensor) -> torch.Tensor:
        logits = self.layers((raw - self.feature_mean) / self.feature_scale).squeeze(-1)
        spot_over_strike = torch.exp(raw[:, 0])
        discount = torch.exp(-raw[:, 2] * raw[:, 1])
        lower = torch.relu(spot_over_strike - discount)
        # Structural bounds are part of the model, not an inference-time clamp.
        return lower + (spot_over_strike - lower) * torch.sigmoid(logits)
