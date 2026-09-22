import hmac
import hashlib
from urllib.parse import urlencode
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.conf import settings
from app_main.models import Prize, StudentLead, WinningResult
from app_main.services import verify_telegram_init_data, process_referral

@override_settings(ALLOW_MOCK_INIT_DATA=True)
class TexnoparkMiniAppApiTests(TestCase):
    def setUp(self):
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

    def test_referral_system_extra_spins(self):
        # 1. User 999888777 initial status
        val_url = reverse('api-validate-init')
        resp = self.client.post(val_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['available_spins'], 1)

        # 2. First two friends join — no bonus yet, only progress
        for friend_id in (555666771, 555666772):
            success, ref_lead, awarded = process_referral(999888777, friend_id)
            self.assertTrue(success)
            self.assertFalse(awarded)
        self.assertEqual(ref_lead.extra_spins, 0)

        resp_mid = self.client.post(val_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(resp_mid.data['available_spins'], 1)
        self.assertEqual(resp_mid.data['invited_count'], 2)

        # 3. Third friend joins -> +1 spin
        success, ref_lead, awarded = process_referral(999888777, 555666773)
        self.assertTrue(awarded)
        self.assertEqual(ref_lead.extra_spins, 1)

        resp2 = self.client.post(val_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(resp2.data['available_spins'], 2)
        self.assertEqual(resp2.data['invited_count'], 3)

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
