The documentation below is a quick-start guide to using ServeStatic to serve your static files. For more detailed information see the [full installation docs](django.md).

---

## Installation

!!! note "Optional Extras" ServeStatic has optional extras ('brotli' and 'minify') for Brotli compression and minification. The example below shows how to install with these extras, but you can omit them if you don't need those features.

To install from PyPI, run the following command:

```bash linenums="0"

pip install servestatic[brotli, minify]
```

## Using with ASGI

!!! note

    For configuration instructions, see the [ASGI guide](asgi.md).

## Using with WSGI

!!! note

    For configuration instructions, see the [WSGI guide](wsgi.md).

## Using with Django

!!! note

    For advanced configuration instructions, see the [full Django guide](django.md).

Edit your `settings.py` file and add ServeStatic to the `MIDDLEWARE` list, above all other middleware apart from Django's [SecurityMiddleware](https://docs.djangoproject.com/en/stable/ref/middleware/#module-django.middleware.security).

```python linenums="0"
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "servestatic.middleware.ServeStaticMiddleware",
    # ...
]
```

That's it, you're ready to go.

Want forever-cacheable files and compression support? Just add this to your `settings.py`.

```python linenums="0"
STORAGES = {
    "staticfiles": {
        "BACKEND": "servestatic.storage.CompressedManifestStaticFilesStorage",
    },
}
```
