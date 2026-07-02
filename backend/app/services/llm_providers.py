import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse, urlunparse

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


def _append_endpoint_path(raw_url: str, default_versioned_path: str, endpoint_suffix: str) -> str:
    parsed = urlparse(raw_url)
    path = parsed.path.rstrip("/")
    if path.endswith(endpoint_suffix):
        return raw_url
    if not path:
        path = default_versioned_path
    else:
        path = f"{path}{endpoint_suffix}"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, parsed.fragment))


def openai_chat_endpoint_url(raw_url: str) -> str:
    return _append_endpoint_path(raw_url, "/v1/chat/completions", "/chat/completions")


def anthropic_messages_endpoint_url(raw_url: str) -> str:
    return _append_endpoint_path(raw_url, "/v1/messages", "/messages")


def provider_endpoint_url(provider: LlmProviderSetting, settings: Settings) -> str:
    if provider.base_url:
        base_url = validate_provider_base_url(provider.base_url, allow_private=settings.allow_private_llm_base_urls)
        if provider.provider == "anthropic":
            return anthropic_messages_endpoint_url(base_url)
        return openai_chat_endpoint_url(base_url)
    if provider.provider == "anthropic":
        return ANTHROPIC_MESSAGES_URL
    return OPENAI_CHAT_COMPLETIONS_URL


def openai_chat_completion_text(raw: Any) -> str:
    if not isinstance(raw, dict):
        raise ValueError("Provider returned non-object JSON; check Base URL points to a chat/completions endpoint")
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Provider response is not OpenAI chat completions JSON; check Base URL, model and provider type")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("Provider response choice is malformed; check provider compatibility")
    message = first.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("Provider response is missing choices[0].message.content; check provider compatibility")
    return message["content"]


def anthropic_message_text(raw: Any) -> str:
    if not isinstance(raw, dict):
        raise ValueError("Provider returned non-object JSON; check Base URL points to a messages endpoint")
    content = raw.get("content")
    if not isinstance(content, list) or not content:
        raise ValueError("Provider response is not Anthropic messages JSON; check Base URL, model and provider type")
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    text = "\n".join(part for part in text_parts if part)
    if not text:
        raise ValueError("Provider response is missing text content; check provider compatibility")
    return text
