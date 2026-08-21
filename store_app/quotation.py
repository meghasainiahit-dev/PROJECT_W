import io
import json
import logging
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

from .models import (
    Order, Product, Quotation, QuotationBankAccount, QuotationCompanyProfile,
    QuotationItem, QuotationSettings,
)

logger = logging.getLogger(__name__)


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


def _exact_quotation_html(quote, company, bank=None):
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
    words_cell = soup.select_one(".words-cell")
    if bank and words_cell:
        bank_box = soup.new_tag("div")
        bank_box["style"] = "margin-top:12px;font-size:11px;line-height:1.4"
        bank_box.append(NavigableString("Bank Details"))
        bank_box.append(soup.new_tag("br"))
        details = " | ".join(filter(None, [
            bank.bank_name, f"A/C Name: {bank.account_name}" if bank.account_name else "",
            f"A/C No: {bank.account_number}" if bank.account_number else "",
            f"IFSC: {bank.ifsc}" if bank.ifsc else "", f"Branch: {bank.branch}" if bank.branch else "",
        ]))
        strong = soup.new_tag("strong")
        strong.string = details
        bank_box.append(strong)
        words_cell.append(bank_box)
    soup.select_one(".company-for").string = f"for {company.company_name or 'Company'}"
    return str(soup)


