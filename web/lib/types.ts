/** Типы ответов backend-API (зеркалят Pydantic-схемы interfaces/api/schemas.py). */

export interface UserResponse {
  id: number;
  email: string;
  email_verified: boolean;
  is_active: boolean;
  city: string | null;
  preferred_format: string | null;
}

export interface AuthResponse {
  user: UserResponse;
  access_token: string;
  token_type: string;
}

export interface MessageResponse {
  status: string;
  detail: string | null;
}

export interface Recommendation {
  event_id: number;
  title: string;
  description: string;
  date: string;
  city: string;
  format: string;
  event_type: string | null;
  source_url: string | null;
  score: number;
  topics: string[];
}

export interface EventDetail {
  id: number;
  source: string;
  title: string;
  description: string;
  format: string;
  city: string;
  level: string;
  date: string;
  start_at: string | null;
  event_type: string | null;
  target_audience: string | null;
  source_url: string | null;
  summary: string | null;
  tech_stack: string[];
  seniority: string | null;
  quality_score: number | null;
  hype_score: number | null;
  series_slug: string | null;
  topics: string[];
}

export interface NlSearchResponse {
  relaxed: boolean;
  filters: Record<string, unknown>;
  results: EventDetail[];
}

export interface NotificationItem {
  id: number;
  type: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  read: boolean;
}

export interface InboxResponse {
  unread: number;
  items: NotificationItem[];
}

export interface Preferences {
  digest_frequency: string;
  email_enabled: boolean;
  telegram_enabled: boolean;
  quiet_hours_start: number | null;
  quiet_hours_end: number | null;
}

export interface TelegramLinkToken {
  token: string;
  deep_link: string;
}

export interface ApiErrorBody {
  error: { code: string; message: string };
}
