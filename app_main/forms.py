import re

import requests
from django import forms
from django.db import models

from app_main.models import Broadcast, Prize, PrizeCategory, RequiredChannel, SiteSettings


# Google Maps havolalaridan koordinata ajratib olish shablonlari.
# Masalan: .../@41.311081,69.240562,15z  yoki  ?q=41.311081,69.240562
_COORD_PATTERNS = (
    r'@(-?\d+\.\d+),(-?\d+\.\d+)',
    r'[?&](?:q|query|ll|center|daddr)=(-?\d+\.\d+),\s*(-?\d+\.\d+)',
    r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)',
    r'^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$',
)


def extract_coordinates(value: str):
    """
    Google Maps havolasidan (yoki "41.31, 69.24" ko'rinishidagi matndan)
    (latitude, longitude) juftligini qaytaradi. Topilmasa (None, None).

    Qisqa havolalar (maps.app.goo.gl) ichida koordinata bo'lmaydi — ular
    uchun avval to'liq manzilga yo'naltirish kuzatiladi.
    """
    value = (value or '').strip()
    if not value:
        return None, None

    if 'goo.gl' in value or 'maps.app' in value:
        try:
            resp = requests.get(value, allow_redirects=True, timeout=5)
            value = resp.url
        except requests.RequestException:
            pass

    for pattern in _COORD_PATTERNS:
        match = re.search(pattern, value)
        if match:
            try:
                lat, lng = float(match.group(1)), float(match.group(2))
            except (TypeError, ValueError):
                continue
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng

    return None, None


class PrizeForm(forms.ModelForm):
    """
    Dashboarddagi sovg'a qo'shish/tahrirlash formasi.
    Rasm fayl sifatida yuklanadi yoki tashqi URL sifatida kiritiladi.
    """

    clear_image = forms.BooleanField(
        required=False,
        label="Yuklangan rasmni o'chirish"
    )

    # Model maydoni emas — havoladan latitude/longitude ajratib olish uchun
    map_link = forms.CharField(
        required=False,
        label="Google Maps havolasi",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'id': 'id_map_link',
            'placeholder': 'https://maps.app.goo.gl/... yoki 41.311081, 69.240562',
        })
    )

    class Meta:
        model = Prize
        fields = [
            'title',
            'category',
            'rarity',
            'image',
            'image_url',
            'probability',
            'valid_days',
            'stock',
            'pickup_address',
            'latitude',
            'longitude',
            'is_active',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': "Masalan: 10% Chegirma",
                'maxlength': 100,
            }),
            'category': forms.Select(attrs={'class': 'form-input'}),
            'rarity': forms.Select(attrs={'class': 'form-input'}),
            # FileInput (ClearableFileInput emas) — Django'ning "Hozirda/Aniq/O'zgartirish"
            # standart belgilari o'rniga o'zimizning clear_image katagimiz ishlatiladi
            'image': forms.FileInput(attrs={
                'class': 'form-file',
                'accept': 'image/png,image/jpeg,image/webp,image/gif',
            }),
            'image_url': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'https://... (fayl yuklamasangiz)',
            }),
            'probability': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
                'max': 100,
                'step': 1,
            }),
            'valid_days': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 1,
                'max': 365,
                'step': 1,
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
                'step': 1,
                'placeholder': "Bo'sh — cheksiz",
            }),
            'pickup_address': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': "Masalan: Toshkent sh., Olmazor t., Yoshlar Texnoparki",
                'maxlength': 255,
            }),
            'latitude': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': 'any',
                'placeholder': '41.311081',
            }),
            'longitude': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': 'any',
                'placeholder': '69.240562',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }

    MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
    ALLOWED_CONTENT_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].empty_label = "— Kategoriyasiz —"
        self.fields['category'].required = False

        # Ro'yxatda aktiv kategoriyalar; tahrirlashda joriy (noaktiv) kategoriya ham qolsin
        qs = PrizeCategory.objects.filter(is_active=True)
        current = getattr(self.instance, 'category_id', None)
        if current:
            qs = PrizeCategory.objects.filter(
                models.Q(is_active=True) | models.Q(pk=current)
            )
        self.fields['category'].queryset = qs.order_by('sort_order', 'title')

    def clean_title(self):
        title = (self.cleaned_data.get('title') or '').strip()
        if not title:
            raise forms.ValidationError("Sovg'a nomi bo'sh bo'lishi mumkin emas.")
        return title

    def clean_probability(self):
        value = self.cleaned_data.get('probability')
        if value is None:
            raise forms.ValidationError("Ehtimollik kiritilishi shart.")
        if value < 0 or value > 100:
            raise forms.ValidationError("Ehtimollik 0 va 100 oralig'ida bo'lishi kerak.")
        return value

    def clean_valid_days(self):
        value = self.cleaned_data.get('valid_days')
        if value is None:
            raise forms.ValidationError("Amal qilish muddati kiritilishi shart.")
        if value < 1 or value > 365:
            raise forms.ValidationError("Muddat 1 va 365 kun oralig'ida bo'lishi kerak.")
        return value

    def clean_image(self):
        image = self.cleaned_data.get('image')
        # Mavjud fayl o'zgarmagan bo'lsa tekshirishning hojati yo'q
        if not image or not hasattr(image, 'content_type'):
            return image

        if image.content_type not in self.ALLOWED_CONTENT_TYPES:
            raise forms.ValidationError(
                "Faqat PNG, JPG, WEBP yoki GIF formatidagi rasm yuklash mumkin."
            )
        if image.size > self.MAX_IMAGE_BYTES:
            raise forms.ValidationError(
                f"Rasm hajmi {self.MAX_IMAGE_BYTES // (1024 * 1024)} MB dan oshmasligi kerak."
            )
        return image

    def clean_pickup_address(self):
        return (self.cleaned_data.get('pickup_address') or '').strip()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('clear_image'):
            cleaned['image'] = None
            self.instance.image = None

        # Havola kiritilgan bo'lsa, koordinatalarni undan olamiz —
        # qo'lda kiritilgan lat/lng ustidan yozadi.
        link = (cleaned.get('map_link') or '').strip()
        if link:
            lat, lng = extract_coordinates(link)
            if lat is None:
                self.add_error(
                    'map_link',
                    "Havoladan koordinata topilmadi. Google Maps'da nuqtani "
                    "bosib, «Ulashish» havolasini nusxalang yoki "
                    "«41.311081, 69.240562» ko'rinishida kiriting."
                )
            else:
                cleaned['latitude'] = lat
                cleaned['longitude'] = lng

        lat, lng = cleaned.get('latitude'), cleaned.get('longitude')
        if (lat is None) != (lng is None):
            raise forms.ValidationError(
                "Kenglik va uzunlik birgalikda kiritilishi kerak."
            )

        return cleaned


