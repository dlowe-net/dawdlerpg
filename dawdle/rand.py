import random
from typing import cast, Any, Dict, List, MutableSequence, Sequence, TypeVar

T = TypeVar("T")


overrides: Dict[str,Any] = {}


def randomly(key: str, odds: int) -> bool:
    """Overrideable random func which returns true at 1:ODDS odds."""
    if key in overrides:
        return cast(bool, overrides[key])
    return random.randint(0, odds-1) < 1


def randint(key: str, bottom: int, top: int) -> int:
    """Overrideable random func which returns an integer bottom <= i <= top."""
    if key in overrides:
        return cast(int, overrides[key])
    return random.randint(int(bottom), int(top))


def gauss(key: str, mu: float, sigma: float) -> int:
    """Overrideable func which returns an random int with gaussian distribution."""
    if key in overrides:
        return cast(int, overrides[key])
    return int(random.gauss(mu, sigma))

def sample(key: str, seq: Sequence[T], count: int) -> List[T]:
    """Overrideable random func which returns random COUNT elements of SEQ."""
    if key in overrides:
        return cast(List[T], overrides[key])
    return random.sample(seq, count)


def choice(key: str, seq: Sequence[T]) -> T:
    """Overrideable random func which returns one random element of SEQ."""
    if key in overrides:
        return cast(T, overrides[key])
    # Don't use random.choice here - it uses random access, which
    # is unsupported by the dict_keys view.
    return random.sample(seq, 1)[0]


def shuffle(key: str, seq: MutableSequence[Any]) -> None:
    """Overrideable random func which does an in-place shuffle of SEQ."""
    if key in overrides:
        seq.clear()
        seq.extend(overrides[key])
        return None
    random.shuffle(seq)
    return None
