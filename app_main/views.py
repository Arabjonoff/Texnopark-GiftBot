from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from app_main.models import SiteSettings, StudentLead, WinningResult
from app_main.serializers import (
    PrizeSerializer,
    WinningResultSerializer,
    ClaimPrizeSerializer,
    VerifyCodeSerializer,
    PublicWinnerSerializer
)
from app_main.messaging import notify_referral_confirmed
from app_main.services import (
    verify_telegram_init_data,
    campaign_info,
    check_user_spin_status,
    claim_daily_bonus,
    daily_bonus_available,
    get_pending_winning,
    get_spinnable_prizes,
    referrals_per_spin,
    start_spin,
    confirm_referral,
    confirmed_referrals,
    top_referrers,
    CampaignClosed,
    NoSpinsLeft,
)
from app_main.subscription import subscription_status


def _invalid_init_data():
    return Response(
        {"error": "Xavfsizlik tekshiruvidan o'tmadi (Invalid Telegram initData)"},
        status=status.HTTP_403_FORBIDDEN
    )


def _authenticate(init_data_raw):
    """Telegram initData'ni tekshiradi. Returns user_data yoki None."""
    is_valid, user_data = verify_telegram_init_data(init_data_raw)
    if not is_valid or not user_data or not user_data.get('id'):
        return None
    return user_data


def _saved_phone_digits(lead):
    """+998901234567 -> '901234567' (formani oldindan to'ldirish uchun)."""
    digits = ''.join(ch for ch in (lead.phone_number or '') if ch.isdigit()) if lead else ''
    if digits.startswith('998'):
        digits = digits[3:]
    return digits if len(digits) == 9 else ''


def _user_state(tg_id):
    """
    MiniApp'ga kerak bo'lgan foydalanuvchi holati — validate, claim va
    my-prize javoblarida bir xil ko'rinishda qaytadi.
    """
    available_spins, lead, winnings = check_user_spin_status(tg_id)
    pending = get_pending_winning(lead)
    site = SiteSettings.load()
    per_spin = referrals_per_spin()

    invited_count = 0
    pending_invites = 0
    referral_friends = []
    if lead:
        referrals = list(
            confirmed_referrals(lead).order_by('referral_confirmed_at')
            .values_list('first_name', flat=True)
        )
        invited_count = len(referrals)
        # Havola orqali kirgan, lekin hali yutug'ini rasmiylashtirmagan do'stlar
        pending_invites = lead.referrals.filter(referral_confirmed_at__isnull=True).count()
        # Joriy "3 talik" tsikldagi do'stlar — referal kartasidagi avatarlar uchun
        in_cycle = invited_count % per_spin
        referral_friends = referrals[invited_count - in_cycle:] if in_cycle else []

    return {
        "available_spins": available_spins,
        "winnings": WinningResultSerializer(winnings, many=True).data,
        "pending_prize": PrizeSerializer(pending.prize).data if pending else None,
        "referral_link": f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start=ref_{tg_id}",
        "invited_count": invited_count,
        "pending_invites": pending_invites,
        "referral_friends": referral_friends,
        "referrals_per_spin": per_spin,
        "campaign": campaign_info(site),
        "daily_bonus": {
            "enabled": site.daily_bonus_enabled,
            "available": daily_bonus_available(lead, site),
        },
        "saved_profile": {
            "first_name": lead.first_name if lead and lead.phone_number else '',
            "last_name": (lead.last_name or '') if lead and lead.phone_number else '',
            "phone_digits": _saved_phone_digits(lead),
        },
    }


class ValidateInitDataView(APIView):
    def post(self, request):
        user_data = _authenticate(request.data.get('init_data'))
        if not user_data:
            return _invalid_init_data()

        tg_id = user_data['id']
        return Response({
            "valid": True,
            "telegram_id": tg_id,
            "user_info": user_data,
            "subscription": subscription_status(tg_id),
            **_user_state(tg_id),
        }, status=status.HTTP_200_OK)


class CheckSubscriptionView(APIView):
    """«Obunani tekshirish» tugmasi — kanalga qo'shilgandan keyin bosiladi."""

    def post(self, request):
        user_data = _authenticate(request.data.get('init_data'))
        if not user_data:
            return _invalid_init_data()
        return Response(subscription_status(user_data['id']), status=status.HTTP_200_OK)


