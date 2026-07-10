"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) {
      setError("Пароль — минимум 8 символов");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.register(email, password);
      router.push("/feed");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ошибка регистрации");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <div className="auth-wrap card">
        <h2 style={{ marginTop: 0 }}>Регистрация</h2>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Пароль (8+ символов)</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          {error && <p className="error">{error}</p>}
          <button className="primary" type="submit" disabled={busy} style={{ marginTop: "0.6rem" }}>
            {busy ? "Создаём…" : "Создать аккаунт"}
          </button>
        </form>
        <p className="notice" style={{ marginTop: "1rem" }}>
          Уже есть аккаунт? <Link href="/login">Войти</Link>
        </p>
      </div>
    </main>
  );
}
