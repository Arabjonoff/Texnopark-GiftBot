from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from django.utils import timezone
from datetime import timedelta

from app_main.models import Prize, StudentLead, WinningResult
from app_main.serializers import (
    PrizeSerializer,
    StudentLeadSerializer,
    WinningResultSerializer,
    ClaimPrizeSerializer,
    VerifyCodeSerializer,
    PublicWinnerSerializer
)
from app_main.services import (
    verify_telegram_init_data,
    calculate_weighted_prize,
    check_user_spin_status,
    generate_unique_promo_code,
    get_spinnable_prizes,
    REFERRALS_PER_SPIN,
)


class ValidateInitDataView(APIView):
    def post(self, request):
        init_data_raw = request.data.get('init_data')
        is_valid, user_data = verify_telegram_init_data(init_data_raw)

        if not is_valid or not user_data:
            return Response(
                {"error": "Xavfsizlik tekshiruvidan o'tmadi (Invalid Telegram initData)"},
                status=status.HTTP_403_FORBIDDEN
            )

        tg_id = user_data.get('id')
        available_spins, lead, winnings = check_user_spin_status(tg_id)

        winnings_data = WinningResultSerializer(winnings, many=True).data
        invited_count = lead.referrals.count() if lead else 0
        bot_username = "texnogiftbot"
        referral_link = f"https://t.me/{bot_username}?start=ref_{tg_id}"

        return Response({
            "valid": True,
            "telegram_id": tg_id,
            "user_info": user_data,
            "available_spins": available_spins,
            "winnings": winnings_data,
            "referral_link": referral_link,
            "invited_count": invited_count,
            "referrals_per_spin": REFERRALS_PER_SPIN,
        }, status=status.HTTP_200_OK)


class PrizeListView(APIView):
    def get(self, request):
        # Noaktiv kategoriyaning sovg'alari lentada ham ko'rinmasligi kerak
        prizes = get_spinnable_prizes()
        serializer = PrizeSerializer(prizes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SpinRouletteView(APIView):
    def post(self, request):
        init_data_raw = request.data.get('init_data')
        is_valid, user_data = verify_telegram_init_data(init_data_raw)

        if not is_valid or not user_data:
            return Response(
                {"error": "Xavfsizlik tekshiruvidan o'tmadi (Invalid Telegram initData)"},
                status=status.HTTP_403_FORBIDDEN
            )

        tg_id = user_data.get('id')
        available_spins, lead, winnings = check_user_spin_status(tg_id)

        if available_spins <= 0:
            return Response(
                {
                    "error": "Sizda aylantirish imkoniyati qolmagan! Do'stlaringizni taklif qilib qo'shimcha spin oling.",
                    "available_spins": 0,
                    "winnings": WinningResultSerializer(winnings, many=True).data
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            won_prize = calculate_weighted_prize()
        except Exception as e:
            return Response(
                {"error": f"Sovg'ani aniqlashda xatolik: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        target_index = 65
        prize_serializer = PrizeSerializer(won_prize)

        return Response({
            "prize": prize_serializer.data,
            "target_index": target_index,
            "message": "Yutuq backend serverda aniqlandi!"
        }, status=status.HTTP_200_OK)


class ClaimPrizeView(APIView):
    def post(self, request):
        serializer = ClaimPrizeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        init_data_raw = data['init_data']
        is_valid, user_data = verify_telegram_init_data(init_data_raw)

        if not is_valid or not user_data:
            return Response(
                {"error": "Xavfsizlik tekshiruvidan o'tmadi (Invalid Telegram initData)"},
                status=status.HTTP_403_FORBIDDEN
            )

        tg_id = user_data.get('id')
        available_spins, lead, winnings = check_user_spin_status(tg_id)

        if available_spins <= 0:
            return Response(
                {"error": "Aylantirish va yutuqni biriktirish imkoniyati tugagan"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            prize = Prize.objects.get(id=data['prize_id'], is_active=True)
        except Prize.DoesNotExist:
            return Response(
                {"error": "Tanlangan sovg'a topilmadi yoki faol emas"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update or create StudentLead
        student_lead, created = StudentLead.objects.update_or_create(
            telegram_id=tg_id,
            defaults={
                'first_name': data['first_name'],
                'last_name': data.get('last_name', ''),
                'phone_number': data['phone_number'],
            }
        )

        promo_code = generate_unique_promo_code()
        expires_at = timezone.now() + timedelta(days=prize.valid_days)

        winning = WinningResult.objects.create(
            lead=student_lead,
            prize=prize,
            promo_code=promo_code,
            status=WinningResult.Status.ACTIVE,
            expires_at=expires_at
        )

        # Recalculate remaining spins & winnings
        updated_spins, updated_lead, updated_winnings = check_user_spin_status(tg_id)
        referral_link = f"https://t.me/texnogiftbot?start=ref_{tg_id}"

        return Response({
            "message": "Muvaffaqiyatli saqlandi va yutuq biriktirildi!",
            "winning_result": WinningResultSerializer(winning).data,
            "available_spins": updated_spins,
            "winnings": WinningResultSerializer(updated_winnings, many=True).data,
            "referral_link": referral_link,
            "invited_count": updated_lead.referrals.count(),
            "referrals_per_spin": REFERRALS_PER_SPIN,
        }, status=status.HTTP_201_CREATED)


class MyPrizeView(APIView):
    def get(self, request):
        init_data_raw = request.query_params.get('init_data')
        tg_id_param = request.query_params.get('telegram_id')

        tg_id = None
        if init_data_raw:
            is_valid, user_data = verify_telegram_init_data(init_data_raw)
            if is_valid and user_data:
                tg_id = user_data.get('id')

        if not tg_id and tg_id_param:
            try:
                tg_id = int(tg_id_param)
            except ValueError:
                pass

        if not tg_id:
            return Response(
                {"error": "Telegram ID topilmadi"},
                status=status.HTTP_400_BAD_REQUEST
            )

        available_spins, lead, winnings = check_user_spin_status(tg_id)
        winnings_data = WinningResultSerializer(winnings, many=True).data
        invited_count = lead.referrals.count() if lead else 0
        referral_link = f"https://t.me/texnogiftbot?start=ref_{tg_id}"

        return Response({
            "available_spins": available_spins,
            "winnings": winnings_data,
            "referral_link": referral_link,
            "invited_count": invited_count,
            "referrals_per_spin": REFERRALS_PER_SPIN,
        }, status=status.HTTP_200_OK)


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

        qs = WinningResult.objects.select_related('lead', 'prize').order_by('-created_at')
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

        if not winning:
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
        winning.status = WinningResult.Status.USED
        winning.used_at = timezone.now()
        winning.save(update_fields=['status', 'used_at'])

        return Response({
            "success": True,
            "confirmed": True,
            "can_activate": False,
            "message": "Yutuq muvaffaqiyatli aktivlashtirildi va berildi!",
            "winning_result": WinningResultSerializer(winning).data
        }, status=status.HTTP_200_OK)
