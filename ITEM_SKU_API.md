# Item SKU App API

Use this endpoint to permanently edit a product's master SKU from the app.

```http
PATCH /api/app/products/{product_id}/sku/
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json
```

Request:

```json
{
  "sku": "NEW-SKU-001"
}
```

Success response (`200`):

```json
{
  "id": 1,
  "name": "Product Name",
  "old_sku": "OLD-SKU-001",
  "sku": "NEW-SKU-001",
  "detail": "Product SKU updated successfully."
}
```

Errors:

- `400`: SKU is empty or longer than 150 characters.
- `401`: JWT is missing or invalid.
- `403`: User does not have Items module access.
- `404`: Product does not exist.
- `409`: SKU is already assigned to another product.

The updated SKU is returned by `GET /api/app/products/` and is used by product and quotation searches.
