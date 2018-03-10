
# -*- coding: utf-8 -*-

import re

import os
import os.path

import random
import json
import sys
import zipfile

import datetime
import pprint
import urllib.parse
import traceback

import bs4

import nameTools as nt

import settings

import WebRequest

import MangaCMS.cleaner.processDownload
import MangaCMS.ScrapePlugins.RetreivalBase

class ContentLoader(MangaCMS.ScrapePlugins.RetreivalBase.RetreivalBase):




	logger_path = "Main.Manga.Pururin.Cl"
	plugin_name = "Pururin Content Retreiver"
	plugin_key  = "pu"
	is_manga    = False


	urlBase = "http://pururin.io/"



	retreivalThreads = 1


	def getFileName(self, soup):
		container = soup.find("span", class_='info')
		# Descriptive, eh?
		link_w_title = container.find("a", title=True)
		title = link_w_title['title']

		bad_prefix = "Read "
		bad_postfix = " Online"
		if title.startswith(bad_prefix):
			title = title[len(bad_prefix):]
		if title.endswith(bad_postfix):
			title = title[: -1 * len(bad_postfix)]

		if "/" in title:
			title = title.split("/")[0]

		return title



	def imageUrls(self, soup):
		thumbnailDiv = soup.find("div", id="thumbnail-container")

		ret = []

		for link in thumbnailDiv.find_all("a", class_='gallerythumb'):

			referrer = urllib.parse.urljoin(self.urlBase, link['href'])
			if hasattr(link, "data-src"):
				thumbUrl = link.img['data-src']
			else:
				thumbUrl = link.img['src']

			if not "t." in thumbUrl[-6:]:
				raise ValueError("Url is not a thumb? = '%s'" % thumbUrl)
			else:
				imgUrl = thumbUrl[:-6] + thumbUrl[-6:].replace("t.", '.')

			imgUrl   = urllib.parse.urljoin(self.urlBase, imgUrl)
			imgUrl = imgUrl.replace("//t.", "//i.")

			ret.append((imgUrl, referrer))

		return ret


	def getCategoryTags(self, soup):
		container = soup.find("span", class_='info')
		# Descriptive, eh?
		tagTable = container.find("table", class_="table")

		tags = []

		formatters = {
						"Artist"     : "Artist",
						"Circle"     : "Circles",
						"Parody"     : "Parody",
						"Characters" : "Characters",
						"Contents"   : "",
						"Language"   : "",
						"Scanlator"  : "scanlators",
						"Convention" : "Convention"
					}

		ignoreTags = [
					"Uploader",
					"Pages",
					"Ranking",
					"Rating"]

		category = "Unknown?"
		for tr in tagTable.find_all("tr"):
			if len(tr.find_all("td")) != 2:
				continue

			what, values = tr.find_all("td")

			what = what.get_text()
			if what in ignoreTags:
				continue
			elif what == "Category":
				category = values.get_text().strip()
				if category == "Manga One-shot":
					category = "=0= One-Shot"
			elif what in formatters:
				for li in values.find_all("li"):
					tag = " ".join([formatters[what], li.get_text()])
					tag = tag.strip()
					tag = tag.replace("  ", " ")
					tag = tag.replace(" ", "-")
					tags.append(tag)

		return category, tags

	def getNote(self, soup):
		note = soup.find("div", class_="gallery-description")
		if note == None:
			note = ""
		else:
			note = note.get_text()


	def getDownloadInfo(self, source_url, row_id):

		self.log.info("Retrieving item: %s", source_url)


		soup = self.wg.getSoup(source_url, addlHeaders={'Referer': 'http://pururin.us/'})

		if not soup:
			self.log.critical("No download at url %s!", source_url)
			raise IOError("Invalid webpage")

		category, tags = self.getCategoryTags(soup)
		note = self.getNote(soup)

		ret = {}
		ret['file_name'] = self.getFileName(soup)

		read_url = soup.find("a", text=re.compile("Read Online", re.IGNORECASE))
		spage = urllib.parse.urljoin(self.urlBase, read_url['href'])

		ret["s_page"] = spage


		with self.row_context(dbid=row_id) as row:
			if tags:
				self.update_tags(tags, row=row)
			if note:
				row.additional_metadata = {"note" : note}

			row.last_checked = datetime.datetime.now()
			row.series_name  = category
			ret["source_url"] = row.source_id

		return ret

	def getImage(self, imageUrl, referrer):

		content, handle = self.wg.getpage(imageUrl, returnMultiple=True, addlHeaders={'Referer': referrer})
		if not content or not handle:
			raise ValueError("Failed to retreive image from page '%s'!" % referrer)

		fileN = urllib.parse.unquote(urllib.parse.urlparse(handle.geturl())[2].split("/")[-1])
		fileN = bs4.UnicodeDammit(fileN).unicode_markup
		self.log.info("retreived image '%s' with a size of %0.3f K", fileN, len(content)/1000.0)
		return fileN, content

	def getImages(self, dl_info):
		soup = self.wg.getSoup(dl_info['s_page'], addlHeaders={'Referer': dl_info["source_url"]})
		scripts = "\n".join([scrt.get_text() for scrt in soup.find_all("script")])
		dat_arr = None
		for line in [t.strip() for t in scripts.split("\n") if t.strip()]:
			var_prefix = "var chapters = "
			if line.startswith(var_prefix):
				# Trin off the assignment and semicoln
				data = line[len(var_prefix):-1]
				dat_arr = json.loads(data)
		if not dat_arr:
			return []

		self.log.info("Found %s images", len(dat_arr))

		images = []
		values = list(dat_arr.values())
		values.sort(key=lambda x: x['page'])
		for value in values:
			images.append(self.getImage(value['image'], dl_info['s_page']))

		return images


	def get_link(self, link_row_id):

		with self.row_context(dbid=link_row_id) as row:
			row.state  = 'fetching'
			source_url = row.source_id

		try:
			dl_info = self.getDownloadInfo(source_url=source_url, row_id=link_row_id)
			images = self.getImages(dl_info=dl_info)
			file_name = dl_info['file_name']

		except WebRequest.WebGetException:
			with self.row_context(dbid=link_row_id) as row:
				row.state = 'error'
			return False



		if not images:
			with self.row_context(dbid=link_row_id) as row:
				row.state = 'error'
			return False


		fileN = file_name+".zip"
		fileN = nt.makeFilenameSafe(fileN)


		with self.row_sess_context(dbid=link_row_id) as row_tup:
			row, sess = row_tup

			container_dir = os.path.join(settings.puSettings["dlDir"], nt.makeFilenameSafe(row.series_name))
			wholePath = os.path.join(container_dir, row.origin_name)
			fqFName = self.save_image_set(row, sess, wholePath, images)

		with self.row_context(dbid=link_row_id) as row:
			row.state = 'processing'

		# We don't want to upload the file we just downloaded, so specify doUpload as false.
		# As a result of this, the seriesName paramerer also no longer matters
		MangaCMS.cleaner.processDownload.processDownload(seriesName=False, archivePath=fqFName, doUpload=False)


		self.log.info( "Done")
		with self.row_context(dbid=link_row_id) as row:
			row.state = 'complete'





	def setup(self):
		self.wg.stepThroughJsWaf(self.urlBase, titleContains="Pururin")



if __name__ == "__main__":
	import utilities.testBase as tb

	with tb.testSetup(load=False):

		run = ContentLoader()
		run.do_fetch_content()

		# todo = run._retreiveTodoLinksFromDB()
		# for link in todo:
		# 	run.getLink(link)
