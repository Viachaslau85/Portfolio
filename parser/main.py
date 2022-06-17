import re
import requests
from requests import get
from bs4 import BeautifulSoup as bs
import pandas as pd
import os
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from time import sleep


def get_all_brands(brand_set: set):
    proxies = {'http': 'socks5h://viachaslau85:V6m1WyL@217.21.55.3:45786',
               'https': 'socks5h://viachaslau85:V6m1WyL@217.21.55.3:45786'}

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/94.0.4606.85 YaBrowser/21.11.4.730 Yowser/2.5 Safari/537.36'}
    request = get('https://interlamp.by/', proxies=proxies, timeout=None, headers=headers)
    soup = bs(request.content, 'lxml')
    brands = soup.find_all('span')
    for i in brands:
        if re.search('[A-Za-z0-9-]+$', i.get_text()):
            brand_set.add(i.get_text())
    brand_set.add('ST Luce')
    for i in brand_set:
        print(i)


def get_links_interiors(urls: set):   # take URl`s list for crawling
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/94.0.4606.85 YaBrowser/21.11.4.730 Yowser/2.5 Safari/537.36'}
    page = True

    page_count = 0

    while page is True:
        page_count += 1

        request = get('https://interlamp.by/svetilniki?page={number}'.format(number=page_count), timeout=None,
                      headers=headers)

        soup = bs(request.content, 'lxml')

        links = soup.find_all('a', {'href': re.compile('(https:)+(\//interlamp.by\/svetilniki\/)+(?!spalnya|bar|zal'
                                                       '|dekor|bra|osqona|sonex|lyustri|kuhnya|ofis|restoran-i-bar'
                                                       '|detskaya|arte|artglass|divinare|eglo|gostinaya|freya|elstead|'
                                                       'ideallux|kolarz|lightstar|lumion|maytoni|nowodvorski|'
                                                       'odeon-light|novotech|orion|osgona|searchlight|nastennye|'
                                                       'potolochnye|nastenno-potolochnie|tochechnie-nakladnie|'
                                                       'napolnye|trekovie|spoti|nastolnye|vstraivaemye|'
                                                       'podsvetka-dlya-kartin|lenta-svetodiodnaya|podvesnie|'
                                                       'abazhury|nochniki|vannaya|prihozhaya|besedka|kafe|park)'
                                                       )
                                    }
                              )
        for i_link in links:
            if i_link['href']:
                urls.add(i_link['href'])

        sleep(1)
        print('Parsing of the page {count_page} ended\n'.format(count_page=page_count))

        check = soup.find_all('div', {'class': 'category container'})
        for i_string in check:
            if 'К сожалению, товары в данной категории отсутствуют.' in i_string.get_text():
                page = False
            else:
                sleep(1)


def get_links_outdoor(urls: set):   # take URl`s list for crowling
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/94.0.4606.85 YaBrowser/21.11.4.730 Yowser/2.5 Safari/537.36'}
    page = True

    page_count = 0

    while page is True:
        page_count += 1

        request = get('https://interlamp.by/ulichnye-svetilniki?page={number}'.format(number=page_count), timeout=None,
                      headers=headers)

        soup = bs(request.content, 'lxml')

        links = soup.find_all('a', {'href': re.compile('(https:)+(\//interlamp.by\/ulichnye-svetilniki\/)+(?!spalnya|'
                                                       'bar|zal|dekor|bra|osqona|sonex|lyustri|kuhnya|ofis|'
                                                       'restoran-i-bar|detskaya|arte|artglass|divinare|eglo|gostinaya|'
                                                       'freya|elstead|ideallux|kolarz|lightstar|lumion|maytoni|'
                                                       'nowodvorski|odeon-light|novotech|orion|osgona|searchlight|'
                                                       'nastennye|potolochnye|nastenno-potolochnie|'
                                                       'tochechnie-nakladnie|napolnye|trekovie|spoti|nastolnye|'
                                                       'vstraivaemye|podsvetka-dlya-kartin|lenta-svetodiodnaya|'
                                                       'podvesnie|abazhury|nochniki|vannaya|prihozhaya|nazemnye|fonari|'
                                                       'prozhektory|fasadnye-svetilniki|n-vstraivaemye|'
                                                       'sadovye-perenosnye|n-nastennye|n-podvesnye|n-potolochnye|'
                                                       'besedka|kryltso|kafe|park)'
                                                       )
                                    }
                              )
        for i_link in links:
            if i_link['href']:
                urls.add(i_link['href'])

        sleep(1)
        print('Parsing of the page {count_page} ended\n'.format(count_page=page_count))

        check = soup.find_all('div', {'class': 'category container'})
        for i_string in check:
            if 'К сожалению, товары в данной категории отсутствуют.' in i_string.get_text():
                page = False
            else:
                sleep(1)


def get_url_file(urls: set):    # get text file with URL`s list
    with open('urls.txt', 'w') as urls_file:
        for i_urls in urls:
            urls_file.write(i_urls + '\n')


