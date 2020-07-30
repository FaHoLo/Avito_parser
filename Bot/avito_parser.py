import logging
import os
from pprint import pprint

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests

import db_aps


avito_logger = logging.getLogger('avito-logger')


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


def parse_avito_products_update(url) -> list:
    '''Parse avito url and find new and updated products'''
    avito_page = get_avito_soup_page(url)
    products = collect_products(avito_page)
    product_infos = parse_product_infos(products)
    return db_aps.find_new_and_updated_products(product_infos)


def get_avito_soup_page(url: str) -> BeautifulSoup:
    '''Get website (avito) response and parse with BS4'''
    response = requests.get(url)
    try:
        response.raise_for_status()
    except Exception:
        avito_logger.error(Exception)

    avito_logger.debug('Got 200 response from avito')
    return BeautifulSoup(response.text, 'lxml')


def collect_products(page: BeautifulSoup) -> list:
    '''Collect products from page and remove offers from other cities'''
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


def parse_product_infos(products: list) -> list:
    '''
    Parse info about products -> list of dicts

    dict keys: id, title, price, img_url, product_url, pub_date
    '''
    product_infos = []
    for product in products:
        product_info = {
            'id': product['data-item-id'],
            'title': product.select_one('.snippet-link')['title'],
            'price': product.select_one('.snippet-price').text.strip(),
            'img_url': product.select_one('img')['src'],
            'product_url': 'https://www.avito.ru{}'.format(
                product.select_one('.snippet-link')['href']
            ),
            'pub_date': product.select_one('.snippet-date-info')['data-tooltip'],
        }
        product_infos.append(product_info)
    return product_infos


if __name__ == '__main__':
    main()
