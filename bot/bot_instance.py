import logging
from django.conf import settings
from telegram.ext import Application
from bot.handlers import post_init, post_shutdown, setup_handlers

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def create_bot_application():
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token or token.endswith('_TEXNOPARK_TEST'):
        logger.warning("Telegram bot tokeni to'liq sozlanmagan. Standart sozlama faol.")

    application = (
        Application.builder().token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    setup_handlers(application)
    return application
