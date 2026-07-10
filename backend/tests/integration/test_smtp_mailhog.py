"""Integration: SmtpEmailChannel реально доставляет письмо (перехват Mailhog)."""
from __future__ import annotations

import email
from collections.abc import Iterator
from email.policy import default

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from eventmind.application.ports.email import EmailMessage
from eventmind.config import Settings
from eventmind.infrastructure.email.renderer import Jinja2EmailRenderer
from eventmind.infrastructure.email.smtp import SmtpEmailChannel

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def mailhog() -> Iterator[tuple[str, int, int]]:
    container = DockerContainer("mailhog/mailhog:v1.0.1").with_exposed_ports(1025, 8025)
    container.start()
    try:
        wait_for_logs(container, "Serving under", timeout=30)
        host = container.get_container_host_ip()
        smtp_port = int(container.get_exposed_port(1025))
        http_port = int(container.get_exposed_port(8025))
        yield host, smtp_port, http_port
    finally:
        container.stop()


async def test_smtp_channel_delivers_to_mailhog(mailhog: tuple[str, int, int]) -> None:
    host, smtp_port, http_port = mailhog
    settings = Settings(
        smtp_host=host,
        smtp_port=smtp_port,
        smtp_use_tls=False,
        smtp_use_ssl=False,
        email_from="EventMind <noreply@eventmind.local>",
    )
    channel = SmtpEmailChannel(settings)
    renderer = Jinja2EmailRenderer("http://localhost:3000")
    message: EmailMessage = renderer.render_verification(
        "recipient@example.com", "http://localhost:3000/verify-email?token=abc"
    )

    await channel.send(message)

    # Mailhog HTTP API: письмо доставлено и содержит unsubscribe-ссылку
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.get(f"http://{host}:{http_port}/api/v2/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    headers = item["Content"]["Headers"]
    assert headers["To"] == ["recipient@example.com"]

    # Тело — multipart/alternative с base64 CTE (внутри кириллица), поэтому
    # искать ссылку в сыром `Body` нельзя — она внутри base64. Собираем сырое
    # письмо из заголовков+тела и декодируем через email-парсер (снимает CTE и
    # charset), а затем ищем ссылку/отписку в человекочитаемом тексте.
    raw = (
        "".join(f"{key}: {value}\n" for key, values in headers.items() for value in values)
        + "\n"
        + item["Content"]["Body"]
    )
    parsed = email.message_from_string(raw, policy=default)
    text = "".join(
        part.get_content()
        for part in parsed.walk()
        if part.get_content_maintype() == "text"
    )
    assert "verify-email?token=abc" in text
    assert "отписаться" in text
    assert "List-Unsubscribe" in headers
