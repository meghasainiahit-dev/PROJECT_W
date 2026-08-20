import io
import json
import os
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .models import Order, Product, Quotation, QuotationItem, QuotationSettings


def money(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def amount_words(value):
    ones = ["Zero","One","Two","Three","Four","Five","Six","Seven","Eight","Nine","Ten","Eleven","Twelve","Thirteen","Fourteen","Fifteen","Sixteen","Seventeen","Eighteen","Nineteen"]
    tens = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"]
    def under1000(n):
        parts=[]
        if n>=100: parts += [ones[n//100],"Hundred"]; n%=100
        if n>=20: parts.append(tens[n//10]); n%=10
        if n: parts.append(ones[n])
        return " ".join(parts)
    n=int(Decimal(value).quantize(Decimal("1"))); parts=[]
    for divisor,label in ((10000000,"Crore"),(100000,"Lakh"),(1000,"Thousand")):
        if n>=divisor: parts += [under1000(n//divisor),label]; n%=divisor
    if n: parts.append(under1000(n))
    return "INR " + (" ".join(parts) or "Zero") + " Only"


def _exact_quotation_html(quote, company):
    """Inject data into the user's exact table.html without changing its design."""
    from bs4 import BeautifulSoup, NavigableString

    source_path = settings.BASE_DIR / "store_app/templates/inventory/quotation_exact_source.html"
    soup = BeautifulSoup(source_path.read_text(encoding="utf-8"), "html.parser")

    def set_lines(element, lines):
        element.clear()
        for index, line in enumerate(lines):
            if index:
                element.append(soup.new_tag("br"))
            element.append(NavigableString(str(line or "")))

    def set_field(label, value):
        span = next((node for node in soup.select(".label") if node.get_text(strip=True) == label), None)
        if not span:
            return
        cell = span.parent
        cell.clear()
        cell.append(span)
        if value not in (None, ""):
            strong = soup.new_tag("strong")
            strong.string = str(value)
            cell.append(strong)

    def fmt_date(value):
        return f"{value.day}-{value.strftime('%b')}-{value.strftime('%y')}" if value else ""

    soup.select_one(".company-name").string = company.company_name or "Company Name"
    company_lines = [line for line in (company.address or "").splitlines() if line]
    company_lines.extend(filter(None, [
        f"GSTIN/UIN: {company.gstin}" if company.gstin else "",
        f"Phone: {company.phone}" if company.phone else "",
        f"E-Mail : {company.email}" if company.email else "",
    ]))
    set_lines(soup.select_one(".company-address"), company_lines)

    set_field("Voucher No.", quote.number)
    set_field("Dated", fmt_date(quote.quote_date))
    set_field("Mode/Terms of Payment", quote.payment_terms)
    set_field("Buyer's Ref./Order No.", quote.buyer_reference)
    set_field("Other References", quote.other_references)
    set_field("Dispatched through", quote.dispatched_through)
    set_field("Destination", quote.destination)
    set_field("Terms of Delivery", quote.delivery_terms)

    parties = soup.select(".party-block-cell")
    party_values = [
        (
            quote.consignee_name or quote.customer_name,
            quote.consignee_address or quote.customer_address,
            quote.consignee_state or quote.customer_state,
            quote.consignee_state_code or quote.customer_state_code,
            quote.consignee_gstin or quote.customer_gstin,
        ),
        (quote.customer_name, quote.customer_address, quote.customer_state, quote.customer_state_code, quote.customer_gstin),
    ]
    for block, (name, address, state, state_code, gstin) in zip(parties, party_values):
        block.select_one(".party-name").string = name or ""
        lines = [line for line in (address or "").splitlines() if line]
        if gstin:
            lines.append(f"GSTIN/UIN: {gstin}")
        lines.append(f"State Name : {state or ''}, Code : {state_code or ''}")
        set_lines(block.select_one(".party-lines"), lines)

    tbody = soup.select_one(".items-table tbody")
    tbody.clear()
    items = list(quote.items.all())

    def add_row(values, classes=None, row_class=None):
        row = soup.new_tag("tr")
        if row_class:
            row["class"] = [row_class]
        for index, value in enumerate(values):
            cell = soup.new_tag("td")
            if classes and classes[index]:
                cell["class"] = classes[index].split()
            if value == "__NBSP__":
                cell.append(NavigableString("\xa0"))
            else:
                cell.string = str(value or "")
            row.append(cell)
        tbody.append(row)
        return row

    total_quantity = Decimal("0")
    for index, item in enumerate(items, 1):
        total_quantity += item.quantity
        add_row(
            [index, item.product_name, fmt_date(item.due_on), f"{item.quantity:g} {item.unit}", f"{item.unit_price:,.2f}", item.unit, f"{item.discount_percentage:g}" if item.discount_percentage else "__NBSP__", f"{item.taxable_amount:,.2f}"],
            ["center", "desc", "center dateval", "num", "num", "center", "center", "amt"],
        )

    subtotal_row = add_row(["__NBSP__", "", "", "", "", "", "", f"{quote.subtotal:,.2f}"], ["", "", "", "", "", "", "", "amt"])
    subtotal_row.find_all("td")[-1]["style"] = "border-top:1px solid #000;"
    gst = items[0].gst_percentage if items else Decimal("0")
    add_row(["__NBSP__", f"OUTPUTIGST@{gst:g}%", "", "", f"{gst:g}", "%", "", f"{quote.tax_total:,.2f}"], ["", "taxline", "", "", "num", "center", "", "taxamt"])
    add_row(["__NBSP__", "Shipping Charges", "", "", "", "", "", f"{quote.shipping_amount:,.2f}"], ["", "taxline", "", "", "", "", "", "taxamt"])
    add_row(["__NBSP__", quote.shipment_details, "", "", "", "", "", ""], ["", "subline", "", "", "", "", "", ""])
    # The source table.html contains exactly five filler rows. Keep that exact
    # count; only their surrounding data rows are dynamic.
    for _ in range(5):
        add_row(["__NBSP__", "", "", "", "", "", "", ""], row_class="filler-row")
    total_row = add_row(["Total", "", "", f"{total_quantity:g} PCS", "", "", "", f"₹ {quote.grand_total:,.2f}"], ["", "", "", "num", "", "", "", "amt"], "total-row")
    first_total_cell = total_row.find_all("td")[0]
    first_total_cell["colspan"] = "2"
    first_total_cell["style"] = "text-align:right;"
    total_row.find_all("td")[1].extract()

    soup.select_one(".amt-words-value").string = amount_words(quote.grand_total)
    soup.select_one(".company-for").string = f"for {company.company_name or 'Company'}"
    return str(soup)


def settings_payload(obj):
    fields = ("company_name","address","gstin","phone","email","bank_name","account_name","account_number","ifsc","branch","terms")
    return {field: getattr(obj, field, "") for field in fields}


def quotation_payload(quote):
    fields = (
        "number", "quote_date", "valid_until", "customer_name", "customer_phone",
        "customer_email", "customer_address", "customer_gstin", "customer_state",
        "customer_state_code", "consignee_name", "consignee_address", "consignee_gstin",
        "consignee_state", "consignee_state_code", "payment_terms", "buyer_reference",
        "other_references", "dispatched_through", "destination", "delivery_terms",
        "shipment_details", "shipping_amount", "notes",
    )
    data = {field: getattr(quote, field) for field in fields}
    for field in ("quote_date", "valid_until"):
        data[field] = data[field].isoformat() if data[field] else ""
    data["shipping_amount"] = str(data["shipping_amount"])
    data["items"] = [{
        "id": item.id, "product_id": item.product_id, "product_name": item.product_name,
        "sku": item.sku, "hsn_code": item.hsn_code,
        "due_on": item.due_on.isoformat() if item.due_on else "", "unit": item.unit,
        "discount_percentage": str(item.discount_percentage), "quantity": str(item.quantity),
        "unit_price": str(item.unit_price), "gst_percentage": str(item.gst_percentage),
        "taxable_amount": str(item.taxable_amount), "tax_amount": str(item.tax_amount),
        "total_amount": str(item.total_amount),
    } for item in quote.items.all()]
    return data


def save_quotation(data, user, quote=None):
    items = data.get("items") or []
    if not str(data.get("customer_name", "")).strip() or not items:
        raise ValueError("Customer and at least one product are required.")
    if any(money(row.get("gst_percentage")) not in (Decimal("5.00"), Decimal("18.00")) for row in items):
        raise ValueError("Each product GST must be 5% or 18%.")
    if any(money(row.get("quantity")) <= 0 for row in items):
        raise ValueError("Product quantity must be greater than zero.")
    number = (data.get("number") or f"QT-{date.today():%Y%m%d}-{Quotation.objects.count()+1:04d}")[:40]
    duplicate = Quotation.objects.filter(number=number)
    if quote:
        duplicate = duplicate.exclude(pk=quote.pk)
    if duplicate.exists():
        raise ValueError("This quotation number already exists.")

    with transaction.atomic():
        if quote is None:
            quote = Quotation(created_by=user)
        quote.number = number
        quote.customer_name = str(data["customer_name"])[:180]
        quote.customer_phone = str(data.get("customer_phone", ""))[:30]
        quote.customer_email = str(data.get("customer_email", ""))[:254]
        quote.customer_address = str(data.get("customer_address", ""))
        quote.customer_gstin = str(data.get("customer_gstin", ""))[:30]
        quote.customer_state = str(data.get("customer_state", ""))[:80]
        quote.customer_state_code = str(data.get("customer_state_code", ""))[:10]
        quote.consignee_name = str(data.get("consignee_name", ""))[:180]
        quote.consignee_address = str(data.get("consignee_address", ""))
        quote.consignee_gstin = str(data.get("consignee_gstin", ""))[:30]
        quote.consignee_state = str(data.get("consignee_state", ""))[:80]
        quote.consignee_state_code = str(data.get("consignee_state_code", ""))[:10]
        quote.payment_terms = str(data.get("payment_terms", ""))[:180]
        quote.buyer_reference = str(data.get("buyer_reference", ""))[:180]
        quote.other_references = str(data.get("other_references", ""))[:180]
        quote.dispatched_through = str(data.get("dispatched_through", ""))[:180]
        quote.destination = str(data.get("destination", ""))[:180]
        quote.delivery_terms = str(data.get("delivery_terms", ""))
        quote.quote_date = data.get("quote_date") or date.today()
        quote.valid_until = data.get("valid_until") or None
        quote.shipment_details = str(data.get("shipment_details", ""))
        quote.notes = str(data.get("notes", ""))
        quote.shipping_amount = money(data.get("shipping_amount"))
        quote.save()
        quote.items.all().delete()

        subtotal = tax_total = Decimal("0")
        for row in items:
            product = Product.objects.filter(pk=row.get("product_id")).select_related("hsn").first()
            qty, price = money(row.get("quantity")), money(row.get("unit_price"))
            gst, discount = money(row.get("gst_percentage")), money(row.get("discount_percentage"))
            taxable = (qty * price * (Decimal("100") - discount) / 100).quantize(Decimal("0.01"))
            tax = (taxable * gst / 100).quantize(Decimal("0.01"))
            QuotationItem.objects.create(
                quotation=quote, product=product,
                product_name=(product.name if product else str(row.get("product_name", "")))[:180],
                sku=(product.sku if product else str(row.get("sku", "")))[:80],
                hsn_code=(getattr(product.hsn, "hsn_code", "") if product and product.hsn else str(row.get("hsn_code", "")))[:30],
                due_on=row.get("due_on") or None, unit=str(row.get("unit", "PCS"))[:20],
                discount_percentage=discount, quantity=qty, unit_price=price,
                gst_percentage=gst, taxable_amount=taxable, tax_amount=tax, total_amount=taxable + tax,
            )
            subtotal += taxable
            tax_total += tax
        quote.subtotal, quote.tax_total = subtotal, tax_total
        quote.grand_total = subtotal + tax_total + quote.shipping_amount
        quote.save(update_fields=["subtotal", "tax_total", "grand_total"])
        quote.refresh_from_db()
    return quote


@login_required
def quotation_list_page(request):
    search = request.GET.get("search", "").strip()
    quotes = Quotation.objects.select_related("created_by").order_by("-created_at")
    if search:
        from django.db.models import Q
        quotes = quotes.filter(Q(number__icontains=search) | Q(customer_name__icontains=search) | Q(customer_phone__icontains=search))
    return render(request, "inventory/quotation_list.html", {"quotes": quotes[:250], "search": search})


@login_required
def quotation_preview_script(request):
    response = FileResponse(
        open(settings.BASE_DIR / "static/js/quotation-preview.js", "rb"),
        content_type="application/javascript; charset=utf-8",
    )
    response["Cache-Control"] = "no-store, max-age=0"
    return response


@login_required
def quotation_page(request, pk=None):
    settings_obj, _ = QuotationSettings.objects.get_or_create(pk=1)
    products = Product.objects.select_related("hsn").order_by("name")
    customers = (Order.objects.exclude(customer_name="").values("customer_name","mobile","customer_email").order_by("customer_name").distinct()[:500])
    quote = get_object_or_404(Quotation.objects.prefetch_related("items"), pk=pk) if pk else None
    next_number = f"QT-{date.today():%Y%m%d}-{(Quotation.objects.count() + 1):04d}"
    return render(request, "inventory/quotation.html", {
        "products_json": json.dumps([{
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "hsn": getattr(p.hsn, "hsn_code", "") or "",
            # Prefer the saved selling price. If it is not configured, use the
            # saved purchase price instead of silently showing zero.
            "price": str(p.retailer_price or p.wholesale_price or p.unit_purchase_price or 0),
            "price_source": (
                "Retailer Price" if p.retailer_price
                else "Wholesale Price" if p.wholesale_price
                else "Purchase Price"
            ),
        } for p in products]),
        "customers_json": json.dumps(list(customers)), "company_json": json.dumps(settings_payload(settings_obj)),
        "quote_json": json.dumps(quotation_payload(quote)) if quote else "null",
        "editing_id": quote.id if quote else "", "next_number": next_number, "today": date.today().isoformat(),
        "valid_until": (date.today()+timedelta(days=15)).isoformat(),
    })


@login_required
@require_http_methods(["POST"])
def quotation_settings_api(request):
    data = json.loads(request.body or "{}")
    obj, _ = QuotationSettings.objects.get_or_create(pk=1)
    for field in settings_payload(obj):
        setattr(obj, field, str(data.get(field, "")).strip())
    obj.save()
    return JsonResponse({"settings": settings_payload(obj)})


@login_required
@require_http_methods(["POST"])
def quotation_save_api(request):
    data = json.loads(request.body or "{}")
    quote = get_object_or_404(Quotation, pk=data.get("id")) if data.get("id") else None
    try:
        quote = save_quotation(data, request.user, quote)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse({"id": quote.id, "number": quote.number, "download_url": f"/api/quotations/{quote.id}/pdf/", "detail_url": f"/api/app/quotations/{quote.id}/"}, status=200 if data.get("id") else 201)


@login_required
@require_http_methods(["POST"])
def quotation_delete(request, pk):
    get_object_or_404(Quotation, pk=pk).delete()
    return redirect("quotation-list-page")


@login_required
def quotation_pdf(request, pk):
    if os.path.isdir("/opt/homebrew/lib"):
        existing_library_path = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
            path for path in ("/opt/homebrew/lib", existing_library_path) if path
        )
    from weasyprint import CSS, HTML

    quote = get_object_or_404(Quotation.objects.prefetch_related("items"), pk=pk)
    company, _ = QuotationSettings.objects.get_or_create(pk=1)
    html = _exact_quotation_html(quote, company)
    # The supplied HTML is 8mm taller than A4 when printed by an HTML engine.
    # Keep its design untouched and only give the PDF enough paper height so
    # the signature is not moved onto a second page.
    pdf_bytes = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf(
        stylesheets=[CSS(string="@page { size: 210mm 305mm; margin: 0; }")]
    )
    return FileResponse(io.BytesIO(pdf_bytes), as_attachment=True, filename=f"{quote.number}.pdf")
