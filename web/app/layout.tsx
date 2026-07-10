import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "EventMind",
  description: "Агрегация IT-мероприятий и персональные рекомендации",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
