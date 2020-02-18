# coding=utf-8
"""
User friendly wrapper for Arxiv API

See:
  - https://arxiv.org/help/api/user-manual#_calling_the_api
  - https://github.com/lukasschwab/arxiv.py
  - https://github.com/titipata/arxivpy
 """
import re
from datetime import timedelta
import datetime
from time import sleep
from random import uniform
from feedparser import parse
from json import load, dump


__author__ = 'Christophe Ecabert'

# Arxiv entry point
_base_url = 'http://export.arxiv.org/api/query?'


def _is_category(entry):
  """
  Check if `entry` is a category entry
  :param entry:
  :return:  True if entry is a categoriy, False otherwise.
  """
  res = re.search(r"^[a-zA-Z.-]+\.?[a-zA-Z.-]+", entry)
  return res is not None and len(res.group()) > 4


def _is_paper_id(entry):
  """
  Check if `entry` can be considered as paper ID
  :param entry:   str to check for paper id
  :return:  True if paper id, False otherwise
  """
  res = re.search(r"\d+\.\d+", entry)
  return res is not None


class Search:
  """ User defined search request """

  def __init__(self, search):
    """
    Constructor
    :param search:  List or str, list of categories/paper id or plain arxiv
                    search
    """

    # Search queries -> text
    self.search_query = ''
    # Search for paper ids
    self.id_list = ''

    # Parse input search
    if isinstance(search, list):
      # List of categories/paper_id
      if all([_is_category(s) for s in search]):
        # List of categories
        self.search_query = '+OR+'.join(['cat:%s' % c for c in search])
      elif all([_is_paper_id(s) for s in search]):
        # List of paper id => comma-delimited string
        self.id_list = ','.join(search)
      else:
        raise RuntimeError('Unrecognized list input: {}'.format(search))
    else:
      # string
      if _is_category(search):
        self.search_query = 'cat:{}'.format(search)
      elif _is_paper_id(search):
        self.id_list = search
      else:
        # Raw query
        self.search_query = search

  @classmethod
  def FromSubject(cls, subject):
    """
    Create search for a given subject
    :param subject: Subject
    :return:  Search
    """
    search = '+AND+'.join(['all:{}'.format(p) for p in subject.split(' ')])
    return cls(search)

  @classmethod
  def FromPaper(cls, title, author=None):
    """
    Create search for a given paper title and author optionally
    :param title:   Paper title
    :param author:  Author name (optional)
    :return:  Seach
    """
    search = 'ti:{}'.format(title)
    if author is not None:
      search += '+AND+au:{}'.format(author)
    return cls(search)

  def Finalize(self,
               start=0,
               max_results=25,
               sort_by='submittedDate',
               sort_order='descending'):
    """
    Create complete search request
    :param start: Position where to start
    :param max_results: Maximum number of outputs in the query
    :param sort_by: How to sort results: 'relevance', 'lastUpdatedDate' or 'submittedDate'
    :param sort_order:  Sort ordering: 'ascending' or 'descending'
    :return:  str
    """
    # Check parameters
    if sort_by not in ['relevance', 'lastUpdatedDate', 'submittedDate']:
      raise RuntimeError('Unknown sorting type: {}'.format(sort_by))
    if sort_order not in ['ascending', 'descending']:
      raise RuntimeError('Unknown ordering: {}'.format(sort_order))
    # Build request
    srch = ('search_query={}&' 
            'id_list={}&'
            'start={}&'
            'max_results={}&'
            'sortBy={}&'
            'sortOrder={}'.format(self.search_query,
                                  self.id_list,
                                  start,
                                  max_results,
                                  sort_by,
                                  sort_order))
    return _base_url + srch


class Article:
  """
  Container for an article reference

  Arguments
  ---------

  title: str      Article's title
  authors:  list  List of authors
  summary:  str   Article's summary
  link: str       Link to article's main page
  """

  def __init__(self,
               title: str,
               authors: list,
               summary: str,
               date: str,
               link: str):
    """
    Constructor
    :param title:   Article's title
    :param authors: List of authors of the aricle
    :param summary: Summary
    :param date:    Submitted date
    :param link:    Reference to paper
    """
    self.title = title.replace('\n', ' ').replace('  ', ' ')
    self.authors = authors
    self.summary = summary.replace('\n', ' ').replace('  ', ' ')
    self.date = date
    self.link = link


class ArxivParser:
  """ Callback for arxiv query """

  def __init__(self,
               category=None,
               wait_time=5.0):
    """
    Create Arxiv wrapper
    :param category:  str or list of categories to search for
    :param wait_time: Waiting time between to batch request
    """

    self.category = category or 'cs.CV'
    self.wait_time = wait_time

  @classmethod
  def from_config(cls, filename):
    """
    Create ArxivParser object from config file
    :param filename:  Path to the configuration file
    :return:  ArxivParser object
    """
    with open(filename, 'r') as f:
      data = load(f)
    return cls(**data)

  def save_config(self, filename):
    """
    Dump configuration into a file
    :param filename:  Path where to dump the configuration
    """
    with open(filename, 'w') as f:
      data = {'category': self.category,
              'wait_time': self.wait_time}
      dump(data, f)

  def _query_daily_paper(self,
                         start,
                         max_results,
                         res_per_iter):
    """
    Perform a query
    :param start: Start index
    :param max_results:   Ending index
    :param res_per_iter: Number of article parsing per iteration
          this control so not too many articles are parsed at once
    """

    articles = []
    n_left = max_results
    n_start = start
    # Process request by batch
    submitted_date = datetime.date.today()
    if submitted_date.weekday() == 0:   # Is it monday ?
      submitted_date -= timedelta(3)
    else:
      submitted_date -= timedelta(1)
    submitted_date_str = submitted_date.strftime('%Y-%m-%d')
    while n_left > 0:
      # Define search
      search = Search(search=self.category).Finalize(start=n_start,
                                                     max_results=res_per_iter)
      # Call webserver
      res = parse(search)
      if res.get('status') != 200:
        print('HTTP Error {} in query'.format(res.get('status', 'no status')))
        break

      # Get entries + update number of results left to downloads
      entries = res.get('entries')
      n_left -= len(entries)
      n_start += len(entries)
      if len(entries) == 0:
        print('No more fetch')
        break
      for entry in entries:
        date = entry.get('date', '')
        if submitted_date_str in date:
          articles.append(entry)
        else:
          n_left = 0
          break
      # Sleep for a while to avoid IP ban
      if n_left > res_per_iter:
        sleep(self.wait_time + uniform(0, 3))
    return articles

  def run_daily_search(self,
                       keywords=()):
    """
    Run daily search on arxiv. Can filter articles based on specific keywords
    :param keywords:  List of keywords to filter paper
    :return: List of articles matching the criterions
    """

    # Query all articles publish today (i.e. submitted yesterday)
    articles = []
    daily_articles = self._query_daily_paper(0, 200, 100)
    for art in daily_articles:
      title = art.title
      authors = [author['name'] for author in art.authors]
      summary = art.summary
      link = art.link
      date = art.date
      paper = Article(title, authors, summary, date, link)
      if (len(keywords) == 0 or
        any([kw in paper.title.lower() for kw in keywords])):
        articles.append(paper)
    return articles


if __name__ == '__main__':

    arxiv = ArxivParser(category=['cs.CV', 'cs.AI', 'cs.LG', 'stat.ML'])
    articles = arxiv.run_daily_search()

    for k, art in enumerate(articles):
      print('{}: {} - {}'.format(k, art.title, art.date))


    a = 0