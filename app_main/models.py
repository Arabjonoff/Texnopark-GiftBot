from urllib.parse import quote

from django.conf import settings
from django.db import models
from django.utils import timezone


# Rarity ranglari — model, dashboard va serializerlar uchun yagona manba
RARITY_COLORS = {
    'COMMON': '#3b82f6',     # Blue
    'RARE': '#8b5cf6',       # Purple
    'EPIC': '#ec4899',       # Pink
    'LEGENDARY': '#eab308',  # Gold
}


class PrizeCategory(models.Model):
    """
    Sovg'alarni guruhlash uchun kategoriya.
    Barabanning ishlashiga ta'sir qilmaydi — barcha aktiv sovg'alar bitta
    lentada qoladi. Faqat noaktiv kategoriyaning sovg'alari yashiriladi.
    """
    title = models.CharField(max_length=100, unique=True, verbose_name="Kategoriya nomi")
    description = models.TextField(blank=True, verbose_name="Tavsifi")
    image = models.ImageField(
        upload_to='categories/',
        blank=True,
        null=True,
        verbose_name="Kategoriya rasmi (fayl)"
    )
    icon = models.CharField(
        max_length=8,
        blank=True,
        verbose_name="Ikonka (emoji)",
        help_text="Rasm yuklanmasa shu emoji ishlatiladi. Masalan: 🎮"
    )
    sort_order = models.IntegerField(
        default=0,
        verbose_name="Tartib raqami",
        help_text="Kichik raqam yuqorida turadi"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktivligi",
        help_text="O'chirilsa bu kategoriyadagi sovg'alar barabanda qatnashmaydi"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqti")

    class Meta:
        verbose_name = "Sovg'a kategoriyasi"
        verbose_name_plural = "Sovg'a kategoriyalari"
        ordering = ['sort_order', 'title']

    def __str__(self):
        return self.title

    @property
    def display_image(self):
        """Yuklangan fayl ustunroq; bo'lmasa bo'sh qaytadi (emoji ishlatiladi)."""
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return ''

    @property
    def display_icon(self):
        return self.icon or '📦'


class Prize(models.Model):
    class Rarity(models.TextChoices):
        COMMON = 'COMMON', 'Oddiy'
        RARE = 'RARE', 'Noyob'
        EPIC = 'EPIC', 'Epik'
        LEGENDARY = 'LEGENDARY', 'Afsonaviy'

    title = models.CharField(max_length=100, verbose_name="Sovg'a nomi")
    category = models.ForeignKey(
        PrizeCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prizes',
        verbose_name="Kategoriyasi"
    )
    rarity = models.CharField(
        max_length=20,
        choices=Rarity.choices,
        default=Rarity.COMMON,
        verbose_name="Kamyoblik darajasi"
    )
    image = models.ImageField(
        upload_to='prizes/',
        blank=True,
        null=True,
        verbose_name="Sovg'a rasmi (fayl)"
    )
    image_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="Rasm yoki Ikonka URL (fayl o'rniga)"
    )
    probability = models.IntegerField(
        default=10,
        verbose_name="Ehtimollik og'irligi (0-100%)"
    )
    valid_days = models.IntegerField(
        default=3,
        verbose_name="Yutuq amal qilish muddati (kun)"
    )
    pickup_address = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Sovg'ani olish manzili",
        help_text="QR-kod ostida ko'rinadi. Masalan: Toshkent sh., Yoshlar Texnoparki"
    )
    latitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Kenglik (latitude)",
        help_text="Google Maps havolasidan avtomatik olinadi"
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Uzunlik (longitude)"
    )
    stock = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Qoldiq (dona)",
        help_text="Bo'sh qoldirilsa — cheksiz. 0 ga tushsa sovg'a barabandan chiqadi."
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktivligi"
    )

    class Meta:
        verbose_name = "Sovg'a"
        verbose_name_plural = "Sovg'alar"
        ordering = ['-probability', 'title']

    def __str__(self):
        return f"{self.title} [{self.rarity}] ({self.probability}%)"

    @property
    def display_image(self):
        """
        Yuklangan fayl ustunroq; bo'lmasa qo'lda kiritilgan URL qaytariladi.
        Frontend shu bitta maydondan foydalanadi.
        """
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return self.image_url or ''

    @property
    def map_link(self):
        """
        Google Maps havolasi. Koordinata kiritilgan bo'lsa aniq nuqtaga,
        bo'lmasa matnli manzil bo'yicha qidiruvga olib boradi.
        """
        if self.latitude is not None and self.longitude is not None:
            return (
                "https://www.google.com/maps/search/?api=1&query="
                f"{self.latitude},{self.longitude}"
            )
        if self.pickup_address:
            return (
                "https://www.google.com/maps/search/?api=1&query="
                + quote(self.pickup_address)
            )
        return ''

    @property
    def hex_color(self):
        return RARITY_COLORS.get(self.rarity, RARITY_COLORS['COMMON'])

    @property
    def is_out_of_stock(self):
        return self.stock is not None and self.stock <= 0


