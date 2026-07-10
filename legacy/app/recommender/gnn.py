"""LightGCN-подобный collaborative-эмбеддинг на чистом numpy/scipy.

Граф двудольный: User—interaction—Event (вес +1 для like/save, -1 для dislike).
Эмбеддинги получаются через `K` шагов message passing на нормализованной
матрице смежности:

    e^(k+1) = D^(-1/2) A D^(-1/2) · e^(k)

Финальный эмбеддинг — среднее по слоям (как в LightGCN).

Зачем чистый numpy, а не PyTorch-Geometric:
- избегаем 1.5GB зависимостей,
- модель тривиальна на нашем масштабе (десятки–сотни узлов),
- результат тот же при условии, что мы не обучаем embedding'и градиентом.
  Мы используем pure-propagation вариант (LightGCN без learned embedding'ов),
  стартующий от уже посчитанных sentence-transformer векторов событий и
  усреднённых эмбеддингов пользователей.

Best-effort:
- Если событий и interactions слишком мало (<MIN_GRAPH_NODES) — модель
  не обучается, scoring возвращает 0.
- При любом сбое — `gnn_score` возвращает 0 и hybrid деградирует.

Запуск переобучения: `python -m scripts.train_gnn` (или в digest-job).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


MIN_GRAPH_NODES = 5
DEFAULT_LAYERS = 3
CACHE_FILE = Path("data/gnn_embeddings.npz")


_runtime_cache: dict[str, np.ndarray] = {}


def _ensure_dir() -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _build_adjacency(
    interactions: list,
    n_users: int,
    n_events: int,
    user_idx: dict[int, int],
    event_idx: dict[int, int],
) -> np.ndarray:
    """Билдим (n_users+n_events) × (n_users+n_events) симметричную adjacency."""
    n = n_users + n_events
    A = np.zeros((n, n), dtype=np.float32)
    weights = {"like": 1.0, "save": 1.5, "dislike": -1.0}
    for i in interactions:
        if i.user_id not in user_idx or i.event_id not in event_idx:
            continue
        u = user_idx[i.user_id]
        e = n_users + event_idx[i.event_id]
        w = weights.get(i.action, 0.0)
        # LightGCN ожидает неотрицательные веса; для dislike используем подавление через прокол на 0
        # (отдельный отрицательный сигнал реализуется через bandit/Bayesian, GNN остаётся про "близость").
        if w <= 0:
            continue
        A[u, e] += w
        A[e, u] += w
    return A


def _normalize(A: np.ndarray) -> np.ndarray:
    deg = A.sum(axis=1)
    # Защита от деления на ноль для изолированных узлов.
    safe = np.where(deg > 0, deg, 1.0)
    deg_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(safe), 0.0)
    D_inv_sqrt = np.diag(deg_inv_sqrt)
    return D_inv_sqrt @ A @ D_inv_sqrt


def _init_event_embeddings(events, dim: int) -> np.ndarray:
    """Стартуем event-эмбеддинги из уже посчитанных sentence-transformer векторов.

    Если у события есть JSON-embedding в `Event.embedding` — берём первые
    `dim` компонент (или паддинг нулями). Иначе — нули.
    """
    mat = np.zeros((len(events), dim), dtype=np.float32)
    for i, ev in enumerate(events):
        raw = getattr(ev, "embedding", None)
        if not raw:
            continue
        try:
            vec = np.array(json.loads(raw), dtype=np.float32)
        except Exception:
            continue
        if vec.shape[0] >= dim:
            mat[i] = vec[:dim]
        else:
            mat[i, : vec.shape[0]] = vec
    return mat


def _init_user_embeddings(users, events_emb: np.ndarray, interactions, user_idx, event_idx, dim: int) -> np.ndarray:
    """Стартовый user-emb = среднее по событиям, с которыми он взаимодействовал положительно."""
    mat = np.zeros((len(users), dim), dtype=np.float32)
    counts = np.zeros(len(users), dtype=np.float32)
    weights = {"like": 1.0, "save": 1.5}
    for i in interactions:
        if i.action not in weights:
            continue
        if i.user_id not in user_idx or i.event_id not in event_idx:
            continue
        u = user_idx[i.user_id]
        e = event_idx[i.event_id]
        w = weights[i.action]
        mat[u] += w * events_emb[e]
        counts[u] += w
    nonzero = counts > 0
    mat[nonzero] = mat[nonzero] / counts[nonzero, None]
    return mat


def train_gnn(db, layers: int = DEFAULT_LAYERS) -> dict:
    """Полный rebuild GNN-эмбеддингов. Сохраняет npz и runtime-кэш.

    Возвращает мета: размеры графа, число шагов, путь к кэшу.
    """
    from app.db.models.event import Event
    from app.db.models.interaction import Interaction
    from app.db.models.user import User

    users = db.query(User).all()
    events = db.query(Event).all()
    interactions = db.query(Interaction).all()

    if len(users) + len(events) < MIN_GRAPH_NODES or len(interactions) == 0:
        return {"status": "skipped", "reason": "not_enough_data"}

    user_idx = {u.id: i for i, u in enumerate(users)}
    event_idx = {e.id: i for i, e in enumerate(events)}
    n_users, n_events = len(users), len(events)
    dim = settings.gnn_embedding_dim

    A = _build_adjacency(interactions, n_users, n_events, user_idx, event_idx)
    A_norm = _normalize(A)

    e_events = _init_event_embeddings(events, dim)
    e_users = _init_user_embeddings(users, e_events, interactions, user_idx, event_idx, dim)
    E = np.vstack([e_users, e_events])  # (n_users+n_events, dim)

    # LightGCN propagation: average across layers.
    layer_outs = [E]
    cur = E
    for _ in range(layers):
        cur = A_norm @ cur
        layer_outs.append(cur)
    final = np.mean(np.stack(layer_outs, axis=0), axis=0)

    user_emb = final[:n_users]
    event_emb = final[n_users:]

    _ensure_dir()
    np.savez(
        CACHE_FILE,
        user_ids=np.array(list(user_idx.keys()), dtype=np.int64),
        event_ids=np.array(list(event_idx.keys()), dtype=np.int64),
        user_emb=user_emb,
        event_emb=event_emb,
    )
    _load_cache(force=True)

    return {
        "status": "ok",
        "n_users": n_users,
        "n_events": n_events,
        "n_interactions": len(interactions),
        "layers": layers,
        "cache_file": str(CACHE_FILE),
    }


def _load_cache(force: bool = False) -> None:
    """Подгрузить npz в runtime, если ещё не загружено."""
    if not force and _runtime_cache:
        return
    if not CACHE_FILE.exists():
        return
    try:
        data = np.load(CACHE_FILE)
        _runtime_cache.clear()
        _runtime_cache["user_ids"] = data["user_ids"]
        _runtime_cache["event_ids"] = data["event_ids"]
        _runtime_cache["user_emb"] = data["user_emb"]
        _runtime_cache["event_emb"] = data["event_emb"]
    except Exception as e:
        logger.warning("GNN cache load failed: %s", e)


def gnn_score(user, event) -> float:
    """Cosine между GNN-эмбеддингами user и event; 0 при отсутствии данных."""
    _load_cache()
    if not _runtime_cache:
        return 0.0
    try:
        user_ids = _runtime_cache["user_ids"]
        event_ids = _runtime_cache["event_ids"]
        u_pos = np.where(user_ids == user.id)[0]
        e_pos = np.where(event_ids == event.id)[0]
        if u_pos.size == 0 or e_pos.size == 0:
            return 0.0
        ue = _runtime_cache["user_emb"][u_pos[0]]
        ev = _runtime_cache["event_emb"][e_pos[0]]
        denom = float(np.linalg.norm(ue) * np.linalg.norm(ev) + 1e-9)
        return float(np.dot(ue, ev) / denom)
    except Exception:
        return 0.0


def invalidate_cache() -> None:
    _runtime_cache.clear()
