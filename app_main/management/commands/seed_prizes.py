from django.core.management.base import BaseCommand
from app_main.models import Prize

class Command(BaseCommand):
    help = 'Seeds initial CS2 skin style prizes into database'

    def handle(self, *args, **options):
        prizes_data = [
            {
                "title": "10% Chegirma Sertifikati",
                "rarity": Prize.Rarity.COMMON,
                "probability": 40,
                "valid_days": 7
            },
            {
                "title": "Texnopark 3D Brelok",
                "rarity": Prize.Rarity.RARE,
                "probability": 25,
                "valid_days": 5
            },
            {
                "title": "VR Ekspeditsiya Seansi",
                "rarity": Prize.Rarity.EPIC,
                "probability": 20,
                "valid_days": 3
            },
            {
                "title": "Robototexnika Mahorat Darsi",
                "rarity": Prize.Rarity.EPIC,
                "probability": 10,
                "valid_days": 3
            },
            {
                "title": "VIP 3D Pechat Vauchera",
                "rarity": Prize.Rarity.LEGENDARY,
                "probability": 5,
                "valid_days": 3
            },
        ]

        created_count = 0
        for data in prizes_data:
            prize, created = Prize.objects.get_or_create(
                title=data['title'],
                defaults=data
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Yaratildi: {prize.title} [{prize.rarity}]"))
            else:
                self.stdout.write(self.style.WARNING(f"Mavjud: {prize.title}"))

        self.stdout.write(self.style.SUCCESS(f"Barcha sovg'alar tayyor! (Yangi yaratildi: {created_count})"))
