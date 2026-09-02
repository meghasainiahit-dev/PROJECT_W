from django.contrib import admin
from django.urls import path, include
from . import views
from .api import (purchase, barcode, otherView, app, activity, quotation as quotation_api)
from . import webview
from . import download_sam
from . import download_sam1
from . import quotation
from . import lead_management

from django.views.generic import RedirectView
from store_app import webview


urlpatterns = [
    # Login
    path("login/", views.VerifyOTPView.as_view(), name="login"),
    path('', RedirectView.as_view(url='/api/home')),
    # Vendors
    path("vendors-page/", webview.vendors_page, name="vendors-page"),
    path("vendors-page/add/", webview.add_vendor_page, name="add-vendor-page"),
    path("vendors/add/", webview.add_vendor_page, name="add-vendor-legacy-page"),
    path("vendors-page/<int:vendor_id>/page/", webview.vendor_details_page, name="vendor-details-page"),
    path("vendors/<int:vendor_id>/page/", webview.vendor_details_page, name="vendor-details-legacy-page"),
    
    path("vendors/", views.VendorListCreateView.as_view(), name="vendor-list-create"),
    path("vendors/<int:pk>/", views.VendorDetailView.as_view(), name="vendor-detail"),
    path("vendor-dashboard/<int:vendor_id>/",views.VendorDashboardView.as_view(), name="vendor-dashboard"),
    path("vendors/<int:vendor_id>/edit/", webview.edit_vendor_page, name="edit-vendor-page"),
    path("vendors/<int:vendor_id>/delete/", webview.delete_vendor, name="delete-vendor"),

    # Sales Channels
    path('channels/', views.SalesChannelListCreateView.as_view(), name='channel-list-create'),
    path('channels/<int:pk>/', views.SalesChannelDetailView.as_view(), name='channel-detail'),

    # Products
    path('products/', views.ProductListCreateView.as_view(), name='product-list-create'),
    path('products/<int:pk>/', views.ProductListCreateView.as_view(), name='product-list-create'),
    path('products-update/<int:pk>', views.ProductUpdateAPIView.as_view(), name='product-updated-noslash'),
    path('products-update/<int:pk>/', views.ProductUpdateAPIView.as_view(), name='product-updated'),
    path('products/<int:pk>/', views.ProductDetailView.as_view(), name='product-detail'),
   
    path('products/<int:product_id>/variants/', views.ProductVariantListCreateView.as_view(),name='product-varient'),
    path('variants/<int:pk>/', views.ProductVariantDetailView.as_view(),name='varients'),
    path('variants/<int:variant_id>/images/',views.ProductVariantImageUploadView.as_view(),name='varient-image'),
    path('products/<int:pk>/stock/', views.ProductStockView.as_view(), name='product-stock'),
    path('stock-filter/', views.StockFilterAPIView.as_view(), name='stock-filter'),

    # Inventory
    path('inventory/', views.InventoryListCreateView.as_view(), name='inventory-list-create'),
    path('inventory/<int:pk>/', views.InventoryDetailView.as_view(), name='inventory-detail'),
    path('inventory/adjust/', views.InventoryAdjustView.as_view(), name='inventory-adjust'),

    # Orders
    path('orders/', views.OrderListCreateView.as_view(), name='order-list-create'),
    path('orders/<int:order_id>/add-remark/', views.AddOrderRemarkView.as_view(), name='add-remark'),
    path('orders/<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('orders/sales_by_channel/', views.SalesByChannelView.as_view(), name='sales-by-channel'),
    path('orders/product_summary/', views.ProductSummaryView.as_view(), name='product-summary'),
    path("orders/<int:order_id>/delivered/", views.MarkOrderDeliveredAPIView.as_view(), name="order-delivered"),
    path("orders/<int:order_id>/serial-barcodes/pdf/", views.SerialBarcodePDFAPIView.as_view(), name="serial-barcodes-pdf"),

    # Product Delete
    path('product-del/<int:idpk>/', views.ProductSelectedDelete.as_view(), name='product-del'),

    path("wps-return/", views.WPSReturnAPIView.as_view(), name="wps-return"),

    # Low Stock
    path("low-stck/", views.LowStocksAlterts.as_view(), name='low-stock'),

    # Return History
    path("return-filter-history/", views.ReturnDataHistory.as_view(), name='filterReturnHistory'),

    path("all-bills", purchase.BillingView.as_view(), name="bills"),
    path("bills-perticuler/<int:id>/", purchase.BillingPertculerView.as_view(), name="bills-perticuler"),
    path("order-bills-perticuler/<int:order_id>/", purchase.UpdatePaymentDetailsOrderView.as_view(), name="bills-perticuler"),
    path("order-bills-perticulerss/<int:order_id>/", purchase.UpdatePaymentDetailsOrderNewView.as_view(), name="bills-perticulerss"),
    path("purchase-item", purchase.CreatePurchaseBillView.as_view(), name="purchase"),
    path("purchase-list", purchase.GetAllPurchase.as_view(), name="get-all-purchse"),
    path("purchase-detail/<int:id>/", purchase.GetPurchaseBillView.as_view(), name="purchase-detail"),
    path("purchase-update/<int:id>/", purchase.UpdatePurchaseBillView.as_view(), name="purchase-update"),
    path("purchase-delete/<int:id>/", purchase.DeletePurchaseBillView.as_view(), name="purchase-delete"),


    path("genrate-barcode", barcode.GenerateBulkBarcode.as_view(), name="genrate-barcode"),
    path("scan-barcode-product/", barcode.ScanBarcode.as_view(), name="scan-barcode-product"),
    path("hsn/", purchase.HsnListCreateAPIView.as_view(), name="hsn-list-create"),
    path("low-stock-products/", otherView.LowStockProductView.as_view(), name="low-stock-products"),
    path("product-list/", otherView.ProductListView.as_view(), name="product-list"),
    path("vendor-dashboard/<int:vendor_id>/", otherView.VendorDashboardView.as_view(), name="vendor-dashboard"),
    path("courier-return/", otherView.CourierReturnCreateView.as_view()),
    path("courier-return-list/", otherView.CourierReturnListView.as_view()),
    path("courier-return-update/<int:id>/", otherView.CourierReturnUpdateStatusView.as_view(), name="courier-return-update"),
    path("courier-return-report/", otherView.CourierClaimReportView.as_view()),
    path("courier-finance-settlement/", otherView.CourierFinanceSettlementView.as_view()),
    path("customer-return/", otherView.CustomerReturnCreateView.as_view()),
    path("customer-return-list/", otherView.CustomerReturnListView.as_view()),
    path("customer-return-update/<int:id>/", otherView.CustomerReturnUpdateStatusView.as_view(), name="customer-return-update"),
    path("customer-refund-report/", otherView.CustomerRefundReportView.as_view()),
    path("customer-refund-settlement/", otherView.CustomerRefundSettlementView.as_view()),
    path("order-barcodes/<int:order_id>/", barcode.GetAllOrderBarcodes.as_view()),
    
    path('upload-image/', views.ImageUploadAPIView.as_view(), name='upload-image'),
    path('products-delete/<int:pk>/', views.ProductDeleteSafeView.as_view(), name='product-delete-safe'),
    path("return-report/", otherView.ReturnOrderFullReportView.as_view(), name="return-report"),
    path("order/<int:order_id>/soft-delete/", views.OrderSoftDeleteView.as_view()),
    path("order/<int:order_id>/cancel/", views.CancelOrderView.as_view()),
    path("courier/create/", views.CourirPartnerCreateAPIView.as_view()),
    path("courier/list/", views.CourirPartnerListAPIView.as_view()),
    path("courier/<int:pk>/", views.CourirPartnerDetailAPIView.as_view()),
    path("order/<int:order_id>/create-shipment/", views.CreateShipmentFromOrderAPIView.as_view()),
    path("order-with-shipments/", views.OrderWithShipmentAPIView.as_view()),
    path('order-status/', views.OrderStatusListCreateView.as_view(), name='order-status-list-create'),
    path('order-status/<int:pk>/', views.OrderStatusDetailView.as_view(), name='order-status-detail'),
    
    # WEb API For Dashboard
    path("upload-products/", download_sam.upload_products, name="upload-products"),
    path("download-sample/", download_sam.download_sample, name="download-sample"),
    path("get-products/", download_sam.get_products, name="get-products"),
   path("download-sample1/", download_sam1.download_sample1, name="download-sample1"),
   path("upload-products1/", download_sam1.upload_products1, name="upload-products1"),

    # Web Routes
    path("home", webview.home, name='home'),
    path("inventory-page/", webview.inventory_page, name="inventory-page"),
    path("purchase-page/", webview.purchase_page, name="purchase-page"),
    path("purchase-create-page/", webview.create_purchase_page, name="purchase-create-page"),
    path("purchase-details-page/", webview.purchase_details_page, name="purchase-details-page"),
    path("items/", webview.items_page, name='items_page'),
    path("items/<int:pk>/", webview.item_details_page, name='item_details_page'),
    path("items/add/", webview.add_item_page, name='add_item_page'),
    path("items/edit/<int:pk>/", webview.add_item_page, name='edit_item_page'),
    path("orders-page/", webview.orders_page, name="Orders-Page"),
    path("couriers-page/", webview.couriers_page, name="couriers-page"),
    path("order-ui-details/", webview.order_details_page, name="order-ui-details"),
    path("create-order/", webview.create_order_page, name="create-order"),

    path("order-ui-list/", views.OrderListAPIView.as_view(), name="order-ui-list-api"),
    path("order-ui-detail/<int:order_id>/", views.OrderDetailAPIView.as_view(), name="order-ui-detail-api"),
    path("order-ui-delete/<int:order_id>/", views.OrderSoftDeleteView.as_view(), name="order-ui-delete-api"),
    path("order-ui-cancel/<int:order_id>/", views.CancelOrderView.as_view(), name="order-ui-cancel-api"),
    path("order-ui-pack/<int:order_id>/", views.PackOrderAPIView.as_view(), name="order-ui-pack-api"),
    path("order-ui-delivered/<int:order_id>/", views.MarkOrderDeliveredAPIView.as_view(), name="order-ui-delivered-api"),
    path("order-ui-serial-pdf/<int:order_id>/", views.SerialBarcodePDFAPIView.as_view(), name="order-ui-serial-pdf-api"),
    path("order-ui-shipment/<int:order_id>/", views.CreateShipmentFromOrderAPIView.as_view(), name="order-ui-shipment-api"),

    # App APIs
    path("app/dashboard/", app.AppDashboardAPIView.as_view(), name="app-dashboard-api"),
    path("app/login/", app.AppLoginAPIView.as_view(), name="app-login-api"),
    path("app/products/", app.AppProductsAPIView.as_view(), name="app-products-api"),
    path("app/products/<int:pk>/sku/", app.AppProductSKUUpdateAPIView.as_view(), name="app-product-sku-update-api"),
    path("app/vendors/", app.AppVendorsAPIView.as_view(), name="app-vendors-api"),
    path("app/users/", app.AppUsersAPIView.as_view(), name="app-users-api"),
    path("app/purchases/", app.AppPurchasesAPIView.as_view(), name="app-purchases-api"),
    path("app/orders/", app.AppOrdersAPIView.as_view(), name="app-orders-api"),
    path("app/orders/<int:order_id>/", app.AppOrderDetailAPIView.as_view(), name="app-order-detail-api"),
    path("app/activity/", activity.UserActivityAPIView.as_view(), name="app-user-activity-api"),
    path("app/activity/all/", activity.AllUserActivityAPIView.as_view(), name="app-all-user-activity-api"),
    path("app/quotations/", quotation_api.AppQuotationListCreateAPIView.as_view(), name="app-quotation-list-create"),
    path("app/quotations/products/", quotation_api.AppQuotationProductsAPIView.as_view(), name="app-quotation-products"),
    path("app/quotations/companies/", quotation_api.AppQuotationCompanyListCreateAPIView.as_view(), name="app-quotation-companies"),
    path("app/quotations/companies/<int:pk>/", quotation_api.AppQuotationCompanyDetailAPIView.as_view(), name="app-quotation-company-detail"),
    path("app/quotations/banks/", quotation_api.AppQuotationBankListCreateAPIView.as_view(), name="app-quotation-banks"),
    path("app/quotations/banks/<int:pk>/", quotation_api.AppQuotationBankDetailAPIView.as_view(), name="app-quotation-bank-detail"),
    path("app/quotations/<int:pk>/", quotation_api.AppQuotationDetailAPIView.as_view(), name="app-quotation-detail"),
    path("app/quotations/<int:pk>/pdf/", quotation_api.AppQuotationPDFAPIView.as_view(), name="app-quotation-pdf"),
    path("quotations/", quotation.quotation_list_page, name="quotation-list-page"),
    path("quotations/create/", quotation.quotation_page, name="quotation-create-page"),
    path("quotations/preview.js", quotation.quotation_preview_script, name="quotation-preview-script"),
    path("quotations/<int:pk>/edit/", quotation.quotation_page, name="quotation-edit-page"),
    path("quotations/<int:pk>/delete/", quotation.quotation_delete, name="quotation-delete"),
    path("quotations/settings/", quotation.quotation_settings_api, name="quotation-settings"),
    path("quotations/save/", quotation.quotation_save_api, name="quotation-save"),
    path("quotations/<int:pk>/pdf/", quotation.quotation_pdf, name="quotation-pdf"),

    # Lead Management (isolated web pages and APIs)
    path("leads-page/", lead_management.lead_list_page, name="lead-list-page"),
    path("leads-page/add/", lead_management.lead_form_page, name="lead-add-page"),
    path("leads-page/follow-ups/", lead_management.follow_ups_page, name="lead-follow-ups-page"),
    path("leads-page/export/", lead_management.export_leads, name="lead-export"),
    path("leads-page/bulk/", lead_management.bulk_lead_action, name="lead-bulk-action"),
    path("leads-page/follow-ups/<int:pk>/status/", lead_management.follow_up_web_status, name="follow-up-web-status"),
    path("leads-page/<int:pk>/", lead_management.lead_detail_page, name="lead-detail-page"),
    path("leads-page/<int:pk>/edit/", lead_management.lead_form_page, name="lead-edit-page"),
    path("leads-page/<int:pk>/<str:action>/", lead_management.lead_web_action, name="lead-web-action"),

    path("leads/", lead_management.LeadListCreateAPI.as_view(), name="lead-list-create-api"),
    path("leads/options/", lead_management.LeadOptionsAPI.as_view(), name="lead-options-api"),
    path("leads/stats/", lead_management.LeadStatsAPI.as_view(), name="lead-stats-api"),
    path("leads/bulk/", lead_management.LeadBulkAPI.as_view(), name="lead-bulk-api"),
    path("leads/export/", lead_management.export_leads, name="lead-export-api"),
    path("leads/follow-ups/", lead_management.LeadFollowUpListAPI.as_view(), name="lead-follow-up-list-api"),
    path("leads/follow-ups/<int:pk>/", lead_management.FollowUpDetailAPI.as_view(), name="lead-follow-up-detail-api"),
    path("leads/<int:pk>/", lead_management.LeadDetailAPI.as_view(), name="lead-detail-api"),
    path("leads/<int:pk>/activities/", lead_management.LeadRelatedAPI.as_view(), {"resource": "activities"}, name="lead-activities-api"),
    path("leads/<int:pk>/follow-ups/", lead_management.LeadRelatedAPI.as_view(), {"resource": "follow-ups"}, name="lead-related-follow-ups-api"),
    path("leads/<int:pk>/notes/", lead_management.LeadRelatedAPI.as_view(), {"resource": "notes"}, name="lead-notes-api"),
    path("leads/<int:pk>/status-history/", lead_management.LeadRelatedAPI.as_view(), {"resource": "status-history"}, name="lead-status-history-api"),
    path("leads/<int:pk>/<str:action>/", lead_management.LeadActionAPI.as_view(), name="lead-action-api"),

]
