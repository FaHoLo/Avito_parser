from logging import getLogger
import os
from textwrap import dedent

from aiogram import Bot, Dispatcher, executor, types  # noqa: F401
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.exceptions import BotBlocked
from dotenv import load_dotenv

import db_aps
import keyboards
import phrases
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


class AdminPanel(StatesGroup):
    """Show and work with admin panel."""
    waiting_admin_command = State()


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
    await message.answer(phrases.welcome)
    bot_logger.debug(f'Sent welcome message to {message.chat.id}')


@dispatcher.message_handler(state='*', commands=['help'])
async def send_help(message: types.Message, state: FSMContext):
    """Send help message."""
    current_state = await state.get_state()
    if current_state:
        await state.finish()

    await message.answer(phrases.help_text, disable_web_page_preview=True)
    bot_logger.debug(f'Sent help to {message.chat.id}')


@dispatcher.message_handler(state='*', commands=['cancel'])
async def cancel_handler(message: types.Message, state: FSMContext):
    """Cancel all states and send message about it."""
    current_state = await state.get_state()

    cancel_text = phrases.send_help
    if current_state == 'AddSearch:waiting_url':
        cancel_text = phrases.cancel_new_search
    elif current_state == 'DelSearch:waiting_search_number':
        cancel_text = phrases.cancel_del_search
    await message.answer(cancel_text, reply_markup=types.ReplyKeyboardRemove())

    if current_state is not None:
        await state.set_state(None)
    bot_logger.debug(f'Canceled state: {current_state}')


@dispatcher.message_handler(state='*', commands=['add_search'])
async def start_search_adding(message: types.Message):
    """Start search adding conversation."""
    not_paid_search_limit = 2

    if message.chat.id in db_aps.get_admins():
        await AddSearch.waiting_url.set()
        await message.answer(phrases.waiting_url, disable_web_page_preview=True)
        bot_logger.debug(f'Start adding new search for {message.chat.id}')
        return

    # TODO check for paid searches.
    # user_limit = get_user_search_limit(message.chat.id)
    # ... and len(exist) == user_limit
    # and change text new_search_not_allowed
    existing_searches = db_aps.get_user_existing_searches(message.chat.id)
    if existing_searches and len(existing_searches) == not_paid_search_limit:
        text = phrases.new_search_not_allowed.format(limit=not_paid_search_limit)
        debug_text = f'New search wasn\'t allowed to user {message.chat.id}. \
            He had {len(existing_searches)} active searches.'
    else:
        text = phrases.waiting_url
        debug_text = f'Start adding new search for {message.chat.id}'

    await AddSearch.waiting_url.set()
    await message.answer(text, disable_web_page_preview=True)
    bot_logger.debug(debug_text)


@dispatcher.message_handler(state=AddSearch.waiting_url)
async def add_search_url_to_db(message: types.Message, state: FSMContext):
    """Add new search url to db. Finish AddSearch state if success."""
    if not message.text.startswith('https://www.avito.ru/'):
        await message.answer(phrases.bad_url)
        bot_logger.debug(f'Got wrong url: {message.text} from {message.chat.id}')
        return

    existing_searches = db_aps.get_user_existing_searches(message.chat.id)
    if existing_searches and message.text in existing_searches.values():
        await message.answer(phrases.search_already_exists)
        bot_logger.debug(f'Got existing url: {message.text} from {message.chat.id}')
        return

    db_aps.add_new_search(user_id=message.chat.id, url=message.text)
    await state.finish()
    await message.answer(phrases.search_added)
    bot_logger.debug(f'New search url for {message.chat.id} added: {message.text}')


@dispatcher.message_handler(state='*', commands=['del_search'])
async def start_search_deletion(message: types.Message):
    """Start search deletion conversation."""
    exisiting_searches = db_aps.get_user_existing_searches(message.chat.id)
    if not exisiting_searches:
        await message.answer(phrases.no_searches_found)
        bot_logger.debug(f'Got delete request from user ({message.chat.id}) with no searches')
        return
    text = phrases.search_deletion
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for search_number, search_url in sorted(exisiting_searches.items()):
        text += dedent(f'''\
            {search_number}-й поиск:
            {search_url}\n
        ''')
        keyboard.insert(types.KeyboardButton(search_number))
    text += phrases.send_cancel
    await DelSearch.waiting_search_number.set()
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)
    bot_logger.debug(f'Start search deletion for {message.chat.id}')


@dispatcher.message_handler(state=DelSearch.waiting_search_number)
async def delete_search(message: types.Message, state: FSMContext):
    """Delete search from db. Finish DelSearch state if success."""
    try:
        search_number = int(message.text)
    except ValueError:
        await message.answer(phrases.not_number)
        bot_logger.debug(
            f'Got not int search number ({message.text}) for deletion from {message.chat.id}'
        )
        return

    if search_number > len(db_aps.get_user_existing_searches(message.chat.id)):
        await message.answer(phrases.wrong_number)
        bot_logger.debug(
            f'Got out of range deletion search number ({search_number}) from {message.chat.id}'
        )
        return

    db_aps.remove_search(user_id=message.chat.id, search_number=message.text)
    await state.finish()
    await message.answer(phrases.search_deleted, reply_markup=types.ReplyKeyboardRemove())
    bot_logger.debug(f'Search deleted for {message.chat.id}')


