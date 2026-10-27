/**
 * Типизированный API-клиент. Все вызовы идут через BFF-прокси (`/bff/...`),
 * который держит httpOnly-cookie same-site. В браузере — относительный URL;
 * `credentials: "include"` шлёт cookie на свой origin.
 */
import type {
  AgentHistory,
  AgentReply,
  AuthResponse,
  EventDetail,
  Explanation,
  InboxResponse,
  MessageResponse,
  NlSearchResponse,
  Preferences,
  Recommendation,
  SavedPage,
  TelegramLinkToken,
  UserProfile,
  UserResponse,
} from "./types";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = { method, credentials: "include", headers: {} };
  if (body !== undefined) {
    (init.headers as Record<string, string>)["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const resp = await fetch(`/bff${path}`, init);
  const text = await resp.text();
  const data = text ? JSON.parse(text) : null;
  if (!resp.ok) {
    const err = data?.error ?? {};
    throw new ApiError(resp.status, err.code ?? "error", err.message ?? resp.statusText);
  }
  return data as T;
}

export const api = {
  // auth
  register: (email: string, password: string) =>
    request<AuthResponse>("POST", "/api/v1/auth/register", { email, password }),
  login: (email: string, password: string) =>
    request<AuthResponse>("POST", "/api/v1/auth/login", { email, password }),
  googleLogin: (idToken: string) =>
    request<AuthResponse>("POST", "/api/v1/auth/google", { id_token: idToken }),
  logout: () => request<MessageResponse>("POST", "/api/v1/auth/logout"),
  me: () => request<UserResponse>("GET", "/api/v1/users/me"),

  // profile / preferences
  updateProfile: (city: string | null, preferredFormat: string | null) =>
    request<UserResponse>("PATCH", "/api/v1/users/me", {
      city,
      preferred_format: preferredFormat,
    }),
  getUserProfile: () => request<UserProfile>("GET", "/api/v1/users/me/profile"),
  // interests / anti_interests: null — пусть система извлечёт сама из текста
  saveUserProfile: (
    about: string,
    interests: string[] | null = null,
    antiInterests: string[] | null = null,
  ) =>
    request<UserProfile>("PUT", "/api/v1/users/me/profile", {
      about,
      interests,
      anti_interests: antiInterests,
    }),
  getPreferences: () => request<Preferences>("GET", "/api/v1/users/me/preferences"),
  updatePreferences: (patch: Partial<Preferences>) =>
    request<Preferences>("PATCH", "/api/v1/users/me/preferences", patch),

  // recommendations & interactions
  recommendations: (limit = 20) =>
    request<Recommendation[]>("GET", `/api/v1/recommendations?limit=${limit}`),
  interact: (eventId: number, action: "like" | "dislike" | "save" | "view") =>
    request<MessageResponse>("POST", "/api/v1/interactions", {
      event_id: eventId,
      action,
    }),

  // search & events
  nlSearch: (q: string, limit = 5) =>
    request<NlSearchResponse>(
      "GET",
      `/api/v1/events/nl-search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  event: (id: number) => request<EventDetail>("GET", `/api/v1/events/${id}`),
  explain: (id: number) => request<Explanation>("GET", `/api/v1/events/${id}/explain`),

  // saved
  saved: (offset = 0, limit = 10) =>
    request<SavedPage>("GET", `/api/v1/saved?offset=${offset}&limit=${limit}`),
  removeSaved: (id: number) => request<MessageResponse>("DELETE", `/api/v1/saved/${id}`),

  // диалоговый агент
  agentSend: (message: string) =>
    request<AgentReply>("POST", "/api/v1/agent/messages", { message }),
  agentConfirm: (actionId: string, approve: boolean) =>
    request<AgentReply>("POST", "/api/v1/agent/confirm", { action_id: actionId, approve }),
  agentHistory: () => request<AgentHistory>("GET", "/api/v1/agent/session"),
  agentReset: () => request<MessageResponse>("DELETE", "/api/v1/agent/session"),

  // notifications
  inbox: (limit = 30) =>
    request<InboxResponse>("GET", `/api/v1/notifications?limit=${limit}`),
  markRead: (id: number) =>
    request<MessageResponse>("POST", `/api/v1/notifications/${id}/read`),

  // telegram link
  telegramLinkToken: () =>
    request<TelegramLinkToken>("POST", "/api/v1/channels/telegram/link-token"),
};
