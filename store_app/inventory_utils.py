# store_app/inventory_utils.py
"""
All serial / ProductUnit business logic lives here.
Views stay thin.
"""
from django.db import transaction
from .models import Inventory, ProductUnit


# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — Add stock: create ProductUnit rows
# ──────────────────────────────────────────────────────────────────────────────
# inventory_utils.py — replace add_inventory_with_serials ============================================================

def add_inventory_with_serials(product, quantity: int, reason_note: str = "") -> list[str]:
    with transaction.atomic():
        inv, _ = Inventory.objects.select_for_update().get_or_create(
            product=product, defaults={"quantity": 0}
        )

        # ── find last sequence number ──────────────────────────────────────
        # Use DB MAX on the integer suffix to avoid alphabetic sort bugs
        all_serials = (
            ProductUnit.objects
            .filter(product=product)
            .values_list("serial_number", flat=True)
        )

        last_seq = 0
        for s in all_serials:
            try:
                num = int(s.rsplit("-", 1)[-1])
                if num > last_seq:
                    last_seq = num
            except (ValueError, IndexError):
                pass

        # ── bulk-create units ──────────────────────────────────────────────
        units = [
            ProductUnit(
                product=product,
                serial_number=f"{product.sku}-{str(last_seq + i + 1).zfill(5)}",
                status="in_stock",
            )
            for i in range(quantity)
        ]
        ProductUnit.objects.bulk_create(units)

        inv.quantity += quantity
        inv.save(update_fields=["quantity"])

    return [u.serial_number for u in units]
# ===============================================================================================
# def add_inventory_with_serials(product, quantity: int, reason_note: str = "") -> list[str]:
#     """
#     1. Finds the highest existing serial sequence number for this product.
#     2. Creates `quantity` new ProductUnit rows (in_stock).
#     3. Increments Inventory.quantity by `quantity`.
#     Returns list of generated serial_numbers.
#     """
#     with transaction.atomic():
#         # ── lock inventory row ─────────────────────────────────────────────
#         inv, _ = Inventory.objects.select_for_update().get_or_create(
#             product=product, defaults={"quantity": 0}
#         )

#         # ── find next sequence number ──────────────────────────────────────
#         # serial_number format: SKU-00001  (last segment is the counter)
#         existing = (
#             ProductUnit.objects
#             .filter(product=product)
#             .order_by("-serial_number")
#             .values_list("serial_number", flat=True)
#             .first()
#         )
#         if existing:
#             last_seq = int(existing.rsplit("-", 1)[-1])
#         else:
#             last_seq = 0

#         # ── bulk-create units ──────────────────────────────────────────────
#         units = [
#             ProductUnit(
#                 product=product,
#                 serial_number=f"{product.sku}-{str(last_seq + i + 1).zfill(5)}",
#                 status="in_stock",
#             )
#             for i in range(quantity)
#         ]
#         ProductUnit.objects.bulk_create(units)

#         # ── update inventory counter ───────────────────────────────────────
#         inv.quantity += quantity
#         inv.save(update_fields=["quantity"])

#     return [u.serial_number for u in units]


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — Allocate serials for an order (atomic, race-condition safe)
# ──────────────────────────────────────────────────────────────────────────────

