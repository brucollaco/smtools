#!/usr/bin/env python

import warnings
warnings.simplefilter("ignore", DeprecationWarning)
#import numpy.oldnumeric

#stdlib
import os.path
import sys
import re
from datetime import datetime,timedelta
from xml.dom import minidom
import urllib.request, urllib.parse, urllib.error
import urllib.request, urllib.error, urllib.parse
import urllib.parse
import base64

#third party
import numpy as np
from obspy.core.utcdatetime import UTCDateTime
from obspy.core.util.geodetics import gps2DistAzimuth
from obspy.core.trace import Trace
from obspy.core.trace import Stats
import matplotlib.pyplot as plt

#local
from .fetcher import StrongMotionFetcher,StrongMotionFetcherException
from .trace2xml import trace2xml
from . import util

#default Turkey spatial search parameters
LATMIN = 35.81
LATMAX = 42.10
LONMIN = 25.6
LONMAX = 44.82

TIMEFMT = '%Y-%m-%d %H:%M:%S'

#the dst part of this URL is base64 "urlsafe" encoded - it translates back to:
#MODULE_NAME=earthquake&MODULE_TASK=search
URLBASE = 'http://kyhdata.deprem.gov.tr/2K/kyhdata_v4.php?dst=TU9EVUxFX05BTUU9ZWFydGhxdWFrZSZNT0RVTEVfVEFTSz1zZWFyY2g%3D'

