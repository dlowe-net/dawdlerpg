import itertools
from typing import Iterable, Iterator, Tuple, TypeVar


T = TypeVar("T")


def chunk(iterable: Iterable[T], n: int) -> Iterator[Tuple[T, ...]]:
    """Collect data into chunks of size not more than n.

    The last chunk may be a different length than n.
    chunk('ABCDEFG', 3) --> ABC DEF G
    """
    iterator = iter(iterable)
    while True:
        group = tuple(itertools.islice(iterator, 0, n))
        if not group:
            break
        yield group


def padded_chunk(iterable: Iterable[T], n: int, pad: T) -> Iterator[Tuple[T, ...]]:
    """Collect data into chunks of exactly n elements.

    The chunks will all be the same size, padded with the pad value.
    padded_chunk('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    """
    iterator = iter(iterable)
    while True:
        group = list(itertools.islice(iterator, 0, n))
        if not group:
            break
        group.extend(itertools.repeat(pad, n - len(group)))
        yield tuple(group)
