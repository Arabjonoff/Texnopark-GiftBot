import hmac
import hashlib
import json
import random
import string
from urllib.parse import parse_qsl, unquote
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from app_main.models import Prize, StudentLead, WinningResult

def verify_telegram_init_data(init_data_raw: str) -> tuple[bool, dict | None]:
    """
    Validates Telegram WebApp initData hash using HMAC-SHA256.
    Returns (is_valid, parsed_user_data_dict).
    """
    if not init_data_raw:
        return False, None

    # Dev/test uchun soxta foydalanuvchi: mock_<id>_<ism>. Productionda o'chiq —
    # aks holda istalgan odam istalgan Telegram ID nomidan so'rov yubora olardi.
    if init_data_raw.startswith('mock_'):
        if not settings.ALLOW_MOCK_INIT_DATA:
            return False, None
        parts = init_data_raw.split('_')
        tg_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 999888777
        first_name = parts[2] if len(parts) > 2 else "TestUser"
        return True, {
            'id': tg_id,
            'first_name': first_name,
            'last_name': 'Dev',
            'username': 'test_dev_user'
        }

    try:
        parsed_data = dict(parse_qsl(init_data_raw, keep_blank_values=True))
        if 'hash' not in parsed_data:
            return False, None

        received_hash = parsed_data.pop('hash')

        # Format key=value pairs sorted by key
        data_check_arr = [f"{k}={v}" for k, v in sorted(parsed_data.items())]
        data_check_string = "\n".join(data_check_arr)

        # Telegram secret key generation
        bot_token = settings.TELEGRAM_BOT_TOKEN
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode('utf-8'),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        is_valid = hmac.compare_digest(calculated_hash, received_hash)

        user_data = None
        if 'user' in parsed_data:
            try:
                user_str = parsed_data['user']
                try:
                    user_data = json.loads(user_str)
                except Exception:
                    user_data = json.loads(unquote(user_str))
            except Exception:
                pass

        return is_valid, user_data

    except Exception as e:
        return False, None


def get_spinnable_prizes():
    """
    Barabanda qatnashadigan sovg'alar queryset'i.

    Sovg'a aktiv bo'lishi kerak; agar kategoriyasi bo'lsa, u ham aktiv bo'lishi
    shart. Kategoriyasi yo'q sovg'alar ham qatnashadi.

    Bu mantiq API va spin algoritmida bir xil bo'lishi uchun bitta joyda turadi.
    """
    return (
        Prize.objects
        .filter(is_active=True)
        .exclude(category__is_active=False)
        .select_related('category')
    )


def calculate_weighted_prize() -> Prize:
    """
    Server-side weighted probability selection algorithm for the Gift Box roulette.
    Determines prize purely on server side according to Prize.probability weights.
    """
    active_prizes = list(get_spinnable_prizes())
    if not active_prizes:
        raise ValueError("Aktiv sovg'alar topilmadi. Baza bo'sh.")

    weights = [max(0, p.probability) for p in active_prizes]
    if sum(weights) == 0:
        weights = [1] * len(active_prizes)

    selected_prize = random.choices(active_prizes, weights=weights, k=1)[0]
    return selected_prize


def check_user_spin_status(telegram_id: int) -> tuple[int, StudentLead | None, list[WinningResult]]:
    """
    Calculates available spins for a user based on initial spin (1) + extra_spins - used spins.
    Returns (available_spins, student_lead, list_of_winnings).

    PENDING yutuqlar ham spin sifatida hisoblanadi, lekin ro'yxatga
    kirmaydi — ular hali rasmiylashtirilmagan (get_pending_winning'ga qarang).
    """
    lead = StudentLead.objects.filter(telegram_id=telegram_id).first()
    if not lead:
        return 1, None, []

    all_winnings = list(
        WinningResult.objects.filter(lead=lead).select_related('prize').order_by('-created_at')
    )
    allowed_total = 1 + lead.extra_spins
    available_spins = max(0, allowed_total - len(all_winnings))
    winnings = [w for w in all_winnings if w.status != WinningResult.Status.PENDING]

    return available_spins, lead, winnings


