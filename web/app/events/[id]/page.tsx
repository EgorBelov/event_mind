"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { EventDetail } from "@/lib/types";

export default function EventPage({ params }: { params: { id: string } }) {
  const [ev, setEv] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = Number(params.id);
    if (!Number.isFinite(id)) {
      setError("Некорректный идентификатор");
      return;
    }
    api
      .event(id)
      .then(setEv)
      .catch((e) =>
        setError(e instanceof ApiError && e.status === 404 ? "Событие не найдено" : "Ошибка"),
      );
  }, [params.id]);

  if (error) return <main className="container"><p className="error">{error}</p></main>;
  if (!ev) return <main className="container">Загрузка…</main>;

  return (
    <main className="container">
      <article className="card">
        <h2 style={{ marginTop: 0 }}>{ev.title}</h2>
        <div className="meta">
          <span>📅 {ev.date}</span>
          {ev.city && <span>📍 {ev.city}</span>}
          {ev.format && <span>💻 {ev.format}</span>}
          {ev.event_type && <span>🏷 {ev.event_type}</span>}
          {ev.level && <span>🎓 {ev.level}</span>}
          <span>источник: {ev.source}</span>
        </div>
        {ev.summary && <p style={{ fontWeight: 500 }}>{ev.summary}</p>}
        <p style={{ whiteSpace: "pre-wrap" }}>{ev.description}</p>
        {ev.tech_stack.length > 0 && (
          <div style={{ marginTop: "0.6rem" }}>
            <strong className="notice">Стек: </strong>
            {ev.tech_stack.map((t) => (
              <span key={t} className="tag">
                {t}
              </span>
            ))}
          </div>
        )}
        {ev.topics.length > 0 && (
          <div style={{ marginTop: "0.4rem" }}>
            {ev.topics.map((t) => (
              <span key={t} className="tag">
                {t}
              </span>
            ))}
          </div>
        )}
        {ev.source_url && (
          <p style={{ marginTop: "1rem" }}>
            <a className="btn primary" href={ev.source_url} target="_blank" rel="noreferrer">
              Открыть источник ↗
            </a>
          </p>
        )}
      </article>
    </main>
  );
}
