import logging
import os
import typing

import redis
import requests


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
        db_product = db.hgetall('avito:product_info:{}'.format(product['id']))
        if not db_product:
            new_products.append(product)
            continue
        if product['price'] != db_product[b'price'].decode('utf-8'):
            updated_products.append(product)
    return new_products, updated_products


def store_watched_product_info(product_info: dict) -> None:
    '''Store product into redis db'''
    db = get_database_connection()
    db.hmset(product_info['id'], product_info)


def find_expired_products() -> None:
    '''Find expired products in db'''
    db = get_database_connection()

    existing_keys = db.keys()
    product_keys = []
    for key in existing_keys:
        if b'avito:product_info:' in key:
            product_keys.append(key)

    expired_keys = []
    for key in product_keys:
        if _is_expired(key):
            expired_keys.append(key)
    if expired_keys:
        db.delete(*expired_keys)


def _is_expired(key: str) -> typing.Optional[bool]:
    '''Get product page and check for expiration selectors in it'''
    db = get_database_connection()
    expired_selectors = ['item-closed-warning', 'item-view-warning-content']
    product_url = db.hgetall(key)[b'product_url'].decode('utf-8')
    response = requests.get(product_url)
    response.raise_for_status()
    text = response.text
    for selector in expired_selectors:
        if text.find(selector) != -1:
            return True
