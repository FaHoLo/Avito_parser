from asyncio import sleep
import json
from logging import getLogger
import os
from random import randint
from typing import Tuple, Union, Optional

import redis

import utils


db_logger = getLogger('db_logger')

_database = None

DB_PRODUCT_PREFIX = 'avito:product_info:'
DB_SEARCH_PREFIX = 'avito:user_search:'
DB_LAUNCHED_SEARCHES = 'avito:launched_searches'
PRODUCT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'ru,en-US;q=0.7,en;q=0.3',
    # 'Cache-Control': 'max-age=0',
    # 'DNT': '1',
    # 'Host': 'www.avito.ru',
    # 'TE': 'Trailers',
    # 'Upgrade-Insecure-Requests': '1',
    # 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) Gecko/20100101 Firefox/79.0'
}  # Сommented headers are left for possible request checks


def get_database_connection() -> redis.Redis:
    """Get or create Redis db connection."""
    global _database
    if _database is None:
        database_password = os.getenv('DB_PASSWORD')
        database_host = os.getenv('DB_HOST')
        database_port = os.getenv('DB_PORT')
        _database = redis.Redis(host=database_host, port=database_port,  # type: ignore
                                password=database_password)
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
    db_logger.debug(f'Found {len(new_products)} new and {len(updated_products)} updated products')
    return new_products, updated_products


def store_watched_product_info(product_info: dict, user_id: str, search_url: str) -> None:
    """Store product into redis db."""
    db = get_database_connection()
    product_key = f'{DB_PRODUCT_PREFIX}{user_id}:{product_info["product_id"]}'
    # TODO check, if all product ads expires every month? even after edits?
    # If they do, we can set "expires" value to db product entry and help
    # expired products collector (he then can check, if product expires soon
    # and not handle it)
    db.hmset(
        product_key,
        {
            'product_id': product_info['product_id'],
            'product_url': product_info['product_url'],
            'title': product_info['title'],
            'price': product_info['price'],
            'search_url': search_url,
        }
    )
    db_logger.debug(f'Stored {product_key}')


def collect_searches() -> dict:
    """Collect all existing searches from db."""
    db = get_database_connection()
    search_pattern = f'{DB_SEARCH_PREFIX}*'
    search_keys = db.keys(pattern=search_pattern)
    search_keys = [key.decode('utf-8') for key in search_keys]
    search_keys = remove_banned_users(search_keys)
    searches = {}
    for key in search_keys:
        user_id = key.split(':')[-1]
        user_searches = {search_url.decode('utf-8') for search_url in db.hvals(key)}
        searches[user_id] = user_searches
    db_logger.debug(f'Collected {len(searches)} searches')
    return searches


def remove_banned_users(search_keys: list) -> list:
    """Remove banned users from search keys."""
    banned_users = os.environ.get('BAN_LIST')
    if not banned_users:
        return search_keys
    else:
        banned_users = banned_users.split(',')  # type: ignore

    for key in search_keys.copy():
        if key in banned_users:
            search_keys.remove(key)
    return search_keys


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
    product_keys = db.keys(pattern=products_pattern)
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
    if response.status_code in (301, 302):
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


def get_user_existing_searches(user_id: Union[str, int]):
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
    remove_launched_search(user_id, search_url.decode('utf-8'))
    products_pattern = f'{DB_PRODUCT_PREFIX}{user_id}:*'
    user_product_keys = db.keys(pattern=products_pattern)
    keys_for_deletion = []
    for key in user_product_keys:
        if db.hget(key, 'search_url') == search_url:
            keys_for_deletion.append(key)

    if not keys_for_deletion:
        db_logger.debug(f'Removed 0 products for search {search_number} of user {user_id}')
        return
    db.delete(*keys_for_deletion)
    db_logger.debug(f'Removed products for search {search_number} of user {user_id}')