def get_pending_winning(lead: StudentLead | None) -> WinningResult | None:
    """Aylantirilgan, lekin hali ism/telefon yuborilmagan yutuq."""
    if not lead:
        return None
    return (
        lead.winnings.filter(status=WinningResult.Status.PENDING)
        .select_related('prize')
        .order_by('-created_at')
        .first()
    )


class NoSpinsLeft(Exception):
    pass


def start_spin(telegram_id: int, user_data: dict) -> tuple[WinningResult, bool]:
    """
    Sovg'ani serverda aniqlaydi va darhol PENDING yutuq sifatida saqlaydi.

    Spin shu yerda sarflanadi — foydalanuvchi natija yoqmasa ilovani yopib
    qayta aylantira olmaydi. Rasmiylashtirilmagan yutuq bo'lsa, yangisi
    aylantirilmaydi, o'sha qaytariladi.

    Returns (winning, created). Imkoniyat qolmagan bo'lsa NoSpinsLeft.
    """
    with transaction.atomic():
        lead, _ = StudentLead.objects.select_for_update().get_or_create(
            telegram_id=telegram_id,
            defaults={
                'first_name': user_data.get('first_name') or "Foydalanuvchi",
                'last_name': user_data.get('last_name') or '',
                'phone_number': "",
            },
        )

        pending = get_pending_winning(lead)
        if pending:
            return pending, False

        if 1 + lead.extra_spins - lead.winnings.count() <= 0:
            raise NoSpinsLeft()

        prize = calculate_weighted_prize()
        winning = WinningResult.objects.create(
            lead=lead,
            prize=prize,
            promo_code=generate_unique_promo_code(),
            status=WinningResult.Status.PENDING,
            expires_at=timezone.now() + timedelta(days=prize.valid_days),
        )

    return winning, True


# Har nechta taklif qilingan do'st uchun +1 aylantirish beriladi
REFERRALS_PER_SPIN = 3


def referral_progress(invited_count: int) -> int:
    """Keyingi bonus spingacha yig'ilgan do'stlar soni (0..REFERRALS_PER_SPIN-1)."""
    return invited_count % REFERRALS_PER_SPIN


def process_referral(
    referrer_tg_id: int,
    new_user_tg_id: int,
    new_user_first_name: str = '',
) -> tuple[bool, StudentLead | None, bool]:
    """
    ref_123456789 havolasi orqali kirgan yangi foydalanuvchini taklif
    qiluvchiga bog'laydi. Har REFERRALS_PER_SPIN ta do'st uchun +1 spin.

    Faqat botga birinchi marta kirayotgan foydalanuvchi hisoblanadi —
    aks holda bitta odam havolani qayta bosib cheksiz spin yig'ib olardi.

    Returns (success, referrer_lead, spin_awarded).
    """
    if not referrer_tg_id or not new_user_tg_id or referrer_tg_id == new_user_tg_id:
        return False, None, False

    with transaction.atomic():
        if StudentLead.objects.filter(telegram_id=new_user_tg_id).exists():
            return False, None, False

        referrer_lead, _ = StudentLead.objects.select_for_update().get_or_create(
            telegram_id=referrer_tg_id,
            # Taklif qiluvchi hali forma to'ldirmagan bo'lsa — vaqtinchalik yozuv
            defaults={'first_name': "Foydalanuvchi", 'phone_number': ""},
        )

        StudentLead.objects.create(
            telegram_id=new_user_tg_id,
            first_name=new_user_first_name or "Foydalanuvchi",
            phone_number="",
            referrer=referrer_lead,
        )

        spin_awarded = referrer_lead.referrals.count() % REFERRALS_PER_SPIN == 0
        if spin_awarded:
            referrer_lead.extra_spins += 1
            referrer_lead.save(update_fields=['extra_spins'])

    return True, referrer_lead, spin_awarded


def generate_unique_promo_code() -> str:
    """
    Generates a unique promo code in TX-XXXX format (e.g. TX-8923).
    """
    while True:
        num = ''.join(random.choices(string.digits, k=4))
        code = f"TX-{num}"
        if not WinningResult.objects.filter(promo_code=code).exists():
            return code
