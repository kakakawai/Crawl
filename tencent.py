# -*- encoding: utf-8 -*-

import urllib
import argparse
import base64
import json
import os
import re
import threading
from time import sleep

import requests
from lxml import html

requestSession = requests.session()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
      AppleWebKit/537.36 (KHTML, like Gecko) \
      Chrome/52.0.2743.82 Safari/537.36'  # Chrome on win10
requestSession.headers.update({'User-Agent': UA})


class ErrorCode(Exception):
    '''自定义错误码:
        1: URL不正确
        2: URL无法跳转为移动端URL
        3: 中断下载'''

    def __init__(self, code):
        self.code = code

    def __str__(self):
        return repr(self.code)


def isLegelUrl(url):
    legal_url_list = [
        re.compile(r'^http://ac.qq.com/Comic/[Cc]omicInfo/id/\d+?'),
        re.compile(r'^http://m.ac.qq.com/Comic/[Cc]omicInfo/id/\d+?'),
        re.compile(r'^http://m.ac.qq.com/comic/index/id/\d+?'),
        re.compile(r'^http://ac.qq.com/\w+/?$'),
    ]

    for legal_url in legal_url_list:
        if legal_url.match(url):
            return True
    return False


def getId(url):
    if not isLegelUrl(url):
        print('请输入正确的url！')
        raise ErrorCode(1)

    numRE = re.compile(r'\d+$')
    id = numRE.findall(url)
    if not id:
        get_id_request = requestSession.get(url)
        url = get_id_request.url
        id = numRE.findall(url)
        # print(id)
        if not isLegelUrl(url) or not id:
            print('无法自动跳转移动端URL，请进入http://m.ac.qq.com，找到'
                  '该漫画地址。\n'
                  '地址应该像这样: '
                  'http://m.ac.qq.com/Comic/comicInfo/id/xxxxx (xxxxx为整数)')
            raise ErrorCode(2)

    return id[0]


def getContent(id):
    comic_info_page = 'http://ac.qq.com/Comic/comicInfo/id/{}'.format(id)
    page = requestSession.get(comic_info_page).text
    tree = html.fromstring(page)
    comic_name_xpath = '//*[@id="special_bg"]/div[3]/div[1]/div[1]/div[2]/div[1]/div[1]/h2/strong/text()'
    comicName = tree.xpath(comic_name_xpath)[0].strip()
    comic_intro_xpath = '//*[@id="special_bg"]/div[3]/div[1]/div[1]/div[2]/div[1]/p[2]/text()'
    comicIntrd = tree.xpath(comic_intro_xpath)[0].strip()
    chapter_list_xpath = '//*[@id="chapter"]/div[2]/ol[1]/li/p/span/a'
    chapter_list = tree.xpath(chapter_list_xpath)
    count = len(chapter_list)
    sortedContentList = []

    for chapter_element in chapter_list:
        sortedContentList.append(
            {'name': chapter_element.text.strip(), 'url': 'http://ac.qq.com' + chapter_element.get('href')})

    return (comicName, comicIntrd, count, sortedContentList)


def getImgList(chapter_url):
    retry_num = 0
    retry_max = 5
    while True:
        try:
            chapter_page = requestSession.get(chapter_url, timeout=5).text
            base64data = re.findall(r"DATA\s*=\s*'(.+?)'", chapter_page)[0][1:]
            img_detail_json = json.loads(base64.b64decode(base64data).decode('utf-8'))
            imgList = []
            for img_url in img_detail_json.get('picture'):
                imgList.append(img_url['url'])
            return imgList
            break
        except (KeyboardInterrupt, SystemExit):
            print('\n\n中断下载！')
            raise ErrorCode(3)
        except:
            retry_num += 1
            if retry_num >= retry_max:
                raise
            print('下载失败，重试' + str(retry_num) + '次')
            sleep(2)

    return []


def downloadImg(imgUrlList, contentPath, one_folder=False):
    count = len(imgUrlList)
    # print('该集漫画共计{}张图片'.format(count))
    i = 1
    downloaded_num = 0

    def __download_callback():
        nonlocal downloaded_num
        nonlocal count
        downloaded_num += 1
        # print('\r{}/{}... '.format(downloaded_num, count), end='')

    download_threads = []
    for imgUrl in imgUrlList:
        if not one_folder:
            imgPath = os.path.join(contentPath, '{0:0>3}.jpg'.format(i))
        else:
            imgPath = contentPath + '{0:0>3}.jpg'.format(i)
        i += 1

        # 目标文件存在就跳过下载
        if os.path.isfile(imgPath):
            count -= 1
            continue
        download_thread = threading.Thread(target=__download_one_img,
                                           args=(imgUrl, imgPath, __download_callback))
        download_threads.append(download_thread)
        download_thread.start()
    [t.join() for t in download_threads]
    # print('完毕!\n')