def _reportlab_quotation_pdf(quote, company, bank=None):
    """Portable one-page fallback for servers without WeasyPrint/Pango."""
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    output = io.BytesIO()
    width, height = 210 * mm, 305 * mm
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    left, right, top = 12 * mm, width - 12 * mm, height - 9 * mm
    content_width = right - left

    def text(value, x, y, size=7, bold=False, align="left"):
        value = str(value or "")
        font = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFont(font, size)
        if align == "right":
            x -= stringWidth(value, font, size)
        elif align == "center":
            x -= stringWidth(value, font, size) / 2
        pdf.drawString(x, y, value)

    def wrapped(value, x, y, max_width, size=7, bold=False, leading=8):
        font = "Helvetica-Bold" if bold else "Helvetica"
        words, lines, current = str(value or "").replace("\n", " \n ").split(), [], ""
        for word in words:
            if word == "\n":
                lines.append(current); current = ""; continue
            candidate = f"{current} {word}".strip()
            if current and stringWidth(candidate, font, size) > max_width:
                lines.append(current); current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for line in lines[:8]:
            text(line, x, y, size, bold); y -= leading
        return y

    text("QUOTATION", width / 2, top, 11, True, "center")
    y1 = top - 7 * mm
    header_bottom = y1 - 54 * mm
    split = left + content_width * .51
    pdf.rect(left, header_bottom, content_width, y1 - header_bottom)
    pdf.line(split, header_bottom, split, y1)
    text(company.company_name or "Company Name", left + 2 * mm, y1 - 4 * mm, 7.5, True)
    company_info = " | ".join(filter(None, [company.address, f"GSTIN/UIN: {company.gstin}" if company.gstin else "", f"E-Mail: {company.email}" if company.email else ""]))
    wrapped(company_info, left + 2 * mm, y1 - 8 * mm, split - left - 4 * mm, 6.5, False, 7)

    meta = [
        ("Voucher No.", quote.number), ("Dated", quote.quote_date.strftime("%d-%b-%y")),
        ("Mode/Terms of Payment", quote.payment_terms), ("Buyer's Ref./Order No.", quote.buyer_reference),
        ("Other References", quote.other_references), ("Dispatched through", quote.dispatched_through),
    ]
    col = (right - split) / 2
    row_h = 13.5 * mm
    for index in range(3):
        row_top = y1 - index * row_h
        row_bottom = row_top - row_h
        pdf.line(split, row_bottom, right, row_bottom)
        pdf.line(split + col, row_bottom, split + col, row_top)
        for side in range(2):
            label, value = meta[index * 2 + side]
            x = split + side * col + 1.5 * mm
            text(label, x, row_top - 3 * mm, 5.5)
            wrapped(value, x, row_top - 6.5 * mm, col - 3 * mm, 6.5, True, 7)

    party_top = y1 - 18 * mm
    party_mid = header_bottom + 18 * mm
    pdf.line(left, party_top, split, party_top)
    text("Consignee (Ship to)", left + 2 * mm, party_top - 3 * mm, 5.5)
    wrapped(f"{quote.consignee_name or quote.customer_name}\n{quote.consignee_address or quote.customer_address}\nGSTIN/UIN: {quote.consignee_gstin or quote.customer_gstin}\nState: {quote.consignee_state or quote.customer_state}, Code: {quote.consignee_state_code or quote.customer_state_code}", left + 2 * mm, party_top - 7 * mm, split-left-4*mm, 6.5, True, 7)
    pdf.line(left, party_mid, split, party_mid)
    text("Buyer (Bill to)", left + 2 * mm, party_mid - 3 * mm, 5.5)
    wrapped(f"{quote.customer_name}\n{quote.customer_address}\nGSTIN/UIN: {quote.customer_gstin}\nState: {quote.customer_state}, Code: {quote.customer_state_code}", left + 2 * mm, party_mid - 7 * mm, split-left-4*mm, 6.5, True, 7)

    info_top = y1 - 40.5 * mm
    pdf.line(split, info_top, right, info_top)
    text("Destination", split + 2 * mm, info_top - 3 * mm, 5.5)
    text(quote.destination, split + 2 * mm, info_top - 7 * mm, 6.5, True)
    text("Terms of Delivery", split + col + 2 * mm, info_top - 3 * mm, 5.5)
    text(quote.delivery_terms, split + col + 2 * mm, info_top - 7 * mm, 6.5, True)

    table_top, table_bottom = header_bottom, header_bottom - 79 * mm
    widths = [.035, .405, .095, .105, .09, .055, .07, .145]
    xs = [left]
    for ratio in widths:
        xs.append(xs[-1] + content_width * ratio)
    pdf.rect(left, table_bottom, content_width, table_top - table_bottom)
    for x in xs[1:-1]: pdf.line(x, table_bottom, x, table_top)
    head_bottom = table_top - 9 * mm
    total_top = table_bottom + 7 * mm
    pdf.line(left, head_bottom, right, head_bottom); pdf.line(left, total_top, right, total_top)
    headers = ["Sl No.", "Description of Goods and Services", "Due on", "Quantity", "Rate", "per", "Disc.%", "Amount"]
    for i, label in enumerate(headers): text(label, (xs[i]+xs[i+1])/2, table_top-5.5*mm, 5.5, False, "center")
    row_y = head_bottom - 5 * mm
    total_qty = Decimal("0")
    for index, item in enumerate(quote.items.all(), 1):
        if row_y < total_top + 24 * mm: break
        total_qty += item.quantity
        values = [index, item.product_name, item.due_on.strftime("%d-%b-%y") if item.due_on else "", f"{item.quantity:g} {item.unit}", f"{item.unit_price:,.2f}", item.unit, f"{item.discount_percentage:g}", f"{item.taxable_amount:,.2f}"]
        for i, value in enumerate(values): text(value, xs[i]+1.2*mm, row_y, 6.2, i in (1,3,7))
        row_y -= 5 * mm
    gst = quote.items.first().gst_percentage if quote.items.exists() else Decimal("0")
    text(f"OUTPUTIGST@{gst:g}%", xs[2]-2*mm, total_top+24*mm, 6.5, True, "right")
    text("Shipping Charges", xs[2]-2*mm, total_top+19*mm, 6.5, True, "right")
    text(f"{quote.tax_total:,.2f}", right-2*mm, total_top+24*mm, 6.5, True, "right")
    text(f"{quote.shipping_amount:,.2f}", right-2*mm, total_top+19*mm, 6.5, True, "right")
    text("Total", xs[2]-2*mm, table_bottom+2.5*mm, 6.5, True, "right")
    text(f"{total_qty:g} PCS", (xs[3]+xs[4])/2, table_bottom+2.5*mm, 6.5, True, "center")
    text(f"Rs. {quote.grand_total:,.2f}", right-2*mm, table_bottom+2.5*mm, 6.5, True, "right")

    bottom = table_bottom - 63 * mm
    pdf.rect(left, bottom, content_width, table_bottom - bottom)
    text("Amount Chargeable (in words)", left+2*mm, table_bottom-4*mm, 5.5)
    text(amount_words(quote.grand_total), left+2*mm, table_bottom-8*mm, 6.5, True)
    if bank:
        text("Bank Details", left+2*mm, table_bottom-15*mm, 5.5)
        bank_line = " | ".join(filter(None, [bank.bank_name, bank.account_name, f"A/C: {bank.account_number}", f"IFSC: {bank.ifsc}" if bank.ifsc else "", bank.branch]))
        wrapped(bank_line, left+2*mm, table_bottom-19*mm, content_width/2-4*mm, 6, True, 7)
    text("E. & O.E", right-2*mm, table_bottom-4*mm, 6, False, "right")
    sig_left, sig_top = left + content_width/2, bottom + 25*mm
    pdf.rect(sig_left, bottom, right-sig_left, sig_top-bottom)
    text(f"for {company.company_name or 'Company'}", right-2*mm, sig_top-5*mm, 6.5, True, "right")
    text("Authorised Signatory", right-2*mm, bottom+3*mm, 6, False, "right")
    text("This is a Computer Generated Document", width/2, bottom-5*mm, 5.5, False, "center")
    pdf.showPage(); pdf.save(); output.seek(0)
    return output.getvalue()


def settings_payload(obj):
    fields = ("company_name","address","gstin","phone","email","bank_name","account_name","account_number","ifsc","branch","terms")
    return {field: getattr(obj, field, "") for field in fields}


def company_payload(obj):
    return {field: getattr(obj, field, "") for field in ("id", "label", "company_name", "address", "gstin", "phone", "email", "terms")}


