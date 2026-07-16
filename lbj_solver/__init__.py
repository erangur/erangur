"""Lightning Blackjack optimal-strategy engine."""

from .config import GameConfig, DEFAULT_CONFIG
from .multipliers import MultiplierModel, BUCKET_RANGES, CARRY_VALUES, bucket_of
from .dealer import dealer_distribution
from .engine import Evaluator, Action, STAND, HIT, DOUBLE, SPLIT
from .carry import solve_carry_values

__all__ = [
    "GameConfig", "DEFAULT_CONFIG", "MultiplierModel", "BUCKET_RANGES",
    "CARRY_VALUES", "bucket_of", "dealer_distribution", "Evaluator", "Action",
    "STAND", "HIT", "DOUBLE", "SPLIT", "solve_carry_values",
]
