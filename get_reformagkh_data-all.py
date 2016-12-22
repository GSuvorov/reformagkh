#!/usr/bin/env python -u
# -*- coding: utf-8 -*-

#******************************************************************************
#
# get_reformagkh_data-v2.py
# ---------------------------------------------------------
# Grab reformagkh.ru data on buildings, put it in the CSV table.
# More: https://github.com/nextgis/reformagkh
#
# Usage:
#      usage: get_reformagkh_data-v2.py [-h] [-o ORIGINALS_FOLDER] id output_name
#      where:
#           -h           show this help message and exit
#           id           Region ID
#           -o,overwrite Overwite all, will write over previously downloaded files
#           output_name  Where to store the results (path to CSV file)
#           -of ORIGINALS_FOLDER  Folder to save original html files. Skip saving if empty.
#           --cache_only only parse cache, do not touch the web site
#           --no_tor do not use tor, connect to the site directly
#           --parser PARSER specify which parser to use:
#               none -- do not use any parser, only read/download pages
#               original -- use parser from the original project (limited set of variables, default)
#               attrlist -- use parser and attribute list loaded from tsv file
#           --outputformat FORMAT specify output format
#               csv -- CSV (default)
#               sqlite -- sqlite database (only implemented for attrlist parser)
# Examples:
#      python get_reformagkh_data-v2.py 2280999 data/housedata2.csv -o html_orig
#      python get_reformagkh_data-all.py 2291922 housedata.csv -of omsk --no_tor --cache_only
#
# to use with Anaconda do once after installing python 2.7 as py27:
#     source activate py27
#
# Copyright (C) 2014-2016 Maxim Dubinin (sim@gis-lab.info)
# Created: 18.03.2014
#
# This source is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This code is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# A copy of the GNU General Public License is available on the World Wide Web
# at <http://www.gnu.org/copyleft/gpl.html>. You can also obtain it by writing
# to the Free Software Foundation, Inc., 59 Temple Place - Suite 330, Boston,
# MA 02111-1307, USA.
#
#******************************************************************************

from bs4 import BeautifulSoup
import urllib2
import csv
from progressbar import *
from httplib import BadStatusLine,IncompleteRead
import socket
import argparse
from collections import namedtuple
from time import sleep
import requesocks
from stem import Signal
from stem.control import Controller
# module to serialize/deserialize object on the disk
import pickle
import shutil
import datetime
import re
import editdistance
import sqlite3
#from pytest import attrlist

parser = argparse.ArgumentParser()
parser.add_argument('id', help='Region ID')
parser.add_argument('output_name', help='Where to store the results (path to CSV file)')
parser.add_argument('-o','--overwrite', action="store_true", help='Overwite all, will write over previously downloaded files.')
parser.add_argument('-of','--originals_folder', help='Folder to save original html files. Skip saving if empty.')
parser.add_argument('--no_tor', help='Do not use tor connection', action="store_true")
parser.add_argument('--cache_only', help='Do not connect to the web site, use only cached entries', action="store_true")
parser.add_argument('--parser', help='Parser to use', default='original', choices=['original', 'attrlist', 'none'])
parser.add_argument('--outputformat', help='output format', default='csv', choices=['csv', 'sqlite'])
parser.add_argument('--outputmode', help='output mode', default='append', choices=['append', 'overwrite'])
args = parser.parse_args()
dirsep = '/' if not os.name == 'nt' else '\\'

# check if arguments make sense
if args.originals_folder:
    if not args.originals_folder.endswith(dirsep): args.originals_folder = args.originals_folder + dirsep
    if not os.path.exists(args.originals_folder): os.mkdir(args.originals_folder)
if args.cache_only:
    if not args.originals_folder:
        print 'cache-only requested but originals folder was not specified, quitting...'
        sys.exit(-1)
    if args.no_tor:
        print 'with cache_only no_tor has no effect'
if args.outputformat == 'sqlite' and args.parser == 'origina':
        print 'sqlite outputformat works only for attrlist parser'
        sys.exit(-1)
if args.parser == 'none' and args.outputformat:
    print 'outputformat has no effect when parser=none'

