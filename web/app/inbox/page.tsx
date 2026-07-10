"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { InboxResponse } from "@/lib/types";

export default function InboxPage() {
  const [data, setData] = useState<InboxResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setData(await api.inbox(30));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить инбокс");
      setData({ unread: 0, items: [] });
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function markRead(id: number) {
    await api.markRead(id).catch(() => undefined);
    setData((d) =>
      d
        ? {
            unread: Math.max(0, d.unread - 1),
            items: d.items.map((i) => (i.id === id ? { ...i, read: true } : i)),
          }
        : d,
    );
  }

  if (data === null) return <main className="container">Загрузка…</main>;

  return (
    <main className="container">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: "0 0 0.5rem" }}>
          Инбокс{data.unread > 0 ? ` · ${data.unread} новых` : ""}
        </h2>
        <button onClick={load}>Обновить</button>
      </div>
      {error && <p className="error">{error}</p>}
      {data.items.length === 0 && !error && (
        <p className="notice">Уведомлений пока нет.</p>
      )}
      {data.items.map((n) => (
        <article
          key={n.id}
          className="card"
          style={{ opacity: n.read ? 0.7 : 1 }}
        >
          <h3>
            {!n.read && <span className="unread-dot" />}
            {n.title}
          </h3>
          <div className="meta">
            <span>{n.type}</span>
          </div>
          <p style={{ whiteSpace: "pre-wrap", margin: "0.3rem 0" }}>{n.body}</p>
          {!n.read && (
            <button onClick={() => markRead(n.id)}>Отметить прочитанным</button>
          )}
        </article>
      ))}
    </main>
  );
}
