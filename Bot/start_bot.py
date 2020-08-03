from dotenv import load_dotenv

from avito_parser import start_parser
from db_aps import run_expired_products_collector
from tg_bot import bot, dispatcher, executor
from utils import handle_exception


def main():
    load_dotenv()
    start_bot()


def start_bot():
    parser_sleep_time = 1800
    collector_sleep_time = 43200  # 12 hours
    dispatcher.loop.create_task(start_parser(bot, parser_sleep_time))
    dispatcher.loop.create_task(run_expired_products_collector(collector_sleep_time))
    executor.start_polling(dispatcher)


if __name__ == '__main__':
    main()
