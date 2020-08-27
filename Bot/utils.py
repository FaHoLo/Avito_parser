import datetime
import os
import traceback
import typing

from aiogram import Bot
import httpx
from proxy_randomizer.providers import RegisteredProviders
from random_user_agent.user_agent import UserAgent
from random_user_agent.params import SoftwareName, OperatingSystem


_log_bot = None
_user_agents = None
_registered_providers = None


async def handle_exception(logger_name, additional_text=None):
    log_traceback = get_log_traceback(logger_name)
    if additional_text:
        log_traceback += '\n' + additional_text
    await send_error_log_async_to_telegram(log_traceback)


def get_log_traceback(logger_name):
    timezone_offset = datetime.timedelta(hours=3)  # Moscow
    time = datetime.datetime.utcnow() + timezone_offset
    tb = traceback.format_exc()
    exception_text = f'{time} - {logger_name} - ERROR\n{tb}'
    return exception_text


async def send_error_log_async_to_telegram(text):
    chat_id = os.environ.get('TG_LOG_CHAT_ID')
    message_max_length = 4096

    logger_bot = get_logger_bot()
    if len(text) <= message_max_length:
        await logger_bot.send_message(chat_id, text)
        return

    parts = split_text_on_parts(text, message_max_length)
    for part in parts:
        await logger_bot.send_message(chat_id, part)


def split_text_on_parts(text, message_max_length):
    parts = []
    while text:
        if len(text) <= message_max_length:
            parts.append(text)
            break
        part = text[:message_max_length]
        first_lnbr = part.rfind('\n')
        if first_lnbr != -1:
            parts.append(part[:first_lnbr])
            text = text[first_lnbr+1:]
        else:
            parts.append(part)
            text = text[message_max_length:]
    return parts


def get_logger_bot():
    global _log_bot
    if not _log_bot:
        tg_bot_token = os.environ.get('TG_LOG_BOT_TOKEN')
        proxy = os.environ.get('TG_PROXY')
        _log_bot = Bot(token=tg_bot_token, proxy=proxy)
    return _log_bot


def get_user_agent_header(limit=300):
    """Get random user agent header."""

    global _user_agents
    if not _user_agents:
        software_names = [SoftwareName.CHROME.value, SoftwareName.FIREFOX.value]
        operating_systems = [OperatingSystem.LINUX.value]
        _user_agents = UserAgent(software_names=software_names,
                                 operating_systems=operating_systems, limit=limit)

    user_agent = _user_agents.get_random_user_agent()
    agent_header = {'UserAgent': user_agent}
    return agent_header


def get_random_proxy():
    """Get proxy from _registered_providers and remove anonymity and country info."""

    if not _registered_providers:
        parse_providers()
    return str(_registered_providers.get_random_proxy()).split(' ')[0]


def parse_providers():
    """Updates registered providers and parse proxies of them."""

    global _registered_providers
    _registered_providers = RegisteredProviders()
    _registered_providers.parse_providers()


async def make_get_request(url: str, headers: dict = None) -> typing.Optional[httpx.Response]:
    """Make async GET request with proxy."""

    if not headers:
        headers = dict()
    for _ in range(100):
        agent_header = get_user_agent_header()
        headers.update(agent_header)
        proxies = {'https://': f'http://{get_random_proxy()}'}
        async with httpx.AsyncClient(headers=headers,
                                     proxies=proxies,
                                     timeout=10) as client:
            try:
                response = await client.get(url, allow_redirects=False)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                    httpx.ReadError, httpx.RemoteProtocolError, httpx.ProxyError):
                continue

            response.raise_for_status()
            return response
    return None
