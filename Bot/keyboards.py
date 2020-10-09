from aiogram.types import InlineKeyboardButton


admin_panel = InlineKeyboardButton('Панель админки', callback_data='admin_panel')

db = InlineKeyboardButton('База данных', callback_data='db')

exit_admin = InlineKeyboardButton('Выход из админки', callback_data='exit_admin')

users = InlineKeyboardButton('Пользователи', callback_data='users')


def get_pagination_button(direction: str, callback_data: str) -> InlineKeyboardButton:
    """Get pagination button.

    Args:
        direction: paginator direction, choices = ['next', 'previous'].
        callback_data: button callback data.

    Returns:
        button: inline keyboard button with callback_data.
    """
    if direction not in ('next', 'previous'):
        raise KeyError('Direction argument must be one of (\'next\', \'previous\')')

    text = '→' if direction == 'next' else '←'
    return InlineKeyboardButton(text, callback_data=callback_data)
