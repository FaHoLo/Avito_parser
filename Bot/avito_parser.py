from asyncio import sleep
import logging
import os
from pprint import pprint
from random import randint
from textwrap import dedent
from typing import Tuple, List

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests

import db_aps
import utils


avito_logger = logging.getLogger('avito-logger')
SEARCH_HEADERS = {
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'ru,en-US;q=0.7,en;q=0.3',
    'Connection': 'keep-alive',
    # 'Content-Length': '87',
    'Content-Type': 'text/plain;charset=UTF-8',
    # 'DNT': '1',
    # 'Host': 'socket.avito.ru',
    'Origin': 'https://www.avito.ru',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) Gecko/20100101 Firefox/79.0',
}



def main():
    load_dotenv()
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level='DEBUG'
    )
    url = os.getenv('SEARCH_URL')
    new_products, updated_products = parse_avito_products_update(url)
    print('New Products:')
    pprint(new_products)
    print('_'*40, '\nUpdated products:')
    pprint(updated_products)


async def start_parser(bot, sleep_time=1800):
    """Start parser avito parser.

    Parser gets search queries from db,
    checks them for updates and send updates to users.
    """
    while True:
        searches = db_aps.collect_searches()
        for user_id, user_searches in searches.items():
            await check_user_searches(user_id, user_searches, bot)
        await sleep(sleep_time)


async def check_user_searches(user_id, user_searches, bot):
    for url in user_searches:
        try:
            new_products, updated_products = await parse_avito_products_update(url, user_id)
            await send_product_updates(bot, user_id, updated_products, url)
            await send_product_updates(bot, user_id, new_products, url, is_new_products=True)
            await sleep(randint(10, 20))
        except Exception:
            await utils.handle_exception('avito_parser_logger')


async def send_product_updates(bot, chat_id, product_infos, search_url, is_new_products=False):
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
        db_aps.store_watched_product_info(product, chat_id, search_url)


async def parse_avito_products_update(url, user_id) -> Tuple[list, list]:
    """Parse avito url and find new and updated products."""
    avito_page = await get_avito_soup_page(url)
    products = collect_products(avito_page)
    product_infos = parse_product_infos(products)
    new_products, updated_products = db_aps.find_new_and_updated_products(product_infos, user_id)
    for product in new_products:
        try:
            product['img_url'] = await get_product_image_url(product['product_url'])
        except:
            await utils.handle_exception('avito_parser_logger', 'image_parse')
            continue
    for product in updated_products:
        try:
            product['img_url'] = await get_product_image_url(product['product_url'])
        except:
            await utils.handle_exception('avito_parser_logger', 'image_parse')
            continue
    return new_products, updated_products


async def get_product_image_url(product_url):
    response = await utils.make_get_request(product_url, headers=db_aps.PRODUCT_HEADERS)
    if not response:
        return
    img_url = 'https:{}'.format(
        BeautifulSoup(response.text, 'lxml').select_one('.gallery-img-frame')['data-url'])
    return img_url


async def get_avito_soup_page(url: str) -> BeautifulSoup:
    """Get website (avito) response and parse with BS4."""
    response = await utils.make_get_request(url, headers=SEARCH_HEADERS)
    if not response:
        return

    avito_logger.debug('Got 200 response from avito')
    return BeautifulSoup(response.text, 'lxml')


def collect_products(page: BeautifulSoup) -> list:
    """Collect products from page and remove offers from other cities."""
    products = page.select('.item_table')
    extra_blocks = page.select('.extra-block__title')
    if len(extra_blocks) > 1:  # Expected one extra block
        avito_logger.warning(f'Got {len(extra_blocks)} extra blocks')

    extra_products = 0
    for block in extra_blocks:
        products_count = block.select_one('.extra-block__count')
        if products_count:
            extra_products += int(products_count.text)

    if extra_products:
        products = products[:-extra_products]
    avito_logger.debug(f'Removed {extra_products} extra products. Got {len(products)} products')
    return products


def parse_product_infos(products: list) -> List[dict]:
    """Parse info about products.

    Dict keys: product_id, title, price, product_url, pub_date
    """
    product_infos = []
    for product in products:
        product_info = {
            'product_id': product['data-item-id'],
            'title': product.select_one('.snippet-link')['title'],
            'price': product.select_one('.snippet-price').text.strip(),
            'product_url': 'https://www.avito.ru{}'.format(
                product.select_one('.snippet-link')['href']
            ),
            'pub_date': product.select_one('.snippet-date-info')['data-tooltip'],
        }
        product_infos.append(product_info)
    return product_infos


if __name__ == '__main__':
    main()
