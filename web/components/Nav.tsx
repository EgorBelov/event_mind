"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

const LINKS = [
  { href: "/feed", label: "Лента" },
  { href: "/search", label: "Поиск" },
  { href: "/inbox", label: "Инбокс" },
  { href: "/settings", label: "Настройки" },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .me()
      .then(() => alive && setAuthed(true))
      .catch((e) => {
        if (alive) setAuthed(e instanceof ApiError && e.status === 401 ? false : false);
      });
  }, [pathname]);

  async function logout() {
    await api.logout().catch(() => undefined);
    setAuthed(false);
    router.push("/login");
  }

  return (
    <nav className="nav">
      <Link href="/" className="brand">
        EventMind
      </Link>
      {authed &&
        LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={pathname.startsWith(l.href) ? "active" : ""}
          >
            {l.label}
          </Link>
        ))}
      {authed === false && (
        <>
          <Link href="/login" className={pathname === "/login" ? "active" : ""}>
            Вход
          </Link>
          <Link href="/register" className={pathname === "/register" ? "active" : ""}>
            Регистрация
          </Link>
        </>
      )}
      {authed && (
        <button onClick={logout} style={{ padding: "0.3rem 0.7rem" }}>
          Выйти
        </button>
      )}
    </nav>
  );
}