class PrizeListView(APIView):
    def get(self, request):
        # Noaktiv kategoriyaning sovg'alari lentada ham ko'rinmasligi kerak
        prizes = get_spinnable_prizes()
        serializer = PrizeSerializer(prizes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SpinRouletteView(APIView):
    """
    Sovg'ani serverda aniqlaydi va darhol PENDING yutuq sifatida saqlaydi.
    Rasmiylashtirilmagan yutuq bo'lsa, yangi spin o'rniga o'sha qaytadi.
    """
    def post(self, request):
        user_data = _authenticate(request.data.get('init_data'))
        if not user_data:
            return _invalid_init_data()

        tg_id = user_data['id']

        # Rasmiylashtirilmagan sovg'a bo'lsa, u baribir qaytariladi — obuna
        # faqat yangi aylantirish uchun talab qilinadi
        lead = StudentLead.objects.filter(telegram_id=tg_id).first()
        if not get_pending_winning(lead):
            subscription = subscription_status(tg_id)
            if not subscription['ok']:
                return Response(
                    {
                        "error": "Barabanni aylantirish uchun kanallarga obuna bo'ling.",
                        "code": "not_subscribed",
                        "subscription": subscription,
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        try:
            winning, created = start_spin(tg_id, user_data)
        except CampaignClosed:
            info = campaign_info()
            return Response(
                {"error": info['message'], "code": "campaign_closed", "campaign": info},
                status=status.HTTP_403_FORBIDDEN
            )
        except NoSpinsLeft:
            return Response(
                {
                    "error": "Sizda aylantirish imkoniyati qolmagan! Do'stlaringizni taklif qilib qo'shimcha imkoniyat oling.",
                    "available_spins": 0,
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except ValueError as e:
            return Response(
                {"error": f"Sovg'ani aniqlashda xatolik: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            "prize": PrizeSerializer(winning.prize).data,
            "target_index": 65,
            # False — foydalanuvchi avval aylantirgan, lekin rasmiylashtirmagan
            "is_new_spin": created,
        }, status=status.HTTP_200_OK)


class ClaimPrizeView(APIView):
    """
    PENDING yutuqni rasmiylashtiradi. Qaysi sovg'a tushgani serverda
    saqlangan — frontend yuborgan prize_id hisobga olinmaydi.
    """
    def post(self, request):
        serializer = ClaimPrizeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        user_data = _authenticate(data['init_data'])
        if not user_data:
            return _invalid_init_data()

        tg_id = user_data['id']

        with transaction.atomic():
            lead = StudentLead.objects.select_for_update().filter(telegram_id=tg_id).first()
            winning = get_pending_winning(lead)
            if not winning:
                return Response(
                    {"error": "Rasmiylashtiriladigan yutuq topilmadi. Avval barabanni aylantiring."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            lead.first_name = data['first_name']
            lead.last_name = data.get('last_name', '')
            lead.phone_number = data['phone_number']
            lead.save(update_fields=['first_name', 'last_name', 'phone_number'])

            # Muddat rasmiylashtirilgan paytdan boshlab hisoblanadi
            winning.status = WinningResult.Status.ACTIVE
            winning.expires_at = timezone.now() + timedelta(days=winning.prize.valid_days)
            winning.save(update_fields=['status', 'expires_at'])

            # Do'st haqiqiy ishtirokchi bo'ldi — taklif qiluvchiga hisoblanadi
            referrer, spin_awarded = confirm_referral(lead)
            if referrer:
                notify_referral_confirmed(referrer, lead, spin_awarded, referrals_per_spin())

        return Response({
            "message": "Muvaffaqiyatli saqlandi va yutuq biriktirildi!",
            "winning_result": WinningResultSerializer(winning).data,
            **_user_state(tg_id),
        }, status=status.HTTP_201_CREATED)


class MyPrizeView(APIView):
    """
    Foydalanuvchining o'z yutuqlari. Faqat imzolangan initData bilan —
    promokod = sovg'a, shuning uchun telegram_id bo'yicha ochiq berilmaydi.
    """
    def get(self, request):
        user_data = _authenticate(request.query_params.get('init_data'))
        if not user_data:
            return _invalid_init_data()

        return Response(_user_state(user_data['id']), status=status.HTTP_200_OK)


class DailyBonusView(APIView):
    """Kunlik +1 aylantirish (dashboardda yoqilgan bo'lsa)."""

    def post(self, request):
        user_data = _authenticate(request.data.get('init_data'))
        if not user_data:
            return _invalid_init_data()

        if not claim_daily_bonus(user_data['id'], user_data):
            return Response(
                {"error": "Bugungi bonus allaqachon olingan. Ertaga qaytib keling!"},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response({
            "message": "+1 aylantirish qo'shildi!",
            **_user_state(user_data['id']),
        }, status=status.HTTP_200_OK)


class TopReferrersView(APIView):
    """Eng ko'p do'st taklif qilganlar — ochiq ro'yxat, ismlar qisqartirilgan."""

    def get(self, request):
        return Response({"referrers": top_referrers(10)}, status=status.HTTP_200_OK)


class PublicWinnersView(APIView):
    """
    MiniApp'dagi «Yutuq olganlar» bo'limi uchun ochiq ro'yxat.

    Maxfiylik: telefon va Telegram ID qaytarilmaydi, familiya bosh harfga
    qisqartiriladi (PublicWinnerSerializer'ga qarang).
    """
    # Ro'yxat ochiq — hamma ishtirokchi ko'ra oladi
    MAX_LIMIT = 100
    DEFAULT_LIMIT = 30

    def get(self, request):
        try:
            limit = int(request.query_params.get('limit', self.DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = max(1, min(limit, self.MAX_LIMIT))

        try:
            offset = int(request.query_params.get('offset', 0))
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)

        qs = (
            WinningResult.objects.select_related('lead', 'prize')
            .exclude(status=WinningResult.Status.PENDING)
            .order_by('-created_at')
        )
        total = qs.count()
        rows = qs[offset:offset + limit]

        return Response({
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
            "winners": PublicWinnerSerializer(rows, many=True).data,
        }, status=status.HTTP_200_OK)


class AdminVerifyCodeView(APIView):
    """
    Promokodni tekshirish va sovg'ani berish.

    Ikki bosqichli ishlaydi:
      confirm=False (default) -> faqat ma'lumot qaytaradi, holat o'zgarmaydi.
      confirm=True            -> yutuqni USED holatiga o'tkazadi.

    Shu tufayli tasodifan skanerlangan QR sovg'ani "yoqib" yubormaydi.
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = VerifyCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        code = serializer.validated_data['promo_code'].strip().upper()
        confirm = bool(request.data.get('confirm', False))

        winning = WinningResult.objects.select_related('lead', 'prize').filter(
            promo_code__iexact=code
        ).first()

        # Rasmiylashtirilmagan yutuqning promokodi foydalanuvchiga hali ko'rsatilmagan
        if not winning or winning.status == WinningResult.Status.PENDING:
            return Response(
                {"error": f"Promokod '{code}' bazadan topilmadi!"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Muddati o'tgan bo'lsa holatni yangilab, rad etamiz
        if winning.status == WinningResult.Status.ACTIVE and winning.is_expired():
            winning.status = WinningResult.Status.EXPIRED
            winning.save(update_fields=['status'])

        if winning.status == WinningResult.Status.EXPIRED:
            return Response(
                {
                    "error": "Ushbu yutuqning amal qilish muddati tugagan!",
                    "can_activate": False,
                    "winning_result": WinningResultSerializer(winning).data
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if winning.status == WinningResult.Status.USED:
            used_at = timezone.localtime(winning.used_at).strftime('%Y-%m-%d %H:%M') if winning.used_at else '-'
            return Response(
                {
                    "error": f"Ushbu promokod allaqachon ishlatilgan ({used_at})",
                    "can_activate": False,
                    "winning_result": WinningResultSerializer(winning).data
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1-bosqich: faqat ko'rsatish, holat o'zgarmaydi
        if not confirm:
            return Response({
                "success": True,
                "confirmed": False,
                "can_activate": True,
                "message": "Ma'lumot topildi. Sovg'ani berish uchun tasdiqlang.",
                "winning_result": WinningResultSerializer(winning).data
            }, status=status.HTTP_200_OK)

        # 2-bosqich: sovg'ani berish
        winning.mark_used(request.user)

        return Response({
            "success": True,
            "confirmed": True,
            "can_activate": False,
            "message": "Yutuq muvaffaqiyatli aktivlashtirildi va berildi!",
            "winning_result": WinningResultSerializer(winning).data
        }, status=status.HTTP_200_OK)
