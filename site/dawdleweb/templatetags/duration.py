from django import template

register = template.Library()

def plural(num, singlestr='', pluralstr='s'):
    """Return singlestr when num is 1, otherwise pluralstr."""
    if num == 1:
        return singlestr
    return pluralstr

def duration(secs):
    d, secs = int(secs / 86400), secs % 86400
    h, secs = int(secs / 3600), secs % 3600
    m, secs = int(secs / 60), secs % 60
    return f"{d} day{plural(d)}, {h:02d}:{m:02d}:{int(secs):02d}"

register.filter(duration)
