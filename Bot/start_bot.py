import logging
import os

from dotenv import load_dotenv

from avito_parser import start_parser
from db_aps import start_expired_products_collector
from tg_bot import bot, dispatcher, executor


avito_logger = logging.getLogger('avito_loger')


def main():
    load_dotenv()
    start_bot()


def start_bot():
    """Start parser, expired_collector and tg bot."""
    if os.getenv('DEBUG', 'False').lower() in ['true', 'yes', 'y', '1']:
        parser_sleep_time = 10
        collector_sleep_time = 20
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level='DEBUG'
        )
        avito_logger.debug('Starting avito parser in debug mode')
    else:
        parser_sleep_time = 300
        collector_sleep_time = 43200  # 12 hours
        avito_logger.debug('Starting normal avito parser')
    dispatcher.loop.create_task(start_parser(bot, parser_sleep_time))
    dispatcher.loop.create_task(start_expired_products_collector(collector_sleep_time))
    executor.start_polling(dispatcher)
    avito_logger.debug('Parser stopped working')


if __name__ == '__main__':
    main()
