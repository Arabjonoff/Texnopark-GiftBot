"""
seed_prizes buyrug'i ilgari `/static/images/*.png` yo'llarini yozgan edi,
lekin bu fayllar loyihada hech qachon mavjud bo'lmagan. Natijada barabanda
va dashboardda "buzuq rasm" belgisi chiqardi.

Shu yo'llarni tozalaymiz — rasm endi dashboard orqali yuklanadi.
Qo'lda kiritilgan boshqa havolalar (http/https yoki /media/) tegilmaydi.
"""
from django.db import migrations


BROKEN_PREFIX = '/static/images/'


def clear_broken_urls(apps, schema_editor):
    Prize = apps.get_model('app_main', 'Prize')
    Prize.objects.filter(image_url__startswith=BROKEN_PREFIX).update(image_url='')


def noop_reverse(apps, schema_editor):
    """Tozalangan yo'llarni tiklashning ma'nosi yo'q — fayllar mavjud emas."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app_main', '0003_prize_image_alter_prize_image_url'),
    ]

    operations = [
        migrations.RunPython(clear_broken_urls, noop_reverse),
    ]
