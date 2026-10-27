"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { EventDetail, Explanation } from "@/lib/types";

export default function EventPage({ params }: { params: { id: string } }) {
  const [ev, setEv] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [explainState, setExplainState] = useState<"idle" | "busy" | "login" | "error">("idle");

  async function explain() {
    if (!ev) return;
    setExplainState("busy");
    try {
      setExplanation(await api.explain(ev.id));
      setExplainState("idle");
    } catch (e) {
      setExplainState(e instanceof ApiError && e.status === 401 ? "login" : "error");
    }
  }

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
        <div className="row" style={{ marginTop: "1rem" }}>
          {!explanation && (
            <button onClick={explain} disabled={explainState === "busy"}>
              {explainState === "busy" ? "Готовлю…" : "📖 Подробнее и почему мне"}
            </button>
          )}
          {ev.source_url && (
            <a className="btn primary" href={ev.source_url} target="_blank" rel="noreferrer">
              Открыть источник ↗
            </a>
          )}
        </div>
        {explainState === "login" && (
          <p className="notice">
            <Link href={`/login?next=/events/${ev.id}`}>Войдите</Link>, чтобы увидеть, почему
            событие вам подходит.
          </p>
        )}
        {explainState === "error" && (
          <p className="error">Не удалось получить описание — попробуйте позже.</p>
        )}
      </article>
      {explanation && (
        <article className="card">
          <h3>📖 Коротко о событии</h3>
          <p style={{ whiteSpace: "pre-wrap" }}>{explanation.summary}</p>
          {explanation.reasons.length > 0 && (
            <>
              <h3>Почему рекомендовано</h3>
              <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                {explanation.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          )}
        </article>
      )}
    </main>
  );
}
