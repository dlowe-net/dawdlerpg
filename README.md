# DawdleRPG

DawdleRPG is an IdleRPG clone written in Python.

## Setup

- Edit `dawdle.conf` to configure your bot.
- Run `dawdle.py <path to dawdle.conf>`
- The data directory defaults to the parent directory of the
  configuration file, and dawdlerpg expects files to be in that
  directory.

## Migrating from IdleRPG

DawdleRPG is capable of being a drop-in replacement.

- Run `dawdle.py <path to old irpg.conf>`

If you have any command line overrides to the configuration, you will
need to replace them with the `-o key=value` option.

## Differences from IdleRPG

- Quest pathfinding is much more efficient.
- Fights caused by map collisions have chance of finding item.
- All worn items have a chance to get buffs/debuffs instead of a subset.
