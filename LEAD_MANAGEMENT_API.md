# Lead Management API

Base URL: `https://your-domain.example/api`

All lead endpoints require an authenticated user and the matching **Lead Management** permission. Send the access token returned by the existing app login API:

```http
Authorization: Bearer <token>
Content-Type: application/json
```

If an Apache/Passenger proxy removes the standard `Authorization` header, the
same token is also accepted through this app-safe fallback header:

```http
X-Access-Token: <token>
```

The supplied Postman collection sends both headers automatically after login.

## Authentication and access

### Login

`POST /app/login/`

```json
{
  "username": "sales-user",
  "password": "password"
}
```

The response contains `token`, `user.modules`, `user.action_permissions`, and `user.module_catalog`. Lead access appears under the module key `leads`.

```json
{
  "modules": ["leads"],
  "action_permissions": {
    "leads": ["view", "add", "edit", "delete"]
  }
}
```

Permission mapping:

| Permission | Operations |
|---|---|
| `view` | Lists, details, stats, options, timelines, follow-ups, notes and export |
| `add` | Create lead, add note, add follow-up |
| `edit` | Update lead, status, conversion, lost lead, follow-up and non-delete bulk actions |
| `delete` | Delete lead, delete follow-up and bulk delete |

An unauthenticated request returns `401`. A user without the required module/action permission receives `403`.

## App endpoint checklist

| Method | Endpoint | Purpose | Permission |
|---|---|---|---|
| `POST` | `/app/login/` | Login and receive a 7-day Bearer token | Public |
| `GET` | `/leads/options/` | Form choices, employees, countries and products | View |
| `GET` | `/leads/stats/` | Lead and follow-up dashboard totals | View |
| `GET`, `POST` | `/leads/` | Paginated lead list and lead creation | View / Add |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/leads/{id}/` | Lead detail, full/partial update and soft delete | View / Edit / Delete |
| `POST` | `/leads/{id}/status/` | Change non-terminal status | Edit |
| `POST` | `/leads/{id}/note/` | Add a note | Add |
| `POST` | `/leads/{id}/follow-up/` | Schedule a follow-up | Add |
| `POST` | `/leads/{id}/convert/` | Convert a lead | Edit |
| `POST` | `/leads/{id}/mark-lost/` | Mark a lead lost with reason | Edit |
| `GET` | `/leads/{id}/activities/` | Activity timeline | View |
| `GET` | `/leads/{id}/follow-ups/` | Follow-ups for one lead | View |
| `GET` | `/leads/{id}/notes/` | Notes for one lead | View |
| `GET` | `/leads/{id}/status-history/` | Status audit trail | View |
| `GET` | `/leads/follow-ups/` | Filtered, paginated follow-up list | View |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/leads/follow-ups/{id}/` | Follow-up detail, update and delete | View / Edit / Delete |
| `POST` | `/leads/bulk/` | Bulk status, priority, assignment or delete | Edit / Delete |
| `POST` | `/leads/import/` | Shopify checkout CSV import | Add |
| `GET` | `/leads/export/` | Download filtered leads CSV | View |

## Reference data

### Get all form options, employees, countries and products

`GET /leads/options/`

Returns statuses, priorities, lead sources, lost reasons, follow-up types/statuses,
payment statuses, active employees, country/dial-code pairs and the product list.

### Statistics

`GET /leads/stats/`

```json
{
  "total": 24,
  "new": 4,
  "active": 16,
  "converted": 5,
  "lost": 3,
  "follow_ups_today": 2,
  "overdue_follow_ups": 1,
  "conversion_rate": 20.8
}
```

## Leads

### List leads

`GET /leads/`

Supported query parameters:

- `search`: shipping name, phone, shipping phone, email, city, country, product name or SKU
- `status`, `priority`, `source`, `assigned_to`
- `date_from`, `date_to`: `YYYY-MM-DD`
- `view`: `all`, `active`, `converted`, `lost`
- `sort`: `created_at`, `-created_at`, `name`, `-name`, `status`, `-status`, `priority`, `-priority`, `next_follow_up`, `-next_follow_up`
- `page`, `page_size` (`1`–`100`)

```json
{
  "count": 1,
  "page": 1,
  "pages": 1,
  "results": [
    {
      "id": 12,
      "lead_id": "LEAD-00012",
      "full_name": "Asha Patel",
      "phone": "9876543210",
      "status": "new",
      "status_display": "New",
      "priority": "hot",
      "priority_display": "Hot"
    }
  ]
}
```

### Create lead

`POST /leads/`

```json
{
  "shipping_name": "Asha Patel",
  "country_code": "+91",
  "phone": "9876543210",
  "shipping_phone": "9876543211",
  "email": "asha@example.com",
  "shipping_address1": "101 MG Road",
  "shipping_address2": "Near Metro Station",
  "shipping_city": "Mumbai",
  "shipping_zip": "400001",
  "shipping_province": "MH",
  "shipping_province_name": "Maharashtra",
  "shipping_country": "India",
  "product_ids": [12, 18, 21]
}
```

Required fields: `shipping_name`, `phone`. `country_code` defaults to `+91`.
`product_ids` accepts multiple existing product IDs. The API response includes the
selected products. Legacy `full_name` and address fields remain accepted for existing
integrations. A new lead cannot be created directly as `converted` or `lost`; use the
dedicated actions.

### Bulk import Shopify checkout CSV

`POST /leads/import/`

Send as `multipart/form-data` with the CSV in the `file` field.

```bash
curl -X POST "https://your-domain.example/api/leads/import/" \
  -H "Authorization: Bearer <token>" \
  -F "file=@checkouts_export.csv"
```

