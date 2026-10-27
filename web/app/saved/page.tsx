"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EventCard } from "@/components/EventCard";
import { api, ApiError } from "@/lib/api";
import type { EventDetail } from "@/lib/types";

const PAGE = 10;

/** «Сохранённое» — общее с ботом (⭐ в любом клиенте). */
export default function SavedPage() {
  const [items, setItems] = useState<EventDetail[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function load(offset: number) {
    setError(null);
    try {
      const page = await api.saved(offset, PAGE);
      setItems((prev) => (offset === 0 || !prev ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось загрузить сохранённое");
      setItems((prev) => prev ?? []);
    }
  }

  useEffect(() => {
    load(0);
  }, []);

  async function remove(id: number) {
    try {
      await api.removeSaved(id);
      setItems((s) => (s ?? []).filter((e) => e.id !== id));
      setTotal((t) => Math.max(0, t - 1));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось убрать");
    }
  }

  if (items === null) return <main className="container">Загрузка…</main>;

  return (
    <main className="container">
      <h2 style={{ marginTop: 0 }}>Сохранённое {total > 0 && `(${total})`}</h2>
      {error && <p className="error">{error}</p>}
      {items.length === 0 && !error && (
        <p className="notice">
          Пока пусто — жмите ⭐ в <Link href="/feed">ленте</Link>, поиске или у помощника.
        </p>
      )}
      {items.map((ev) => (
        <EventCard
          key={ev.id}
          ev={ev}
          actions={false}
          extra={<button onClick={() => remove(ev.id)}>🗑 Убрать</button>}
        />
      ))}
      {items.length < total && (
        <button onClick={() => load(items.length)}>Показать ещё</button>
      )}
    </main>
  );
}