def console_out(text):
    #write httplib error messages to console
    time_current = datetime.datetime.now()
    timestamp = time_current.strftime('%Y-%m-%d %H:%M:%S')

    f_errors.write(timestamp + ': '+ text)

def get_content(link):
    numtries = 5
    timeoutvalue = 40

    # this function should never be called if no_cache is specified
    assert not args.no_cache

    if args.no_tor:
        print('Directly retrieving ' + link)
        live_url = urllib2.urlopen(link)
        res = live_url.read()
    else:
        print('TOR Retrieving ' + link)
        for i in range(1,numtries+1):
            try:
                res = session.get(link).text
            except:
                time.sleep(3)
                res = ''
            else:
                break

        if res == '':
            print('Session time out')
            sys.exit()

    return res

def urlopen_house(link,id):
    #fetch html data on a house

    res = get_content(link)
    if args.originals_folder:
        f = open(args.originals_folder + id + ".html","wb")
        f.write(res)#.encode('utf-8'))  #writing in utf-8 causes exceptions.UnicodeDecodeError
        f.close()

    return res

def change_proxy():
    with Controller.from_port(port = 9151) as controller:
            controller.authenticate(password="password")
            controller.signal(Signal.NEWNYM)

def extract_value(tr):
    #extract value for general attributes
    res = tr.findAll('td')[1].text.strip()

    return res

def extract_subvalue(tr,num):
    #extract value for general attributes
    res = tr.findAll('tr')[num].text.strip()

    return res

def check_size(link):

    res = get_content(link)
    soup = BeautifulSoup(''.join(res), 'html.parser')
    captcha = check_captcha(soup)

    while captcha == True:
        res = get_content(link)
        soup = BeautifulSoup(''.join(res), 'html.parser')
        captcha = check_captcha(soup)
        change_proxy()

    divs = soup.findAll('div', { 'class' : 'clearfix' })
    table = divs[1].find('table', { 'class' : 'col_list' })
    size = table.findAll('td')[3].text.replace(u' ед.','').replace(' ','')

    return size

def get_house_list(link):
    size = check_size(link)
    if size == 0: size = check_size(link)

    pages = (int(size) / 10000) + 1

    houses_ids = []
    for page in range(1,pages+1):
        res = get_content(link + '&page=' + str(page) + '&limit=10000')
        soup = BeautifulSoup(''.join(res), 'html.parser')
        captcha = check_captcha(soup)

        while captcha == True:
            if args.no_tor:
                print "Captcha received: the limit of connections was likely exceeded, quitting"
                sys.exit(-1)
            res = get_content(link + '&page=' + str(page) + '&limit=10000')
            soup = BeautifulSoup(''.join(res), 'html.parser')
            captcha = check_captcha(soup)
            change_proxy()

        tds = soup.findAll('td')
        for td in tds:
            if td.find('a') is not None:
                if td.find('a').has_attr('href') and 'myhouse' in td.find('a')['href']:
                    house_id = td.find('a')['href'].split('/')[4]
                    houses_ids.append(house_id)

    return houses_ids

def get_data_links(id):
    f_atd = open('atd.csv','rb')
    csvreader = csv.reader(f_atd, delimiter=',')
    regs = []
    for row in csvreader:
        if id in row:
            r = region(row[0],row[1],row[2],row[3],row[4],row[5])
            regs.append(r)

    return regs

def check_captcha(soup):
    captcha = soup.find('form', { 'name' : 'request_limiter_captcha'})
    if captcha != None or u'Каптча' in soup.text or 'captcha' in str(soup):
        return True
    else:
        return False

