#!/usr/bin/python3

import dawdle
import os.path
import random
import sys
import tempfile
import unittest

class TestPlayerDB(unittest.TestCase):
    def test_db(self):
        dawdle.conf['rpbase'] = 600
        with tempfile.TemporaryDirectory() as tmpdir:
            db = dawdle.PlayerDB(os.path.join(tmpdir, 'dawdle_test.db'))
            self.assertFalse(db.exists())
            db.create()
            p = db.new_player('foo', 'bar', 'baz')
            p.online = True
            db.write()
            self.assertTrue(db.exists())
            db.load()
            self.assertEqual(db['foo'].name, 'foo')
            self.assertEqual(db['foo'].online, True)
            db.close()

    def test_passwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = dawdle.PlayerDB(os.path.join(tmpdir, 'dawdle_test.db'))
            self.assertFalse(db.exists())
            db.create()
            p = db.new_player('foo', 'bar', 'baz')
            self.assertTrue(db.check_login('foo', 'baz'))
            self.assertFalse(db.check_login('foo', 'azb'))
            p.set_password('azb')
            self.assertTrue(db.check_login('foo', 'azb'))
            db.close()


class TestIRCMessage(unittest.TestCase):
    def test_basic(self):
        line = "@time=2021-07-31T13:55:00,bar=baz :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {"time": "2021-07-31T13:55:00", "bar": "baz"})
        self.assertEqual(msg.src, "nick")
        self.assertEqual(msg.user, "example")
        self.assertEqual(msg.host, "example.com")
        self.assertEqual(msg.cmd, "PART")
        self.assertEqual(msg.args, ["#example", "later!"])
        self.assertEqual(msg.trailing, "later!")
        self.assertEqual(msg.line, line)
        self.assertEqual(msg.time, 1627754100)

    def test_notags(self):
        line = ":nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_badtags(self):
        line = "@asdf :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {'asdf': None})
        self.assertEqual(msg.src, "nick")

        line = "@ :nick!example@example.com PART #example :later!"
        msg = dawdle.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_bad_encoding(self):
        line = "\255\035"
        msg = dawdle.IRCClient.parse_message(None, line)


class FakeIRCClient(object):
    def __init__(self):
        self.chanmsgs = []
        self.notices = {}

    def chanmsg(self, text):
        self.chanmsgs.append(text)

    def notice(self, nick, text):
        self.notices[nick] = self.notices.get(nick, []).append(text)

class FakePlayerDB(object):
    def __init__(self):
        pass


    def write(self):
        pass

class TestTeamBattle(unittest.TestCase):


    def setUp(self):
        dawdle.conf['rpbase'] = 600
        self.bot = dawdle.DawdleBot(None)
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_setup_insufficient_players(self):
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcde"]
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs, [])


    def test_win(self):
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcdef"]
        op[0].amulet, op[0].nextlvl = 20, 1200
        op[1].amulet, op[1].nextlvl = 20, 3600
        op[2].amulet, op[2].nextlvl = 20, 3600
        op[3].amulet, op[3].nextlvl = 40, 3600
        op[4].amulet, op[4].nextlvl = 40, 3600
        op[5].amulet, op[5].nextlvl = 40, 3600
        self.bot._overrides = {
            'team_battle_members': op,
            'team_a_roll': 60,
            'team_b_roll': 30
        }
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs[0], "a, b, and c [60/60] have team battled d, e, and f [30/120] and won!  0 days, 00:04:00 is removed from their clocks.")

    def test_loss(self):
        op = [dawdle.Player.new_player(pname, 'a', 'b') for pname in "abcdef"]
        op[0].amulet, op[0].nextlvl = 20, 1200
        op[1].amulet, op[1].nextlvl = 20, 3600
        op[2].amulet, op[2].nextlvl = 20, 3600
        op[3].amulet, op[3].nextlvl = 40, 3600
        op[4].amulet, op[4].nextlvl = 40, 3600
        op[5].amulet, op[5].nextlvl = 40, 3600
        self.bot._overrides = {
            'team_battle_members': op,
            'team_a_roll': 30,
            'team_b_roll': 60
        }
        self.bot.team_battle(op)
        self.assertEqual(self.irc.chanmsgs[0], "a, b, and c [30/60] have team battled d, e, and f [60/120] and lost!  0 days, 00:04:00 is added to their clocks.")

        
class TestHandOfGod(unittest.TestCase):


    def setUp(self):
        dawdle.conf['rpbase'] = 600
        self.bot = dawdle.DawdleBot(FakePlayerDB())
        self.irc = FakeIRCClient()
        self.bot.connected(self.irc)


    def test_forward(self):
        op = [dawdle.Player.new_player('a', 'b', 'c')]
        self.bot._overrides = {
            'hog_effect': True,
            'hog_amount': 10
        }
        self.bot.hand_of_god(op)
        self.assertEqual(self.irc.chanmsgs[0], "Verily I say unto thee, the Heavens have burst forth, and the blessed hand of God carried a 0 days, 00:01:30 toward level 1.")
        self.assertEqual(self.irc.chanmsgs[1], "a reaches next level in 0 days, 00:08:30.")


    def test_back(self):
        op = [dawdle.Player.new_player('a', 'b', 'c')]
        self.bot._overrides = {
            'hog_effect': False,
            'hog_amount': 10
        }
        self.bot.hand_of_god(op)
        self.assertEqual(self.irc.chanmsgs[0], "Thereupon He stretched out His little finger among them and consumed a with fire, slowing the heathen 0 days, 00:01:30 from level 1.")
        self.assertEqual(self.irc.chanmsgs[1], "a reaches next level in 0 days, 00:11:30.")


if __name__ == "__main__":
    unittest.main()
