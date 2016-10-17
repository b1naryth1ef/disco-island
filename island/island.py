from __future__ import print_function

import random
import gevent
import time

from collections import defaultdict

from disco.bot import Plugin, Config


def weighted_random(obj):
    total = sum(obj.values())
    choice = random.randint(1, total)

    for k, v in obj.items():
        choice -= v
        if choice <= 0:
            return k


class IslandPluginConfig(Config):
    servers = {}
    admin_roles = []


@Plugin.with_config(IslandPluginConfig)
class IslandPlugin(Plugin):
    def load(self):
        super(IslandPlugin, self).load()

        self.messages = {}
        self.next_vote = {}
        self.votes = {}
        self.vote_messages = {}

        for server in self.config.servers.values():
            for cid, cfg in server['channels'].items():
                self.messages[cid] = defaultdict(int)
                self.vote_messages[cid] = set()
                self.spawn(self.loop, cid, cfg)

    @Plugin.pre_command()
    def pre_command(self, event, args, kwargs):
        if not event.msg.guild or event.msg.guild.id not in self.config.servers:
            return

        member = event.msg.guild.get_member(event.msg.author)

        if not set(member.roles) & set(self.config.admin_roles):
            return

        return event

    def get_channel_for_message(self, event):
        if event.channel.id not in self.messages:
            if event.guild.id not in self.config.servers:
                return None
            else:
                return self.state.channels.get(self.config.servers[event.guild.id]['channels'].keys()[0])
        return self.state.channels.get(event.channel.id)

    @Plugin.command('status')
    def status(self, event):
        channel = self.get_channel_for_message(event)
        if not channel:
            event.msg.reply('Cannot find a vote channel for this server')
            return

        event.msg.reply('{} total users have sent messages, vote begins in {} seconds'.format(
            len(self.messages[channel.id]),
            int(self.next_vote[channel.id] - time.time())
        ))

    @Plugin.command('vote [size:int] [time:int]')
    def vote(self, event, size=None, time=None):
        channel = self.get_channel_for_message(event)
        if not channel:
            event.msg.reply('Cannot find a vote channel for this server')
            return

        config = self.config.servers[channel.guild.id]['channels'][channel.id]
        self.next_vote[channel.id] = time.time() + config['interval']
        self.process_vote(channel.id, time or config['vote_time'], size or config['pool_size'])

    @Plugin.listen('MessageCreate')
    def on_message_create(self, event):
        if event.author.id == self.state.me.id or event.channel.id not in self.messages:
            return

        if event.channel.id in self.votes:
            if event.mentions and event.without_mentions == '':
                for mention in event.mentions:
                    member = event.channel.guild.get_member(mention)
                    if member in self.votes[event.channel.id]:
                        self.votes[event.channel.id][member].add(event.author.id)
                        self.vote_messages[event.channel.id].add(event.message)
        else:
            member = event.channel.guild.get_member(event.author)
            roles = set(self.config.servers[event.channel.guild.id]['ignore_roles'])
            if roles & set(member.roles) or member.owner:
                return

            self.messages[event.channel.id][event.author.id] += 1

    def format_votes(self, votes):
        votes = reversed(sorted(votes.items(), key=lambda i: i[1]))
        return '\n'.join('{}: {}'.format(k.mention, len(v)) for k, v in votes)

    def process_vote(self, cid, vote_time, pool_size):
        channel = self.state.channels.get(cid)
        channel.send_message(":fire: :exclamation: It's time for someone to leave the island... :fire: :exclamation:")

        # Give us a better mapping to work with
        messages = {
            channel.guild.get_member(k): v
            for k, v in self.messages[cid].items() if k in channel.guild.members
        }

        tributes = []
        for _ in range(pool_size):
            if not len(messages):
                break
            k = weighted_random(messages)
            tributes.append(k)
            del messages[k]

        # Set up vote mapping
        self.votes[channel.id] = {i: set() for i in tributes}

        channel.send_message('The following tributes have been selected: \n{}'.format(
            '\n   '.join(map(lambda i: i.mention, tributes)) + '\nVote now by mentioning them!'
        ))

        # If you set vote_time to something less than 11 fuck off
        gevent.sleep(vote_time - 10)

        channel.send_message('10 seconds remaining: \n{}'.format(self.format_votes(self.votes[channel.id])))

        gevent.sleep(10)

        # Delete all the messages sent by people when voting
        try:
            channel.delete_messages_bulk(self.vote_messages[channel.id])
        except:
            pass

        self.vote_messages[channel.id] = set()

        # Stop the voting and tally
        votes = self.votes.pop(channel.id)

        # If nobody voted, kick 'em all
        if not sum(map(len, votes.values())):
            channel.send_message(':exclamation: NO VOTES - ENGAGING EMERGENCY PURGE PROTOCOL :exclamation:')
            member = random.choice(votes.keys())
        else:
            member = max(votes.items(), key=lambda i: i[1])[0]

        channel.send_message(':pray: Any last words for {}? :pray:'.format(member.mention))
        gevent.sleep(5)
        member.kick()

        emojis = ':coffin: :skull_crossbones:'

        channel.send_message(
            '{} {} HAS BEEN KICKED OFF THE ISLAND {}'.format(
                emojis,
                member.nick or member.user.username,
                emojis))

    def loop(self, channel, config):
        interval = config.get('interval', 3600)
        vote_time = config.get('vote_time', 90)
        pool_size = config.get('pool_size', 5)
        need_messages = config.get('need_messages', 10)

        # Set first vote time
        self.next_vote[channel] = time.time() + interval

        while True:
            # Inner loop, this allows us to "reschedule" votes
            while time.time() < self.next_vote[channel]:
                print('Waiting {} seconds'.format(self.next_vote[channel] - time.time()))
                gevent.sleep(self.next_vote[channel] - time.time())

            if channel in self.votes:
                continue

            if need_messages and len(self.messages[channel]) < need_messages:
                continue

            self.process_vote(channel, vote_time, pool_size)