class StudentLead(models.Model):
    telegram_id = models.BigIntegerField(unique=True, db_index=True, verbose_name="Telegram ID")
    first_name = models.CharField(max_length=100, verbose_name="Ismi")
    last_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="Familiyasi")
    phone_number = models.CharField(max_length=20, verbose_name="Telefon raqami")
    extra_spins = models.IntegerField(default=0, verbose_name="Qo'shimcha spinlar soni")
    referrer = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals',
        verbose_name="Taklif qilgan o'quvchi"
    )
    # Taklif qilingan do'st birinchi yutug'ini rasmiylashtirgan payt.
    # Faqat shundan keyin u taklif qiluvchining hisobiga qo'shiladi —
    # aks holda soxta akkauntlar bilan /start bosib spin yig'ish oson edi.
    referral_confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Taklif tasdiqlangan vaqt"
    )
    # Foydalanuvchi botni bloklagan — ommaviy xabarlar unga yuborilmaydi.
    # /start qayta bosilsa avtomatik False bo'ladi.
    bot_blocked = models.BooleanField(default=False, verbose_name="Botni bloklagan")
    # Kunlik bonus oxirgi marta olingan sana (Toshkent vaqti bo'yicha)
    last_daily_bonus = models.DateField(null=True, blank=True, verbose_name="Oxirgi kunlik bonus")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqti")

    class Meta:
        verbose_name = "O'quvchi Lead"
        verbose_name_plural = "O'quvchilar Leads"
        ordering = ['-created_at']

    def __str__(self):
        name = f"{self.first_name} {self.last_name or ''}".strip()
        return f"{name} ({self.phone_number})"


class WinningResult(models.Model):
    class Status(models.TextChoices):
        # Baraban aylandi, lekin foydalanuvchi hali ism/telefonni yubormagan.
        # Spin shu zahoti sarflanadi — ilovani yopib qayta aylantirib bo'lmaydi.
        PENDING = 'PENDING', 'Rasmiylashtirilmagan'
        ACTIVE = 'ACTIVE', 'Aktiv'
        USED = 'USED', 'Ishlatilgan'
        EXPIRED = 'EXPIRED', 'Muddati o\'tgan'

    lead = models.ForeignKey(
        StudentLead,
        on_delete=models.CASCADE,
        related_name='winnings',
        verbose_name="O'quvchi"
    )
    prize = models.ForeignKey(
        Prize,
        on_delete=models.PROTECT,
        related_name='winnings',
        verbose_name="Yutib olingan sovg'a"
    )
    promo_code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        verbose_name="Promokod"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Holati"
    )
    expires_at = models.DateTimeField(verbose_name="Amal qilish muddati")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqt")
    used_at = models.DateTimeField(blank=True, null=True, verbose_name="Ishlatilgan vaqt")
    # Muddat tugashidan oldin botdan eslatma yuborilgan vaqt (qayta yubormaslik uchun)
    reminder_sent_at = models.DateTimeField(blank=True, null=True, verbose_name="Eslatma yuborilgan")
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_winnings',
        verbose_name="Sovg'ani bergan xodim"
    )

    class Meta:
        verbose_name = "Yutuq Natijasi"
        verbose_name_plural = "Yutuqlar Jurnali"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.promo_code} - {self.lead.first_name} ({self.prize.title})"

    def is_expired(self):
        return timezone.now() > self.expires_at

    def mark_used(self, staff_user=None):
        """Sovg'a qo'lga berildi — kim bergani ham yozib qo'yiladi."""
        self.status = self.Status.USED
        self.used_at = timezone.now()
        self.used_by = staff_user if staff_user and staff_user.is_authenticated else None
        self.save(update_fields=['status', 'used_at', 'used_by'])

    def save(self, *args, **kwargs):
        if self.status == self.Status.ACTIVE and self.is_expired():
            self.status = self.Status.EXPIRED
        super().save(*args, **kwargs)


