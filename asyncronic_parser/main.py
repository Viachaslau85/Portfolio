from bs4 import BeautifulSoup
import re
import pandas as pd
from random import choice
import time
import asyncio
import aiohttp


brands = set()

name = list()
brand_list = list()
price_list = list()
article_list = list()
photo_list = list()
status_list = list()

sem = asyncio.Semaphore(1000)


async def get_brands_set(session, url='https://interlamp.by/svetilniki'):
    headers = await get_random_headers()

    proxy = await get_random_proxy()

    response = await session.get(url=url, headers=headers, timeout=10000, proxy=proxy)

    response_text = await asyncio.shield(response.text())

    soup = BeautifulSoup(response_text, 'lxml')

    brands_list = soup.find_all('span')  # get list of all brands on web-site

    for i_brands in brands_list:
        if re.search('[A-Za-z]+', i_brands.get_text()):
            brands.add(i_brands.get_text())
    brands.add('Larte Luce')
    brands.add('F-promo')
    brands.add('ST Luce')


async def get_random_headers():
    desktop_agents = ('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/94.0.4606.85 YaBrowser/21.11.4.730 Yowser/2.5 Safari/537.36',
                      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) '
                      'Version/15.5 Safari/605.1.15',
                      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/102.0.0.0 Safari/537.36',
                      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/102.0.0.0 Safari/537.36',
                      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/103.0.5060.53 Safari/537.36 Edg/103.0.1264.37')

    headers = {'User-Agent': choice(desktop_agents),
               'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,'
                         'image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
               'accept-language': 'ru-RU,ru;q=0.9'}

    return headers


async def get_random_proxy():
    proxies = ('http://login:password@proxy-server:port_for_HTTP',
               'http://login:password@proxy-server:port_for_HTTP', 
               'http://login:password@proxy-server:port_for_HTTP',
               'http://login:password@proxy-server:port_for_HTTP',
               'http://login:password@proxy-server:port_for_HTTP',
               'http://login:password@proxy-server:port_for_HTTP',
               'http://login:password@proxy-server:port_for_HTTP'
               )

    random_proxy = choice(proxies)

    return random_proxy


async def get_total_pages(session, url='https://interlamp.by/svetilniki'):
    headers = await get_random_headers()
    proxy = await get_random_proxy()

    try:
        response = await session.get(url=url,
                                     headers=headers,
                                     timeout=10000,
                                     proxy=proxy)

        soup = BeautifulSoup(await response.text(), 'lxml')

        total_pages = int(soup.select_one('#page > div.row.row-small > div.col-lg-9.col-lg-4ths > ul > li:nth-child(9) '
                                          '> a').text)  # get total quantity of pages on catalog of interior light

        return total_pages

    except asyncio.TimeoutError:
        with open('errors.txt', 'a') as log_file:
            log_file.write('Failed to get the total number of pages in the directory\n')


async def get_total_pages_outdoor(session, url='https://interlamp.by/ulichnye-svetilniki'):
    headers = await get_random_headers()
    proxy = await get_random_proxy()

    try:
        response = await session.get(url=url,
                                     headers=headers,
                                     timeout=10000,
                                     proxy=proxy)

        soup = BeautifulSoup(await response.text(), 'lxml')

        total_pages = int(soup.select_one('#page > div.row.row-small > div.col-lg-9.col-lg-4ths > ul > li:nth-child(9) '
                                          '> a').text)  # get total quantity of pages on catalog of outdoor light

        return total_pages

    except asyncio.TimeoutError:
        with open('errors.txt', 'a') as log_file:
            log_file.write('Failed to get the total number of pages in the directory\n')


async def get_catalogs_pages(total_pages, total_pages_outdoor):
    pages = set()

    for i_page in range(1, total_pages + 1):

        if i_page == 1:
            url = 'https://interlamp.by/svetilniki'

            pages.add(url)

        else:
            url = 'https://interlamp.by/svetilniki?page={page_number}'.format(page_number=i_page)

            pages.add(url)

    for i_page in range(1, total_pages_outdoor + 1):

        if i_page == 1:
            url = 'https://interlamp.by/ulichnye-svetilniki'

            pages.add(url)

        else:
            url = 'https://interlamp.by/ulichnye-svetilniki?page={page_number}'.format(page_number=i_page)

            pages.add(url)

    return pages


async def get_goods_pages(catalogs, session):
    try:
        goods_pages = set()

        for i_pages in catalogs:
            headers = await get_random_headers()

            proxy = await get_random_proxy()

            response = await session.get(url=i_pages, timeout=100000, headers=headers, proxy=proxy)

            soup = BeautifulSoup(await response.text(), 'lxml')

            links = soup.find_all('div', class_='title')

            for i_thing in links:  # get list of links for good`s cards with regex
                if len(i_thing.find_all('a', {'href': re.compile(r'^(https:)+')})) > 0:
                    i_links = i_thing.find_all('a', {'href': re.compile(r'^(https:)+')})

                    goods_link = i_links[0]['href']

                    goods_pages.add(goods_link)

                    print('[INFO] Added {quantity} pages'.format(quantity=len(goods_pages)))

        return goods_pages

    except TypeError as e:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} {e}' + '\n')

        pass

    except asyncio.TimeoutError as e:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} {e}' + '\n')

        pass

    except aiohttp.ClientOSError as e:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} {e}' + '\n')

        pass

    except ConnectionResetError as e:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} {e}' + '\n')

        pass