class PrizeCategoryForm(forms.ModelForm):
    """Dashboarddagi kategoriya qo'shish/tahrirlash formasi."""

    clear_image = forms.BooleanField(
        required=False,
        label="Yuklangan rasmni o'chirish"
    )

    class Meta:
        model = PrizeCategory
        fields = ['title', 'description', 'image', 'icon', 'sort_order', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': "Masalan: Chegirmalar",
                'maxlength': 100,
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': "Ixtiyoriy qisqa izoh",
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-file',
                'accept': 'image/png,image/jpeg,image/webp,image/gif',
            }),
            'icon': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '🎮',
                'maxlength': 8,
            }),
            'sort_order': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
                'max': 9999,
                'step': 1,
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }

    MAX_IMAGE_BYTES = PrizeForm.MAX_IMAGE_BYTES
    ALLOWED_CONTENT_TYPES = PrizeForm.ALLOWED_CONTENT_TYPES

    def clean_title(self):
        title = (self.cleaned_data.get('title') or '').strip()
        if not title:
            raise forms.ValidationError("Kategoriya nomi bo'sh bo'lishi mumkin emas.")

        # unique=True bo'lsa ham, katta-kichik harf farqini ham tekshiramiz
        clash = PrizeCategory.objects.filter(title__iexact=title)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Bu nomdagi kategoriya allaqachon mavjud.")
        return title

    def clean_sort_order(self):
        value = self.cleaned_data.get('sort_order')
        if value is None:
            return 0
        if value < 0:
            raise forms.ValidationError("Tartib raqami manfiy bo'lishi mumkin emas.")
        return value

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image or not hasattr(image, 'content_type'):
            return image

        if image.content_type not in self.ALLOWED_CONTENT_TYPES:
            raise forms.ValidationError(
                "Faqat PNG, JPG, WEBP yoki GIF formatidagi rasm yuklash mumkin."
            )
        if image.size > self.MAX_IMAGE_BYTES:
            raise forms.ValidationError(
                f"Rasm hajmi {self.MAX_IMAGE_BYTES // (1024 * 1024)} MB dan oshmasligi kerak."
            )
        return image

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('clear_image'):
            cleaned['image'] = None
            self.instance.image = None
        return cleaned


