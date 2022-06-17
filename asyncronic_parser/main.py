import re
from bs4 import BeautifulSoup
# import pandas
import asyncio
import backoff
import aiohttp


@backoff.on_exception(backoff.expo, aiohttp.ClientError, max_tries=100, max_time=100)
async def get_goods_data(url, headers, session):
    titles = []
    async with session.get(url=url, headers=headers) as response:
        response_text = await response.text()

        b_soup = BeautifulSoup(response_text, 'lxml')

        title = b_soup.select_one('#product_page_top > h1')

        if not title:
            with open('errors.txt', 'a') as log:
                log.write(f'On page {url} title not found' + '\n')
        else:
            with open('titles.txt', 'a', encoding='utf-8') as titles_file:
                titles_file.write(title.get_text()+'\n')

            titles.append(title.get_text())

        print(f'[INFO] parsed url: {url}, title is {title.get_text()}')


@backoff.on_exception(backoff.expo, aiohttp.ClientError, max_tries=100, max_time=100)
async def get_tasks():
    home_page = 'https://interlamp.by/svetilniki'

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/94.0.4606.85 YaBrowser/21.11.4.730 Yowser/2.5 Safari/537.36'}

    async with aiohttp.ClientSession() as session:

        response = await session.get(url=home_page, headers=headers)

        soup = BeautifulSoup(await response.text(), 'lxml')

        last_page = int(soup.select_one('#page > div.row.row-small > div.col-lg-9.col-lg-4ths > ul > li:nth-child(9) > '
                                        'a').text)

        tasks = []

        for i_page in range(1, last_page + 1):
            url = 'https://interlamp.by/svetilniki?page={page_number}'.format(page_number=i_page)

            async with session.get(url=url, headers=headers) as response:

                soup = BeautifulSoup(await response.text(), 'lxml')

                links = soup.find_all('a',
                                      {'href': re.compile('(https:)+(\//interlamp.by\/svetilniki\/)+(?!spalnya|bar|zal'
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
                        task = asyncio.create_task(get_goods_data(url=i_link['href'], headers=headers, session=session))

                        tasks.append(task)

        await asyncio.gather(*tasks)


def main():
    asyncio.run(get_tasks())


if __name__ == '__main__':
    main()
