// k6 смоук-нагрузка на хот-пути EventMind.
//
// Запуск:  k6 run -e BASE_URL=http://localhost:8000 deploy/loadtest/k6-smoke.js
//
// Сценарий на VU: регистрация уникального аккаунта (ставит httpOnly-cookie) →
// N раз читаем персональную ленту (read-only hot-path, кэш) → health/ready.
// NL-поиск НЕ бьём в нагрузке — он ходит в внешний LLM (лимиты/стоимость).
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const errors = new Counter("app_errors");

export const options = {
  scenarios: {
    smoke: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 20 },
        { duration: "1m", target: 20 },
        { duration: "30s", target: 0 },
      ],
      gracefulStop: "10s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"], // <1% сетевых ошибок
    http_req_duration: ["p(95)<1000"], // p95 < 1s
    app_errors: ["count<50"],
  },
};

function register(jar) {
  const email = `load_${__VU}_${__ITER}_${Date.now()}@loadtest.local`;
  const res = http.post(
    `${BASE_URL}/api/v1/auth/register`,
    JSON.stringify({ email, password: "password123" }),
    { headers: { "Content-Type": "application/json" }, jar },
  );
  if (!check(res, { "register 201": (r) => r.status === 201 })) {
    errors.add(1);
  }
}

export default function () {
  const jar = http.cookieJar();

  // liveness/readiness — дёшево и всегда доступно
  check(http.get(`${BASE_URL}/health`), { "health 200": (r) => r.status === 200 });

  register(jar);

  for (let i = 0; i < 3; i++) {
    const res = http.get(`${BASE_URL}/api/v1/recommendations?limit=20`, { jar });
    if (!check(res, { "recs 200": (r) => r.status === 200 })) {
      errors.add(1);
    }
    sleep(1);
  }
}
