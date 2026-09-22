from urllib.parse import quote

from django.db import models
from django.utils import timezone


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
        color_map = {
            'COMMON': '#3b82f6',     # Blue
            'RARE': '#8b5cf6',       # Purple
            'EPIC': '#ec4899',       # Pink
            'LEGENDARY': '#eab308'   # Gold
        }
        return color_map.get(self.rarity, '#3b82f6')


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

    class Meta:
        verbose_name = "Yutuq Natijasi"
        verbose_name_plural = "Yutuqlar Jurnali"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.promo_code} - {self.lead.first_name} ({self.prize.title})"

    def is_expired(self):
        return timezone.now() > self.expires_at

    def save(self, *args, **kwargs):
        if self.status == self.Status.ACTIVE and self.is_expired():
            self.status = self.Status.EXPIRED
        super().save(*args, **kwargs)
