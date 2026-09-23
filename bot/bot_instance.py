import logging
from django.conf import settings
from telegram.ext import Application
from bot.handlers import post_init, post_shutdown, setup_handlers

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# httpx har bir so'rovni INFO darajada to'liq URL bilan yozadi — URL ichida
# bot tokeni bor (https://api.telegram.org/bot<TOKEN>/...). Token logga
# (journalctl) tushmasligi uchun faqat ogohlantirish va xatolar qoldiriladi.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


class RedactTokenFilter(logging.Filter):
    """Har ehtimolga qarshi: log matnida token uchrasa, uni yashiradi."""

    def __init__(self, token):
        super().__init__()
        self.token = token

    def filter(self, record):
        if self.token:
            message = record.getMessage()
            if self.token in message:
                record.msg = message.replace(self.token, '<TOKEN>')
                record.args = ()
        return True


def _install_token_filter(token):
    if not token:
        return
    token_filter = RedactTokenFilter(token)
    for handler in logging.getLogger().handlers:
        handler.addFilter(token_filter)


def create_bot_application():
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token or token.endswith('_TEXNOPARK_TEST'):
        logger.warning("Telegram bot tokeni to'liq sozlanmagan. Standart sozlama faol.")
    _install_token_filter(token)

    application = (
        Application.builder().token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    setup_handlers(application)
    return application
