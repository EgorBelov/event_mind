"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    api
      .me()
      .then(() => router.replace("/feed"))
      .catch(() => undefined);
  }, [router]);

  return (
    <main className="container">
      <h1 style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>EventMind</h1>
      <p className="notice" style={{ fontSize: "1rem", maxWidth: 560 }}>
        Агрегируем IT-мероприятия из десятков источников и строим персональную
        ленту: контентные эмбеддинги, Thompson-sampling и NL-поиск по обычной
        фразе. Войдите, чтобы получить рекомендации.
      </p>
      <div className="row" style={{ marginTop: "1.5rem" }}>
        <Link href="/login" className="btn primary">
          Войти
        </Link>
        <Link href="/register" className="btn">
          Создать аккаунт
        </Link>
      </div>
    </main>
  );
}
