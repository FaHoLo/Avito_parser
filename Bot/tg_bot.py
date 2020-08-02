from asyncio import sleep
import logging
import os
from textwrap import dedent

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.dispatcher import FSMContext
from dotenv import load_dotenv

import avito_parser
import db_aps
import utils


load_dotenv()

bot_logger = logging.getLogger('avito_bot_logger')

# bot settings
proxy = os.environ.get('TG_PROXY')
bot = Bot(token=os.environ['TG_BOT_TOKEN'], proxy=proxy)
dispatcher = Dispatcher(
    bot=bot,
    storage=RedisStorage2(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        password=os.environ['DB_PASSWORD']
    ),
)


def main():
    sleep_time = 600
    dispatcher.loop.create_task(start_parser(sleep_time))
    executor.start_polling(dispatcher)


async def start_parser(sleep_time):
    url = os.environ['SEARCH_URL']
    while True:
        try:
            new_products, updated_products = avito_parser.parse_avito_products_update(url)
            await send_product_updates([updated_products[0]])
            await send_product_updates([new_products[0]], is_new_products=True)
        except Exception:
            utils.handle_exception('avito_parser_logger')
        await sleep(sleep_time)


async def send_product_updates(product_infos, is_new_products=False):
    chat_id = os.environ.get('TG_CHAT_ID')

    message_start = 'Объявление обновилось'
    if is_new_products:
        message_start = 'Появилось новое объявление'

    for product in product_infos:
        message = dedent(f'''\
        {message_start}
        {product['title']}
        Цена: {product['price']}
        Дата публикации: {product['pub_date']}\n
        Ссылка: {product['product_url']}
        ''')
        await bot.send_photo(chat_id, product['img_url'], caption=message)
        db_aps.store_watched_product_info(product)
    dispatcher.loop.create_task(avito_parser.start_parser(bot, parser_sleep_time))


@dispatcher.errors_handler()
async def errors_handler(update, exception):
    logger_name = 'avito_bot_logger'
    await utils.handle_exception(logger_name)
    return True


@dispatcher.message_handler(state='*', commands=['start'])
async def send_welcome(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.finish()
    text = 'Привет! Я бот, буду скидывать тебе объявления с Avito. Жми /help'
    await message.answer(text)


@dispatcher.message_handler(state='*', commands=['help'])
async def send_help(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.finish()
    text = dedent('Создай поиск и пришли мне ссылку на него. (Пока эта функция не работает)')
    await message.answer(text, disable_web_page_preview=True)

if __name__ == '__main__':
    main()