class BroadcastForm(forms.ModelForm):
    """Dashboarddan ommaviy xabar yuborish formasi."""

    class Meta:
        model = Broadcast
        fields = ['text', 'audience', 'with_button']
        widgets = {
            'text': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 7,
                'maxlength': 4000,
                'placeholder': "Masalan: Bugun soat 18:00 gacha barcha sovg'alarni olib ketish mumkin!",
            }),
            'audience': forms.RadioSelect,
            'with_button': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }

    def clean_text(self):
        text = (self.cleaned_data.get('text') or '').strip()
        if not text:
            raise forms.ValidationError("Xabar matni bo'sh bo'lishi mumkin emas.")
        return text


DATETIME_LOCAL_FORMAT = '%Y-%m-%dT%H:%M'


class SiteSettingsForm(forms.ModelForm):
    """Dashboard → Sozlamalar: aksiya muddati, obuna, bonuslar."""

    class Meta:
        model = SiteSettings
        fields = [
            'subscription_required',
            'campaign_start',
            'campaign_end',
            'campaign_closed_message',
            'daily_bonus_enabled',
            'referrals_per_spin',
        ]
        widgets = {
            'subscription_required': forms.CheckboxInput(attrs={'class': 'form-check'}),
            'daily_bonus_enabled': forms.CheckboxInput(attrs={'class': 'form-check'}),
            'campaign_start': forms.DateTimeInput(
                format=DATETIME_LOCAL_FORMAT, attrs={'class': 'form-input', 'type': 'datetime-local'}
            ),
            'campaign_end': forms.DateTimeInput(
                format=DATETIME_LOCAL_FORMAT, attrs={'class': 'form-input', 'type': 'datetime-local'}
            ),
            'campaign_closed_message': forms.TextInput(attrs={
                'class': 'form-input',
                'maxlength': 255,
                'placeholder': "Masalan: Aksiya yakunlandi, keyingisi tez orada!",
            }),
            'referrals_per_spin': forms.NumberInput(attrs={
                'class': 'form-input', 'min': 1, 'max': 50, 'step': 1,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('campaign_start', 'campaign_end'):
            self.fields[name].input_formats = [DATETIME_LOCAL_FORMAT, '%Y-%m-%d %H:%M']

    def clean_referrals_per_spin(self):
        value = self.cleaned_data.get('referrals_per_spin')
        if value is None or value < 1 or value > 50:
            raise forms.ValidationError("1 dan 50 gacha bo'lishi kerak.")
        return value

    def clean_campaign_closed_message(self):
        return (self.cleaned_data.get('campaign_closed_message') or '').strip()

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('campaign_start'), cleaned.get('campaign_end')
        if start and end and end <= start:
            self.add_error('campaign_end', "Tugash vaqti boshlanishidan keyin bo'lishi kerak.")
        return cleaned


_CHANNEL_USERNAME = re.compile(r'^@[A-Za-z][A-Za-z0-9_]{3,31}$')
_CHANNEL_NUMERIC_ID = re.compile(r'^-100\d{5,}$')


class RequiredChannelForm(forms.ModelForm):
    """Majburiy obuna kanali."""

    class Meta:
        model = RequiredChannel
        fields = ['title', 'chat_id', 'invite_link']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input', 'maxlength': 100, 'placeholder': "Yoshlar Texnoparki",
            }),
            'chat_id': forms.TextInput(attrs={
                'class': 'form-input', 'maxlength': 100, 'placeholder': "@texnopark_uz",
            }),
            'invite_link': forms.URLInput(attrs={
                'class': 'form-input', 'placeholder': "https://t.me/+AbCdEf (yopiq kanal uchun)",
            }),
        }

    def clean_title(self):
        title = (self.cleaned_data.get('title') or '').strip()
        if not title:
            raise forms.ValidationError("Nomini kiriting.")
        return title

    def clean_chat_id(self):
        value = (self.cleaned_data.get('chat_id') or '').strip()
        # https://t.me/kanal havolasi kiritilsa ham @kanal ga aylantiramiz
        match = re.match(r'^(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})/?$', value)
        if match:
            value = '@' + match.group(1)
        elif value and not value.startswith(('@', '-')):
            value = '@' + value
        if not (_CHANNEL_USERNAME.match(value) or _CHANNEL_NUMERIC_ID.match(value)):
            raise forms.ValidationError(
                "Ochiq kanal uchun @username, yopiq kanal uchun -100 bilan boshlanuvchi ID kiriting."
            )
        return value

    def clean_invite_link(self):
        link = (self.cleaned_data.get('invite_link') or '').strip()
        if link and not re.match(r'^https://t\.me/', link):
            raise forms.ValidationError("Havola https://t.me/ bilan boshlanishi kerak.")
        return link

    def clean(self):
        cleaned = super().clean()
        chat_id = cleaned.get('chat_id') or ''
        if chat_id.startswith('-') and not cleaned.get('invite_link'):
            self.add_error('invite_link', "Yopiq kanal uchun taklif havolasi majburiy.")
        return cleaned
