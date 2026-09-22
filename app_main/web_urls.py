from django.urls import path

from app_main.web_views import admin_scan_redirect, index_view

urlpatterns = [
    path('', index_view, name='miniapp-index'),
    path('admin-scan/', admin_scan_redirect, name='admin-scan'),
]
