import hmac
import hashlib
import json
import random
import string
from urllib.parse import parse_qsl, unquote
from django.conf import settings
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

    # Handle dev/testing mock bypass if init_data_raw starts with 'mock_'
    if init_data_raw.startswith('mock_'):
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
    Server-side weighted probability selection algorithm for CS2 Skin Roulette.
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
    Calculates available spins for a user based on initial spin (1) + extra_spins - claimed winnings.
    Returns (available_spins, student_lead, list_of_winnings).
    """
    lead = StudentLead.objects.filter(telegram_id=telegram_id).first()
    if not lead:
        return 1, None, []

    winnings = list(WinningResult.objects.filter(lead=lead).order_by('-created_at'))
    allowed_total = 1 + lead.extra_spins
    claimed_count = len(winnings)
    available_spins = max(0, allowed_total - claimed_count)

    return available_spins, lead, winnings


def process_referral(referrer_tg_id: int, new_user_tg_id: int) -> tuple[bool, StudentLead | None]:
    """
    Grants +1 extra spin to referrer when a new user joins via ref_123456789.
    """
    if not referrer_tg_id or referrer_tg_id == new_user_tg_id:
        return False, None

    referrer_lead = StudentLead.objects.filter(telegram_id=referrer_tg_id).first()
    if not referrer_lead:
        # Create lead shell for referrer if they haven't submitted lead form yet
        referrer_lead = StudentLead.objects.create(
            telegram_id=referrer_tg_id,
            first_name="Foydalanuvchi",
            phone_number="",
            extra_spins=1
        )
    else:
        referrer_lead.extra_spins += 1
        referrer_lead.save()

    return True, referrer_lead


def generate_unique_promo_code() -> str:
    """
    Generates a unique promo code in TX-XXXX format (e.g. TX-8923).
    """
    while True:
        num = ''.join(random.choices(string.digits, k=4))
        code = f"TX-{num}"
        if not WinningResult.objects.filter(promo_code=code).exists():
            return code