def get_housedata(link,house_id,lvl1_name,lvl1_id,lvl2_name,lvl2_id):
    #process house data to get main attributes

    if args.originals_folder:
        cache_fname = args.originals_folder + '/' + house_id + ".html"
        if not os.path.isfile(cache_fname):
            if args.cache_only:
                print('Cache file ' + cache_fname + ' does not exist, skipping');
                res = False
            else:
                try:
                    res = urlopen_house(link + 'view/' + house_id,house_id)
                except:
                    print "Error with " + link + 'view/' + house_id + ": ", sys.exc_info()[0]
                    f_errors.write(link + 'view/' + house_id + '\n')
                    res = False
        else:
            res = open(args.originals_folder + '/' + house_id + ".html",'rb').read()
    else:
       try:
           res = urlopen_house(link + 'view/' + house_id,house_id)
       except:
           f_errors.write(link + 'view/' + house_id + '\n')
           res = False

    if res != False and args.parser != 'none':
        soup = BeautifulSoup(''.join(res),'html.parser')
        f_ids.write(link + 'view/' + house_id + ',' + house_id + '\n')

        if len(soup) > 0 and 'Time-out' not in soup.text and '502 Bad Gateway' not in soup.text: #u'Ошибка' not in soup.text
            if args.parser == 'attrlist':
                return parse_house_page_attrlist(soup)
            else:
                return parse_house_page_original(soup)
        else:
            return False
    else:
        return True

