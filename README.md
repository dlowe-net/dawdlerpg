# DawdleRPG

DawdleRPG is an IdleRPG clone written in Python.

## Basic Setup

- Edit `dawdle.conf` to configure your bot.
- Run `dawdle.py <path to dawdle.conf>`
- The data directory defaults to the parent directory of the
  configuration file, and dawdlerpg expects files to be in that
  directory.

## Setup with Website

The included `install.sh` script will set up the dawdlerpg bot and
website on a freshly installed Debian system.  It uses nginx, uwsgi,
and django for the site.  At some point, you should be prompted to
edit the dawdle.conf file, and you'll need to edit some configuration
parameters explained by the comments in the file.

```sh
./install.sh <hostname>
```

If you don't have a clean install, you should instead look at the
`install.sh` script and use the pieces that work for your setup.

## Migrating from IdleRPG

DawdleRPG is capable of being a drop-in replacement.

- Run `dawdle.py <path to old irpg.conf>`

If you have any command line overrides to the configuration, you will
need to replace them with the `-o key=value` option.

## Differences from IdleRPG

- Names, items, and durations are in different colors.
- Output throttling allows configurable rate over a period.
- Long messages are word wrapped.
- Logging can be set to different levels.
- Better IRC protocol support.
- More game numbers are configurable.
- Quest pathfinding is much more efficient.
- Fights caused by map collisions have chance of finding item.
- All worn items have a chance to get buffs/debuffs instead of a subset.
