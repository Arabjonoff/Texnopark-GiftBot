from rest_framework import serializers
from app_main.models import Prize, PrizeCategory, StudentLead, WinningResult
from app_main.services import mask_name

class PrizeCategorySerializer(serializers.ModelSerializer):
    display_image = serializers.ReadOnlyField()
    display_icon = serializers.ReadOnlyField()

    class Meta:
        model = PrizeCategory
        fields = ['id', 'title', 'description', 'display_image', 'display_icon', 'sort_order']


class PrizeSerializer(serializers.ModelSerializer):
    hex_color = serializers.ReadOnlyField()
    # Yuklangan fayl yoki qo'lda kiritilgan URL — frontend shu maydonni ishlatadi
    display_image = serializers.ReadOnlyField()
    # Sovg'ani olish manzili — QR-kod ostida ko'rsatiladi
    map_link = serializers.ReadOnlyField()
    category = PrizeCategorySerializer(read_only=True)

    class Meta:
        model = Prize
        fields = [
            'id',
            'title',
            'category',
            'rarity',
            'image_url',
            'display_image',
            'probability',
            'valid_days',
            'pickup_address',
            'map_link',
            'is_active',
            'hex_color'
        ]


class StudentLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentLead
        fields = [
            'id',
            'telegram_id',
            'first_name',
            'last_name',
            'phone_number',
            'created_at'
        ]


class WinningResultSerializer(serializers.ModelSerializer):
    prize = PrizeSerializer(read_only=True)
    lead = StudentLeadSerializer(read_only=True)

    class Meta:
        model = WinningResult
        fields = [
            'id',
            'lead',
            'prize',
            'promo_code',
            'status',
            'expires_at',
            'created_at',
            'used_at'
        ]


class ClaimPrizeSerializer(serializers.Serializer):
    init_data = serializers.CharField(required=True)
    # Eski (keshdagi) klientlar uchun qabul qilinadi, lekin hisobga olinmaydi —
    # qaysi sovg'a tushgani serverda saqlanadi
    prize_id = serializers.IntegerField(required=False)
    first_name = serializers.CharField(max_length=100, required=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=True)


class VerifyCodeSerializer(serializers.Serializer):
    promo_code = serializers.CharField(max_length=20, required=True)


class PublicWinnerSerializer(serializers.ModelSerializer):
    """
    «Yutuq olganlar» ro'yxati uchun ochiq serializer.

    Maxfiylik: telefon raqami va Telegram ID hech qachon qaytarilmaydi,
    familiya esa faqat bosh harf sifatida beriladi (masalan: "Sevara Y.").
    """
    display_name = serializers.SerializerMethodField()
    prize_title = serializers.CharField(source='prize.title', read_only=True)
    prize_rarity = serializers.CharField(source='prize.rarity', read_only=True)
    prize_color = serializers.CharField(source='prize.hex_color', read_only=True)
    prize_image = serializers.CharField(source='prize.display_image', read_only=True)

    class Meta:
        model = WinningResult
        fields = [
            'display_name',
            'prize_title',
            'prize_rarity',
            'prize_color',
            'prize_image',
            'created_at',
        ]

    def get_display_name(self, obj):
        return mask_name(obj.lead.first_name, obj.lead.last_name)
