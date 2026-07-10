"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { NlSearchResponse } from "@/lib/types";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<NlSearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setRes(await api.nlSearch(q.trim(), 5));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ошибка поиска");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <h2 style={{ marginTop: 0 }}>Поиск по фразе</h2>
      <p className="notice">
        Например: «конференции по AI с 3 по 10 июня в Москве» или «онлайн вебинары
        про Go».
      </p>
      <form onSubmit={submit} className="row" style={{ marginBottom: "1rem" }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Опишите, что ищете…"
          style={{ flex: 1, minWidth: 220 }}
        />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Ищем…" : "Найти"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {res && res.relaxed && res.results.length > 0 && (
        <p className="notice">
          Точных совпадений нет — показываем ближайшее по смыслу событие.
        </p>
      )}
      {res && res.results.length === 0 && (
        <p className="notice">Ничего не нашлось. Попробуйте переформулировать.</p>
      )}

      {res?.results.map((ev) => (
        <article key={ev.id} className="card">
          <h3>
            <Link href={`/events/${ev.id}`}>{ev.title}</Link>
          </h3>
          <div className="meta">
            <span>📅 {ev.date}</span>
            {ev.city && <span>📍 {ev.city}</span>}
            {ev.format && <span>💻 {ev.format}</span>}
            {ev.event_type && <span>🏷 {ev.event_type}</span>}
          </div>
          <p style={{ margin: "0.4rem 0", color: "var(--muted)" }}>
            {(ev.summary ?? ev.description).slice(0, 220)}…
          </p>
          <div>
            {ev.topics.slice(0, 6).map((t) => (
              <span key={t} className="tag">
                {t}
              </span>
            ))}
          </div>
        </article>
      ))}
    </main>
  );
}
