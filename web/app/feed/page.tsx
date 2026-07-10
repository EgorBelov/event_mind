"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Recommendation } from "@/lib/types";

export default function FeedPage() {
  const [items, setItems] = useState<Recommendation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acted, setActed] = useState<Record<number, string>>({});

  async function load() {
    setError(null);
    try {
      setItems(await api.recommendations(20));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить ленту");
      setItems([]);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function act(id: number, action: "like" | "dislike" | "save") {
    setActed((s) => ({ ...s, [id]: action }));
    await api.interact(id, action).catch(() => undefined);
  }

  if (items === null) return <main className="container">Загрузка ленты…</main>;

  return (
    <main className="container">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: "0 0 0.5rem" }}>Рекомендации</h2>
        <button onClick={load}>Обновить</button>
      </div>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && !error && (
        <p className="notice">
          Пока пусто. Настройте интересы в{" "}
          <Link href="/settings">настройках</Link> или воспользуйтесь{" "}
          <Link href="/search">поиском</Link>.
        </p>
      )}
      {items.map((it) => {
        const chosen = acted[it.event_id];
        return (
          <article key={it.event_id} className="card">
            <h3>
              <Link href={`/events/${it.event_id}`}>{it.title}</Link>
            </h3>
            <div className="meta">
              <span>📅 {it.date}</span>
              {it.city && <span>📍 {it.city}</span>}
              {it.format && <span>💻 {it.format}</span>}
              {it.event_type && <span>🏷 {it.event_type}</span>}
              <span title="итоговый скор ранкера">★ {it.score.toFixed(2)}</span>
            </div>
            <p style={{ margin: "0.4rem 0", color: "var(--muted)" }}>
              {it.description.slice(0, 240)}
              {it.description.length > 240 ? "…" : ""}
            </p>
            <div>
              {it.topics.slice(0, 6).map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
            <div className="row" style={{ marginTop: "0.7rem" }}>
              <button
                className={chosen === "like" ? "primary" : ""}
                onClick={() => act(it.event_id, "like")}
              >
                👍 Нравится
              </button>
              <button
                className={chosen === "save" ? "primary" : ""}
                onClick={() => act(it.event_id, "save")}
              >
                ⭐ Сохранить
              </button>
              <button
                className={chosen === "dislike" ? "primary" : ""}
                onClick={() => act(it.event_id, "dislike")}
              >
                👎 Скрыть
              </button>
              {it.source_url && (
                <a className="btn" href={it.source_url} target="_blank" rel="noreferrer">
                  Источник ↗
                </a>
              )}
            </div>
          </article>
        );
      })}
    </main>
  );
}