class Broadcast(models.Model):
    """Dashboarddan bot foydalanuvchilariga ommaviy xabar."""

    class Audience(models.TextChoices):
        ALL = 'ALL', "Botdagi barcha foydalanuvchilar"
        REGISTERED = 'REGISTERED', "Forma to'ldirganlar"
        ACTIVE_PRIZE = 'ACTIVE_PRIZE', "Olib ketilmagan sovg'asi borlar"
        NO_SPIN = 'NO_SPIN', "Hali barabanni aylantirmaganlar"
        HAS_SPINS = 'HAS_SPINS', "Ishlatilmagan aylantirishi borlar"

    class Status(models.TextChoices):
        SENDING = 'SENDING', "Yuborilmoqda"
        DONE = 'DONE', "Yakunlandi"
        CANCELLED = 'CANCELLED', "Bekor qilindi"

    text = models.TextField(max_length=4000, verbose_name="Xabar matni")
    audience = models.CharField(
        max_length=20, choices=Audience.choices, default=Audience.ALL, verbose_name="Kimlarga"
    )
    with_button = models.BooleanField(default=True, verbose_name="«Ochish» tugmasi qo'shilsin")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SENDING, verbose_name="Holati"
    )
    total = models.PositiveIntegerField(default=0, verbose_name="Jami qabul qiluvchilar")
    sent_count = models.PositiveIntegerField(default=0, verbose_name="Yuborildi")
    failed_count = models.PositiveIntegerField(default=0, verbose_name="Yetib bormadi")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='broadcasts', verbose_name="Yuborgan xodim"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqti")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Tugagan vaqti")

    class Meta:
        verbose_name = "Ommaviy xabar"
        verbose_name_plural = "Ommaviy xabarlar"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_audience_display()} — {self.text[:40]}"

    @property
    def progress_percent(self):
        if not self.total:
            return 100
        return round((self.sent_count + self.failed_count) / self.total * 100)


