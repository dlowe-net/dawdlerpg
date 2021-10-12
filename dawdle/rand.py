import random


overrides = {}


def randomly(key, odds):
    """Overrideable random func which returns true at 1:ODDS odds."""
    if key in overrides:
        return overrides[key]
    return random.randint(0, odds-1) < 1


def randint(key, bottom, top):
    """Overrideable random func which returns an integer bottom <= i <= top."""
    if key in overrides:
        return overrides[key]
    return random.randint(bottom, top)


def gauss(key, mu, sigma):
    """Overrideable func which returns an random int with gaussian distribution."""
    if key in overrides:
        return overrides[key]
    return int(random.gauss(mu, sigma))


def sample(key, seq, count):
    """Overrideable random func which returns random COUNT elements of SEQ."""
    if key in overrides:
        return overrides[key]
    return random.sample(seq, count)


def choice(key, seq):
    """Overrideable random func which returns one random element of SEQ."""
    if key in overrides:
        return overrides[key]
    # Don't use random.choice here - it uses random access, which
    # is unsupported by the dict_keys view.
    return random.sample(seq, 1)[0]


def shuffle(key, seq):
    """Overrideable random func which does an in-place shuffle of SEQ."""
    if key in overrides:
        return overrides[key]
    random.shuffle(seq)
