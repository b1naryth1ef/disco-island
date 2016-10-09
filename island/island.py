from __future__ import print_function

import random
import gevent

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
    channels = [
        234458992544448514
    ]

    ignores_roles = []

    interval = 60 * 60
    vote_time = 60 * 2

    pool_size = 5


@Plugin.with_config(IslandPluginConfig)
class IslandPlugin(Plugin):
    def load(self):
        super(IslandPlugin, self).load()

        self.messages = {
            k: defaultdict(int) for k in self.config.channels
        }

        self.votes = {}

        self.ignore_roles = set(self.config.ignore_roles)

        self.register_schedule(self.loop, self.config.interval, init=False)

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
                        try:
                            event.message.delete()
                        except:
                            print("Can't delete")
        else:
            member = event.channel.guild.get_member(event.author)
            if len(set(self.ignore_roles) & set(member.roles)) or member.owner:
                return

            self.messages[event.channel.id][event.author.id] += 1

    def format_votes(self, votes):
        votes = reversed(sorted(votes.items(), key=lambda i: i[1]))
        return '\n'.join('{}: {}'.format(k.mention, len(v)) for k, v in votes)

    def process_vote(self, channel, messages):
        channel.send_message(":fire: :exclamation: It's time for someone to leave the island... :fire: :exclamation:")

        # Give us a better mapping to work with
        messages = {
            channel.guild.get_member(k): v for k, v in messages.items() if k in channel.guild.members
        }

        tributes = []
        for _ in range(self.config.pool_size):
            if not len(messages):
                break
            k = weighted_random(messages)
            tributes.append(k)
            del messages[k]

        # Set up vote mapping
        self.votes[channel.id] = {i: set() for i in tributes}

        channel.send_message('The following tributes have been selected: \n{}'.format(
            '\n   '.join(map(lambda i: i.mention, tributes)) + 'Vote now by mentioning them!'
        ))

        # If you set vote_time to something less than 11 fuck off
        gevent.sleep(self.config.vote_time - 10)

        channel.send_message('10 seconds remaining: \n{}'.format(self.format_votes(self.votes[channel.id])))

        gevent.sleep(10)

        # Stop the voting and tally
        votes = self.votes.pop(channel.id)

        # If nobody voted, kick 'em all
        if not sum(map(len, votes.values())):
            channel.send_message(':exclamation: NO VOTES - ENGAGING EMERGENCY PURGE PROTOCOL :exclamation:')
            random.choice(votes.keys()).kick()
        else:
            member = max(votes.items(), key=lambda i: i[1])[0]
            channel.send_message(':pray: Any last words for {}? :pray:'.format(member.mention))
            gevent.sleep(2)
            member.kick()

    def loop(self):
        for cid, messages in self.messages.items():
            if cid in self.votes:
                return
            # Ignore channels where less than 10 people have spoke
            if len(messages) < 10:
                continue
            self.spawn(self.process_vote, self.state.channels.get(cid), messages)
