from django import template

register = template.Library()


@register.filter
def yen(value):
    """金額を 3桁区切りの円表記にする(例: 12345 → ¥12,345、-500 → -¥500)"""
    value = int(value)
    sign = '-' if value < 0 else ''
    return f'{sign}¥{abs(value):,}'
