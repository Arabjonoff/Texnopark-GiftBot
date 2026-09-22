from django.core.management.base import BaseCommand
from bot.bot_instance import create_bot_application

class Command(BaseCommand):
    help = 'Runs Telegram Bot Polling'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Telegram Bot ishga tushirilmoqda..."))
        app = create_bot_application()
        app.run_polling()
