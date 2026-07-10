/**
 * BFF-прокси: браузер ходит на /bff/... (тот же origin, что фронт), а мы
 * пересылаем запрос на backend-API server-side, прокидывая cookie в обе стороны.
 *
 * Зачем: JWT лежит в httpOnly-cookie с `SameSite=Lax`, которую браузер НЕ шлёт
 * на кросс-origin fetch к :8000. Проксируя через свой origin, мы держим cookie
 * same-site и не раскрываем токен JS-коду.
 */
import { type NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://api:8000";

// Заголовки ответа API, которые НЕ пробрасываем клиенту (пусть Next выставит свои).
const HOP_BY_HOP = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
]);

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const search = request.nextUrl.search;
  const target = `${API_BASE_URL}/${path.join("/")}${search}`;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);

  const method = request.method;
  const body =
    method === "GET" || method === "HEAD" ? undefined : await request.text();

  let upstream: Response;
  try {
    upstream = await fetch(target, { method, headers, body, redirect: "manual" });
  } catch {
    return NextResponse.json(
      { error: { code: "upstream_unreachable", message: "API недоступен" } },
      { status: 502 },
    );
  }

  const responseBody = await upstream.arrayBuffer();
  const response = new NextResponse(responseBody, { status: upstream.status });

  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "set-cookie") {
      response.headers.set(key, value);
    }
  });
  // Set-Cookie: несколько заголовков — забираем массивом (undici getSetCookie).
  const setCookies = upstream.headers.getSetCookie?.() ?? [];
  for (const c of setCookies) {
    response.headers.append("set-cookie", c);
  }
  return response;
}

export async function GET(
  request: NextRequest,
  context: { params: { path: string[] } },
): Promise<NextResponse> {
  return proxy(request, context.params.path);
}

export const POST = GET;
export const PATCH = GET;
export const PUT = GET;
export const DELETE = GET;
