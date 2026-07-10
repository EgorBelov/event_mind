/**
 * Гейт защищённых маршрутов: без access-cookie редиректим на /login.
 * Cookie httpOnly — доступна только серверу (middleware), не JS.
 * Настоящая проверка подписи — на backend; здесь лишь дешёвый UX-редирект.
 */
import { type NextRequest, NextResponse } from "next/server";

const PROTECTED = ["/feed", "/search", "/inbox", "/settings"];
const ACCESS_COOKIE = "eventmind_access";

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED.some((p) => pathname.startsWith(p));
  if (!isProtected) return NextResponse.next();

  if (!request.cookies.has(ACCESS_COOKIE)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/feed/:path*", "/search/:path*", "/inbox/:path*", "/settings/:path*"],
};
