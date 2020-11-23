from asyncio import sleep
import logging
import os
from random import randint
from typing import Tuple, List

from aiogram import Bot
from bs4 import BeautifulSoup
from httpx import StreamError

import db_aps
import phrases
import utils


avito_parser_logger = logging.getLogger('avito_parser_logger')

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
DEFAULT_IMG = 'https://upload.wikimedia.org/wikipedia/commons/8/84/Avito_logo1.png'


async def start_parser(bot: Bot, sleep_time: int = 1800):
    """Start parser avito parser.

    Parser gets search queries from db,
    checks them for updates and send updates to users.
    """
    bot.loop.create_task(utils.run_proxi_updater())
    while True:
        avito_parser_logger.debug('Starting new parser cycle stage')
        searches = db_aps.collect_searches()
        for user_id, user_searches in searches.items():
            await check_user_searches(user_id, user_searches, bot)
        avito_parser_logger.debug(f'All searches checked, parser start sleeping for {sleep_time}')
        await sleep(sleep_time)


async def check_user_searches(user_id: str, user_searches: set, bot: Bot):
    """Check user's searches and send new and updated products to him."""
    for url in user_searches:
        try:
            new_products, updated_products = await parse_avito_products_update(url, user_id)
            await send_product_updates(bot, user_id, updated_products, url)
            await send_product_updates(bot, user_id, new_products, url, is_new_products=True)
            await sleep(randint(10, 20))
        except StreamError:
            avito_parser_logger.debug(f'Got StreamError for {url}')
            await sleep(randint(10, 20))
            continue
        except Exception:
            await utils.handle_exception('avito_parser_logger')


async def send_product_updates(bot: Bot, chat_id: str, product_infos: List[dict],
                               search_url: str, is_new_products: bool = False):
    """Send user's products updates to him."""
    msg_type = phrases.advert_updated
    if is_new_products:
        msg_type = phrases.new_advert

    for product in product_infos:
        message = phrases.advert_message.format(
            msg_type=msg_type, title=product['title'],
            price=product['price'], pub_date=product['pub_date'],
            url=product['product_url']
        )

        await bot.send_photo(chat_id, product['img_url'], caption=message)
        db_aps.store_watched_product_info(product, chat_id, search_url)
        avito_parser_logger.debug(f'Sent product update to {chat_id}')
        await sleep(0.3)


async def parse_avito_products_update(url: str, user_id: str) -> Tuple[list, list]:
    """Parse avito url and find new and updated products."""
    avito_page = await get_avito_soup_page(url)
    if not avito_page:
        raise StreamError('Failed to download search page.')
    products = collect_products(avito_page)
    product_infos = parse_product_infos(products)
    new_products, updated_products = db_aps.find_new_and_updated_products(product_infos, user_id)
    for products in (new_products, updated_products):
        for product in products:
            try:
                product['img_url'] = await get_product_image_url(product['product_url'])
            except Exception:  # Image parsing is now in debugging state
                product['img_url'] = DEFAULT_IMG
                await utils.handle_exception('avito_parser_logger', 'image_parse')
                continue
    avito_parser_logger.debug('Products update had been parsed')
    return new_products, updated_products


async def get_product_image_url(product_url: str) -> str:
    """Get product image url from product page."""
    response = await utils.make_get_request(product_url, headers=db_aps.PRODUCT_HEADERS)
    if not response:
        avito_parser_logger.debug('Failed to parse product image. Set default url')
        return DEFAULT_IMG

    page_data = BeautifulSoup(response.text, 'lxml')
    img_frame_selectors = ('.gallery-img-frame', '.image-frame-wrapper-2FMhm')
    try:
        for selector in img_frame_selectors:
            img_url = page_data.select_one(selector)
            if img_url:
                break
        img_url = str(img_url['data-url'])
    except TypeError:
        # Sometimes request fetch page with no product image,
        # so there is no gallery-img-frame in it.
        logger = utils.get_logger_bot()
        chat_id = os.environ.get('TG_LOG_CHAT_ID')
        text = f'into_image_parse: response.code: {response.status_code}\nurl: {product_url}'
        await utils.handle_exception('avito_parser_logger', text)
        try:
            await logger.send_document(chat_id, ('resp_text_page.html', response.text.encode()))
            await logger.send_document(chat_id, ('product_page.html', page_data.encode()))
        except Exception:
            utils.handle_exception('avito_parser_logger', 'into_image_parse')
        finally:
            return DEFAULT_IMG
    avito_parser_logger.debug(f'Got product image url: {img_url}')
    return img_url


async def get_avito_soup_page(url: str) -> BeautifulSoup:
    """Get website (avito) response and parse with BS4."""
    response = await utils.make_get_request(url, headers=SEARCH_HEADERS)
    if not response:
        avito_parser_logger.debug(f'Failed to get response from avito page: {url}')
        return

    avito_parser_logger.debug('Got 200 response from avito, soup page returned')
    return BeautifulSoup(response.text, 'lxml')


def collect_products(page: BeautifulSoup) -> list:
    """Collect products from page and remove offers from other cities."""
    products = page.select('.item_table')
    extra_blocks = page.select('.extra-block__title')
    if len(extra_blocks) > 1:  # Expected only one extra block
        avito_parser_logger.warning(f'Got {len(extra_blocks)} extra blocks')

    extra_products = 0
    for block in extra_blocks:
        products_count = block.select_one('.extra-block__count')
        if products_count:
            extra_products += int(products_count.text)

    if extra_products:
        products = products[:-extra_products]
    avito_parser_logger.debug(
        f'Collected {len(products)} products (removed {extra_products} extra products)'
    )
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
    avito_parser_logger.debug('Parsed product infos')
    return product_infos
