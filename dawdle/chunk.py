#!/usr/bin/python3

import itertools
import sys
from typing import Iterable, Iterator, Generator, Tuple, TypeVar

T = TypeVar("T")

def chunk(iterable: Iterable[T], n: int) -> Iterator[Tuple[T, ...]]:
    """Collect data into chunks of size not more than n.

    The la
    chunk('ABCDEFG', 3) --> ABC DEF G
    """
    iterator = iter(iterable)
    group = list()
    while True:
        try:
            for _ in range(0,n):
                group.append(next(iterator))
            yield tuple(group)
            group.clear()
        except StopIteration:
            if group:
                yield tuple(group)
            break


def padded_chunk(iterable: Iterable[T], n: int, pad: T) -> Iterator[Tuple[T, ...]]:
    """Collect data into chunks of exactly n elements.

    The chunks will all be the same size, padded with the pad value.
    padded_chunk('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    """
    iterator = iter(iterable)
    group = list()
    while True:
        try:
            for _ in range(0,n):
                group.append(next(iterator))
            yield tuple(group)
            group.clear()
        except StopIteration:
            if group:
                group.extend(itertools.repeat(pad, n - len(group)))
                yield tuple(group)
            break
