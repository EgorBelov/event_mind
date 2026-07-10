"""Ручной запуск compaction для всех пользователей с разросшейся памятью.

    python -m scripts.compact_memories
    python -m scripts.compact_memories --threshold 30
"""
from __future__ import annotations

import argparse

from app.db.models.user import User
from app.db.session import SessionLocal
from app.recommender.memory import compact_user_memories


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=int, default=50)
    parser.add_argument("--target-per-category", type=int, default=5)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print("=== Memory compaction ===")
        for user in db.query(User).all():
            result = compact_user_memories(
                db, user.id,
                threshold=args.threshold,
                target_per_category=args.target_per_category,
            )
            if result["status"] == "ok":
                print(f"user {user.id}: before={result['before']} -{result['removed']} +{result['added']}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
