import hmac
import hashlib
from urllib.parse import urlencode
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.conf import settings
from app_main.models import Prize, StudentLead, WinningResult
from app_main.services import verify_telegram_init_data, process_referral

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

    def test_claim_prize_and_spin_limits(self):
        claim_url = reverse('api-claim-prize')
        payload = {
            'init_data': self.mock_init_data,
            'prize_id': self.prize_common.id,
            'first_name': 'Ali',
            'last_name': 'Valiyev',
            'phone_number': '+998901234567',
        }
        response = self.client.post(claim_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['available_spins'], 0)

        # Spinning when available_spins == 0 returns HTTP 400 error
        spin_url = reverse('api-spin')
        spin_resp = self.client.post(spin_url, {'init_data': self.mock_init_data}, format='json')
        self.assertEqual(spin_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(spin_resp.data['available_spins'], 0)