def get_admins() -> Tuple[int, ...]:
    """Get admins from db."""
    db = get_database_connection()
    admins = [int(admin_id) for admin_id in db.lrange('avito:admin_list', 0, -1)]
    return tuple(admins)


def get_super_admin() -> int:
    """Get super admin id."""
    db = get_database_connection()
    return int(db.get('avito:superadmin'))


def get_useful_db_info():
    """Collect useful info about db."""
    db = get_database_connection()
    db_info = db.info()

    input_MB = round(db_info['total_net_input_bytes']/1048576, 2)
    output_MB = round(db_info['total_net_output_bytes']/1048576, 2)
    usefull_info = {
        'connected_clients': db_info['connected_clients'],
        'connected_slaves': db_info['connected_slaves'],
        'db0_keys_amount': db_info['db0']['keys'],
        'keyspace_hits': db_info['keyspace_hits'],
        'commands_processed': db_info['total_commands_processed'],
        'connections_received': db_info['total_connections_received'],
        'total_net_input_MB': f'{input_MB} MB',
        'total_net_output_MB': f'{output_MB} MB',
        'uptime_in_days': db_info['uptime_in_days'],
        'used_memory_human': db_info['used_memory_human'].replace('M', ' MB'),
        'used_memory_peak_human': db_info['used_memory_peak_human'].replace('M', ' MB'),
    }
    return usefull_info


def get_users() -> Tuple[int, ...]:
    """Count user ids in db."""
    db = get_database_connection()
    user_searches = db.keys(pattern=f'{DB_SEARCH_PREFIX}*')
    user_ids = [
        int(user_search.decode('utf-8').lstrip(DB_SEARCH_PREFIX))
        for user_search in user_searches
    ]
    return tuple(user_ids)


def get_user_products_amount(user_id: Union[str, int]) -> int:
    """Count user product keys."""
    db = get_database_connection()
    product_keys = db.keys(pattern=f'{DB_PRODUCT_PREFIX}{user_id}:*')
    return len(product_keys)


def add_launched_search(user_id: str, search_url: str):
    """Add search url into launched searches.

    We store launched searches separately from active user's searches,
    so that we can launch coroutines of the search process
    for newly added searches.
    """
    db = get_database_connection()
    raw_launched_urls = db.hget(DB_LAUNCHED_SEARCHES, str(user_id))
    if raw_launched_urls:
        launched_urls = json.loads(raw_launched_urls)
        launched_urls.append(search_url)
    else:
        launched_urls = [search_url]
    db.hset(DB_LAUNCHED_SEARCHES, str(user_id), json.dumps(launched_urls))


def get_launched_searches() -> Optional[dict]:
    """Get all launched searches."""
    db = get_database_connection()
    raw_launched_searches = db.hgetall(DB_LAUNCHED_SEARCHES)

    launched_searches = {
        user_id.decode(): set(json.loads(search_urls))
        for user_id, search_urls in raw_launched_searches.items()
    }
    return launched_searches


def get_user_launched_searches(user_id: str) -> Optional[list]:
    """Get user launched searches."""
    db = get_database_connection()
    raw_searches = db.hget(DB_LAUNCHED_SEARCHES, user_id)
    if not raw_searches:
        return None
    return json.loads(raw_searches)


def remove_launched_search(user_id: str, search_url: str):
    """Remove search url from launched searches."""
    db = get_database_connection()
    raw_launched_urls = db.hget(DB_LAUNCHED_SEARCHES, user_id)
    if not raw_launched_urls:
        error_text = 'Tried to remove search url from empty user launched urls. ' + \
            f'User id is {user_id}, search url is {search_url}'
        db_logger.error(error_text)
        return
    launched_urls = json.loads(raw_launched_urls)
    launched_urls.remove(search_url)
    if not launched_urls:
        db.hdel(DB_LAUNCHED_SEARCHES, str(user_id))
        return
    db.hset(DB_LAUNCHED_SEARCHES, str(user_id), json.dumps(launched_urls))
