import ipaddress
import socket
from urllib.parse import urlparse

from app.core.settings import Settings
from app.models import LlmProviderSetting


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def provider_supports_vision(provider: LlmProviderSetting) -> bool:
    model = (provider.model or "").lower()
    if provider.provider == "anthropic":
        return model.startswith("claude-3") or any(marker in model for marker in ("sonnet", "opus", "haiku"))
    if provider.provider == "openai":
        return any(marker in model for marker in ("vision", "gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4", "gemini"))
    return False


def reject_private_address(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise ValueError("Provider base_url must resolve to a public address")


def validate_provider_base_url(raw_url: str, allow_private: bool = False) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"https"} and not allow_private:
        raise ValueError("Provider base_url must use HTTPS")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Provider base_url must use HTTP or HTTPS")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("Provider base_url must include a host")
    if parsed.username or parsed.password:
        raise ValueError("Provider base_url must not include credentials")

    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost") or hostname.endswith(".local"):
        if not allow_private:
            raise ValueError("Provider base_url must not use localhost or .local hosts")
        return raw_url
    if allow_private:
        return raw_url

    try:
        reject_private_address(hostname)
    except ValueError as exc:
        if str(exc).startswith("Provider base_url"):
            raise
        try:
            records = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as dns_error:
            raise ValueError("Provider base_url host could not be resolved") from dns_error
        addresses = {record[4][0] for record in records}
        if not addresses:
            raise ValueError("Provider base_url host could not be resolved")
        for address in addresses:
            reject_private_address(address)
    return raw_url


def provider_endpoint_url(provider: LlmProviderSetting, settings: Settings) -> str:
    if provider.base_url:
        return validate_provider_base_url(provider.base_url, allow_private=settings.allow_private_llm_base_urls)
    if provider.provider == "anthropic":
        return ANTHROPIC_MESSAGES_URL
    return OPENAI_CHAT_COMPLETIONS_URL
