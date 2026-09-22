"""
Yuklangan rasm fayllarini diskda yetim qolib ketishidan saqlaydi.

Django o'z-o'zidan ImageField faylini o'chirmaydi: yozuv o'chirilsa yoki rasm
boshqasiga almashtirilsa, eski fayl `media/` da abadiy qolib ketadi. Vaqt o'tib
bu disk to'lishiga olib keladi.

Shu sababli ikki hodisani ushlaymiz:
  post_delete -> yozuv o'chirildi, faylni ham o'chiramiz
  pre_save    -> rasm almashtirildi, eskisini o'chiramiz
"""
import logging

from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from app_main.models import Prize, PrizeCategory

logger = logging.getLogger(__name__)


def _delete_file(field_file):
    """
    Faylni xavfsiz o'chiradi. Xatolik yuz bersa log yoziladi, lekin
    asosiy amal (o'chirish yoki saqlash) to'xtatilmaydi.
    """
    if not field_file:
        return
    try:
        field_file.delete(save=False)
    except Exception as exc:
        logger.warning("Rasm faylini o'chirib bo'lmadi (%s): %s", field_file, exc)


def _handle_pre_save(sender, instance, field_name):
    """Rasm almashtirilgan bo'lsa eskisini o'chiradi."""
    if not instance.pk:
        return  # yangi yozuv — eski fayl yo'q

    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    old_file = getattr(old, field_name)
    new_file = getattr(instance, field_name)

    # Fayl o'zgarmagan bo'lsa tegmaymiz
    if not old_file or old_file.name == getattr(new_file, 'name', None):
        return

    _delete_file(old_file)


# ---------------------------------------------------------------- Prize

@receiver(post_delete, sender=Prize)
def prize_deleted(sender, instance, **kwargs):
    _delete_file(instance.image)


@receiver(pre_save, sender=Prize)
def prize_image_replaced(sender, instance, **kwargs):
    _handle_pre_save(sender, instance, 'image')


# ---------------------------------------------------------------- PrizeCategory

@receiver(post_delete, sender=PrizeCategory)
def category_deleted(sender, instance, **kwargs):
    _delete_file(instance.image)


@receiver(pre_save, sender=PrizeCategory)
def category_image_replaced(sender, instance, **kwargs):
    _handle_pre_save(sender, instance, 'image')
