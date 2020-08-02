from asyncio import sleep
import logging
import os
from random import randint
import typing

import redis
import requests


DB_PRODUCT_PREFIX = 'avito:product_info:'
db_logger = logging.getLogger('db_logger')
_database = None


def get_database_connection() -> redis.Redis:
    '''Get or create Redis db connection'''
    global _database
    if _database is None:
        database_password = os.getenv('DB_PASSWORD')
        database_host = os.getenv('DB_HOST')
        database_port = os.getenv('DB_PORT')
        _database = redis.Redis(host=database_host, port=database_port, password=database_password)
        db_logger.debug('Got new db connection')
    return _database


def find_new_and_updated_products(product_infos: list) -> list:
    '''Find new and updated products'''
    db = get_database_connection()
    new_products = []
    updated_products = []
    for product in product_infos:
        db_product = db.hgetall('{}{}'.format(DB_PRODUCT_PREFIX, product['product_id']))
        if not db_product:
            new_products.append(product)
            continue
        if product['price'] != db_product[b'price'].decode('utf-8'):
            updated_products.append(product)
    return new_products, updated_products


def store_watched_product_info(product_info: dict) -> None:
    '''Store product into redis db'''
    db = get_database_connection()
    db.hmset('{}{}'.format(DB_PRODUCT_PREFIX, product_info['product_id']), product_info)


def collect_searches() -> dict:
    '''Collect all existing searches from db'''
    db = get_database_connection()
    db_keys = [key.decode('utf-8') for key in db.keys()]
    search_keys = [key for key in db_keys if key.startswith(DB_SEARCH_PREFIX)]
    searches = {}
    for key in search_keys:
        user_id = key.split(':')[-1]
        user_searches = [search_url.decode('utf-8') for search_url in db.hvals(key)]
        searches[user_id] = user_searches
    return searches


async def run_expired_products_collector(sleep_time=43200):
    '''Runs collector witch remove expired products from db'''
    while True:
        await find_expired_products()
        await sleep(sleep_time)


async def find_expired_products() -> None:
    '''Find and remove expired products from db'''
    db = get_database_connection()
    existing_keys = db.keys()

    product_keys = [key for key in existing_keys if DB_PRODUCT_PREFIX.encode() in key]
    expired_keys = []
    for key in product_keys:
        if _is_expired(key):
            expired_keys.append(key)
        await sleep(randint(10, 20))

    if expired_keys:
        db.delete(*expired_keys)


def _is_expired(product_key: str) -> typing.Optional[bool]:
    '''Get product page and check for expiration selectors in it'''
    db = get_database_connection()
    expired_selectors = ['item-closed-warning', 'item-view-warning-content']
    product_url = db.hget(product_key, 'product_url').decode('utf-8')
    response = requests.get(product_url)
    response.raise_for_status()
    text = response.text
    for selector in expired_selectors:
        if text.find(selector) != -1:
            return True