def parse_house_page_original(soup):
    address = soup.find('span', { 'class' : 'float-left loc_name_ohl width650 word-wrap-break-word' }).text.strip()

    #GENERAL
    div = soup.find('div', { 'class' : 'fr' })
    tables = div.findAll('table')
    table0 = tables[0]
    trs = table0.findAll('tr')

    mgmt_company = trs[0].findAll('td')[1].text.strip()                  #gen8 Домом управляет
    if trs[0].findAll('td')[1].find('a'):
        mgmt_company_link = 'http://www.reformagkh.ru' + trs[0].findAll('td')[1].find('a')['href']
        mgmt_company_link = mgmt_company_link.split('?')[0]
    else:
        mgmt_company_link = ''

    table1 = tables[1]
    trs = table1.findAll('tr')
    status = '' #trs[1].findAll('td')[1].text.strip()                    #gen7 Состояние дома (куда-то исчезло в последней версии)

    table1 = tables[1]
    trs = table1.findAll('tr')
    #area = float(trs[2].findAll('td')[1].text.strip().replace(' ',''))  #gen1 Общая площадь
    #year = trs[6].findAll('td')[1].text.strip()                          #gen6 Год ввода в экспл
    lastupdate = trs[8].findAll('td')[1].text.strip()                    #gen2 Последнее изменение анкеты
    lastupdate = ' '.join(lastupdate.replace('\n','').split())
    servicedate_start = trs[10].findAll('td')[1].text.strip()            #gen3 Дата начала обслуживания дома
    servicedate_end = '' #trs[5].findAll('td')[1].text.strip()           #gen4 Плановая дата прекращения обслуживания дома

    #TODO extract lat/long coords from script
    if 'center' in soup.findAll('script')[11]:
        lat,lon = soup.findAll('script')[11].text.split('\n')[3].split('[')[1].split(']')[0].split(',')
    else:
        lat,lon = soup.findAll('script')[12].text.split('\n')[3].split('[')[1].split(']')[0].split(',')

    #PASSPORT
    ##GENERAL
    divs = soup.findAll('div', { 'class' : 'numbered' })
    div0 = divs[0]
    trs = div0.findAll('tr')
    lentrs = len(trs)
    if lentrs > 58:
        trs_offset = lentrs - 58
    else:
        trs_offset = 0

    year = extract_value(trs[3])                            #5 Год ввода в эксплуатацию
    serie = extract_value(trs[5])                            #1 Серия
    house_type = extract_value(trs[7])                       #4 Тип жилого дома
    capfond = extract_value(trs[9])                          #5 Способ формирования фонда капитального ремонта
    avar = extract_value(trs[11])                            #6 Дом признан аварийным
    levels_max = extract_subvalue(trs[12], 1)                #7 Этажность: макс
    levels_min = extract_subvalue(trs[12], 3)                #7 Этажность: мин
    doors = extract_value(trs[18])                           #9 Количество подъездов
    room_count = extract_value(trs[23])                      #10 Количество помещений
    room_count_live = extract_value(trs[26])                 #10 Количество помещений: жилых
    room_count_nonlive = extract_value(trs[28])              #10 Количество помещений: нежилых
    area = extract_value(trs[31]).replace(' ','')            #11 Общая площадь дома
    area_live = extract_value(trs[34]).replace(' ','')       #11 Общая площадь дома, жилых
    area_nonlive = extract_value(trs[36]).replace(' ','')    #11 Общая площадь дома, нежилых

    area_gen = extract_value(trs[38]).replace(' ','')        #11 Общая площадь помещений, входящих в состав общего имущества
    area_land = extract_value(trs[41]).replace(' ','')       #12 Общие сведения о земельном участке, на котором расположен многоквартирный дом
    area_park = extract_value(trs[43]).replace(' ','')       #12 Общие сведения о земельном участке, на котором расположен многоквартирный дом
    cadno = trs[44].findAll('td')[1].text                    #12 кад номер

    energy_class = extract_value(trs[48 + trs_offset])                    #13 Класс энергоэффективности
    blag_playground = extract_value(trs[51 + trs_offset])                 #14 Элементы благоустройства
    blag_sport = extract_value(trs[53 + trs_offset])                      #14 Элементы благоустройства
    blag_other = extract_value(trs[55 + trs_offset])                      #14 Элементы благоустройства
    other = extract_value(trs[57 + trs_offset])                           #14 Элементы благоустройства


    #write to output
    csvwriter_housedata.writerow(dict(LAT=lat,
                                      LON=lon,
                                      HOUSE_ID=house_id,
                                      ADDRESS=address.encode('utf-8'),
                                      YEAR=year.encode('utf-8'),
                                      LASTUPDATE=lastupdate.encode('utf-8'),
                                      SERVICEDATE_START=servicedate_start.encode('utf-8'),
                                      SERIE=serie.encode('utf-8'),
                                      HOUSE_TYPE=house_type.encode('utf-8'),
                                      CAPFOND=capfond.encode('utf-8'),
                                      MGMT_COMPANY=mgmt_company.encode('utf-8'),
                                      MGMT_COMPANY_LINK=mgmt_company_link.encode('utf-8'),
                                      AVAR=avar.encode('utf-8'),
                                      LEVELS_MAX=levels_max.encode('utf-8'),
                                      LEVELS_MIN=levels_min.encode('utf-8'),
                                      DOORS=doors.encode('utf-8'),
                                      ROOM_COUNT=room_count.encode('utf-8'),
                                      ROOM_COUNT_LIVE=room_count_live.encode('utf-8'),
                                      ROOM_COUNT_NONLIVE=room_count_nonlive.encode('utf-8'),
                                      AREA=area.encode('utf-8'),
                                      AREA_LIVE=area_live.encode('utf-8'),
                                      AREA_NONLIVE=area_nonlive.encode('utf-8'),
                                      AREA_GEN=area_gen.encode('utf-8'),
                                      AREA_LAND=area_land.encode('utf-8'),
                                      AREA_PARK=area_park.encode('utf-8'),
                                      #CADNO=cadno.encode('utf-8'),
                                      ENERGY_CLASS=energy_class.encode('utf-8'),
                                      BLAG_PLAYGROUND=blag_playground.encode('utf-8'),
                                      BLAG_SPORT=blag_sport.encode('utf-8'),
                                      BLAG_OTHER=blag_other.encode('utf-8'),
                                      OTHER=other.encode('utf-8')))
    return True