class BotMessage(models.Model):
    """
    Bot yuborishi kerak bo'lgan xabarlar navbati (outbox).

    Web jarayoni Telegram'ga to'g'ridan-to'g'ri murojaat qilmaydi — xabarni
    shu jadvalga yozadi, bot jarayonidagi fon sikli (bot/worker.py) esa
    Telegram limitlariga rioya qilgan holda yuboradi.
    """

    class Kind(models.TextChoices):
        BROADCAST = 'BROADCAST', "Ommaviy xabar"
        REMINDER = 'REMINDER', "Muddat eslatmasi"
        REFERRAL = 'REFERRAL', "Referal bildirishnomasi"

    class Status(models.TextChoices):
        PENDING = 'PENDING', "Navbatda"
        SENT = 'SENT', "Yuborildi"
        FAILED = 'FAILED', "Yetib bormadi"

    chat_id = models.BigIntegerField(verbose_name="Telegram ID")
    text = models.TextField(verbose_name="Matn")
    # '' — oddiy matn (dashboarddan kiritilgan matn shunday yuboriladi), 'HTML' — tizim xabarlari
    parse_mode = models.CharField(max_length=10, blank=True, default='')
    with_button = models.BooleanField(default=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, verbose_name="Turi")
    broadcast = models.ForeignKey(
        Broadcast, on_delete=models.CASCADE, null=True, blank=True, related_name='messages'
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, verbose_name="Holati"
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Bot xabari"
        verbose_name_plural = "Bot xabarlari navbati"
        ordering = ['created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.chat_id} ({self.status})"


class SiteSettings(models.Model):
    """
    Dashboarddan boshqariladigan sozlamalar. Jadvalda doim bitta qator (pk=1)
    bo'ladi — SiteSettings.load() orqali olinadi va qisqa muddat keshlanadi.
    """
    CACHE_KEY = 'site-settings:v1'
    CACHE_SECONDS = 30

    subscription_required = models.BooleanField(
        default=True,
        verbose_name="Majburiy obuna yoqilgan",
        help_text="Yoqilsa, barabanni aylantirishdan oldin quyidagi kanallarga obuna tekshiriladi"
    )
    campaign_start = models.DateTimeField(
        null=True, blank=True, verbose_name="Aksiya boshlanishi",
        help_text="Bo'sh — darhol boshlangan"
    )
    campaign_end = models.DateTimeField(
        null=True, blank=True, verbose_name="Aksiya tugashi",
        help_text="Bo'sh — muddatsiz. Tugagach baraban yopiladi, yutuqlarni olish davom etadi"
    )
    campaign_closed_message = models.CharField(
        max_length=255, blank=True, verbose_name="Aksiya yopiq paytdagi matn",
        help_text="Bo'sh qolsa standart matn ko'rsatiladi"
    )
    daily_bonus_enabled = models.BooleanField(
        default=False,
        verbose_name="Kunlik bonus",
        help_text="Har kuni MiniApp'ga kirgan foydalanuvchi +1 aylantirish oladi"
    )
    referrals_per_spin = models.PositiveSmallIntegerField(
        default=3,
        verbose_name="Necha do'st = +1 aylantirish"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sozlamalar"
        verbose_name_plural = "Sozlamalar"

    def __str__(self):
        return "Sozlamalar"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete(self.CACHE_KEY)

    @classmethod
    def load(cls):
        from django.core.cache import cache
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, obj, cls.CACHE_SECONDS)
        return obj

    def campaign_state(self, now=None):
        """'active' | 'not_started' | 'ended'"""
        now = now or timezone.now()
        if self.campaign_start and now < self.campaign_start:
            return 'not_started'
        if self.campaign_end and now >= self.campaign_end:
            return 'ended'
        return 'active'


class RequiredChannel(models.Model):
    """
    Majburiy obuna kanali yoki guruhi. Bot shu kanalda ADMIN bo'lishi shart —
    aks holda Telegram obunachilar ro'yxatini bermaydi.
    """
    title = models.CharField(max_length=100, verbose_name="Nomi")
    chat_id = models.CharField(
        max_length=100,
        verbose_name="Kanal username yoki ID",
        help_text="Ochiq kanal: @texnopark_uz. Yopiq kanal: -1001234567890"
    )
    invite_link = models.URLField(
        blank=True,
        verbose_name="Taklif havolasi",
        help_text="Yopiq kanal uchun majburiy (https://t.me/+AbCd...). Ochiq kanalda avtomatik"
    )
    sort_order = models.IntegerField(default=0, verbose_name="Tartib")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Majburiy kanal"
        verbose_name_plural = "Majburiy kanallar"
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.title} ({self.chat_id})"

    @property
    def link(self):
        if self.invite_link:
            return self.invite_link
        if self.chat_id.startswith('@'):
            return f"https://t.me/{self.chat_id[1:]}"
        return ''
