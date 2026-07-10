"""Integration: SmtpEmailChannel реально доставляет письмо (перехват Mailhog)."""
from __future__ import annotations

from collections.abc import Iterator

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
    assert item["Content"]["Headers"]["To"] == ["recipient@example.com"]
    body = item["Content"]["Body"]
    assert "verify-email?token=abc" in body
    assert "отписаться" in body or "List-Unsubscribe" in str(item["Content"]["Headers"])
