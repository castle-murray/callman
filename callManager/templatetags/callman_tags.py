# callManager/templatetags/callman_tags.py
from django import template
from datetime import datetime, timedelta

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def subtract(value, arg):
    try:
        return int(value) - int(arg)
    except (ValueError, TypeError):
        return value  # Return original value if subtraction fails

@register.filter
def add_hours(time, hours):
    if time:
        return (datetime.combine(datetime.today(), time) + timedelta(hours=int(hours))).time()
    return time
