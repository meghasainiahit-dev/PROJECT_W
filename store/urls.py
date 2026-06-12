from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from store_app.web import dashboard

from django.views.static import serve
from django.urls import re_path




urlpatterns = [
path('admin/', admin.site.urls),

path('api/', include('store_app.urls')),

path("api/login-admin/", dashboard.login_api),
path("api/login-admin", dashboard.login_api),
path("login/", dashboard.login_page),
path("logout/", dashboard.logout_page),
path("dashboard/", dashboard.dashboard, name="dashboard"),
path("users/", dashboard.users_page, name="users"),
path("billing/", dashboard.billing_coming_soon, name="billing_coming_soon"),
path("api/dashboard-data/", dashboard.dashboard_data, name="dashboard_data"),
]

if settings.DEBUG:
   urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
   urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [
  re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
