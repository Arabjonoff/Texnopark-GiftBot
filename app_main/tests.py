import hmac
import json
import time
import hashlib
from unittest import mock
from urllib.parse import urlencode
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.conf import settings
from app_main import messaging
from app_main.models import BotMessage, Broadcast, Prize, RequiredChannel, SiteSettings, StudentLead, WinningResult
from app_main.services import verify_telegram_init_data, process_referral

@override_settings(ALLOW_MOCK_INIT_DATA=True)
class TexnoparkMiniAppApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        
        self.prize_common = Prize.objects.create(
            title="10% Chegirma",
            rarity=Prize.Rarity.COMMON,
            probability=50,
            valid_days=3,
            is_active=True
        )
        self.prize_rare = Prize.objects.create(
            title="3D Brelok",
            rarity=Prize.Rarity.RARE,
            probability=30,
            valid_days=5,
            is_active=True
        )

        self.mock_init_data = "mock_999888777_Ali"

    def _friend_spins_and_claims(self, friend_id):
        """Taklif qilingan do'st barabanni aylantirib, yutug'ini rasmiylashtiradi."""
        init = "mock_{0}_Friend".format(friend_id)
        self.client.post(reverse('api-spin'), {'init_data': init}, format='json')
        resp = self.client.post(
            reverse('api-claim-prize'),
            {'init_data': init, 'first_name': 'Friend', 'phone_number': '+998901112233'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_referral_system_extra_spins(self):
        val_url = reverse('api-validate-init')
        resp = self.client.post(val_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['available_spins'], 1)

        # 3 ta do'st havola orqali kirdi, lekin hali hech narsa qilmadi — bonus yo'q
        for friend_id in (555666771, 555666772, 555666773):
            success, _ref_lead = process_referral(999888777, friend_id)
            self.assertTrue(success)

        resp_mid = self.client.post(val_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(resp_mid.data['available_spins'], 1)
        self.assertEqual(resp_mid.data['invited_count'], 0)
        self.assertEqual(resp_mid.data['pending_invites'], 3)

        # Ikki do'st yutug'ini rasmiylashtirdi — hali progress
        self._friend_spins_and_claims(555666771)
        self._friend_spins_and_claims(555666772)
        self.assertEqual(StudentLead.objects.get(telegram_id=999888777).extra_spins, 0)

        # Uchinchisi — +1 spin
        self._friend_spins_and_claims(555666773)
        self.assertEqual(StudentLead.objects.get(telegram_id=999888777).extra_spins, 1)

        resp2 = self.client.post(val_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(resp2.data['available_spins'], 2)
        self.assertEqual(resp2.data['invited_count'], 3)
        self.assertEqual(resp2.data['pending_invites'], 0)

    def test_referral_confirmed_only_once(self):
        # Do'stning ikkinchi yutug'i taklif qiluvchiga qayta hisoblanmaydi
        process_referral(999888777, 555666771)
        StudentLead.objects.filter(telegram_id=555666771).update(extra_spins=1)
        self._friend_spins_and_claims(555666771)
        self._friend_spins_and_claims(555666771)
        referrer = StudentLead.objects.get(telegram_id=999888777)
        self.assertEqual(referrer.referrals.filter(referral_confirmed_at__isnull=False).count(), 1)

    def test_stock_decrements_and_sold_out_prize_leaves_roulette(self):
        self.prize_rare.is_active = False
        self.prize_rare.save()
        self.prize_common.stock = 1
        self.prize_common.save()

        first = self.client.post(reverse('api-spin'), {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.prize_common.refresh_from_db()
        self.assertEqual(self.prize_common.stock, 0)

        # Qoldiq tugadi — lentada ham yo'q, boshqa foydalanuvchi yutuq ololmaydi
        self.assertEqual(self.client.get(reverse('api-prizes')).data, [])
        second = self.client.post(reverse('api-spin'), {'init_data': 'mock_123123_Vali'}, format='json')
        self.assertEqual(second.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_sold_out_prize_falls_back_to_other(self):
        self.prize_common.stock = 0
        self.prize_common.save()
        for tg_id in (1001, 1002, 1003):
            resp = self.client.post(reverse('api-spin'), {'init_data': 'mock_{0}_U'.format(tg_id)}, format='json')
            self.assertEqual(resp.data['prize']['id'], self.prize_rare.id)

    def test_promo_code_format(self):
        self.client.post(reverse('api-spin'), {'init_data': self.mock_init_data}, format='json')
        code = WinningResult.objects.get().promo_code
        self.assertRegex(code, r'^TX-[23456789A-HJKMNP-Z]{6}$')

    def test_verify_code_records_staff(self):
        self.client.post(reverse('api-spin'), {'init_data': self.mock_init_data}, format='json')
        self.client.post(reverse('api-claim-prize'), self._claim_payload(), format='json')
        winning = WinningResult.objects.get()

        staff = User.objects.create_user('kassir', password='pass-12345-x', is_staff=True)
        self.client.force_authenticate(staff)
        resp = self.client.post(
            reverse('api-admin-verify-code'),
            {'promo_code': winning.promo_code, 'confirm': True},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        winning.refresh_from_db()
        self.assertEqual(winning.status, WinningResult.Status.USED)
        self.assertEqual(winning.used_by, staff)

    def test_referral_same_friend_counted_once(self):
        # Havolani qayta bosish yoki o'zini taklif qilish hisoblanmaydi
        self.assertTrue(process_referral(999888777, 555666771)[0])
        self.assertFalse(process_referral(999888777, 555666771)[0])
        self.assertFalse(process_referral(999888777, 999888777)[0])
        # Allaqachon ro'yxatda bo'lgan foydalanuvchi boshqa odamning havolasi bilan ham hisoblanmaydi
        self.assertFalse(process_referral(111222333, 555666771)[0])
        self.assertEqual(StudentLead.objects.get(telegram_id=999888777).referrals.count(), 1)

    def _claim_payload(self, **extra):
        payload = {
            'init_data': self.mock_init_data,
            'first_name': 'Ali',
            'last_name': 'Valiyev',
            'phone_number': '+998901234567',
        }
        payload.update(extra)
        return payload

    def test_claim_prize_and_spin_limits(self):
        spin_url = reverse('api-spin')
        claim_url = reverse('api-claim-prize')

        spin_resp = self.client.post(spin_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(spin_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(spin_resp.data['is_new_spin'])

        # Spin darhol sarflanadi — forma yuborilmasa ham
        val = self.client.post(reverse('api-validate-init'), {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(val.data['available_spins'], 0)
        self.assertEqual(val.data['pending_prize']['id'], spin_resp.data['prize']['id'])
        self.assertEqual(val.data['winnings'], [])

        response = self.client.post(claim_url, self._claim_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['available_spins'], 0)
        self.assertIsNone(response.data['pending_prize'])
        self.assertEqual(response.data['saved_profile']['phone_digits'], '901234567')

        # Spinning when available_spins == 0 returns HTTP 400 error
        spin_resp = self.client.post(spin_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(spin_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(spin_resp.data['available_spins'], 0)

    def test_respin_returns_same_pending_prize(self):
        # Ilovani yopib qayta ochish natijani o'zgartirmaydi
        spin_url = reverse('api-spin')
        first = self.client.post(spin_url, {'init_data': self.mock_init_data}, format='json')
        second = self.client.post(spin_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertFalse(second.data['is_new_spin'])
        self.assertEqual(first.data['prize']['id'], second.data['prize']['id'])
        self.assertEqual(WinningResult.objects.count(), 1)

    def test_claim_without_spin_is_rejected(self):
        resp = self.client.post(
            reverse('api-claim-prize'),
            self._claim_payload(prize_id=self.prize_rare.id),
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WinningResult.objects.count(), 0)

    def test_claim_ignores_client_prize_id(self):
        self.client.post(reverse('api-spin'), {'init_data': self.mock_init_data}, format='json')
        won_id = WinningResult.objects.get().prize_id
        other = self.prize_rare.id if won_id == self.prize_common.id else self.prize_common.id

        self.client.post(reverse('api-claim-prize'), self._claim_payload(prize_id=other), format='json')
        winning = WinningResult.objects.get()
        self.assertEqual(winning.prize_id, won_id)
        self.assertEqual(winning.status, WinningResult.Status.ACTIVE)

    def test_pending_hidden_from_public_winners(self):
        self.client.post(reverse('api-spin'), {'init_data': self.mock_init_data}, format='json')
        resp = self.client.get(reverse('api-winners'))
        self.assertEqual(resp.data['total'], 0)

    def test_my_prize_requires_init_data(self):
        resp = self.client.get(reverse('api-my-prize'), {'telegram_id': 999888777})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(ALLOW_MOCK_INIT_DATA=False)
    def test_mock_init_data_rejected_in_production(self):
        is_valid, user = verify_telegram_init_data(self.mock_init_data)
        self.assertFalse(is_valid)
        resp = self.client.post(reverse('api-spin'), {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


TEST_BOT_TOKEN = '123456:TEST-TOKEN'


def signed_init_data(user_id=42, auth_date=None, token=TEST_BOT_TOKEN):
    """Telegram qanday imzolasa, xuddi shunday imzolangan initData."""
    fields = {
        'auth_date': str(int(auth_date if auth_date is not None else time.time())),
        'query_id': 'AAE',
        'user': json.dumps({'id': user_id, 'first_name': 'Ali'}),
    }
    check = "\n".join("{0}={1}".format(k, v) for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@override_settings(TELEGRAM_BOT_TOKEN=TEST_BOT_TOKEN, INIT_DATA_MAX_AGE_SECONDS=3600)
class InitDataSignatureTests(TestCase):
    def test_fresh_signed_init_data_accepted(self):
        is_valid, user = verify_telegram_init_data(signed_init_data())
        self.assertTrue(is_valid)
        self.assertEqual(user['id'], 42)

    def test_stale_init_data_rejected(self):
        old = signed_init_data(auth_date=time.time() - 7200)
        self.assertFalse(verify_telegram_init_data(old)[0])

    def test_tampered_init_data_rejected(self):
        tampered = signed_init_data().replace('Ali', 'Vali')
        self.assertFalse(verify_telegram_init_data(tampered)[0])


class DashboardFilterTests(TestCase):
    """Dashboard ro'yxatlaridagi filtr, saralash va eksport."""

    def setUp(self):
        self.staff = User.objects.create_user('xodim', password='dash-pass-12345', is_staff=True)
        self.client.force_login(self.staff)

        self.prize_common = Prize.objects.create(
            title="10% Chegirma", rarity=Prize.Rarity.COMMON,
            probability=50, valid_days=3, is_active=True,
        )
        self.prize_legendary = Prize.objects.create(
            title="VIP Voucher", rarity=Prize.Rarity.LEGENDARY,
            probability=5, valid_days=10, is_active=False,
        )

        self.old_lead = StudentLead.objects.create(
            telegram_id=111, first_name='Eski', phone_number='+998900000001',
        )
        self.new_lead = StudentLead.objects.create(
            telegram_id=222, first_name='Yangi', phone_number='+998900000002',
            referrer=self.old_lead,
        )

        now = timezone.now()
        # Eski lead 40 kun oldin ro'yxatdan o'tgan
        StudentLead.objects.filter(pk=self.old_lead.pk).update(created_at=now - timedelta(days=40))

        self.active_win = WinningResult.objects.create(
            lead=self.old_lead, prize=self.prize_common, promo_code='TX-1001',
            status=WinningResult.Status.ACTIVE, expires_at=now + timedelta(days=2),
        )
        self.used_win = WinningResult.objects.create(
            lead=self.new_lead, prize=self.prize_legendary, promo_code='TX-1002',
            status=WinningResult.Status.USED, expires_at=now + timedelta(days=30),
            used_at=now,
        )
        WinningResult.objects.filter(pk=self.used_win.pk).update(created_at=now - timedelta(days=40))

    def _codes(self, response):
        return {w.promo_code for w in response.context['page_obj']}

    def test_winning_filters(self):
        url = reverse('dashboard-winnings')

        # Holati bo'yicha
        resp = self.client.get(url, {'status': 'ACTIVE'})
        self.assertEqual(self._codes(resp), {'TX-1001'})

        # Sovg'a bo'yicha
        resp = self.client.get(url, {'prize': self.prize_legendary.id})
        self.assertEqual(self._codes(resp), {'TX-1002'})

        # Daraja bo'yicha
        resp = self.client.get(url, {'rarity': 'COMMON'})
        self.assertEqual(self._codes(resp), {'TX-1001'})

        # Oxirgi 7 kun — eski yutuq chiqmaydi
        resp = self.client.get(url, {'period': 'week'})
        self.assertEqual(self._codes(resp), {'TX-1001'})

        # Muddati tugayotganlar: 3 kun ichidagi aktiv yutuq
        resp = self.client.get(url, {'expiring': 'yes'})
        self.assertEqual(self._codes(resp), {'TX-1001'})

        # Qidiruv promokod bo'yicha
        resp = self.client.get(url, {'q': 'TX-1002'})
        self.assertEqual(self._codes(resp), {'TX-1002'})

    def test_winning_sort_and_invalid_params(self):
        url = reverse('dashboard-winnings')

        resp = self.client.get(url, {'sort': 'old'})
        self.assertEqual([w.promo_code for w in resp.context['page_obj']], ['TX-1002', 'TX-1001'])

        # Noto'g'ri qiymatlar xato bermaydi, e'tiborsiz qoldiriladi
        resp = self.client.get(url, {'sort': 'drop', 'from': 'salom', 'prize': 'abc', 'status': 'XX'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['page_obj']), 2)

    def test_lead_filters(self):
        url = reverse('dashboard-leads')

        resp = self.client.get(url, {'wins': 'yes'})
        self.assertEqual({l.telegram_id for l in resp.context['page_obj']}, {111, 222})

        resp = self.client.get(url, {'source': 'referral'})
        self.assertEqual({l.telegram_id for l in resp.context['page_obj']}, {222})

        resp = self.client.get(url, {'inviter': 'yes'})
        self.assertEqual({l.telegram_id for l in resp.context['page_obj']}, {111})

        resp = self.client.get(url, {'period': 'week'})
        self.assertEqual({l.telegram_id for l in resp.context['page_obj']}, {222})

        resp = self.client.get(url, {'sort': 'invites'})
        self.assertEqual([l.telegram_id for l in resp.context['page_obj']], [111, 222])

    def test_prize_filters(self):
        url = reverse('dashboard-prizes')

        resp = self.client.get(url, {'state': 'active'})
        self.assertEqual([p.title for p in resp.context['prizes']], ["10% Chegirma"])

        resp = self.client.get(url, {'rarity': 'LEGENDARY'})
        self.assertEqual([p.title for p in resp.context['prizes']], ["VIP Voucher"])

        resp = self.client.get(url, {'sort': 'prob_asc'})
        self.assertEqual([p.title for p in resp.context['prizes']], ["VIP Voucher", "10% Chegirma"])

    def test_export_respects_filters(self):
        resp = self.client.get(reverse('dashboard-winnings-export'), {'status': 'ACTIVE'})
        body = resp.content.decode('utf-8-sig')
        self.assertIn('TX-1001', body)
        self.assertNotIn('TX-1002', body)


class DashboardAuthTests(TestCase):
    """Kirish, chiqish va brute-force himoyasi."""

    def setUp(self):
        cache.clear()
        User.objects.create_user('xodim', password='dash-pass-12345', is_staff=True)

    def test_login_rejects_external_next(self):
        resp = self.client.post(
            reverse('dashboard-login') + '?next=//evil.example.com',
            {'username': 'xodim', 'password': 'dash-pass-12345'},
        )
        self.assertEqual(resp.url, '/dashboard/')

    def test_login_allows_internal_next(self):
        resp = self.client.post(
            reverse('dashboard-login') + '?next=/dashboard/winnings/',
            {'username': 'xodim', 'password': 'dash-pass-12345'},
        )
        self.assertEqual(resp.url, '/dashboard/winnings/')

    def test_login_throttled_after_repeated_failures(self):
        url = reverse('dashboard-login')
        for _ in range(10):
            self.client.post(url, {'username': 'xodim', 'password': 'xato'})

        # Bloklangandan keyin to'g'ri parol ham o'tmaydi
        resp = self.client.post(url, {'username': 'xodim', 'password': 'dash-pass-12345'})
        self.assertEqual(resp.status_code, 429)

    def test_logout_requires_post(self):
        self.client.login(username='xodim', password='dash-pass-12345')
        self.assertEqual(self.client.get(reverse('dashboard-logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('dashboard-logout')).status_code, 302)


class MessagingTests(TestCase):
    """Ommaviy xabarlar, eslatmalar va bot outbox'i."""

    def setUp(self):
        cache.clear()
        self.prize = Prize.objects.create(
            title="Brelok", rarity=Prize.Rarity.COMMON, probability=10, valid_days=3,
            pickup_address="Texnopark <1-bino>",
        )
        now = timezone.now()
        self.registered = StudentLead.objects.create(telegram_id=1, first_name='Ali', phone_number='+998900000001')
        self.started = StudentLead.objects.create(telegram_id=2, first_name='Vali', phone_number='')
        self.blocked = StudentLead.objects.create(
            telegram_id=3, first_name='Soli', phone_number='+998900000003', bot_blocked=True,
        )
        self.winning = WinningResult.objects.create(
            lead=self.registered, prize=self.prize, promo_code='TX-AAAAAA',
            status=WinningResult.Status.ACTIVE, expires_at=now + timedelta(hours=5),
        )

    def test_audiences(self):
        from app_main.messaging import audience_queryset
        ids = lambda a: set(audience_queryset(a).values_list('telegram_id', flat=True))
        self.assertEqual(ids(Broadcast.Audience.ALL), {1, 2})
        self.assertEqual(ids(Broadcast.Audience.REGISTERED), {1})
        self.assertEqual(ids(Broadcast.Audience.ACTIVE_PRIZE), {1})
        self.assertEqual(ids(Broadcast.Audience.NO_SPIN), {2})
        self.assertEqual(ids(Broadcast.Audience.HAS_SPINS), {2})

    def test_create_and_cancel_broadcast(self):
        from app_main.messaging import cancel_broadcast, create_broadcast
        b = create_broadcast("Salom <b>", Broadcast.Audience.ALL, True)
        self.assertEqual(b.total, 2)
        self.assertEqual(b.messages.filter(parse_mode='').count(), 2)
        self.assertEqual(cancel_broadcast(b), 2)
        b.refresh_from_db()
        self.assertEqual(b.status, Broadcast.Status.CANCELLED)

    def test_expiry_reminder_sent_once_and_escaped(self):
        from app_main.messaging import queue_expiry_reminders
        self.assertEqual(queue_expiry_reminders(), 1)
        self.assertEqual(queue_expiry_reminders(), 0)
        msg = BotMessage.objects.get(kind=BotMessage.Kind.REMINDER)
        self.assertEqual(msg.chat_id, 1)
        self.assertIn('TX-AAAAAA', msg.text)
        self.assertIn('&lt;1-bino&gt;', msg.text)

    def test_failed_delivery_marks_user_blocked_and_counts(self):
        from app_main.messaging import create_broadcast, finish_broadcasts, mark_failed, mark_sent
        b = create_broadcast("Salom", Broadcast.Audience.ALL, False)
        first, second = list(b.messages.order_by('chat_id'))
        mark_sent(first)
        mark_failed(second, "Forbidden: bot was blocked", permanent=True, user_blocked=True)
        finish_broadcasts()
        b.refresh_from_db()
        self.assertEqual((b.sent_count, b.failed_count, b.status), (1, 1, Broadcast.Status.DONE))
        self.assertTrue(StudentLead.objects.get(telegram_id=2).bot_blocked)

    def test_network_error_retried_before_failing(self):
        from app_main.messaging import MAX_ATTEMPTS, mark_failed, queue_message
        msg = queue_message(1, "x", BotMessage.Kind.REFERRAL)
        for _ in range(MAX_ATTEMPTS - 1):
            mark_failed(msg, "timeout", permanent=False)
            self.assertEqual(msg.status, BotMessage.Status.PENDING)
        mark_failed(msg, "timeout", permanent=False)
        self.assertEqual(msg.status, BotMessage.Status.FAILED)

    def test_register_bot_user_unblocks(self):
        from app_main.messaging import register_bot_user
        register_bot_user(3, 'Soli')
        self.assertFalse(StudentLead.objects.get(telegram_id=3).bot_blocked)
        register_bot_user(77, 'Yangi')
        self.assertEqual(StudentLead.objects.get(telegram_id=77).phone_number, '')

    def test_dashboard_broadcast_flow(self):
        staff = User.objects.create_user('xodim', password='dash-pass-12345', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('dashboard-broadcast-create')).status_code, 200)
        resp = self.client.post(reverse('dashboard-broadcast-create'), {
            'text': 'Yangilik!', 'audience': 'REGISTERED', 'with_button': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        b = Broadcast.objects.get()
        self.assertEqual((b.total, b.created_by), (1, staff))
        self.assertEqual(self.client.get(reverse('dashboard-broadcasts')).status_code, 200)


@override_settings(ALLOW_MOCK_INIT_DATA=True)
class ReferralNotificationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_claim_queues_notification_for_referrer(self):
        Prize.objects.create(title="P", rarity=Prize.Rarity.COMMON, probability=10)
        process_referral(500, 600, 'Do<st>')
        client = APIClient()
        client.post(reverse('api-spin'), {'init_data': 'mock_600_F'}, format='json')
        client.post(reverse('api-claim-prize'), {
            'init_data': 'mock_600_F', 'first_name': 'Do<st>', 'phone_number': '+998901112233',
        }, format='json')
        msg = BotMessage.objects.get(kind=BotMessage.Kind.REFERRAL)
        self.assertEqual(msg.chat_id, 500)
        self.assertIn('Do&lt;st&gt;', msg.text)
        self.assertIn('1/3', msg.text)


class OutboxWorkerTests(TestCase):
    """bot/worker.py — Telegram xatolarini to'g'ri qayta ishlashi."""

    def _run(self, exc=None):
        import asyncio
        from bot import worker
        from app_main.messaging import queue_message

        StudentLead.objects.create(telegram_id=9, first_name='A', phone_number='')
        msg = queue_message(9, "salom", BotMessage.Kind.REFERRAL)

        class FakeBot:
            async def send_message(self, **kwargs):
                if exc:
                    raise exc

        # Async kontekstda ORM ishlatib bo'lmaydi — chaqiruvlarni yozib olib,
        # event loop tugagach shu thread'da bajaramiz
        calls = []

        async def record_sent(m):
            calls.append((messaging.mark_sent, (m,), {}))

        async def record_failed(*args, **kwargs):
            calls.append((messaging.mark_failed, args, kwargs))

        orig = worker.mark_sent, worker.mark_failed
        worker.mark_sent, worker.mark_failed = record_sent, record_failed
        try:
            asyncio.run(worker._send(FakeBot(), msg, lambda: None))
        finally:
            worker.mark_sent, worker.mark_failed = orig
        for func, args, kwargs in calls:
            func(*args, **kwargs)
        msg.refresh_from_db()
        return msg

    def test_success(self):
        self.assertEqual(self._run().status, BotMessage.Status.SENT)

    def test_forbidden_blocks_user(self):
        from telegram.error import Forbidden
        msg = self._run(Forbidden("bot was blocked by the user"))
        self.assertEqual(msg.status, BotMessage.Status.FAILED)
        self.assertTrue(StudentLead.objects.get(telegram_id=9).bot_blocked)

    def test_network_error_keeps_pending(self):
        from telegram.error import NetworkError
        msg = self._run(NetworkError("timeout"))
        self.assertEqual((msg.status, msg.attempts), (BotMessage.Status.PENDING, 1))



@override_settings(ALLOW_MOCK_INIT_DATA=True)
class SubscriptionCampaignBonusTests(TestCase):
    """Majburiy obuna, aksiya muddati, kunlik bonus va referal reytingi."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        Prize.objects.create(title="P", rarity=Prize.Rarity.COMMON, probability=10)
        self.channel = RequiredChannel.objects.create(title="Texnopark", chat_id="@texnopark_uz")
        self.init = "mock_4242_Ali"
        self.member_status = 'left'

        patcher = mock.patch(
            'app_main.subscription._api_get_chat_member',
            side_effect=lambda chat_id, user_id: {'status': self.member_status},
        )
        self.api = patcher.start()
        self.addCleanup(patcher.stop)

    def _spin(self, init=None):
        return self.client.post(reverse('api-spin'), {'init_data': init or self.init}, format='json')

    def test_spin_blocked_until_subscribed(self):
        val = self.client.post(reverse('api-validate-init'), {'init_data': self.init}, format='json')
        self.assertFalse(val.data['subscription']['ok'])
        self.assertEqual(val.data['subscription']['channels'][0]['link'], 'https://t.me/texnopark_uz')

        resp = self._spin()
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data['code'], 'not_subscribed')
        self.assertEqual(WinningResult.objects.count(), 0)

        # Obuna bo'ldi — «Tekshirish» tugmasi
        self.member_status = 'member'
        check = self.client.post(reverse('api-check-subscription'), {'init_data': self.init}, format='json')
        self.assertTrue(check.data['ok'])
        self.assertEqual(self._spin().status_code, status.HTTP_200_OK)

    def test_membership_is_cached_only_when_positive(self):
        self.client.post(reverse('api-check-subscription'), {'init_data': self.init}, format='json')
        self.client.post(reverse('api-check-subscription'), {'init_data': self.init}, format='json')
        self.assertEqual(self.api.call_count, 2)

        self.member_status = 'administrator'
        self.client.post(reverse('api-check-subscription'), {'init_data': self.init}, format='json')
        self.client.post(reverse('api-check-subscription'), {'init_data': self.init}, format='json')
        self.assertEqual(self.api.call_count, 3)

    def test_misconfigured_channel_does_not_block(self):
        from app_main.subscription import ChannelCheckError
        self.api.side_effect = ChannelCheckError("member list is inaccessible")
        self.assertEqual(self._spin().status_code, status.HTTP_200_OK)

    def test_subscription_can_be_disabled(self):
        site = SiteSettings.load()
        site.subscription_required = False
        site.save()
        self.assertEqual(self._spin().status_code, status.HTTP_200_OK)

    def test_pending_prize_returned_even_if_unsubscribed(self):
        self.member_status = 'member'
        first = self._spin()
        cache.clear()
        self.member_status = 'left'
        again = self._spin()
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        self.assertFalse(again.data['is_new_spin'])
        self.assertEqual(again.data['prize']['id'], first.data['prize']['id'])

    def test_campaign_window(self):
        self.member_status = 'member'
        site = SiteSettings.load()
        site.campaign_end = timezone.now() - timedelta(minutes=1)
        site.save()

        resp = self._spin()
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data['code'], 'campaign_closed')
        self.assertIn('yakunlandi', resp.data['error'])

        site.campaign_end = None
        site.campaign_start = timezone.now() + timedelta(days=1)
        site.save()
        val = self.client.post(reverse('api-validate-init'), {'init_data': self.init}, format='json')
        self.assertEqual(val.data['campaign']['state'], 'not_started')

    def test_daily_bonus_once_per_day(self):
        url = reverse('api-daily-bonus')
        self.assertEqual(self.client.post(url, {'init_data': self.init}, format='json').status_code, 400)

        site = SiteSettings.load()
        site.daily_bonus_enabled = True
        site.save()

        resp = self.client.post(url, {'init_data': self.init}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['available_spins'], 2)
        self.assertFalse(resp.data['daily_bonus']['available'])
        self.assertEqual(self.client.post(url, {'init_data': self.init}, format='json').status_code, 400)

        # Ertasiga yana olish mumkin
        StudentLead.objects.filter(telegram_id=4242).update(
            last_daily_bonus=timezone.localdate() - timedelta(days=1)
        )
        self.assertEqual(self.client.post(url, {'init_data': self.init}, format='json').status_code, 200)

    def test_referrals_per_spin_setting_and_top_referrers(self):
        site = SiteSettings.load()
        site.referrals_per_spin = 1
        site.save()
        self.member_status = 'member'

        process_referral(4242, 700, 'Do')
        self._spin('mock_700_Do')
        self.client.post(reverse('api-claim-prize'), {
            'init_data': 'mock_700_Do', 'first_name': 'Do', 'phone_number': '+998901112233',
        }, format='json')
        self.assertEqual(StudentLead.objects.get(telegram_id=4242).extra_spins, 1)

        StudentLead.objects.filter(telegram_id=4242).update(first_name='Sevara', last_name='Yusupova')
        top = self.client.get(reverse('api-top-referrers')).data['referrers']
        self.assertEqual(top, [{'rank': 1, 'display_name': 'Sevara Y.', 'invited': 1}])


class DashboardSettingsTests(TestCase):
    """Sozlamalar sahifasi, kanallar, voronka va xodimlar statistikasi."""

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user('xodim', password='dash-pass-12345', is_staff=True)
        self.client.force_login(self.staff)

    def test_settings_save(self):
        resp = self.client.post(reverse('dashboard-settings'), {
            'subscription_required': 'on',
            'campaign_start': '2026-10-01T09:00',
            'campaign_end': '2026-10-10T18:00',
            'campaign_closed_message': '  Tugadi  ',
            'daily_bonus_enabled': 'on',
            'referrals_per_spin': 5,
        })
        self.assertEqual(resp.status_code, 302)
        site = SiteSettings.load()
        self.assertEqual(site.referrals_per_spin, 5)
        self.assertTrue(site.daily_bonus_enabled)
        self.assertEqual(site.campaign_closed_message, 'Tugadi')
        self.assertEqual(timezone.localtime(site.campaign_start).hour, 9)

    def test_settings_rejects_end_before_start(self):
        resp = self.client.post(reverse('dashboard-settings'), {
            'campaign_start': '2026-10-10T09:00',
            'campaign_end': '2026-10-01T09:00',
            'referrals_per_spin': 3,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('campaign_end', resp.context['form'].errors)

    def test_channel_create_normalizes_username(self):
        self.client.post(reverse('dashboard-channel-create'), {
            'title': 'Texnopark', 'chat_id': 'https://t.me/texnopark_uz',
        })
        channel = RequiredChannel.objects.get()
        self.assertEqual(channel.chat_id, '@texnopark_uz')
        self.assertEqual(channel.link, 'https://t.me/texnopark_uz')

    def test_private_channel_requires_invite_link(self):
        resp = self.client.post(reverse('dashboard-channel-create'), {
            'title': 'Yopiq', 'chat_id': '-1001234567890',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RequiredChannel.objects.count(), 0)
        self.assertIn('invite_link', resp.context['channel_form'].errors)

    def test_channel_toggle_and_delete(self):
        channel = RequiredChannel.objects.create(title='K', chat_id='@kanal_uz')
        self.client.post(reverse('dashboard-channel-toggle', args=[channel.pk]))
        channel.refresh_from_db()
        self.assertFalse(channel.is_active)
        self.client.post(reverse('dashboard-channel-delete', args=[channel.pk]))
        self.assertFalse(RequiredChannel.objects.exists())

    def test_settings_check_uses_diagnosis(self):
        RequiredChannel.objects.create(title='K', chat_id='@kanal_uz')
        with mock.patch('app_main.dashboard_views.diagnose_channel', return_value=(False, 'Bot admin emas')):
            resp = self.client.get(reverse('dashboard-settings'), {'check': '1'})
        self.assertContains(resp, 'Bot admin emas')

    def test_index_funnel_and_staff(self):
        prize = Prize.objects.create(title='P', rarity=Prize.Rarity.COMMON, probability=10)
        now = timezone.now()
        StudentLead.objects.create(telegram_id=1, first_name='A', phone_number='')
        lead = StudentLead.objects.create(telegram_id=2, first_name='B', phone_number='+998900000002')
        WinningResult.objects.create(
            lead=lead, prize=prize, promo_code='TX-BBBBBB', status=WinningResult.Status.USED,
            expires_at=now + timedelta(days=1), used_at=now, used_by=self.staff,
        )
        resp = self.client.get(reverse('dashboard-index'))
        self.assertEqual(resp.status_code, 200)
        funnel = {row['label']: row['count'] for row in resp.context['funnel']}
        self.assertEqual(funnel['Botga kirdi'], 2)
        self.assertEqual(funnel["Sovg'ani qo'lga oldi"], 1)
        self.assertEqual(resp.context['staff_activity'][0].issued_total, 1)
        self.assertEqual(resp.context['stats']['total_leads'], 1)
        self.assertEqual(resp.context['stats']['total_users'], 2)