class TurkeyFetcher(StrongMotionFetcher):
    def __init__(self):
        pass

    def fetch(self,lat,lon,etime,radius,timewindow,outfolder):
        utctime = etime
        htmldata = self.getSearchPage(utctime,lat,lon,radius)
        if htmldata.lower().find("no records found") > -1:
            msg = 'No records found in Turkey database.  Returning.'
            print(msg)
            datafiles = []
            return datafiles
        xmldata = self.getSearchXML(htmldata)
        matchingEvent = self.getMatchingEvent(xmldata,utctime,lat,lon,timewindow,radius)
        if matchingEvent is None:
            msg = 'Failed to find matching event in Turkey database.  Returning.'
            print(msg)
            datafiles = []
            return datafiles

        urlparts = urllib.parse.urlparse(URLBASE)
        url = urllib.parse.urljoin(urlparts.geturl(),matchingEvent['href'])
        urllist = self.getDataLinks(url)
        datafiles = []
        for urltpl in urllist:
            url = urltpl[0]
            station = urltpl[1]
            fh = urllib.request.urlopen(url)
            data = fh.read()
            fh.close()
            fname = '%s_%s.txt' % (utctime.strftime('%Y%m%d%H%M%S'),station)
            localfile = os.path.join(outfolder,fname)
            sys.stderr.write('Downloading data file %s\n' % fname)
            f = open(localfile,'wt')
            f.write(data)
            f.close()
            datafiles.append(localfile)
        return datafiles

    def getSearchPage(self,utctime,lat,lon,distwindow):
        values = {'from_day':0o1,'from_month':0o1,'from_year':2011,
                  'from_md':'','to_md':'',
                  'to_day':31,'to_month':12,'to_year':2011,
                  'from_ml':'','to_ml':'',
                  'from_epi_lat':LATMIN,'from_epi_lat':LATMAX,
                  'from_ms':'','to_ms':'',
                  'from_epi_lon':LONMIN,'to_epi_lon':LONMAX,
                  'from_mw':'','to_mw':'',
                  'from_depth':'','to_depth':'',
                  'from_mb':'','to_mb':''}
        t1 = utctime - timedelta(days=1)
        t2 = utctime + timedelta(days=1)
        values['from_year'] = t1.year
        values['from_month'] = t1.month
        values['from_day'] = t1.day
        values['to_year'] = t2.year
        values['to_month'] = t2.month
        values['to_day'] = t2.day
        ddwindow = distwindow * 1/111.1
        xmin = lon - ddwindow
        xmax = lon + ddwindow
        ymin = lat - ddwindow
        ymax = lat + ddwindow
        values['from_epi_lat'] = ymin
        values['to_epi_lat'] = ymax
        values['from_epi_lon'] = xmin
        values['to_epi_lon'] = xmax
        data = urllib.parse.urlencode(values).encode('ascii')
        req = urllib.request.Request(URLBASE,data)
        response = urllib.request.urlopen(req)
        htmldata = response.read()
        return htmldata

    def getSearchXML(self,htmldata):
        lines = htmldata.split('\n')
        dataOn = False
        xmldata = ''
        for line in lines:
            if line.strip().find('rowtype01_1') > -1:
                xmldata += line.strip()
                dataOn = True
                continue
            if dataOn:
                if line.find('table') > -1:
                    xmldata += line.strip()
                    break
                else:
                    xmldata += line.strip()
        xmldata = '<table>'+xmldata
        xmldata = xmldata.replace('<TR>','<tr>')
        xmldata = xmldata.replace('<TD>','<td>')
        xmldata = xmldata.replace('<br>','')
        badatts = re.findall('class=[a-zA-Z0-9_\-]*',xmldata)
        badatts2 = re.findall('target=[a-zA-Z0-9_\-]*',xmldata)
        badatts += badatts2
        for badatt in badatts:
            xmldata = xmldata.replace(badatt,'')

        #remove non-ascii characters
        xmldata = self.strip_non_ascii(xmldata)

        #delete anything after closing <table> tag
        tabletag = '</table>'
        tidx = xmldata.rfind(tabletag)
        xmldata = xmldata[0:tidx+len(tabletag)]
        return xmldata

    def getMatchingEvent(self,xmldata,utctime,lat,lon,timewindow,distwindow):
        root = minidom.parseString(xmldata)
        table = root.getElementsByTagName('table')[0]
        events = []
        matchingEvent = None
        for tr in table.childNodes:
            if tr.nodeName != 'tr':
                continue
            #now we're in an event
            colidx = 0
            event = {}
            for td in tr.childNodes:
                if td.nodeName != 'td':
                    continue
                if colidx == 1:
                    anchor = td.getElementsByTagName('a')[0]
                    event['href'] = anchor.getAttribute('href')
                    event['id'] = anchor.firstChild.data
                if colidx == 2:
                    datestr = td.firstChild.data
                if colidx == 3:
                    timestr = td.firstChild.data[0:8]
                    event['time'] = datetime.strptime(datestr + ' '+timestr,TIMEFMT)
                if colidx == 4:
                    event['lat'] = float(td.firstChild.data)
                if colidx == 5:
                    event['lon'] = float(td.firstChild.data)
                if colidx == 7:
                    event['mag'] = float(td.firstChild.data)
                    break
                colidx += 1
            if event['time'] > utctime:
                dt = event['time'] - utctime
            else:
                dt = utctime - event['time']
            dtsecs = dt.days*86400 + dt.seconds
            dd,az1,az2 = gps2DistAzimuth(lat,lon,event['lat'],event['lon'])
            dd = dd/1000.0
            if dtsecs < timewindow and dd < distwindow:
                print('The most likely matching event is %s' % event['id'])
                matchingEvent = event.copy()
                break
        return matchingEvent

    def getDataLinks(self,url):
        fh = urllib.request.urlopen(url)
        htmldata = fh.read()
        fh.close()
        xmldata2 = self.getSearchXML(htmldata)
        root = minidom.parseString(xmldata2)
        table = root.getElementsByTagName('table')[0]
        urllist = []
        stationlist = []
        for tr in table.childNodes:
            if tr.nodeName != 'tr':
                continue
            #now we're in a station link
            colidx = 0
            for td in tr.childNodes:
                if td.nodeName != 'td':
                    continue
                if colidx == 1:
                    anchor = td.getElementsByTagName('a')[0]
                    href = anchor.getAttribute('href')
                    urlparts = urllib.parse.urlparse(URLBASE)
                    url = urllib.parse.urljoin(urlparts.geturl(),href)
                    fh = urllib.request.urlopen(url)
                    htmldata2 = fh.read()
                    fh.close()
                    startidx = 0
                    while True:
                        reftag = 'href="'
                        fidx = htmldata2.find(reftag,startidx)
                        cidx = htmldata2.find('"',fidx+len(reftag)+1)
                        href = htmldata2[fidx+len(reftag):cidx]
                        if href.find('css') > -1:
                            startidx = cidx
                            continue
                        else:
                            break
                    url = urllib.parse.urljoin(urlparts.geturl(),href)
                    urllist.append(url)
                if colidx == 6:
                    anchor = td.getElementsByTagName('a')[0]
                    station = anchor.firstChild.data
                    stationlist.append(station)
                colidx += 1
        root.unlink()
        urltuples = list(zip(urllist,stationlist))
        return urltuples

    def strip_non_ascii(self,string):
        ''' Returns the string without non ASCII characters'''
        stripped = (c for c in string if 0 < ord(c) < 127)
        return ''.join(stripped)
    
