import logging
import os
from textwrap import dedent

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
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


class AddSearch(StatesGroup):
    waiting_url = State()


class DelSearch(StatesGroup):
    waiting_search_number = State()


def main():
    parser_sleep_time = 1800
    collector_sleep_time = 43200  # 12 hours
    dispatcher.loop.create_task(avito_parser.start_parser(bot, parser_sleep_time))
    dispatcher.loop.create_task(db_aps.start_expired_products_collector(collector_sleep_time))
    executor.start_polling(dispatcher)


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
    text = 'Привет! Я бот, буду скидывать тебе объявления с Avito.\nЖми /help'
    await message.answer(text)


@dispatcher.message_handler(state='*', commands=['help'])
async def send_help(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.finish()
    text = dedent('''\
    Чтобы создать поиск нажми: /add_search
    Удалить существующий: /del_search
    ''')
    await message.answer(text, disable_web_page_preview=True)


@dispatcher.message_handler(state='*', commands=['cancel'])
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()

    cancel_text = 'Отправь /help чтобы получить подсказку.'
    if current_state == 'AddSearch:waiting_url':
        cancel_text = f'Добавление нового поиска отменено.\n{cancel_text}'
    elif current_state == 'DelSearch:waiting_search_number':
        cancel_text = f'Выбор поиска для удаления отменен.\n{cancel_text}'
    await message.answer(cancel_text, reply_markup=types.ReplyKeyboardRemove())

    if current_state is not None:
        await state.set_state(None)


@dispatcher.message_handler(state='*', commands=['add_search'])
async def start_search_adding(message: types.Message):
    # TODO check for search number, set limit
    text = dedent('''\
    Ожидаю ссылку на поиск, пример:
    https://www.avito.ru/moskva_i_mo?q=bmv
    Отправь /cancel, чтобы отменить добавление нового поиска
    ''')
    await AddSearch.waiting_url.set()
    await message.answer(text, disable_web_page_preview=True)


@dispatcher.message_handler(state=AddSearch.waiting_url)
async def add_search_url_to_db(message: types.Message, state: FSMContext):
    if not message.text.startswith('https://www.avito.ru/'):
        await message.answer('Невереная ссылка, попробуй еще раз')
        return

    existing_searches = db_aps.get_user_existing_searches(message.chat.id)
    if existing_searches and message.text in existing_searches.values():
        await message.answer('Такой поиск уже запущен. Попробуй еще раз.')
        return

    db_aps.add_new_search(user_id=message.chat.id, url=message.text)
    await state.finish()
    await message.answer('Поиск добавлен')


@dispatcher.message_handler(state='*', commands=['del_search'])
async def start_search_deletion(message: types.Message):
    exisiting_searches = db_aps.get_user_existing_searches(message.chat.id)
    if not exisiting_searches:
        await message.answer('У вас нет запущенных поисков')
        return
    text = 'Вот список запущенных поисков.\nВыбери номер поиска, который хочешь удалить:\n\n'
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for search_number, search_url in exisiting_searches.items():
        text += dedent(f'''\
            {search_number}-й поиск:
            {search_url}\n
        ''')
        keyboard.insert(types.KeyboardButton(search_number))
    text += 'Отправь /cancel, чтобы отменить удаление поиска'
    await DelSearch.waiting_search_number.set()
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


@dispatcher.message_handler(state=DelSearch.waiting_search_number)
# @dispatcher.callback_query_handler(state=DelSearch.waiting_search_number)
async def delete_search(message: types.Message, state: FSMContext):
    try:
        search_number = int(message.text)
    except ValueError:
        await message.answer('Неверный запрос. Отправь номер поиска')
        return

    if search_number > len(db_aps.get_user_existing_searches(message.chat.id)):
        await message.answer('Поиска с таким номером не существует. Попробуй еще раз')
        return

    db_aps.remove_search(user_id=message.chat.id, search_number=message.text)
    await state.finish()
    await message.answer('Поиск удален', reply_markup=types.ReplyKeyboardRemove())


if __name__ == '__main__':
    main()