def bank_payload(obj):
    return {field: getattr(obj, field, "") for field in ("id", "label", "bank_name", "account_name", "account_number", "ifsc", "branch")}


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
    data["company_profile_id"] = quote.company_profile_id
    data["bank_account_id"] = quote.bank_account_id
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
        quote.company_profile = QuotationCompanyProfile.objects.filter(pk=data.get("company_profile_id")).first()
        quote.bank_account = QuotationBankAccount.objects.filter(pk=data.get("bank_account_id")).first()
        if not quote.company_profile:
            raise ValueError("Please select a company profile.")
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
    companies = list(QuotationCompanyProfile.objects.all())
    banks = list(QuotationBankAccount.objects.all())
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
        "customers_json": json.dumps(list(customers)),
        "company_json": json.dumps(company_payload(companies[0]) if companies else settings_payload(settings_obj)),
        "companies_json": json.dumps([company_payload(obj) for obj in companies]),
        "banks_json": json.dumps([bank_payload(obj) for obj in banks]),
        "quote_json": json.dumps(quotation_payload(quote)) if quote else "null",
        "editing_id": quote.id if quote else "", "next_number": next_number, "today": date.today().isoformat(),
        "valid_until": (date.today()+timedelta(days=15)).isoformat(),
    })


@login_required
@require_http_methods(["GET", "POST", "PUT", "DELETE"])
def quotation_settings_api(request):
    if request.method == "GET":
        return JsonResponse({
            "companies": [company_payload(obj) for obj in QuotationCompanyProfile.objects.all()],
            "banks": [bank_payload(obj) for obj in QuotationBankAccount.objects.all()],
        })
    data = json.loads(request.body or "{}")
    record_type = data.get("type")
    record_id = data.get("id")
    if request.method == "DELETE":
        model = QuotationCompanyProfile if record_type == "company" else QuotationBankAccount if record_type == "bank" else None
        if model is None:
            return JsonResponse({"detail": "Invalid settings type."}, status=400)
        obj = get_object_or_404(model, pk=record_id)
        if obj.quotations.exists():
            return JsonResponse({"detail": "This record is used in a quotation and cannot be deleted. You can edit it instead."}, status=409)
        obj.delete()
        return JsonResponse({"deleted": True, "id": record_id, "type": record_type})
    if record_type == "company":
        required = str(data.get("company_name", "")).strip()
        if not required:
            return JsonResponse({"detail": "Company name is required."}, status=400)
        obj = get_object_or_404(QuotationCompanyProfile, pk=record_id) if request.method == "PUT" else QuotationCompanyProfile()
        obj.label = str(data.get("label") or required).strip()[:120]
        obj.company_name = required[:180]
        obj.address = str(data.get("address", "")).strip()
        obj.gstin = str(data.get("gstin", "")).strip()[:30]
        obj.phone = str(data.get("phone", "")).strip()[:30]
        obj.email = str(data.get("email", "")).strip()[:254]
        obj.terms = str(data.get("terms", "")).strip()
        obj.save()
        return JsonResponse({"company": company_payload(obj)}, status=200 if request.method == "PUT" else 201)
    if record_type == "bank":
        bank_name, account_number = str(data.get("bank_name", "")).strip(), str(data.get("account_number", "")).strip()
        if not bank_name or not account_number:
            return JsonResponse({"detail": "Bank name and account number are required."}, status=400)
        obj = get_object_or_404(QuotationBankAccount, pk=record_id) if request.method == "PUT" else QuotationBankAccount()
        obj.label = str(data.get("label") or bank_name).strip()[:120]
        obj.bank_name = bank_name[:120]
        obj.account_name = str(data.get("account_name", "")).strip()[:120]
        obj.account_number = account_number[:60]
        obj.ifsc = str(data.get("ifsc", "")).strip()[:30]
        obj.branch = str(data.get("branch", "")).strip()[:120]
        obj.save()
        return JsonResponse({"bank": bank_payload(obj)}, status=200 if request.method == "PUT" else 201)
    return JsonResponse({"detail": "Invalid settings type."}, status=400)


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
    quote = get_object_or_404(Quotation.objects.select_related("company_profile", "bank_account").prefetch_related("items"), pk=pk)
    company = quote.company_profile
    if company is None:
        company, _ = QuotationSettings.objects.get_or_create(pk=1)
    bank = quote.bank_account
    try:
        from weasyprint import CSS, HTML
        html = _exact_quotation_html(quote, company, bank)
        # The supplied HTML is 8mm taller than A4 when printed by an HTML engine.
        pdf_bytes = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf(
            stylesheets=[CSS(string="@page { size: 210mm 305mm; margin: 0; }")]
        )
    except Exception:
        logger.exception("WeasyPrint failed; using portable quotation PDF renderer")
        pdf_bytes = _reportlab_quotation_pdf(quote, company, bank)
    return FileResponse(io.BytesIO(pdf_bytes), as_attachment=True, filename=f"{quote.number}.pdf")
