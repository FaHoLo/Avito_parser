from asyncio import sleep
from logging import getLogger
import os
from random import randint
from typing import Tuple

import redis

import utils


db_logger = getLogger('db_logger')

_database = None

DB_PRODUCT_PREFIX = 'avito:product_info:'
DB_SEARCH_PREFIX = 'avito:user_search:'
PRODUCT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'ru,en-US;q=0.7,en;q=0.3',
    # 'Cache-Control': 'max-age=0',
    # 'DNT': '1',
    # 'Host': 'www.avito.ru',
    # 'TE': 'Trailers',
    # 'Upgrade-Insecure-Requests': '1',
    # 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) Gecko/20100101 Firefox/79.0',
}  # Сommented headers are left for possible request checks


def get_database_connection() -> redis.Redis:
    """Get or create Redis db connection."""
    global _database
    if _database is None:
        database_password = os.getenv('DB_PASSWORD')
        database_host = os.getenv('DB_HOST')
        database_port = os.getenv('DB_PORT')
        _database = redis.Redis(host=database_host, port=database_port, password=database_password)
        db_logger.debug('Got new db connection')
    return _database


def find_new_and_updated_products(product_infos: list, user_id) -> Tuple[list, list]:
    """Find new and updated products."""
    db = get_database_connection()
    new_products = []
    updated_products = []
    for product in product_infos:
        db_product = db.hgetall(f'{DB_PRODUCT_PREFIX}{user_id}:{product["product_id"]}')
        if not db_product:
            new_products.append(product)
            continue
        if product['price'] != db_product[b'price'].decode('utf-8'):
            updated_products.append(product)
    db_logger.debug(f'Found {len(new_products)} new and {len(updated_products)} products')
    return new_products, updated_products


def store_watched_product_info(product_info: dict, user_id: str, search_url: str) -> None:
    """Store product into redis db."""
    db = get_database_connection()
    product_key = f'{DB_PRODUCT_PREFIX}{user_id}:{product_info["product_id"]}'
    db.hmset(
        product_key,
        {
            'product_id': product_info['product_id'],
            'product_url': product_info['product_url'],
            'title': product_info['title'],
            'price':  product_info['price'],
            'search_url': search_url,
        }
    )
    db_logger.debug(f'Stored {product_key}')


def collect_searches() -> dict:
    """Collect all existing searches from db."""
    db = get_database_connection()
    search_pattern = f'{DB_SEARCH_PREFIX}*'
    # All scan methods returns cursor position and then list of keys: (0, [key1, key2])
    search_keys = db.scan(0, match=search_pattern, count=10000)[1]
    search_keys = [key.decode('utf-8') for key in search_keys]
    searches = {}
    for key in search_keys:
        user_id = key.split(':')[-1]
        user_searches = [search_url.decode('utf-8') for search_url in db.hvals(key)]
        searches[user_id] = user_searches
    db_logger.debug(f'Collected {len(searches)} searches')
    return searches


async def start_expired_products_collector(sleep_time: int = 43200):
    """Runs collector witch remove expired products from db."""
    while True:
        db_logger.debug('Starting new cycle stage of expired products collector')
        utils.parse_providers()
        try:
            await find_expired_products()
        except Exception:
            await utils.handle_exception('expired_products_logger')
        db_logger.debug(f'Expired products collector starts sleeping for {sleep_time} sec')
        await sleep(sleep_time)


async def find_expired_products() -> None:
    """Find and remove expired products from db."""
    db = get_database_connection()
    products_pattern = f'{DB_PRODUCT_PREFIX}*'
    product_keys = db.scan(0, match=products_pattern, count=1000)[1]
    expired_keys = []
    for key in product_keys:
        try:
            if await _is_expired(key):
                expired_keys.append(key)
        except Exception:
            await utils.handle_exception('expired_products_logger')
            continue
        await sleep(randint(10, 20))

    if expired_keys:
        db.delete(*expired_keys)
    db_logger.debug(f'Deleted {len(expired_keys)} expired keys from db')


async def _is_expired(product_key: str) -> bool:
    """Get product page and check for expiration selectors in it."""
    db = get_database_connection()
    expiration_selectors = ['item-closed-warning', 'item-view-warning-content']
    product_url = db.hget(product_key, 'product_url').decode('utf-8')
    response = await utils.make_get_request(product_url, headers=PRODUCT_HEADERS)
    if not response:
        return False
    db_logger.debug(f'Got response status code {response.status_code}')
    if response.status_code == 301:
        return True
    for selector in expiration_selectors:
        if response.text.find(selector) != -1:
            return True
            db_logger.debug('Found expiration selector')
    return False


def add_new_search(user_id: str, url: str):
    """Add new search url to user's search hash."""
    db = get_database_connection()
    db_key = f'{DB_SEARCH_PREFIX}{user_id}'
    existing_searches = db.hvals(db_key)
    if not existing_searches:
        search_number = 1
    else:
        search_number = len(existing_searches) + 1
    db.hmset(db_key, {search_number: url})
    db_logger.debug(f'Added new search {db_key}')


def get_user_existing_searches(user_id: str):
    """Get user's existing searches."""
    db = get_database_connection()
    db_key = f'{DB_SEARCH_PREFIX}{user_id}'
    existing_searches = db.hgetall(db_key)
    if not existing_searches:
        return
    existing_searches = {
        search_number.decode('utf-8'): search_url.decode('utf-8')
        for search_number, search_url in existing_searches.items()
    }
    db_logger.debug(f'Got {len(existing_searches)} existing seraches of user {user_id}')
    return existing_searches


def remove_search(user_id: str, search_number: str):
    """Remove search, its products and update remaining searches hash keys."""
    remove_products_by_search_number(user_id, search_number)
    db = get_database_connection()
    db_key = f'{DB_SEARCH_PREFIX}{user_id}'
    db.hdel(db_key, search_number)
    remaining_searches = db.hvals(db_key)
    if remaining_searches:
        updated_searches = {
            search_number+1: search_url
            for search_number, search_url in enumerate(remaining_searches)
        }
        db.delete(db_key)
        db.hmset(db_key, updated_searches)
    db_logger.debug(f'Removed {search_number}\'th search of {user_id} user')
    return 'Поиск удален'


def remove_products_by_search_number(user_id: str, search_number: str):
    """Remove products of search."""
    db = get_database_connection()
    search_url = db.hget(f'{DB_SEARCH_PREFIX}{user_id}', search_number)
    products_pattern = f'{DB_PRODUCT_PREFIX}{user_id}:*'
    user_product_keys = db.scan(0, match=products_pattern, count=1000)[1]
    keys_for_deletion = []
    for key in user_product_keys:
        if db.hget(key, 'search_url') == search_url:
            keys_for_deletion.append(key)

    db.delete(*keys_for_deletion)
    db_logger.debug(f'Removed products for search {search_number} of user {user_id}')
