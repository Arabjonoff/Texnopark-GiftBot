from django.apps import AppConfig

class AppMainConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_main'
    verbose_name = "Texnopark App Main"

    def ready(self):
        # Yetim rasm fayllarini tozalovchi signallarni ro'yxatdan o'tkazamiz
        from app_main import signals  # noqa: F401