def parse_house_page_attrlist(soup):
    """Parses a house page using attrlist information"""

    # create output variable name from the section names
    sect_attrs = ['section-rus', 'subsection-rus', 'attribute-rus', 'subattribute-rus', 'subsubattribute-rus']
    cur_sect = dict.fromkeys(sect_attrs)

    for row in attrlist:

        # update section attributes
        for attr in sect_attrs:
            cur_sect[attr] = row[attr] or cur_sect[attr]
            expected_attr_name = row[attr] or expected_attr_name # expected attr string is set to the last section name

        if row['Selector Code for Name']:
            attr_name = '->'.join([ cur_sect[attr] for attr in sect_attrs if cur_sect[attr] ])
            fixed_selector_code_name = re.sub('nth-child', 'nth-of-type', row['Selector Code for Name']) # this is needed because bs does not support nth-child
            fixed_selector_code_value = re.sub('nth-child', 'nth-of-type', row['Selector Code for Value'])
            #print 'Searching for Selector Code:', row['Selector Code'], fixed_code

            result_name = soup.select(fixed_selector_code_name)

            if result_name:
                found_attr_name = result_name[0].text.strip().encode('utf-8')

                # value extraction
                result_value = soup.select(fixed_selector_code_value)

                found_attr_value = result_value[0].text.strip().encode('utf-8') if result_value else 'not found'

                result_set = dict(HOUSE_ID=house_id,
                                  ATTR_NAME=attr_name,
                                  FOUND_NAME=found_attr_name,
                                  ED_DIST=editdistance.eval(expected_attr_name,found_attr_name),
                                  VALUE=found_attr_value)
            else: # not found
                result_set = dict(HOUSE_ID=house_id,
                                  ATTR_NAME=attr_name,
                                  FOUND_NAME=None,
                                  ED_DIST=None,
                                  VALUE=None)

            if args.outputformat == 'csv':
                csvwriter_housedata.writerow(result_set)
            else:
                sqcur.execute("insert into attrvals values (" + fieldnames_phld + ")", [ str(result_set[k]).decode('utf8') for k in fieldnames_data])

        if args.outputformat == 'sqlite':
            conn.commit()

def load_attrlist():
    """Loads the list of attributes and their id string from a CSV file."""

    attrlist_fname = "attributes.tsv"
    attrlist_fh = open(attrlist_fname, 'rU')
    attrlist_reader = csv.reader(attrlist_fh, delimiter='\t')
    attrlist = []
    ignorecols = [] # columns to be ignored
    attrnames = [] # names of the attributes from the 2nd row
    c=0
    for row in attrlist_reader:
        c += 1
        if c == 3:
            attrnames = [ s.strip(' ') for s in row ]
            # ignore columns with no names
            ignorecols = [ i for i,x in enumerate(attrnames) if not x ] # list of columns with no names
            attrnames = [i for j, i in enumerate(attrnames) if j not in ignorecols] # now remove ignore elements
            #print ':'.join(attrnames)
        elif c > 3:
            row = [i for j, i in enumerate(row) if j not in ignorecols] # remove ignore columns
            attrlist.append(dict(zip( attrnames, [ s.strip(' ').replace('\n', '') for s in row ] )))

    # TODO: create output table column name

    return attrlist

def out_of_the_way(file_name):
    if os.path.isfile(file_name):
        bfile_name = file_name + '.{:%Y-%m-%dT%H.%M.%S}'.format(datetime.datetime.now())
        print('file backed up to ' + bfile_name)
        shutil.move(file_name, bfile_name)

