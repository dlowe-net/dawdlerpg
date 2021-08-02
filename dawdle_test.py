#!/usr/bin/python3

import dawdle
import os.path
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
            self.assertTrue(db.check_login('foo', 'bar'))
            self.assertFalse(db.check_login('foo', 'arb'))
            p.set_password('arb')
            self.assertTrue(db.check_login('foo', 'arb'))
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


if __name__ == "__main__":
    unittest.main()
