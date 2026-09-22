from django.conf import settings

def get_webapp_url() -> str:
    """
    Returns the WebApp URL configured in settings or localhost default
    """
    return getattr(settings, 'TELEGRAM_WEBAPP_URL', 'http://127.0.0.1:8000')
