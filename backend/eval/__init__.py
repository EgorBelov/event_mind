"""Offline-eval harness рекомендера EventMind (воспроизводимо, seed=42).

Работает против **чистой математики** `domain/recommender` + `application`
HybridRanker — без БД/LLM/torch. Синтетический leave-one-out бенчмарк меряет
Recall@k / nDCG@k / MAP@k + coverage/diversity, сравнивая абляции (rule-only /
content-only / bayesian-only / full / no-MMR). Порт идеи из
`legacy/scripts/eval_offline_synthetic.py`, очищенный от sync-SQLAlchemy/JSON-
эмбеддингов: датасет и эмбеддинги генерируются детерминированно.
"""
from __future__ import annotations

SEED = 42