def readturkey(turkeyfile):
    """
    Read strong motion data from a Turkey data file
    @param geonetfile: Path to a valid Turkey data file.
    @return: List of ObsPy Trace objects, containing accelerometer data in m/s.
    """
    f = open(turkeyfile,'rt')
    dataOn = False
    header = {}
    nschannel = []
    ewchannel = []
    udchannel = []
    for line in f.readlines():
        if line.strip().startswith('STATION ID'):
            parts = line.strip().split(':')
            header['station'] = parts[1].strip()
            continue
        if line.strip().startswith('STATION COORD'):
            parts = line.strip().split(':')
            cstr = parts[1].strip()
            parts = cstr.split('-')
            header['lat'] = float(parts[0][0:-1])
            header['lon'] = float(parts[1][0:-1])
            continue
        if line.strip().startswith('STATION ALT'):
            parts = line.strip().split(':')
            try:
                header['height'] = float(parts[1])
            except:
                header['height'] = 0.0
            continue
        if line.strip().startswith('RECORD TIME'):
            parts = line.strip().split(':')
            timestr = ':'.join(parts[1:])
            timestr = timestr.strip().replace('(GMT)','').strip()
            dt = datetime.strptime(timestr[0:19],'%d/%m/%Y %H:%M:%S')
            dt = dt.replace(microsecond=int(timestr[20:]))
            header['starttime'] = UTCDateTime(dt)
            continue
        if line.strip().startswith('NUMBER OF DATA'):
            parts = line.strip().split(':')
            header['npts'] = int(parts[1])
            continue
        if line.strip().startswith('SAMPLING INTERVAL'):
            parts = line.strip().split(':')
            header['delta'] = float(parts[1])
            header['sampling_rate'] = 1.0/header['delta']
            continue
        if line.strip().startswith('N-S'):
            dataOn = True
            continue
        if dataOn:
            parts = line.strip().split()
            nschannel.append(float(parts[0]))
            ewchannel.append(float(parts[1]))
            udchannel.append(float(parts[2]))
    f.close()
    nschannel = np.array(nschannel)
    ewchannel = np.array(ewchannel)
    udchannel = np.array(udchannel)
    header['network'] = 'TR'
    header['units'] = 'acc'
    nsheader = header.copy()
    nsheader['channel'] = 'NS'
    ewheader = header.copy()
    ewheader['channel'] = 'EW'
    udheader = header.copy()
    udheader['channel'] = 'UD'
    nsstats = Stats(nsheader)
    nstrace = Trace(nschannel,header=nsstats)
    ewstats = Stats(ewheader)
    ewtrace = Trace(ewchannel,header=ewstats)
    udstats = Stats(udheader)
    udtrace = Trace(udchannel,header=udstats)
    nstrace.data = nstrace.data * 0.01 #convert to m/s^2
    ewtrace.data = ewtrace.data * 0.01 #convert to m/s^2
    udtrace.data = udtrace.data * 0.01 #convert to m/s^2
    tracelist = [nstrace,ewtrace,udtrace]
    hdrlist = [nsheader,ewheader,udheader]
    return (tracelist,hdrlist)

if __name__ == '__main__':
    etimestr = sys.argv[1]
    etime = datetime.strptime(etimestr,'%Y-%m-%dT%H:%M:%S')
    lat = float(sys.argv[2])
    lon = float(sys.argv[3])
    turkey = TurkeyFetcher()
    datafiles = turkey.fetch(lat,lon,etime,50,60,os.getcwd())
    # turkeyfile = sys.argv[1]
    # traces,headers = readturkey(turkeyfile)
    # for trace in traces:
    #     print trace.data.max()
    #     trace.detrend('demean')
    #     trace.plot()
    #     plt.savefig('turkey.png')

    
