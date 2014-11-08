
import webFunctions
import bs4
import re

import urllib.parse
import time
import dateutil.parser
import runStatus
import settings
import datetime

import ScrapePlugins.RetreivalDbBase
import nameTools as nt


class RhFeedLoader(ScrapePlugins.RetreivalDbBase.ScraperDbBase):



	loggerPath = "Main.Rh.Fl"
	pluginName = "RedHawk Scans Link Retreiver"
	tableKey = "rh"
	dbName = settings.dbName

	wg = webFunctions.WebGetRobust(logPath=loggerPath+".Web")

	tableName = "MangaItems"

	urlBase = "http://manga.redhawkscans.com/"

	feedUrl = "http://manga.redhawkscans.com/reader/list/{num}/"


	def closeDB(self):
		self.log.info( "Closing DB...",)
		self.conn.close()
		self.log.info( "done")




	def extractItemInfo(self, soup):

		ret = {}

		infoDiv = soup.find("div", class_='large comic')

		# titleDiv = soup.find("h1", class_="ttl")
		ret["title"] = infoDiv.find("h1", class_='title').get_text().strip()

		return ret

	def getItemPages(self, url):
		self.log.info("Should get item for '%s'", url)
		page = self.wg.getpage(url)

		if "This series contains mature contents and is meant to be viewed by an adult audience." in page:
			self.log.info("Adult check page. Confirming...")
			page = self.wg.getpage(url, postData={"adult": "true"})


		soup = bs4.BeautifulSoup(page)


		baseInfo = self.extractItemInfo(soup)

		ret = []

		for itemDiv in soup.find_all("div", class_="element"):
			item = {}
			linkDiv = itemDiv.find('div', class_='title')
			link = linkDiv.a

			url = link["href"]
			chapTitle = link.get_text().strip()

			chapDate = itemDiv.find("div", class_="meta_r")




			date = dateutil.parser.parse(chapDate.a.next_sibling.strip(", "), fuzzy=True)

			item["originName"] = "{series} - {file}".format(series=baseInfo["title"], file=chapTitle)
			item["sourceUrl"]  = url
			item["seriesName"] = baseInfo["title"]
			item["retreivalTime"]       = time.mktime(date.timetuple())

			ret.append(item)

		return ret



	def getSeriesUrls(self):
		ret = []

		pageNo = 1
		while 1:
			pageUrl = self.feedUrl.format(num=pageNo)
			page = self.wg.getSoup(pageUrl)
			itemDivs = page.find_all("div", class_='group')

			hadNew = False

			for div in itemDivs:
				link = div.a["href"]
				if not link in ret:
					hadNew = True
					ret.append(link)

			if not hadNew:
				break

			pageNo += 1

		return ret


	def getAllItems(self):
		# for item in items:
		# 	self.log.info( item)
		#

		self.log.info( "Loading Red Hawk Items")

		ret = []

		seriesPages = self.getSeriesUrls()


		for item in seriesPages:

			itemList = self.getItemPages(item)
			for item in itemList:
				ret.append(item)

			if not runStatus.run:
				self.log.info( "Breaking due to exit flag being set")
				break
		self.log.info("Found %s total items", len(ret))
		return ret




	def go(self):

		self.resetStuckItems()
		self.log.info("Getting feed items")

		feedItems = self.getAllItems()
		self.log.info("Processing feed Items")

		self.processLinksIntoDB(feedItems)
		self.log.info("Complete")


