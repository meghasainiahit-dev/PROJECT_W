# inventory/utils.py
from django.db.models import Sum
from .models import OrderItem

def is_popular_product(product):
    total_sold = (
        OrderItem.objects
        .filter(product=product)
        .aggregate(total=Sum("quantity"))
        .get("total") or 0
    )
    return total_sold >= 20


