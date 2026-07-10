"""Jinja2-рендер писем (порт `EmailRenderer`).

Шаблоны инлайн (DictLoader) — писем немного и не хочется тащить data-файлы в
пакет. Каждое письмо содержит HTML + текстовую версию и `List-Unsubscribe`
(анти-абьюз, требование рассылок).
"""
from __future__ import annotations

from jinja2 import Environment

from eventmind.application.ports.email import EmailMessage

_BASE_HTML = """\
<!doctype html><html><body style="font-family:system-ui,Arial,sans-serif;color:#222">
<h2>{{ heading }}</h2>
<p>{{ intro }}</p>
<p><a href="{{ action_url }}"
   style="display:inline-block;padding:10px 18px;background:#2563eb;color:#fff;
   text-decoration:none;border-radius:6px">{{ action_label }}</a></p>
<p style="color:#666;font-size:13px">Если кнопка не работает, откройте ссылку:<br>
<a href="{{ action_url }}">{{ action_url }}</a></p>
<hr style="border:none;border-top:1px solid #eee">
<p style="color:#999;font-size:12px">EventMind ·
<a href="{{ unsubscribe_url }}">отписаться</a></p>
</body></html>"""

_BASE_TEXT = """\
{{ heading }}

{{ intro }}

{{ action_label }}: {{ action_url }}

—
EventMind. Отписаться: {{ unsubscribe_url }}
"""


class Jinja2EmailRenderer:
    def __init__(self, public_web_url: str) -> None:
        self._public_web_url = public_web_url.rstrip("/")
        self._env = Environment(autoescape=True)
        self._html_tmpl = self._env.from_string(_BASE_HTML)
        self._text_tmpl = self._env.from_string(_BASE_TEXT)

    def _unsubscribe_url(self) -> str:
        return f"{self._public_web_url}/settings/notifications"

    def _render(
        self, *, to: str, subject: str, heading: str, intro: str, url: str, label: str
    ) -> EmailMessage:
        ctx = {
            "heading": heading,
            "intro": intro,
            "action_url": url,
            "action_label": label,
            "unsubscribe_url": self._unsubscribe_url(),
        }
        return EmailMessage(
            to=to,
            subject=subject,
            html=self._html_tmpl.render(ctx),
            text=self._text_tmpl.render(ctx),
            headers={"List-Unsubscribe": f"<{self._unsubscribe_url()}>"},
        )

    def render_verification(self, to: str, verify_url: str) -> EmailMessage:
        return self._render(
            to=to,
            subject="Подтвердите email — EventMind",
            heading="Добро пожаловать в EventMind",
            intro="Подтвердите адрес, чтобы начать получать персональные рекомендации.",
            url=verify_url,
            label="Подтвердить email",
        )

    def render_password_reset(self, to: str, reset_url: str) -> EmailMessage:
        return self._render(
            to=to,
            subject="Сброс пароля — EventMind",
            heading="Сброс пароля",
            intro="Вы запросили сброс пароля. Ссылка действует ограниченное время.",
            url=reset_url,
            label="Задать новый пароль",
        )
