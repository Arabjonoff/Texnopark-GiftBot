from django.urls import path
from app_main.views import (
    ValidateInitDataView,
    PrizeListView,
    SpinRouletteView,
    ClaimPrizeView,
    MyPrizeView,
    PublicWinnersView,
    AdminVerifyCodeView
)

urlpatterns = [
    path('validate-init/', ValidateInitDataView.as_view(), name='api-validate-init'),
    path('prizes/', PrizeListView.as_view(), name='api-prizes'),
    path('spin/', SpinRouletteView.as_view(), name='api-spin'),
    path('claim-prize/', ClaimPrizeView.as_view(), name='api-claim-prize'),
    path('my-prize/', MyPrizeView.as_view(), name='api-my-prize'),
    path('winners/', PublicWinnersView.as_view(), name='api-winners'),
    path('admin/verify-code/', AdminVerifyCodeView.as_view(), name='api-admin-verify-code'),
]
