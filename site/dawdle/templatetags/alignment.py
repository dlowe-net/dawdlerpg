from django import template

register = template.Library()

def alignment(align):
    return {"g": "good", "n":"neutral", "e":"evil"}[align]

register.filter(alignment)
