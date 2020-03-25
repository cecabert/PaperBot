# coding=utf-8
from os import environ
from os.path import join as _join
from os.path import exists as _exists
from re import compile as _re_compile
from datetime import datetime
from slack import RTMClient
import asyncio
import schedule
from argparse import ArgumentParser
from arxiv import ArxivParser
from json import load, dump

__author__ = 'Christophe Ecabert'


class BotCommand:
  """ Container for bot command """

  def __init__(self,
               command=None,
               args=None,
               user=None,
               channel=None,
               web_client=None):
    """
    Constructor
    :param command: Command
    :param args:    Command arguments if any
    :param user:    User that trigger the command if any
    :param channel: Channel from which the command was emitted
    :param web_client:  WebClient to reply
    """
    self._cmd = command
    self._args = args
    self._user = user
    self._channel = channel
    self._web_client = web_client

  @classmethod
  def FromText(cls, search, payload):
    """
    Construct command from a regex + payload
    :param search:    Regex object to look for commands
    :param payload:   Message payloads
    :return:  BotCommand object.
    """
    #  Access data
    data = payload.get('data', None)
    text = data.get('text', None)
    web_client = payload.get('web_client', None)
    #  Bot is mentionned ?
    if text:
      res = search.search(text)
      if res:
        #  Detect command
        channel_id = data.get('channel', None)
        user = data.get('user', None)
        cmd = res.groups()[1]
        args = None if len(res.groups()) == 2 else res.groups()[2]
        return cls(command=cmd,
                   args=args,
                   user=user,
                   channel=channel_id,
                   web_client=web_client)
    return cls(web_client=web_client)

  @property
  def cmd(self):
      return self._cmd

  @property
  def args(self):
    return self._args

  @property
  def user(self):
    return self._user

  @property
  def channel(self):
    return self._channel

  @property
  def client(self):
    return self._web_client


