import datetime
import os
import traceback

from aiogram import Bot


_log_bot = None


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
