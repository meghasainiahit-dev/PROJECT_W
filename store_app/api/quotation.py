from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from store_app.api.app import _app_forbidden, _app_has_module
from store_app.models import Product, Quotation, QuotationBankAccount, QuotationCompanyProfile
from store_app.quotation import bank_payload, company_payload, quotation_payload, save_quotation


def _allowed(user):
    return _app_has_module(user, "quotation")


def _summary(request, quote):
    return {
        "id": quote.id,
        "number": quote.number,
        "customer_name": quote.customer_name,
        "customer_phone": quote.customer_phone,
        "quote_date": quote.quote_date.isoformat(),
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "subtotal": str(quote.subtotal),
        "tax_total": str(quote.tax_total),
        "shipping_amount": str(quote.shipping_amount),
        "grand_total": str(quote.grand_total),
        "item_count": quote.items.count(),
        "company_profile": company_payload(quote.company_profile) if quote.company_profile else None,
        "bank_account": bank_payload(quote.bank_account) if quote.bank_account else None,
        "created_at": quote.created_at.isoformat(),
        "detail_url": request.build_absolute_uri(f"/api/app/quotations/{quote.id}/"),
        "pdf_view_url": request.build_absolute_uri(f"/api/app/quotations/{quote.id}/pdf/"),
        "pdf_download_url": request.build_absolute_uri(f"/api/app/quotations/{quote.id}/pdf/?download=1"),
    }


class AppQuotationListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _allowed(request.user):
            return _app_forbidden()
        search = request.query_params.get("search", "").strip()
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            limit = min(max(int(request.query_params.get("limit", 20)), 1), 100)
        except ValueError:
            return Response({"detail": "page and limit must be numbers."}, status=400)
        rows = Quotation.objects.select_related("company_profile", "bank_account").prefetch_related("items").order_by("-created_at")
        if search:
            rows = rows.filter(Q(number__icontains=search) | Q(customer_name__icontains=search) | Q(customer_phone__icontains=search) | Q(customer_gstin__icontains=search))
        count = rows.count()
        start = (page - 1) * limit
        data = [_summary(request, quote) for quote in rows[start:start + limit]]
        return Response({"data": data, "count": count, "page": page, "limit": limit, "has_next": start + limit < count})

    def post(self, request):
        if not _allowed(request.user):
            return _app_forbidden()
        try:
            quote = save_quotation(request.data, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**_summary(request, quote), **quotation_payload(quote)}, status=status.HTTP_201_CREATED)


class AppQuotationDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        return get_object_or_404(Quotation.objects.select_related("company_profile", "bank_account").prefetch_related("items"), pk=pk)

    def get(self, request, pk):
        if not _allowed(request.user):
            return _app_forbidden()
        quote = self.get_object(pk)
        return Response({**_summary(request, quote), **quotation_payload(quote)})

    def put(self, request, pk):
        return self._update(request, pk)

    def patch(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        if not _allowed(request.user):
            return _app_forbidden()
        quote = self.get_object(pk)
        data = quotation_payload(quote)
        data.update(request.data)
        try:
            quote = save_quotation(data, request.user, quote)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**_summary(request, quote), **quotation_payload(quote)})

    def delete(self, request, pk):
        if not _allowed(request.user):
            return _app_forbidden()
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppQuotationProductsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _allowed(request.user):
            return _app_forbidden()
        search = request.query_params.get("search", "").strip()
        products = Product.objects.select_related("hsn").order_by("name")
        if search:
            products = products.filter(Q(name__icontains=search) | Q(sku__icontains=search))
        data = [{
            "id": p.id, "name": p.name, "sku": p.sku,
            "hsn_code": getattr(p.hsn, "hsn_code", "") or "",
            "price": str(p.retailer_price or p.wholesale_price or p.unit_purchase_price or 0),
        } for p in products[:100]]
        return Response({"data": data, "count": len(data)})


class AppQuotationCompanyListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _allowed(request.user):
            return _app_forbidden()
        data = [company_payload(obj) for obj in QuotationCompanyProfile.objects.all()]
        return Response({"data": data, "count": len(data)})

    def post(self, request):
        if not _allowed(request.user):
            return _app_forbidden()
        company_name = str(request.data.get("company_name", "")).strip()
        if not company_name:
            return Response({"detail": "company_name is required."}, status=400)
        obj = QuotationCompanyProfile.objects.create(
            label=str(request.data.get("label") or company_name).strip()[:120],
            company_name=company_name[:180], address=str(request.data.get("address", "")).strip(),
            gstin=str(request.data.get("gstin", "")).strip()[:30], phone=str(request.data.get("phone", "")).strip()[:30],
            email=str(request.data.get("email", "")).strip()[:254], terms=str(request.data.get("terms", "")).strip(),
        )
        return Response(company_payload(obj), status=201)


class AppQuotationCompanyDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _object(self, pk):
        return get_object_or_404(QuotationCompanyProfile, pk=pk)

    def get(self, request, pk):
        if not _allowed(request.user): return _app_forbidden()
        return Response(company_payload(self._object(pk)))

    def put(self, request, pk):
        return self._update(request, pk)

    def patch(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        if not _allowed(request.user): return _app_forbidden()
        obj = self._object(pk)
        company_name = str(request.data.get("company_name", obj.company_name)).strip()
        if not company_name:
            return Response({"detail": "company_name is required."}, status=400)
        for field, limit in (("label", 120), ("company_name", 180), ("gstin", 30), ("phone", 30), ("email", 254)):
            if field in request.data:
                setattr(obj, field, str(request.data.get(field, "")).strip()[:limit])
        for field in ("address", "terms"):
            if field in request.data: setattr(obj, field, str(request.data.get(field, "")).strip())
        obj.company_name = company_name[:180]
        if not obj.label: obj.label = company_name[:120]
        obj.save()
        return Response(company_payload(obj))

    def delete(self, request, pk):
        if not _allowed(request.user): return _app_forbidden()
        obj = self._object(pk)
        if obj.quotations.exists():
            return Response({"detail": "This company profile is used in a quotation and cannot be deleted."}, status=409)
        obj.delete()
        return Response(status=204)


class AppQuotationBankListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _allowed(request.user): return _app_forbidden()
        data = [bank_payload(obj) for obj in QuotationBankAccount.objects.all()]
        return Response({"data": data, "count": len(data)})

    def post(self, request):
        if not _allowed(request.user): return _app_forbidden()
        bank_name = str(request.data.get("bank_name", "")).strip()
        account_number = str(request.data.get("account_number", "")).strip()
        if not bank_name or not account_number:
            return Response({"detail": "bank_name and account_number are required."}, status=400)
        obj = QuotationBankAccount.objects.create(
            label=str(request.data.get("label") or bank_name).strip()[:120], bank_name=bank_name[:120],
            account_name=str(request.data.get("account_name", "")).strip()[:120], account_number=account_number[:60],
            ifsc=str(request.data.get("ifsc", "")).strip()[:30], branch=str(request.data.get("branch", "")).strip()[:120],
        )
        return Response(bank_payload(obj), status=201)


class AppQuotationBankDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _object(self, pk):
        return get_object_or_404(QuotationBankAccount, pk=pk)

    def get(self, request, pk):
        if not _allowed(request.user): return _app_forbidden()
        return Response(bank_payload(self._object(pk)))

    def put(self, request, pk):
        return self._update(request, pk)

    def patch(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        if not _allowed(request.user): return _app_forbidden()
        obj = self._object(pk)
        bank_name = str(request.data.get("bank_name", obj.bank_name)).strip()
        account_number = str(request.data.get("account_number", obj.account_number)).strip()
        if not bank_name or not account_number:
            return Response({"detail": "bank_name and account_number are required."}, status=400)
        for field, limit in (("label", 120), ("bank_name", 120), ("account_name", 120), ("account_number", 60), ("ifsc", 30), ("branch", 120)):
            if field in request.data: setattr(obj, field, str(request.data.get(field, "")).strip()[:limit])
        obj.bank_name, obj.account_number = bank_name[:120], account_number[:60]
        if not obj.label: obj.label = bank_name[:120]
        obj.save()
        return Response(bank_payload(obj))

    def delete(self, request, pk):
        if not _allowed(request.user): return _app_forbidden()
        obj = self._object(pk)
        if obj.quotations.exists():
            return Response({"detail": "This bank account is used in a quotation and cannot be deleted."}, status=409)
        obj.delete()
        return Response(status=204)


class AppQuotationPDFAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _allowed(request.user):
            return _app_forbidden()
        # Reuse the tested web PDF renderer after DRF/JWT authentication.
        from store_app.quotation import quotation_pdf
        response = quotation_pdf.__wrapped__(request._request, pk)
        filename = get_object_or_404(Quotation, pk=pk).number + ".pdf"
        disposition = "attachment" if request.query_params.get("download") in {"1", "true"} else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
        return response