```json
{
  "source_rows": 60,
  "checkout_groups": 50,
  "created": 50,
  "duplicates_skipped": 0,
  "invalid_skipped": 0,
  "products_created": 31,
  "product_links": 32,
  "name_fallbacks": 8,
  "errors": [],
  "unmatched_products": ["UNKNOWN-SKU — Product name"],
  "unmatched_product_count": 1
}
```

Import rules:

- Rows sharing the same checkout `Name` are grouped into one lead.
- Shipping values are preferred; billing values are used only as fallbacks.
- Phone values are normalized and the dial code is stored separately.
- Products match by exact `Lineitem sku`, then exact `Lineitem name`.
- Missing line-item products are created under the `Shopify CSV Import` vendor with zero opening inventory, so they appear in Items and Add Lead.
- Existing checkout IDs are skipped, making repeat uploads duplicate-safe.
- UTF-8 CSV files up to 10 MB and 5,000 data rows are accepted.

### Lead detail

`GET /leads/{id}/`

Returns the complete lead plus `activities`, `follow_ups`, `lead_notes`, and conversion details when available.

### Update lead

`PUT /leads/{id}/` or `PATCH /leads/{id}/`

`PUT` requires the complete required lead data. `PATCH` is a true partial update and accepts only the fields being changed. Status changes are saved to both activity and status history. Conversion and lost status require their dedicated endpoints.

Lead responses include customer/shipping fields, selected `products`, assignment,
creator/updater data, import identifiers (`external_source`, `external_checkout_id`),
lost-lead details, next follow-up and timestamps. Detail responses additionally include
`activities`, `follow_ups`, `lead_notes` and conversion details.

### Delete lead

`DELETE /leads/{id}/`

Deletion is soft: related history remains stored.

### Export filtered leads

`GET /leads/export/`

Accepts the same filters as the lead list and returns a CSV file.

## Lead activity and related data

### Activity timeline

`GET /leads/{id}/activities/`

### Status history

`GET /leads/{id}/status-history/`

### Lead follow-ups

`GET /leads/{id}/follow-ups/`

### Lead notes

`GET /leads/{id}/notes/`

All related-list responses use:

```json
{
  "count": 1,
  "results": []
}
```

## Lead actions

### Change status

`POST /leads/{id}/status/`

```json
{
  "status": "contacted",
  "reason": "Called customer"
}
```

Statuses: `new`, `contacted`, `follow_up`, `interested`, `qualified`, `proposal_sent`, `negotiation`, `converted`, `lost`, `not_interested`, `not_responding`.

Use the dedicated conversion/lost endpoints for `converted` and `lost`.

### Add note

`POST /leads/{id}/note/`

```json
{
  "note": "Customer requested the revised price list."
}
```

### Add follow-up

`POST /leads/{id}/follow-up/`

```json
{
  "follow_up_date": "2026-09-05",
  "follow_up_time": "15:30",
  "follow_up_type": "demo",
  "notes": "Online product demonstration",
  "assigned_to": 4
}
```

Follow-up types: `call`, `whatsapp`, `email`, `meeting`, `demo`.

### Convert lead

`POST /leads/{id}/convert/`

```json
{
  "conversion_date": "2026-09-05",
  "product_service": "Stock Management Setup",
  "deal_amount": "125000.00",
  "payment_status": "partial",
  "notes": "Purchase order received"
}
```

Payment statuses: `pending`, `partial`, `paid`.

### Mark lead lost

`POST /leads/{id}/mark-lost/`

```json
{
  "lost_reason": "budget_issue",
  "notes": "May reconsider next quarter"
}
```

Lost reasons: `price_too_high`, `not_interested`, `competitor_selected`, `no_response`, `budget_issue`, `requirement_changed`, `invalid_lead`, `duplicate_lead`, `other`.

## Follow-ups

### List all follow-ups

`GET /leads/follow-ups/`

Query parameters:

- `section`: `overdue`, `today`, `upcoming`, `completed`
- `status`: `upcoming`, `completed`, `missed`, `cancelled`
- `lead`, `assigned_to`, `date_from`, `date_to`
- `page`, `page_size`

### Follow-up detail

`GET /leads/follow-ups/{follow_up_id}/`

### Update follow-up or its status

`PUT /leads/follow-ups/{follow_up_id}/` or `PATCH /leads/follow-ups/{follow_up_id}/`

```json
{
  "follow_up_date": "2026-09-06",
  "follow_up_time": "11:00",
  "follow_up_type": "call",
  "status": "completed",
  "notes": "Demo completed",
  "assigned_to": 4
}
```

Every field is optional for `PATCH`. Statuses: `upcoming`, `completed`, `missed`, `cancelled`.

### Delete follow-up

`DELETE /leads/follow-ups/{follow_up_id}/`

## Bulk actions

`POST /leads/bulk/`

Change status:

```json
{
  "lead_ids": [12, 14, 18],
  "action": "status",
  "value": "contacted"
}
```

Change priority:

```json
{
  "lead_ids": [12, 14],
  "action": "priority",
  "value": "hot"
}
```

Assign or unassign:

```json
{
  "lead_ids": [12, 14],
  "action": "assign",
  "value": 4
}
```

Use `null` as `value` to unassign.

Delete:

```json
{
  "lead_ids": [12, 14],
  "action": "delete"
}
```

Bulk conversion and bulk lost are intentionally unavailable because each lead requires conversion details or a lost reason.

## Common errors

```json
{"detail": "Please login to access this module."}
```

```json
{"detail": "Aapko Lead Management module ka access nahi hai."}
```

```json
{"detail": "Aapko Lead Management module me edit permission nahi hai."}
```
