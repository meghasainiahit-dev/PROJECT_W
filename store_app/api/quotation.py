from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from store_app.api.app import _app_forbidden, _app_has_module
from store_app.models import Product, Quotation
from store_app.quotation import quotation_payload, save_quotation


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
        rows = Quotation.objects.prefetch_related("items").order_by("-created_at")
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
        return get_object_or_404(Quotation.objects.prefetch_related("items"), pk=pk)

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
