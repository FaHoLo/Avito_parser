from logging import getLogger
import os
from textwrap import dedent

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from dotenv import load_dotenv

import db_aps
import utils


load_dotenv()

bot_logger = getLogger('avito_bot_logger')

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
    """Add search states group."""
    waiting_url = State()


class DelSearch(StatesGroup):
    """Delete search states group."""
    waiting_search_number = State()


@dispatcher.errors_handler()
async def errors_handler(update, exception) -> bool:
    """Aiogram errors handler."""
    logger_name = 'avito_bot_logger'
    await utils.handle_exception(logger_name)
    return True


@dispatcher.message_handler(state='*', commands=['start'])
async def send_welcome(message: types.Message, state: FSMContext):
    """Send welcome message."""
    current_state = await state.get_state()
    if current_state:
        await state.finish()
    text = 'Привет! Я бот, буду скидывать тебе объявления с Avito.\nЖми /help'
    await message.answer(text)
    bot_logger.debug(f'Sent welcome message to {message.chat.id}')


@dispatcher.message_handler(state='*', commands=['help'])
async def send_help(message: types.Message, state: FSMContext):
    """Send help message."""
    current_state = await state.get_state()
    if current_state:
        await state.finish()
    text = dedent('''\
    Чтобы создать поиск нажми: /add_search
    Удалить существующий: /del_search
    ''')
    await message.answer(text, disable_web_page_preview=True)
    bot_logger.debug(f'Sent help to {message.chat.id}')


@dispatcher.message_handler(state='*', commands=['cancel'])
async def cancel_handler(message: types.Message, state: FSMContext):
    """Cancel all states and send message about it."""
    current_state = await state.get_state()

    cancel_text = 'Отправь /help чтобы получить подсказку.'
    if current_state == 'AddSearch:waiting_url':
        cancel_text = f'Добавление нового поиска отменено.\n{cancel_text}'
    elif current_state == 'DelSearch:waiting_search_number':
        cancel_text = f'Выбор поиска для удаления отменен.\n{cancel_text}'
    await message.answer(cancel_text, reply_markup=types.ReplyKeyboardRemove())

    if current_state is not None:
        await state.set_state(None)
    bot_logger.debug(f'Canceled state: {current_state}')


@dispatcher.message_handler(state='*', commands=['add_search'])
async def start_search_adding(message: types.Message):
    """Start search adding conversation."""
    # TODO check for search number, set limit
    text = dedent('''\
    Ожидаю ссылку на поиск, пример:
    https://www.avito.ru/moskva_i_mo?q=bmv
    Отправь /cancel, чтобы отменить добавление нового поиска
    ''')
    await AddSearch.waiting_url.set()
    await message.answer(text, disable_web_page_preview=True)
    bot_logger.debug(f'Start adding new serach for {message.chat.id}')


@dispatcher.message_handler(state=AddSearch.waiting_url)
async def add_search_url_to_db(message: types.Message, state: FSMContext):
    """Add new search url to db. Finish AddSearch state if success."""
    if not message.text.startswith('https://www.avito.ru/'):
        await message.answer('Невереная ссылка, попробуй еще раз')
        bot_logger.debug(f'Got wrong url: {message.text} from {message.chat.id}')
        return

    existing_searches = db_aps.get_user_existing_searches(message.chat.id)
    if existing_searches and message.text in existing_searches.values():
        await message.answer('Такой поиск уже запущен. Попробуй еще раз.')
        bot_logger.debug(f'Got existing url: {message.text} from {message.chat.id}')
        return

    db_aps.add_new_search(user_id=message.chat.id, url=message.text)
    await state.finish()
    await message.answer('Поиск добавлен')
    bot_logger.debug(f'New search url for {message.chat.id} added: {message.text}')


@dispatcher.message_handler(state='*', commands=['del_search'])
async def start_search_deletion(message: types.Message):
    """Start search deletion conversation."""
    exisiting_searches = db_aps.get_user_existing_searches(message.chat.id)
    if not exisiting_searches:
        await message.answer('У вас нет запущенных поисков')
        bot_logger.debug(f'Got delete request from user ({message.chat.id}) with no searches')
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
    bot_logger.debug(f'Start search deletion for {message.chat.id}')


@dispatcher.message_handler(state=DelSearch.waiting_search_number)
async def delete_search(message: types.Message, state: FSMContext):
    """Delete search from db. Finish DelSearch state if success."""
    try:
        search_number = int(message.text)
    except ValueError:
        await message.answer('Неверный запрос. Отправь номер поиска')
        bot_logger.debug(
            f'Got not int search number ({message.text}) for deletion from {message.chat.id}'
        )
        return

    if search_number > len(db_aps.get_user_existing_searches(message.chat.id)):
        await message.answer('Поиска с таким номером не существует. Попробуй еще раз')
        bot_logger.debug(
            f'Got out of range deletion search number ({search_number}) from {message.chat.id}'
        )
        return

    db_aps.remove_search(user_id=message.chat.id, search_number=message.text)
    await state.finish()
    await message.answer('Поиск удален', reply_markup=types.ReplyKeyboardRemove())
    bot_logger.debug(f'Search deleted for {message.chat.id}')