class MessageDispatcher:
  """ Message entry point from slack chat. Reply to direct command send to the
   bot
  """

  def __init__(self,
               token,
               channel,
               cache):
    """
    Constructor
    :param token: Authentification token for bot
    :param channel: Name of the channel where the bot is hosted
    :param cache:   Location where to cache data
    """
    #  Bot mention detection
    self._self_mention = None
    self._channel = channel
    self._bot_id = None

    # Commands
    self._keywords = []
    self._authors = []
    self._known_cmd = {'help': (self._help_callback, ''),
                       'list_keywords': (self._list_keyords_callback,
                                         ''),
                       'add_keywords': (self._add_keyords_callback,
                                        'List of space separated keywords '
                                        'to add'),
                       'run_daily_arxiv_search': (self._run_daily_arxiv_search,
                                                  '')}

    # Arxiv wrapper
    self._cache_folder = cache
    self._arxiv_cfg = _join(self._cache_folder, 'arxiv.cfg')
    if not _exists(self._arxiv_cfg):
      # cs.CV: Compute Vision
      # cs.AI: Artificial Inteligence
      # cs.LG: Machine learning
      # stat.ML: Machine learning
      # cs.GR: Graphics
      self._arxiv = ArxivParser(category=['cs.CV',
                                          'cs.AI',
                                          'cs.LG',
                                          'stat.ML',
                                          'cs.GR'])
      self._arxiv.save_config(self._arxiv_cfg)
    else:
      self._arxiv = ArxivParser.from_config(self._arxiv_cfg)
    # Reload authors/keywords
    self._load_config(self._cache_folder)
    #  Create client, define message callback + start service
    # run aynchronously
    # https://github.com/slackapi/python-slackclient/blob/master/tutorial/PythOnBoardingBot/async_app.py
    # https://stackoverflow.com/questions/56539228
    # Start Slack client + scheduler for daily research
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    self.client = RTMClient(token=token, run_async=True, loop=loop)
    self.client.on(event='open', callback=self.open_callback)
    self.client.on(event='message', callback=self.message_callback)
    loop.run_until_complete(asyncio.gather(self._daily_scheduler(token),
                                           self.client.start()))
    loop.close()

  def __del__(self):
    self._save_config(self._cache_folder)

  def _save_config(self, filename):
    """
    Save configuration
    :param filename:  Path where to dump data
    """
    with open(_join(filename, 'bot.cfg'), 'w') as f:
      cfg = {'keywords': self._keywords,
             'authors': self._authors}
      dump(cfg, f)

  def _load_config(self, filename):
    """
    Reload configuration
    :param filename:  Path where configuration is stored
    """
    fname = _join(filename, 'bot.cfg')
    if _exists(fname):
      with open(fname, 'r') as f:
        cfg = load(f)
        self._keywords = cfg['keywords']
        self._authors = cfg['authors']

  async def _daily_scheduler(self, token):
    """
    Post request to trigger daily search
    :param token: Slack bot's token
    """

    # Create scheduled function
    def _start_daily_search():
      """
      Trigger daily search by posting message to Slack Bot
      :param client: Slack webclient to post messages
      """
      cmd = '<@{}> run_daily_arxiv_search'.format(self._bot_id)
      self.client._web_client.chat_postMessage(channel=self._channel, text=cmd)

    # Add callback to scheduler
    schedule.every().day.at('09:00').do(_start_daily_search)
    # Start loop
    while True:
      schedule.run_pending()  # Run pending job
      await asyncio.sleep(5)  # Sleep for 5'

  def open_callback(self, **payload):
    """
    Call back invoked when bot is started
    :param payload: Payload
    """
    web_client = payload.get('web_client', None)
    data = payload.get('data', None)
    self._bot_id = data['self']['id']
    self._initialize_self_mention(client=web_client)
    # Retrive channels info
    res = web_client.conversations_list()
    channels = res['channels']
    host_chan = self._channel[1:] if self._channel[0] == '#' else self._channel
    for c in channels:
      if c['name'] == host_chan:
        web_client.chat_postMessage(channel=c['id'],
                                    text='PaperBot is now online.')
        break

  def message_callback(self, **payload):
    """
    Callback invoked when message is send to the channel
    :param payload: Message payload
    """
    cmd = BotCommand.FromText(search=self._self_mention, payload=payload)
    if cmd.cmd:
      cb = self._known_cmd.get(cmd.cmd, None)
      if cb is not None:
        cb[0](cmd=cmd)
      else:
        self._boilerplate_callback(cmd=cmd)

  def _initialize_self_mention(self, client):
    """
    Initialize self mention detection
    :param client:  Web client passed to through the message
    """

    #  Build regex to detect when bot is mentionned in the message and reach to
    #  the command.
    #  Retrieve bot ID first
    r = client.auth_test()
    if r['ok']:
      bot_id = r['user_id']
    else:
      #  Something went wrong
      raise RuntimeError('Could not retrive bot ID: {}'.format(r['error']))

    # Bot should react at: @<BotID> <command> but not to <...> @<BotID> <...>
    # self._self_mention = _re_compile(r"^<@{}>".format(bot_id))
    self._self_mention = _re_compile(r"^(<@\w*>) (\w*) ?(.*)".format(bot_id))

  def _boilerplate_callback(self, cmd):
    """
    End point when unknown commands are entered
    :param cmd: Command
    """

    # Format reply
    if cmd.user is None:
      msg = 'Unrecognized command, '
    else:
      msg = 'Sorry <@{}>, the command is *unrecognized*, '.format(cmd.user)
    msg += 'here is a list of all _known_ commands:\n'
    for k in self._known_cmd.keys():
      msg += '• {}\n'.format(k)

    # Insert into blocks in order to have markdown formatting
    blocks = {'type': 'section',
              'text': {'type': 'mrkdwn',
                       'text': msg}}
    # Post on chat
    client = cmd.client
    client.chat_postMessage(channel=cmd.channel,
                            blocks=[blocks])

  def _help_callback(self, cmd):
    """
    Help callback, list all known commands
    :param cmd: Command
    """
    if cmd.user is None:
      msg = 'Here is a list of all recognized commands:\n'
    else:
      msg = 'Hi <@{}>, here is a list of all recognized '\
            'commands\n'.format(cmd.user)
    for k, v in self._known_cmd.items():
      line = ('• {}\n'.format(k) if v[1] == '' else
              '• {}    {}\n'.format(k, v[1]))
      msg += line
    # Insert into blocks in order to have markdown formatting
    blocks = {'type': 'section',
              'text': {'type': 'mrkdwn',
                       'text': msg}}
    cmd.client.chat_postMessage(channel=cmd.channel, blocks=[blocks])

  def _add_keyords_callback(self, cmd):
    """
    Add new keyword
    :param cmd: Command
    """
    new_kw = cmd.args.split(' ')
    for kw in new_kw:
      kw = kw.lower()
      if kw not in self._keywords:
        self._keywords.append(kw)
    # Save
    self._save_config(self._cache_folder)
    # User feedback
    msg = 'Added following keywords: {}'.format(new_kw)
    cmd.client.chat_postMessage(channel=cmd.channel, text=msg)

  def _list_keyords_callback(self, cmd):
    """
    List all keywords
    :param cmd: Command
    """
    msg = 'List of _keywords_ of interest:\n'
    for kw in self._keywords:
      msg += '• {}\n'.format(kw)
    # Insert into blocks in order to have markdown formatting
    blocks = {'type': 'section',
              'text': {'type': 'mrkdwn',
                       'text': msg}}
    cmd.client.chat_postMessage(channel=cmd.channel, blocks=[blocks])

  def _run_daily_arxiv_search(self, cmd):
    """
    Run daily arxiv search for new papers
    :param cmd: Command
    """
    articles = self._arxiv.run_daily_search(self._keywords)
    # Format output similar to slack's block kit template
    # Header
    msg = 'Found *{} papers* on Arxiv, {}'.format(len(articles),
                                                  datetime.today().strftime('%Y-%m-%d'))
    blocks = [{'type': 'section',
               'text': {'type': 'mrkdwn',
                        'text': msg}},
              ]
    # Body
    for k, art in enumerate(articles):
      # Create body content
      authors = ', '.join(art.authors)
      msg = '[{}/{}] *<{}|{}>*\n_*Author(s)*:_ {}\n_{}_'.format(k + 1,
                                                                len(articles),
                                                                art.link,
                                                                art.title,
                                                                authors,
                                                                art.summary)
      bloc = [{'type': 'divider'},
              {'type': 'section',
               'text': {'type': 'mrkdwn',
                        'text': msg}}
              ]
      blocks.extend(bloc)

    for k in range(0, len(blocks), 50):
      # k=0, 50, 100, ...
      start = k
      stop = k + 50
      bck = blocks[start:stop]
      # Post batch of blocks since there is a limit of 50 blocks per layout
      # See: https://api.slack.com/reference/block-kit/blocks
      cmd.client.chat_postMessage(channel=cmd.channel, blocks=bck)


if __name__ == "__main__":
  #  Create message dispatcher
  p = ArgumentParser('PaperBot')
  p.add_argument('--cache_folder',
                 type=str,
                 default='',
                 help='Location where to cache data')
  p.add_argument('--channel',
                 type=str,
                 default='#paperbot_debug',
                 help='Name of the channel where the bot live')
  args = p.parse_args()

  # Start bot
  dispatcher = MessageDispatcher(token=environ['SLACK_BOT_TOKEN'],
                                 channel=args.channel,
                                 cache=args.cache_folder)
