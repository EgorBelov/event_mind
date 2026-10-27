"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { EventCard } from "@/components/EventCard";
import { api, ApiError } from "@/lib/api";
import type { AgentPending, EventDetail } from "@/lib/types";

/**
 * Панель «Помощник» (A5): диалог с агентом поверх тех же use-case'ов, что лента
 * и настройки. Изменения профиля агент только предлагает — применяются по «Да».
 */
interface ChatItem {
  role: "user" | "assistant";
  text: string;
  events?: EventDetail[];
  pending?: AgentPending | null;
}

const SUGGESTIONS = [
  "Что есть по Go на выходных?",
  "Подбери мне что-нибудь онлайн",
  "Фронтенд мне больше не интересен",
  "Хочу перейти в ML — что посоветуешь?",
];

export default function AssistantPage() {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .agentHistory()
      .then((h) => {
        const restored: ChatItem[] = h.messages.map((m) => ({ role: m.role, text: m.text }));
        if (h.pending) {
          restored.push({ role: "assistant", text: h.pending.description, pending: h.pending });
        }
        setItems(restored);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.code === "agent_disabled") setDisabled(true);
      });
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, busy]);

  function fail(e: unknown) {
    if (e instanceof ApiError && e.code === "agent_disabled") setDisabled(true);
    else setError(e instanceof ApiError ? e.message : "Не удалось связаться с помощником");
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setInput("");
    setError(null);
    setBusy(true);
    // новое сообщение отменяет неподтверждённое предложение — убираем кнопки
    setItems((s) => [...s.map((i) => ({ ...i, pending: null })), { role: "user", text: message }]);
    try {
      const reply = await api.agentSend(message);
      if (reply.degraded) {
        setError("Помощник сейчас недоступен — воспользуйтесь поиском или лентой.");
        return;
      }
      setItems((s) => [
        ...s,
        { role: "assistant", text: reply.text, events: reply.events, pending: reply.pending },
      ]);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(pending: AgentPending, approve: boolean) {
    setBusy(true);
    setItems((s) => s.map((i) => (i.pending?.id === pending.id ? { ...i, pending: null } : i)));
    try {
      const reply = await api.agentConfirm(pending.id, approve);
      setItems((s) => [...s, { role: "assistant", text: reply.text }]);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    await api.agentReset().catch(() => undefined);
    setItems([]);
    setError(null);
  }

  if (disabled) {
    return (
      <main className="container">
        <h2 style={{ marginTop: 0 }}>Помощник</h2>
        <p className="notice">
          Помощник отключён. Воспользуйтесь <Link href="/search">поиском</Link> или{" "}
          <Link href="/feed">лентой</Link>.
        </p>
      </main>
    );
  }

  return (
    <main className="container">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Помощник</h2>
        <button onClick={reset} disabled={busy}>
          Новый диалог
        </button>
      </div>
      <p className="notice">
        Спросите о мероприятиях обычными словами или расскажите о своих интересах —
        помощник найдёт события, объяснит выбор и уточнит ваш профиль (с вашего
        согласия).
      </p>

      {items.length === 0 && (
        <div className="row suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="chat">
        {items.map((item, idx) => (
          <div key={idx} style={{ display: "contents" }}>
            <div className={`bubble ${item.role}`}>{item.text}</div>
            {item.pending && (
              <div className="row" style={{ marginLeft: "1rem" }}>
                <button
                  className="primary"
                  onClick={() => confirm(item.pending as AgentPending, true)}
                  disabled={busy}
                >
                  ✅ Да
                </button>
                <button
                  onClick={() => confirm(item.pending as AgentPending, false)}
                  disabled={busy}
                >
                  ✖️ Нет
                </button>
              </div>
            )}
            {item.events?.map((ev) => (
              <EventCard key={`${idx}-${ev.id}`} ev={ev} />
            ))}
          </div>
        ))}
        {busy && <div className="bubble assistant notice">Думаю…</div>}
        <div ref={bottom} />
      </div>

      {error && <p className="error">{error}</p>}

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Например: конференции по ML в ноябре онлайн"
          maxLength={2000}
          style={{ flex: 1, minWidth: 220 }}
        />
        <button className="primary" type="submit" disabled={busy || !input.trim()}>
          Отправить
        </button>
      </form>
    </main>
  );
}
