"""Переобучение LightGCN-эмбеддингов поверх текущего графа взаимодействий.

Запуск:
    python -m scripts.train_gnn

Опционально включается в digest-job через INGEST/GNN-настройки.
"""
from __future__ import annotations

from app.db.session import SessionLocal
from app.recommender.gnn import train_gnn


def main() -> None:
    db = SessionLocal()
    try:
        result = train_gnn(db, layers=3)
    finally:
        db.close()
    print("=== GNN training ===")
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
