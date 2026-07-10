"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Preferences, TelegramLinkToken, UserResponse } from "@/lib/types";

export default function SettingsPage() {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [tg, setTg] = useState<TelegramLinkToken | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.me(), api.getPreferences()])
      .then(([u, p]) => {
        setUser(u);
        setPrefs(p);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Не удалось загрузить настройки"),
      );
  }, []);

  function flash(msg: string) {
    setSaved(msg);
    setError(null);
    setTimeout(() => setSaved(null), 2500);
  }

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    if (!user) return;
    try {
      const updated = await api.updateProfile(user.city, user.preferred_format);
      setUser(updated);
      flash("Профиль сохранён");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ошибка сохранения");
    }
  }

  async function savePrefs(patch: Partial<Preferences>) {
    try {
      setPrefs(await api.updatePreferences(patch));
      flash("Настройки уведомлений сохранены");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ошибка сохранения");
    }
  }

  async function linkTelegram() {
    try {
      setTg(await api.telegramLinkToken());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось создать ссылку");
    }
  }

  if (!user || !prefs) {
    return (
      <main className="container">
        {error ? <p className="error">{error}</p> : "Загрузка…"}
      </main>
    );
  }

  return (
    <main className="container">
      <h2 style={{ marginTop: 0 }}>Настройки</h2>
      {error && <p className="error">{error}</p>}
      {saved && <p style={{ color: "var(--ok)" }}>{saved}</p>}

      <section className="card">
        <h3>Профиль</h3>
        <p className="notice">{user.email}</p>
        <form onSubmit={saveProfile}>
          <label htmlFor="city">Город (влияет на рекомендации)</label>
          <input
            id="city"
            value={user.city ?? ""}
            onChange={(e) => setUser({ ...user, city: e.target.value || null })}
            placeholder="moscow, spb…"
          />
          <label htmlFor="fmt">Предпочитаемый формат</label>
          <select
            id="fmt"
            value={user.preferred_format ?? ""}
            onChange={(e) =>
              setUser({ ...user, preferred_format: e.target.value || null })
            }
          >
            <option value="">не важно</option>
            <option value="online">online</option>
            <option value="offline">offline</option>
            <option value="hybrid">hybrid</option>
          </select>
          <button className="primary" type="submit" style={{ marginTop: "0.7rem" }}>
            Сохранить профиль
          </button>
        </form>
      </section>

      <section className="card">
        <h3>Уведомления</h3>
        <label htmlFor="freq">Частота дайджеста</label>
        <select
          id="freq"
          value={prefs.digest_frequency}
          onChange={(e) => savePrefs({ digest_frequency: e.target.value })}
        >
          <option value="off">выключен</option>
          <option value="daily">ежедневно</option>
          <option value="weekly">еженедельно</option>
        </select>
        <div className="row" style={{ marginTop: "0.8rem" }}>
          <label style={{ margin: 0 }}>
            <input
              type="checkbox"
              checked={prefs.email_enabled}
              onChange={(e) => savePrefs({ email_enabled: e.target.checked })}
              style={{ width: "auto", marginRight: "0.4rem" }}
            />
            Email
          </label>
          <label style={{ margin: 0 }}>
            <input
              type="checkbox"
              checked={prefs.telegram_enabled}
              onChange={(e) => savePrefs({ telegram_enabled: e.target.checked })}
              style={{ width: "auto", marginRight: "0.4rem" }}
            />
            Telegram
          </label>
        </div>
      </section>

      <section className="card">
        <h3>Привязка Telegram</h3>
        <p className="notice">
          Сгенерируйте одноразовую ссылку и откройте её — бот свяжет ваш аккаунт.
        </p>
        <button onClick={linkTelegram}>Создать ссылку</button>
        {tg && (
          <p style={{ marginTop: "0.7rem" }}>
            <a href={tg.deep_link} target="_blank" rel="noreferrer">
              {tg.deep_link}
            </a>
          </p>
        )}
      </section>
    </main>
  );
}
