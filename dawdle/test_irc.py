import unittest

from dawdle import conf
from dawdle import irc

class FakeBot():

    def nick_changed(self, old, new):
        pass


class TestIRCMessage(unittest.TestCase):
    def test_basic(self):
        line = "@time=2021-07-31T13:55:00;bar=baz :nick!example@example.com PART #example :later!"
        msg = irc.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {"time": "2021-07-31T13:55:00", "bar": "baz"})
        self.assertEqual(msg.src, "nick")
        self.assertEqual(msg.user, "example")
        self.assertEqual(msg.host, "example.com")
        self.assertEqual(msg.cmd, "PART")
        self.assertEqual(msg.args, ["#example", "later!"])
        self.assertEqual(msg.trailing, "later!")
        self.assertEqual(msg.line, line)
        self.assertEqual(msg.time, 1627754100)

    def test_one_trailing_arg(self):
        line = ":foo!bar@example.com NICK :baz"
        msg = irc.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "foo")
        self.assertEqual(msg.user, "bar")
        self.assertEqual(msg.host, "example.com")
        self.assertEqual(msg.cmd, "NICK")
        self.assertEqual(msg.args, ["baz"])
        self.assertEqual(msg.trailing, "baz")
        self.assertEqual(msg.line, line)

    def test_complextags(self):
        line = "@keyone=one\\sbig\\:value;keytwo=t\\wo\\rbig\\n\\\\values :nick!example@example.com PART #example :later!"
        msg = irc.IRCClient.parse_message(None, line)
        self.assertEqual(msg.tags, {
            "keyone": "one big;value",
            "keytwo": "two\rbig\n\\values",
            })


    def test_notags(self):
        line = ":nick!example@example.com PART #example :later!"
        msg = irc.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_badtags(self):
        line = "@asdf :nick!example@example.com PART #example :later!"
        msg = irc.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {'asdf': None})
        self.assertEqual(msg.src, "nick")

        line = "@ :nick!example@example.com PART #example :later!"
        msg = irc.IRCClient.parse_message(None,line)
        self.assertEqual(msg.tags, {})
        self.assertEqual(msg.src, "nick")

    def test_bad_encoding(self):
        line = "\255\035"
        msg = irc.IRCClient.parse_message(None, line)


class TestIRCClient(unittest.TestCase):

    def test_handle_cap(self):
        conf._conf['botnick'] = 'foo'
        client = irc.IRCClient(None)
        client.handle_cap(irc.IRCClient.Message(tags={}, src='tungsten.libera.chat', user=None, host=None, cmd='CAP', args=['*', 'ACK', 'multi-prefix'], trailing='multi-prefix', line=':tungsten.libera.chat CAP * ACK :multi-prefix', time=1629501206))
        self.assertIn("multi-prefix", client._caps)


    def test_nick_change(self):
        conf._conf['botnick'] = 'dawdlerpg'
        testbot = FakeBot()
        client = irc.IRCClient(testbot)
        client.handle_join(irc.IRCClient.Message(tags={}, src='foo', user=None, host=None, cmd='NICK', args=['#dawdlerpg'], trailing='', line='', time=0))
        client.handle_nick(irc.IRCClient.Message(tags={}, src='foo', user=None, host=None, cmd='NICK', args=['bar'], trailing='bar', line='', time=0))
        self.assertNotIn('foo', client._users)
        self.assertIn('bar', client._users)
