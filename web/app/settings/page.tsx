"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  Preferences,
  TelegramLinkToken,
  UserProfile,
  UserResponse,
} from "@/lib/types";

const LEVEL_LABELS: Record<string, string> = {
  junior: "junior",
  middle: "middle",
  senior: "senior",
  any: "не указан",
};

export default function SettingsPage() {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [about, setAbout] = useState("");
  const [savingAbout, setSavingAbout] = useState(false);
  const [tg, setTg] = useState<TelegramLinkToken | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.me(), api.getPreferences(), api.getUserProfile()])
      .then(([u, p, prof]) => {
        setUser(u);
        setPrefs(p);
        setProfile(prof);
        setAbout(prof.about);
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

  // interests / anti: null — система извлечёт из текста сама (LLM)
  async function saveAbout(
    interests: string[] | null = null,
    anti: string[] | null = null,
  ) {
    setSavingAbout(true);
    try {
      const updated = await api.saveUserProfile(about, interests, anti);
      setProfile(updated);
      setAbout(updated.about);
      flash("Профиль интересов обновлён — лента пересчитана");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ошибка сохранения профиля");
    } finally {
      setSavingAbout(false);
    }
  }

  function removeTopic(kind: "interests" | "anti_interests", code: string) {
    if (!profile) return;
    const interests = profile.interests.filter((t) => kind !== "interests" || t !== code);
    const anti = profile.anti_interests.filter(
      (t) => kind !== "anti_interests" || t !== code,
    );
    void saveAbout(interests, anti);
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
        <h3>О себе</h3>
        <p className="notice">
          Расскажите своими словами, чем занимаетесь и что интересно — по этому
          тексту система строит модель ваших интересов и подбирает события сразу,
          ещё до первых лайков.
        </p>
        <textarea
          value={about}
          onChange={(e) => setAbout(e.target.value)}
          rows={5}
          maxLength={2000}
          style={{ width: "100%" }}
          placeholder="Например: backend-разработчик на Go, 3 года опыта. Хочу перейти в ML, интересны highload и Kubernetes. Фронтенд не интересен. Предпочитаю онлайн."
        />
        <button
          className="primary"
          onClick={() => saveAbout()}
          disabled={savingAbout}
          style={{ marginTop: "0.7rem" }}
        >
          {savingAbout ? "Разбираю…" : "Сохранить и разобрать"}
        </button>

        {profile && !profile.is_empty && (
          <div style={{ marginTop: "1rem" }}>
            <h4 style={{ margin: "0 0 0.4rem" }}>Как система вас видит</h4>
            {profile.role && <p style={{ margin: "0.2rem 0" }}>Роль: {profile.role}</p>}
            <p style={{ margin: "0.2rem 0" }}>
              Уровень: {LEVEL_LABELS[profile.level] ?? profile.level}
            </p>
            {profile.stack.length > 0 && (
              <p style={{ margin: "0.2rem 0" }}>Стек: {profile.stack.join(", ")}</p>
            )}
            {profile.goals.length > 0 && (
              <p style={{ margin: "0.2rem 0" }}>Цели: {profile.goals.join("; ")}</p>
            )}
            {profile.skill_gaps.length > 0 && (
              <p style={{ margin: "0.2rem 0" }}>
                Не хватает для целей: {profile.skill_gaps.join(", ")}{" "}
                <span className="notice">— подбираем события под это</span>
              </p>
            )}
            <div style={{ marginTop: "0.4rem" }}>
              Интересы:{" "}
              {profile.interests.length === 0 && <span className="notice">—</span>}
              {profile.interests.map((t) => (
                <span key={t} className="tag">
                  {t}{" "}
                  <button
                    title="Убрать из интересов"
                    onClick={() => removeTopic("interests", t)}
                    disabled={savingAbout}
                    style={{ padding: "0 0.3rem" }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <div style={{ marginTop: "0.4rem" }}>
              Не интересно:{" "}
              {profile.anti_interests.length === 0 && <span className="notice">—</span>}
              {profile.anti_interests.map((t) => (
                <span key={t} className="tag">
                  {t}{" "}
                  <button
                    title="Убрать из «не интересно»"
                    onClick={() => removeTopic("anti_interests", t)}
                    disabled={savingAbout}
                    style={{ padding: "0 0.3rem" }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            {!profile.has_embedding && (
              <p className="notice" style={{ marginTop: "0.5rem" }}>
                Семантический вектор профиля пока не построен (модель эмбеддингов
                недоступна) — подбор идёт по объявленным интересам.
              </p>
            )}
          </div>
        )}
      </section>

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