def allocate_serials_for_order(product, quantity: int, order) -> list[str]:
    from django.db import transaction

    with transaction.atomic():

        # 🔒 Lock inventory
        try:
            inv = Inventory.objects.select_for_update().get(product=product)
        except Inventory.DoesNotExist:
            raise ValueError(
                f"No inventory record found for {product.name}."
            )

        if inv.quantity < quantity:
            raise ValueError(
                f"Not enough stock for {product.name}. "
                f"Available: {inv.quantity}, Requested: {quantity}."
            )

        # 🧠 AUTO-SYNC BLOCK (Important Part)
        in_stock_count = ProductUnit.objects.filter(
            product=product, status="in_stock"
        ).count()

        # Agar inventory counter jyada hai aur serial kam hain
        if in_stock_count < inv.quantity:

            missing = inv.quantity - in_stock_count

            # Last serial find karo
            last = (
                ProductUnit.objects
                .filter(product=product)
                .order_by("-serial_number")
                .values_list("serial_number", flat=True)
                .first()
            )

            last_seq = int(last.rsplit("-", 1)[-1]) if last else 0

            new_units = [
                ProductUnit(
                    product=product,
                    serial_number=f"{product.sku}-{str(last_seq + i + 1).zfill(5)}",
                    status="in_stock",
                )
                for i in range(missing)
            ]

            ProductUnit.objects.bulk_create(new_units, ignore_conflicts=True)

        # 🔒 Now lock and allocate
        units = list(
            ProductUnit.objects
            .select_for_update()
            .filter(product=product, status="in_stock")
            .order_by("serial_number")[:quantity]
        )

        if len(units) < quantity:
            raise ValueError(
                f"Not enough serial units for {product.name}. "
                f"Requested {quantity}, available {len(units)}."
            )

        ProductUnit.objects.filter(
            id__in=[u.id for u in units]
        ).update(status="sold", order=order)

        inv.quantity -= quantity
        inv.save(update_fields=["quantity"])

    return [u.serial_number for u in units]


# def allocate_serials_for_order(product, quantity: int, order) -> list[str]:
#     """
#     Selects `quantity` in_stock ProductUnit rows with a SELECT FOR UPDATE,
#     marks them sold, links them to the order, and decrements Inventory.
#     Raises ValueError if insufficient stock.
#     """
#     with transaction.atomic():
#         # ── lock exactly `quantity` in_stock units ─────────────────────────
#         units = list(
#             ProductUnit.objects
#             .select_for_update()
#             .filter(product=product, status="in_stock")
#             .order_by("serial_number")[:quantity]
#         )


#         if len(units) < quantity:
#             raise ValueError(
#                 f"Not enough serial units for {product.name}. "
#                 f"Requested {quantity}, available {len(units)}."
#             )

#         unit_ids = [u.id for u in units]

#         # ── bulk-update status to sold ─────────────────────────────────────
#         ProductUnit.objects.filter(id__in=unit_ids).update(
#             status="sold", order=order
#         )

#         # ── decrement inventory (lock first) ──────────────────────────────
#         try:
#             inv = Inventory.objects.select_for_update().get(product=product)
#         except Inventory.DoesNotExist:
#             raise ValueError(
#                 f"No inventory record found for {product.name}. "
#                 f"Please add stock before placing an order."
#             )
#         # inv = Inventory.objects.select_for_update().get(product=product)
#         # if inv.quantity < quantity:
#         #     raise ValueError(
#         #         f"Inventory counter mismatch for {product.name}."
#         #     )
#         inv.quantity -= quantity
#         inv.save(update_fields=["quantity"])

#     return [u.serial_number for u in units]


# ──────────────────────────────────────────────────────────────────────────────
# STEP 5 — Barcode generation (read-only, zero stock impact)
# ──────────────────────────────────────────────────────────────────────────────

def get_printable_serials(product, quantity: int | None = None) -> list[str]:
    """
    Returns serial numbers available for printing.
    - If quantity is None  → returns ALL in_stock serials.
    - If quantity is given → returns up to `quantity` in_stock serials.
    NO inventory change.
    """
    qs = (
        ProductUnit.objects
        .filter(product=product, status="in_stock")
        .order_by("serial_number")
    )
    if quantity is not None:
        qs = qs[:quantity]
    return list(qs.values_list("serial_number", flat=True))


def get_order_serials(product, order) -> list[str]:
    """Returns serials already assigned to a specific order+product."""
    return list(
        ProductUnit.objects
        .filter(product=product, order=order, status="sold")
        .order_by("serial_number")
        .values_list("serial_number", flat=True)
    )