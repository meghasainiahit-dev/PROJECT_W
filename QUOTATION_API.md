# Quotation App API

Base URL: `http://127.0.0.1:8000/api`

Send the JWT returned by `POST /api/app/login/` in every quotation request:

```http
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json
```

## Endpoints

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/app/quotations/?search=&page=1&limit=20` | Paginated quotation list |
| POST | `/api/app/quotations/` | Create quotation |
| GET | `/api/app/quotations/{id}/` | Full quotation detail with items |
| PUT/PATCH | `/api/app/quotations/{id}/` | Edit quotation and its items |
| DELETE | `/api/app/quotations/{id}/` | Delete quotation |
| GET | `/api/app/quotations/products/?search=tile` | Search products with saved price |
| GET/POST | `/api/app/quotations/companies/` | List or create company profiles |
| GET/PUT/PATCH/DELETE | `/api/app/quotations/companies/{id}/` | View, edit or delete a company profile |
| GET/POST | `/api/app/quotations/banks/` | List or create bank accounts |
| GET/PUT/PATCH/DELETE | `/api/app/quotations/banks/{id}/` | View, edit or delete a bank account |
| GET | `/api/app/quotations/{id}/pdf/` | View PDF inline |
| GET | `/api/app/quotations/{id}/pdf/?download=1` | Download PDF |

## Create/update body

```json
{
  "number": "QT-2026-001",
  "company_profile_id": 1,
  "bank_account_id": 1,
  "quote_date": "2026-08-20",
  "valid_until": "2026-09-04",
  "customer_name": "Customer Name",
  "customer_phone": "9876543210",
  "customer_email": "customer@example.com",
  "customer_address": "Billing address",
  "customer_gstin": "08ABCDE1234F1Z5",
  "customer_state": "Rajasthan",
  "customer_state_code": "08",
  "consignee_name": "Consignee Name",
  "consignee_address": "Shipping address",
  "consignee_gstin": "08ABCDE1234F1Z5",
  "consignee_state": "Rajasthan",
  "consignee_state_code": "08",
  "payment_terms": "Advance",
  "buyer_reference": "PO-100",
  "other_references": "",
  "dispatched_through": "Transport",
  "destination": "Jaipur",
  "delivery_terms": "Door delivery",
  "shipment_details": "Shipping Charges",
  "shipping_amount": "100.00",
  "notes": "Quotation valid for 15 days",
  "items": [
    {
      "product_id": 1,
      "due_on": "2026-09-04",
      "quantity": "2",
      "unit": "PCS",
      "unit_price": "85.00",
      "discount_percentage": "0",
      "gst_percentage": "18"
    }
  ]
}
```

GST accepts `5` or `18`. The product API returns the saved database price as `price`; the app can send an edited value as `unit_price`.

`company_profile_id` is required while saving a quotation. `bank_account_id` is optional. Get these IDs from the company and bank list APIs. Quotation list/detail responses include both the selected IDs and full `company_profile` / `bank_account` objects.

## Company profile CRUD

Create with `POST /api/app/quotations/companies/`:

```json
{
  "label": "A2G Jaipur",
  "company_name": "A2G Traders Private Limited",
  "address": "Jaipur, Rajasthan",
  "gstin": "08ABCDE1234F1Z5",
  "phone": "9876543210",
  "email": "accounts@example.com",
  "terms": "Quotation valid for 15 days."
}
```

Edit using `PUT` or `PATCH /api/app/quotations/companies/{id}/`. Delete using `DELETE` on the same URL.

## Bank account CRUD

Create with `POST /api/app/quotations/banks/`:

```json
{
  "label": "HDFC Current Account",
  "bank_name": "HDFC Bank",
  "account_name": "A2G Traders Private Limited",
  "account_number": "1234567890",
  "ifsc": "HDFC0001234",
  "branch": "Jaipur"
}
```

Edit using `PUT` or `PATCH /api/app/quotations/banks/{id}/`. Delete using `DELETE` on the same URL. Company/bank records already used by a quotation return HTTP `409` on delete so old quotation PDFs remain valid.

## List response

```json
{
  "data": [
    {
      "id": 12,
      "number": "QT-2026-001",
      "customer_name": "Customer Name",
      "grand_total": "300.60",
      "item_count": 1,
      "detail_url": "http://127.0.0.1:8000/api/app/quotations/12/",
      "pdf_view_url": "http://127.0.0.1:8000/api/app/quotations/12/pdf/",
      "pdf_download_url": "http://127.0.0.1:8000/api/app/quotations/12/pdf/?download=1"
    }
  ],
  "count": 1,
  "page": 1,
  "limit": 20,
  "has_next": false
}
```