def __download_one_img(imgUrl, imgPath, callback):
    retry_num = 0
    retry_max = 2
    while True:
        try:
            downloadRequest = requestSession.get(imgUrl, stream=True, timeout=2)
            with open(imgPath, 'wb') as f:
                for chunk in downloadRequest.iter_content(chunk_size=1024):
                    if chunk:  # filter out keep-alive new chunks
                        f.write(chunk)
                        f.flush()
            callback()
            break
        except (KeyboardInterrupt, SystemExit):
            print('\n\n中断下载，删除未下载完的文件！')
            if os.path.isfile(imgPath):
                os.remove(imgPath)
            raise ErrorCode(3)
        except:
            retry_num += 1
            if retry_num >= retry_max:
                raise
            print('下载失败，重试' + str(retry_num) + '次')
            sleep(2)


def parseLIST(lst):
    '''解析命令行中的-l|--list参数，返回解析后的章节列表'''
    legalListRE = re.compile(r'^\d+([,-]\d+)*$')
    if not legalListRE.match(lst):
        raise AttributeError(lst + ' 不匹配正则: ' + r'^\d+([,-]\d+)*$')

    # 先逗号分割字符串，分割后的字符串再用短横杠分割
    parsedLIST = []
    sublist = lst.split(',')
    numRE = re.compile(r'^\d+$')

    for sub in sublist:
        if numRE.match(sub):
            if int(sub) > 0:  # 自动忽略掉数字0
                parsedLIST.append(int(sub))
            else:
                print('警告: 参数中包括不存在的章节0，自动忽略')
        else:
            splitnum = list(map(int, sub.split('-')))
            maxnum = max(splitnum)
            minnum = min(splitnum)  # min-max或max-min都支持
            if minnum == 0:
                minnum = 1  # 忽略数字0
                print('警告: 参数中包括不存在的章节0，自动忽略')
            parsedLIST.extend(range(minnum, maxnum + 1))

    parsedLIST = sorted(set(parsedLIST))  # 按照从小到大的顺序排序并去重
    return parsedLIST


def tencent(url, path, lst=None, one_folder=False):
    '''url: 要爬取的漫画首页。 path: 漫画下载路径。 lst: 要下载的章节列表(-l|--list后面的参数)'''
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
        id = getId(url)
        print(id)
        comicName, comicIntrd, count, contentList = getContent(id)
        contentNameList = []
        for item in contentList:
            contentNameList.append(item['name'])
        print('漫画名: {}'.format(comicName))
        print('简介: {}'.format(comicIntrd))
        print('章节数: {}'.format(count))
        print('章节列表:')
        try:
            print('\n'.join(contentNameList))
        except Exception:
            print('章节列表包含无法解析的特殊字符\n')

        forbiddenRE = re.compile(r'[\\/":*?<>|]')  # windows下文件名非法字符\ / : * ? " < > |
        comicName = re.sub(forbiddenRE, '_', comicName)  # 将windows下的非法字符一律替换为_
        comicPath = os.path.join(path, comicName)
        if not os.path.isdir(comicPath):
            os.makedirs(comicPath)
        print()

        listpath = comicPath + '/list.txt'
        listfile = open(listpath, 'w')
        listfile.write('漫画名: {}'.format(comicName) + '\n')
        listfile.write('简介: {}'.format(comicIntrd) + '\n')
        listfile.write('章节数: {}'.format(count) + '\n')
        listfile.write('章节列表:' + '\n')
        try:
            listfile.write('\n'.join(contentNameList))
        except Exception:
            listfile.write('章节列表包含无法解析的特殊字符\n')

        listfile.close()

        if not lst:
            contentRange = range(1, len(contentList) + 1)
        else:
            contentRange = parseLIST(lst)

        for i in contentRange:
            if i > len(contentList):
                print('警告: 章节总数 {} ,'
                      '参数中包含过大数值,'
                      '自动忽略'.format(len(contentList)))
                break

            contentNameList[i - 1] = re.sub(forbiddenRE, '_', contentNameList[i - 1]).strip()  # 将windows下的非法字符一律替换为_
            contentPath = os.path.join(comicPath, '第{0:0>4}话-{1}'.format(i, contentNameList[i - 1]))

            try:
                print('正在下载第{0:0>4}话: {1}'.format(i, contentNameList[i - 1]))
            except Exception:
                print('正在下载第{0:0>4}话: {0}'.format(i))

            if not one_folder:
                if not os.path.isdir(contentPath):
                    os.mkdir(contentPath)

            imgList = getImgList(contentList[i - 1]['url'])
            downloadImg(imgList, contentPath, one_folder)

    except ErrorCode as e:
        exit(e.code)

def get_id(keyWord):
    URL = "http://ac.qq.com/Comic/searchList/search/"
    URL = URL + urllib.parse.quote(keyWord, safe='/')
    html = requests.get(URL).text
    id = re.findall('/Comic/comicInfo/id/(\d+)"', html, re.S)
    if not id:
        return -1
    return id[0]

if __name__ == '__main__':
    keyWord = "中国惊奇先生"
    url = "http://ac.qq.com/Comic/comicInfo/id/"+get_id(keyWord)
    print(url)

    path = "pictures/"

    tencent(url, path, lst=None, one_folder=None)