async def get_goods_brand(goods_name):
    for i_brands in brands:  # check brand in name of good
        if i_brands in goods_name:
            brand = i_brands
            break
    else:
        brand = 'No brand'

    brand_list.append(brand)


async def get_goods_price(soup_object, url):
    # noinspection PyBroadException
    try:
        price = soup_object.find('div', class_='price').get_text().strip()
    except Exception:
        with open('errors.txt', 'a') as log:
            log.write(f'On page {url} price not found' + '\n')
            price_list.append('No price')
    else:
        price_clear = re.sub('( р.)+', '', price)
        price_list.append(price_clear)


async def get_goods_article(soup_object, url):
    # noinspection PyBroadException
    try:
        article = soup_object.select_one('#product_image > div.sku').get_text().strip().split()[2]

    except Exception:
        with open('errors.txt', 'a') as log:
            log.write(f'On page {url} article not found' + '\n')
            article_list.append('No article')
    else:
        article_list.append(article)


async def get_goods_photo(soup_object, url):
    # noinspection PyBroadException
    try:
        photo_url = soup_object.select_one('#product_image > a > img').attrs['src']

    except Exception:
        with open('errors.txt', 'a') as log:
            log.write(f'On page {url} URL of photo not found' + '\n')
            photo_list.append('No URL of photo')

    else:
        photo_list.append(photo_url)


async def get_goods_status(soup_object, url):
    # noinspection PyBroadException
    try:
        status = soup_object.select_one('#product_info > div.inner > div.info_top > div > div').get_text().strip()

    except Exception:
        with open('errors.txt', 'a') as log:
            log.write(f'On page {url} status not found' + '\n')
            status_list.append('No status')

    else:
        status_list.append(status)


async def get_goods_data(index, url, session):
    try:
        headers = await get_random_headers()

        proxy = await get_random_proxy()

        response = await session.get(url=url, timeout=100000, headers=headers, proxy=proxy)

        response_text = await asyncio.shield(response.text())

        b_soup = BeautifulSoup(response_text, 'lxml')

        title = b_soup.select_one('#product_page_top > h1')

        if not title:
            with open('errors.txt', 'a') as log:
                log.write(f'On page {url} title not found' + '\n')
        else:
            clear_title = title.get_text()
            name.append(clear_title)

            # in last version 09/07/2022 in time 14:23

            tasks = [get_goods_brand(clear_title),
                     get_goods_price(b_soup, url),
                     get_goods_article(b_soup, url),
                     get_goods_photo(b_soup, url),
                     get_goods_status(b_soup, url)
                     ]

            await asyncio.gather(*tasks)

            print(f'[INFO] {time.strftime("%H:%M:%S", time.localtime())} Task number {index}: last URl is {url} '
                  f'with proxy: {proxy}\nQuantity of processed tasks - {len(name)}\nfunction: get_goods_data\n')

    except asyncio.TimeoutError as e:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())}  on page {url} is {e}' + '\n')

        pass

    except aiohttp.ClientOSError as e:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} on page {url} is {e}' + '\n')

        pass


async def make_file_excel(name_lst: list, price: list, article: list, photo: list, status: list, brand: list):
    await asyncio.sleep(0)
    print(f'[INFO] {time.strftime("%H:%M:%S", time.localtime())} Function for create DataFrame is started')

    df = pd.DataFrame({'Наименование элемента': name_lst,
                       'Цена "Розничная цена"': price,
                       'Бренд': brand,
                       'Артикул [CML2_ARTICLE]': article,
                       'Ссылки на фото': photo,
                       'Статус': status})

    print(f'[INFO] {time.strftime("%H:%M:%S", time.localtime())} DataFrame is created')

    df.to_excel('./interlamp.xlsx', sheet_name='Изменение цен', index=False)

    print(f'[INFO] {time.strftime("%H:%M:%S", time.localtime())} End all')


async def main():
    try:
        conn = aiohttp.TCPConnector(limit_per_host=3, limit=30)
        async with aiohttp.ClientSession(timeout=10000, connector=conn) as session:

            await get_brands_set(session=session)

            tasks = set()

            last_page = await get_total_pages(session=session)

            last_page_outdoor = await get_total_pages_outdoor(session=session)

            pages = await get_catalogs_pages(total_pages=last_page, total_pages_outdoor=last_page_outdoor)

            goods_pages = await get_goods_pages(catalogs=pages, session=session)

            for i_index, i_pages in enumerate(goods_pages):

                task = asyncio.create_task(get_goods_data(index=i_index, url=i_pages, session=session))

                tasks.add(task)

                print('[INFO] Added {tasks_remains} from {quantity} tasks'.format(quantity=len(goods_pages),
                                                                                  tasks_remains=len(tasks)
                                                                                  )
                      )

            await asyncio.gather(*tasks)

        await make_file_excel(name, price_list, article_list, photo_list, status_list, brand_list)

    except asyncio.TimeoutError as error:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} is {error} on function gather_data' + '\n')

        pass

    except aiohttp.ClientHttpProxyError as error:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} is {error} on function gather_data' + '\n')

        pass

    except aiohttp.ClientOSError as e:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} {e}' + '\n')

        pass

    except aiohttp.ServerDisconnectedError as error:
        with open('system_log.txt', 'a') as system_log:
            system_log.write(f'{time.strftime("%H:%M:%S", time.localtime())} is {error} on function gather_data' + '\n')

        pass


if __name__ == '__main__':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