if __name__ == '__main__':
    if not args.no_tor:
        session = requesocks.session()
        session.proxies = {'http':  'socks5://127.0.0.1:9150',
                           'https': 'socks5://127.0.0.1:9150'}
        try:
            session.get('http://google.com').text
        except:
            print('Tor isn\'t running or not configured properly')
            sys.exit(1)

    tid = args.id #2280999
    lvl1_link = 'http://www.reformagkh.ru/myhouse?tid=' + tid #+ '&sort=alphabet&item=mkd'
    house_link = 'http://www.reformagkh.ru/myhouse/profile/'
    #house_id = 8625429

    region = namedtuple('reg', 'lvl1name lvl2name lvl3name lvl1tid lvl2tid lvl3tid')

    #init errors.log
    f_errors = open('errors.txt','wb')
    f_ids = open('ids.txt','wb')

    # parser intialization
    if args.parser == 'original':
        #init csv for housedata
        fieldnames_data = ('LAT','LON','HOUSE_ID','ADDRESS','YEAR','LASTUPDATE','SERVICEDATE_START','SERIE','HOUSE_TYPE','CAPFOND','MGMT_COMPANY','MGMT_COMPANY_LINK','AVAR','LEVELS_MAX','LEVELS_MIN','DOORS','ROOM_COUNT','ROOM_COUNT_LIVE','ROOM_COUNT_NONLIVE','AREA','AREA_LIVE','AREA_NONLIVE','AREA_GEN','AREA_LAND','AREA_PARK','CADNO','ENERGY_CLASS','BLAG_PLAYGROUND','BLAG_SPORT','BLAG_OTHER','OTHER')

    elif args.parser == 'attrlist':
        # load csv file with attribute descriptions
        attrlist = load_attrlist()
        fieldnames_data = ('HOUSE_ID','ATTR_NAME','FOUND_NAME','ED_DIST','VALUE')
        fieldnames_type = ('TEXT','TEXT','TEXT','INTEGER','TEXT')
        fieldnames_phld = ', '.join([ ':' + s for s in fieldnames_data]) #placeholder for sqlite

    # create an output file housedata.csv with the requested field names
    if args.parser != 'none':
        f_housedata_name = args.output_name   #data/housedata.csv
        if args.outputmode == 'overwrite':
            out_of_the_way(f_housedata_name)
        if args.outputformat == 'csv':
            if args.outputmode == 'overwrite':
                f_housedata = open(f_housedata_name,'wb')
                fields_str = ','.join(fieldnames_data)
                f_housedata.write(fields_str+'\n')
                f_housedata.close()
        else: # sqlite format for attrlist parser
            conn = sqlite3.connect(f_housedata_name)
            sqcur = conn.cursor()
            sqcur.execute('create table if not exists attrvals(' + ', '.join([ s+' '+t for s,t in zip(fieldnames_data, fieldnames_type)]) + ', primary key(HOUSE_ID, ATTR_NAME) )')
            conn.commit()

    f_housedata = open(f_housedata_name,'ab')

    csvwriter_housedata = csv.DictWriter(f_housedata, fieldnames=fieldnames_data)

    regs = get_data_links(args.id)

    house_ids_fname = args.originals_folder + dirsep + 'house_ids.pickle'

    for reg in regs:
        if reg[5] != '' or len([i for i in regs if reg[4] in i]) == 1: #can't use Counter with cnt(elem[4] for elem in regs)[reg[4]] because of the progressbar
                print(reg[0].decode('utf8') + ', ' + reg[1].decode('utf8') + ', ' + reg[2].decode('utf8'))
                #get list of houses
                if args.cache_only:
                    # load saved ids
                    print('Loading cached house_ids from ' + house_ids_fname)
                    f_house_ids = open(house_ids_fname, 'rb')
                    houses_ids = pickle.load(f_house_ids)
                    f_house_ids.close()
                else:
                    print('retrieve house ids from the site')
                    if reg[5] == '':
                        houses_ids = get_house_list('http://www.reformagkh.ru/myhouse/list?tid=' + reg[4])
                    else:
                        houses_ids = get_house_list('http://www.reformagkh.ru/myhouse/list?tid=' + reg[5])
                    # save IDs in a file making a copy of an existing file
                    print('saving house_ids to ', house_ids_fname)
                    if os.path.isfile(house_ids_fname):
                        out_of_the_way(house_ids_fname)
                    f_house_ids = open(house_ids_fname, 'wb')
                    pickle.dump(houses_ids, f_house_ids)
                    f_house_ids.close()

                #pbar = ProgressBar(widgets=[Bar('=', '[', ']'), ' ', Counter(), ' of ' + str(len(houses_ids)), ' ', ETA()]).start()
                #pbar.maxval = len(houses_ids)

                i = 0
                for house_id in houses_ids:
                    i = i+1
                    print i, '\tProcessing house_id=', house_id
                    res = get_housedata(house_link,str(house_id),reg[0],reg[3],reg[1],reg[4])
                    if not args.no_tor and res == False:
                        change_proxy()
                        res = get_housedata(house_link,str(house_id),reg[0],reg[3],reg[1],reg[4])
                    if res == False:
                        print('Failed to retrieve building data for id=' + house_id)
                    #pbar.update(pbar.currval+1)
                print 'Processed', i, 'house_ids'
                #pbar.finish()

    if args.parser == 'original':
        f_housedata.close()
    f_errors.close()
    f_ids.close()
