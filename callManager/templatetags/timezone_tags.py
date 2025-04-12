from django import template
import pytz

register = template.Library()

@register.filter
def in_manager_timezone(value, manager):
    if value and manager.timezone:
        manager_tz = pytz.timezone(manager.timezone)
        return value.astimezone(manager_tz)
    return value
