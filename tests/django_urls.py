from __future__ import annotations

from django.urls import path


def avoid_django_default_welcome_page():  # pragma: no cover
    pass


urlpatterns = [path("", avoid_django_default_welcome_page)]
