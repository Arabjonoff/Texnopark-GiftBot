from django.urls import path

from app_main import dashboard_views as views

urlpatterns = [
    # Auth
    path('login/', views.dashboard_login, name='dashboard-login'),
    path('logout/', views.dashboard_logout, name='dashboard-logout'),

    # Statistika
    path('', views.dashboard_index, name='dashboard-index'),

    # Sovg'alar CRUD
    path('prizes/', views.prize_list, name='dashboard-prizes'),
    path('prizes/new/', views.prize_create, name='dashboard-prize-create'),
    path('prizes/<int:pk>/edit/', views.prize_edit, name='dashboard-prize-edit'),
    path('prizes/<int:pk>/delete/', views.prize_delete, name='dashboard-prize-delete'),
    path('prizes/<int:pk>/toggle/', views.prize_toggle, name='dashboard-prize-toggle'),

    # Kategoriyalar CRUD
    path('categories/', views.category_list, name='dashboard-categories'),
    path('categories/new/', views.category_create, name='dashboard-category-create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='dashboard-category-edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='dashboard-category-delete'),
    path('categories/<int:pk>/toggle/', views.category_toggle, name='dashboard-category-toggle'),

    # O'quvchilar
    path('leads/', views.lead_list, name='dashboard-leads'),
    path('leads/export/', views.lead_export, name='dashboard-leads-export'),

    # Yutuqlar
    path('winnings/', views.winning_list, name='dashboard-winnings'),
    path('winnings/export/', views.winning_export, name='dashboard-winnings-export'),
    path('winnings/<int:pk>/activate/', views.winning_activate, name='dashboard-winning-activate'),

    # Ommaviy xabarlar
    path('broadcasts/', views.broadcast_list, name='dashboard-broadcasts'),
    path('broadcasts/new/', views.broadcast_create, name='dashboard-broadcast-create'),
    path('broadcasts/<int:pk>/cancel/', views.broadcast_cancel, name='dashboard-broadcast-cancel'),

    # Sozlamalar va majburiy kanallar
    path('settings/', views.settings_view, name='dashboard-settings'),
    path('settings/channels/new/', views.channel_create, name='dashboard-channel-create'),
    path('settings/channels/<int:pk>/toggle/', views.channel_toggle, name='dashboard-channel-toggle'),
    path('settings/channels/<int:pk>/delete/', views.channel_delete, name='dashboard-channel-delete'),

    # Hisob
    path('account/password/', views.account_password, name='dashboard-account-password'),

    # QR skaner
    path('scan/', views.dashboard_scan, name='dashboard-scan'),
]
