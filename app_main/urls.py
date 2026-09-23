from django.urls import path
from app_main.views import (
    ValidateInitDataView,
    PrizeListView,
    SpinRouletteView,
    ClaimPrizeView,
    MyPrizeView,
    PublicWinnersView,
    AdminVerifyCodeView,
    CheckSubscriptionView,
    DailyBonusView,
    TopReferrersView,
)

urlpatterns = [
    path('validate-init/', ValidateInitDataView.as_view(), name='api-validate-init'),
    path('prizes/', PrizeListView.as_view(), name='api-prizes'),
    path('spin/', SpinRouletteView.as_view(), name='api-spin'),
    path('claim-prize/', ClaimPrizeView.as_view(), name='api-claim-prize'),
    path('my-prize/', MyPrizeView.as_view(), name='api-my-prize'),
    path('winners/', PublicWinnersView.as_view(), name='api-winners'),
    path('top-referrers/', TopReferrersView.as_view(), name='api-top-referrers'),
    path('check-subscription/', CheckSubscriptionView.as_view(), name='api-check-subscription'),
    path('daily-bonus/', DailyBonusView.as_view(), name='api-daily-bonus'),
    path('admin/verify-code/', AdminVerifyCodeView.as_view(), name='api-admin-verify-code'),
]
