export default function HomePage() {
  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "3rem 1.5rem" }}>
      <h1 style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>EventMind</h1>
      <p style={{ color: "#555", lineHeight: 1.6 }}>
        Веб-клиент v2 (каркас). Основной интерфейс — лента рекомендаций, профиль
        интересов, NL-поиск, настройки каналов доставки — наполняется в M6.
      </p>
      <p style={{ marginTop: "1.5rem", fontSize: "0.9rem", color: "#888" }}>
        API: <code>/api/v1</code> · статус фронта: <code>/api/health</code>
      </p>
    </main>
  );
}