def chk_file_exist(path=os.path.abspath('urls.txt')):

    return os.path.exists(path)


def crawling(name: list, price_list: list, article_list: list, photo_list: list, status_list: list,
             brand_list: list, brands: set):
    proxies = {'http': 'socks5h://viachaslau85:V6m1WyL@217.21.55.3:45786',
               'https': 'socks5h://viachaslau85:V6m1WyL@217.21.55.3:45786'}

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/94.0.4606.85 YaBrowser/21.11.4.730 Yowser/2.5 Safari/537.36'}
    goods_cards_count = 0
    with open('urls.txt', 'r') as urls_list:
        quantity_line = len(urls_list.readlines())
    with open('urls.txt', 'r') as urls_list:
        while goods_cards_count != quantity_line:
            goods_cards_count += 1
            current_line = urls_list.readline()[:-1]
            print('Scraping the page {current_page} of {total_pages}'.format(current_page=goods_cards_count,
                                                                             total_pages=quantity_line
                                                                             )
                  )

            print(current_line)

            print('Scrapping is {percent_done}% complete\n'.format(percent_done=round(goods_cards_count * 100 /
                                                                                      quantity_line, 2
                                                                                      )
                                                                   )
                  )

            session = requests.Session()
            retry = Retry(connect=27, backoff_factor=3)
            adapter = HTTPAdapter(max_retries=retry)
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            request = session.get(current_line, headers=headers, proxies=proxies, timeout=None)

            b_soup = bs(request.content, 'lxml')

            title = b_soup.select_one('#product_page_top > h1')
            if not title:
                print('Title not found')
                with open('errors.txt', 'a') as log:
                    log.write(f'On page {current_line} title not found' + '\n')
            else:
                name.append(title.get_text())

                for i_brands in brands:
                    if i_brands in title.get_text():
                        brand = i_brands
                        break
                else:
                    brand = 'No brand'

                brand_list.append(brand)

                try:
                    price = b_soup.find('div', class_='price').get_text().strip()
                except Exception:
                    with open('errors.txt', 'a') as log:
                        log.write(f'On page {current_line} price not found' + '\n')
                        price_list.append('No price')
                else:
                    price_clear = re.sub('( р.)+', '', price)
                    price_list.append(price_clear)

                try:
                    article = b_soup.select_one('#product_image > div.sku').get_text().strip().split()[2]

                except Exception:
                    with open('errors.txt', 'a') as log:
                        log.write(f'On page {current_line} article not found' + '\n')
                        article_list.append('No article')
                else:
                    article_list.append(article)

                try:
                    photo_url = b_soup.select_one('#product_image > a > img').attrs['src']

                except Exception:
                    with open('errors.txt', 'a') as log:
                        log.write(f'On page {current_line} URL of photo not found' + '\n')
                        photo_list.append('No URL of photo')

                else:
                    photo_list.append(photo_url)

                try:
                    status = b_soup.select_one('#product_info > div.inner > div.info_top > div > div').get_text().strip()

                except Exception:
                    with open('errors.txt', 'a') as log:
                        log.write(f'On page {current_line} status not found' + '\n')
                        status_list.append('No status')

                else:
                    status_list.append(status)

            if goods_cards_count % 500 == 0:
                print('We are sleep 4 minutes. Zzzz....')
                sleep(240)


def make_file_excel(name: list, price: list, article: list, photo: list, status: list, brand: list):
    df = pd.DataFrame({'Наименование элемента': name,
                       'Цена "Розничная цена"': price,
                       'Бренд': brand,
                       'Артикул [CML2_ARTICLE]': article,
                       'Ссылки на фото': photo,
                       'Статус': status})
    df.to_excel('./interlamp.xlsx', sheet_name='Изменение цен', index=False)


def main():
    brands = set()

    get_all_brands(brands)

    names_list = list()
    prices_list = list()
    articles = list()
    photos = list()
    status = list()
    brands_list = list()

    urls_set = set()    # uniques good`s URLs

    if not chk_file_exist():

        get_links_interiors(urls_set)

        get_links_outdoor(urls_set)

        get_url_file(urls_set)  # file with uniques good`s URLs

    else:
        make_refind = input('Want to update the list of product links in the catalog? [yes / no]: ').strip().lower()
        while make_refind not in ['no', 'n', 'yes', 'y']:
            make_refind = input('Incorrect input. Please repeat [yes / no]: ').strip().lower()

        if make_refind in ['yes', 'y']:
            get_links_interiors(urls_set)

            get_links_outdoor(urls_set)

            get_url_file(urls_set)  # file with uniques good`s URLs

            crawling(names_list, prices_list, articles, photos, status, brands_list, brands)

            make_file_excel(names_list, prices_list, articles, photos, status, brands_list)

        elif make_refind in ['no', 'n']:
            crawling(names_list, prices_list, articles, photos, status, brands_list, brands)

            make_file_excel(names_list, prices_list, articles, photos, status, brands_list)


if __name__ == '__main__':
    main()