@dispatcher.message_handler(chat_id=db_aps.get_super_admin(),
                            state='*', commands=['admin'])
async def show_admin_panel(message: types.Message):
    """Show admin panel to super admin only."""
    keyboard = keyboards.collect_admin_panel_keyboard()
    await AdminPanel.waiting_admin_command.set()
    await message.answer(phrases.admin_panel, reply_markup=keyboard)


@dispatcher.callback_query_handler(
    lambda callback: callback.data == keyboards.exit_admin.callback_data,
    chat_id=db_aps.get_super_admin(),
    state=AdminPanel.waiting_admin_command)
async def handle_admin_exit(callback: types.CallbackQuery, state: FSMContext):
    """Handle admin panel exit."""
    await state.finish()
    await callback.answer(phrases.exit_admin)
    await callback.message.delete()


@dispatcher.callback_query_handler(
    lambda callback: callback.data == keyboards.db.callback_data,
    chat_id=db_aps.get_super_admin(),
    state=AdminPanel.waiting_admin_command)
async def handle_admin_db_info(callback: types.CallbackQuery):
    """Handle admin panel db command and show db info."""
    db_info = db_aps.get_useful_db_info()
    text = ''
    for key, value in db_info.items():
        text += f'{key}: {value}\n'

    text = '```\n' + text + '```'

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(keyboards.admin_panel)
    keyboard.add(keyboards.exit_admin)

    await callback.answer(phrases.db_info)
    await callback.message.edit_text(text, reply_markup=keyboard,
                                     parse_mode=types.ParseMode.MARKDOWN_V2)


@dispatcher.callback_query_handler(
    lambda callback: callback.data == keyboards.admin_panel.callback_data,
    chat_id=db_aps.get_super_admin(),
    state=AdminPanel.waiting_admin_command)
async def handle_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    """Handle admin_panel command and show admin panel."""
    keyboard = keyboards.collect_admin_panel_keyboard()
    await callback.answer(phrases.admin_panel)
    await callback.message.edit_text(phrases.admin_panel, reply_markup=keyboard)


@dispatcher.callback_query_handler(
    lambda callback: keyboards.users.callback_data in callback.data,
    chat_id=db_aps.get_super_admin(),
    state=AdminPanel.waiting_admin_command)
async def handle_admin_users(callback: types.CallbackQuery):
    """Handle users command and show users list with paginationg."""
    # TODO start timer for keyboard deletion and state finish | celery?
    users_callback = keyboards.users.callback_data
    users_on_page = 10

    if callback.data == users_callback:
        page = 0
    else:
        # cb.data == users:1, where 1 - is page (starts from 0)
        page = int(callback.data[len(users_callback):])
    first_user_number = page * users_on_page
    last_user_number = first_user_number + users_on_page

    user_ids = db_aps.get_users()
    users_amount = len(user_ids)
    text = phrases.users.format(amount=users_amount)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row_width = 2

    for user in user_ids[first_user_number:last_user_number]:
        chat_info = await bot.get_chat(user)
        keyboard.insert(types.InlineKeyboardButton(chat_info.username,
                                                   callback_data=f'user_id:{chat_info.id}'))

    if page != 0:
        keyboard.add(keyboards.get_pagination_button('previous', f'users:{page-1}'))
    if last_user_number < users_amount and page != 0:
        keyboard.insert(keyboards.get_pagination_button('next', f'users:{page-1}'))
    if last_user_number < users_amount and page == 0:
        keyboard.add(keyboards.get_pagination_button('next', f'users:{page-1}'))
    keyboard.add(keyboards.admin_panel)

    await callback.answer(phrases.users_page.format(page=page + 1))
    await callback.message.edit_text(text=text, reply_markup=keyboard)


@dispatcher.callback_query_handler(
    lambda callback: 'user_id' in callback.data,
    chat_id=db_aps.get_super_admin(),
    state=AdminPanel.waiting_admin_command)
async def handle_admin_user_id(callback: types.CallbackQuery):
    """Handle user_id command and show user info."""
    id_start_index = len('user_id') + 1  # data = user_id:123456
    user_id = int(callback.data[id_start_index:])
    try:
        chat_info = await bot.get_chat(user_id)
    except BotBlocked:
        await callback.answer('BotBlocked')
        return

    searches = db_aps.get_user_existing_searches(user_id)
    products_amount = db_aps.get_user_products_amount(user_id)

    text = phrases.user_info.format(
        id=chat_info.id, full_name=chat_info.full_name,
        username=chat_info.username, searches_amount=len(searches),
        products_amount=products_amount)

    for search_number, search_url in searches.items():
        text += f'Поиск №{search_number}:\n' + f'{search_url}\n'

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row_width = 2
    keyboard.insert(keyboards.users)
    keyboard.insert(keyboards.admin_panel)
    keyboard.insert(keyboards.exit_admin)

    await callback.answer(phrases.user_info_answer.format(username=chat_info.username))
    await callback.message.edit_text(text=text, reply_markup=keyboard,
                                     disable_web_page_preview=True)
