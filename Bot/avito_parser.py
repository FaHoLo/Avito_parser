from asyncio import sleep
import logging
import os
from random import randint
from typing import List

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


async def start_parser(bot: Bot, sleep_time: int = 300):
    """Start parser avito parser.

    Parser gets search queries from db,
    checks them for updates and send updates to users.
    """
    bot.loop.create_task(utils.run_proxi_updater())
    launched_searches = db_aps.get_launched_searches()
    if launched_searches:
        for user_id, user_searches in launched_searches.items():
            for search in user_searches:
                bot.loop.create_task(check_user_search(user_id, search, bot))

    while True:
        avito_parser_logger.debug('Starting new parser cycle stage')
        all_searches = db_aps.collect_searches()
        launched_searches = db_aps.get_launched_searches()
        if not launched_searches:
            launched_searches = dict()
        for user_id, user_searches in all_searches.items():
            user_launched_searches = launched_searches.get(user_id, [])
            for user_search in user_searches:
                if user_search in user_launched_searches:
                    continue
                db_aps.add_launched_search(user_id, user_search)
                print(dir(bot.loop.create_task(check_user_search(user_id, user_search, bot))))
            await sleep(0)
        avito_parser_logger.debug(
            f'All new searches launched, parser start sleeping for {sleep_time}')
        await sleep(sleep_time)


async def check_user_search(user_id: str, search_url: str, bot: Bot):
    """Check user's search and notify him about new and updated products."""
    while True:
        launched_searches = db_aps.get_user_launched_searches(user_id)
        if not launched_searches:
            return
        if search_url not in launched_searches:
            return
        try:
            await parse_and_handle_avito_products_update(search_url, user_id, bot)
        except StreamError:
            avito_parser_logger.error(f'Got StreamError for {search_url}')
        except Exception:
            await utils.handle_exception('avito_parser_logger')
        await sleep(randint(1200, 2400))


async def parse_and_handle_avito_products_update(search_url: str, user_id: str,
                                                 bot: Bot):
    """Parse avito url, find new and updated products and send notify to user."""
    avito_page = await get_avito_soup_page(search_url)
    if not avito_page:
        raise StreamError('Failed to download search page.')
    products = collect_products(avito_page)
    product_infos = parse_product_infos(products)
    new_products, updated_products = db_aps.find_new_and_updated_products(product_infos, user_id)

    product_coros = []
    for product_info in new_products:
        task = bot.loop.create_task(parse_img_and_send_product_update(bot, user_id,
                                                                      product_info, search_url))
        product_coros.append(task)
    for product_info in updated_products:
        task = bot.loop.create_task(parse_img_and_send_product_update(bot, user_id, product_info,
                                                                      search_url, False))
        product_coros.append(task)

    while product_coros:
        await sleep(60)
        for coro in product_coros.copy():
            if coro.done():
                product_coros.remove(coro)
            sleep(0)
    avito_parser_logger.debug('Products update had been parsed')


async def parse_img_and_send_product_update(bot: Bot, user_id: str, product_info: dict,
                                            search_url: str, is_new_product: bool = True):
    """Get product image and send product info to user."""
    msg_type = phrases.advert_updated
    if is_new_product:
        msg_type = phrases.new_advert

    # TODO set product img url to db and check if it is already parsed
    try:
        product_info['img_url'] = await get_product_image_url(product_info['product_url'])
    except Exception:  # Image parsing is now in debugging state
        product_info['img_url'] = DEFAULT_IMG
        await utils.handle_exception('avito_parser_logger', 'image_parse')

    message = phrases.advert_message.format(
        msg_type=msg_type, title=product_info['title'],
        price=product_info['price'], pub_date=product_info['pub_date'],
        url=product_info['product_url']
    )

    await bot.send_photo(user_id, product_info['img_url'], caption=message)
    db_aps.store_watched_product_info(product_info, user_id, search_url)
    avito_parser_logger.debug(f'Sent all product updates to {user_id}')


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
