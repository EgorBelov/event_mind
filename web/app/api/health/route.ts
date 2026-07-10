import { NextResponse } from "next/server";

// Liveness-проба веб-процесса (для docker/k8s healthcheck).
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok", service: "eventmind-web" });
}
