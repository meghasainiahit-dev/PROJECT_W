from django import template

register = template.Library()


@register.filter
def moneyfmt(value):
    try:
        return f"{value:,.2f}"
    except (TypeError, ValueError):
        return "0.00"
