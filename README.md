# README

Slack Bot for automatic keyword-based search on ArXiv.

## Installation

The Bot is only compatible with python 3. To install the dependencies just call

- `pip3 install -r requirements.txt`

## Usage

In order to connect to Slack service, the Bot need to have an API token. This token is provided through environment variable, you need to define `SLACK_BOT_TOKEN=XXX`.

Then just start the script `bot.py` to make your bot live. The following parameters are required

- `--channel <Name>`, which defines the name of the channel where your bot will leave. At the moment only one channel is supported.
- `--cache_folder` is an optional path to the location where the bot will save its configuration. The default location is where the script is.

## Service

The Bot can be automatically started by using the provided `paper_bot.service` file. It creates a service spawning the Bot when the system is started. First you need to edit the file with proper information about the location of the bot.

Then copy the file in `/etc/systemd/system` with root privileges, as for example:

- `sudo cp paper_bot.service /etc/systemd/system/paper_bot.service`

Once this has been copied, you can attempt to start the service using the following command:

- `sudo systemctl start paper_bot.service`

Stop it using following command:

- ``sudo systemctl stop paper_bot.service`

When you are happy that this starts and stops your app, you can have it start automatically on reboot by using this command:

- `sudo systemctl enable paper_bot.service`

