"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { EventDetail } from "@/lib/types";

type Action = "like" | "dislike" | "save";

/** Компактная карточка события с оценками (помощник, сохранённое). */
export function EventCard({
  ev,
  actions = true,
  extra,
}: {
  ev: EventDetail;
  actions?: boolean;
  extra?: React.ReactNode;
}) {
  const [chosen, setChosen] = useState<Action | null>(null);

  async function act(action: Action) {
    setChosen(action);
    await api.interact(ev.id, action).catch(() => undefined);
  }

  const text = ev.summary ?? ev.description;
  return (
    <article className="card">
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
        {text.slice(0, 220)}
        {text.length > 220 ? "…" : ""}
      </p>
      <div>
        {ev.topics.slice(0, 6).map((t) => (
          <span key={t} className="tag">
            {t}
          </span>
        ))}
      </div>
      <div className="row" style={{ marginTop: "0.7rem" }}>
        {actions && (
          <>
            <button className={chosen === "like" ? "primary" : ""} onClick={() => act("like")}>
              👍
            </button>
            <button className={chosen === "save" ? "primary" : ""} onClick={() => act("save")}>
              ⭐ Сохранить
            </button>
            <button
              className={chosen === "dislike" ? "primary" : ""}
              onClick={() => act("dislike")}
            >
              👎 Скрыть
            </button>
          </>
        )}
        {extra}
        {ev.source_url && (
          <a className="btn" href={ev.source_url} target="_blank" rel="noreferrer">
            Источник ↗
          </a>
        )}
      </div>
    </article>
  );
}
