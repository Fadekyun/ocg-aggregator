import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ocg_aggregator.settings")
application = get_asgi_application()

