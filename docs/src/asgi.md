# Using ServeStatic with ASGI apps

!!! tip

    `ServeStaticASGI` inherits its interface and features from the [WSGI variant](wsgi.md).

To enable ServeStatic you need to wrap your existing ASGI application in a `ServeStaticASGI` instance and tell it where to find your static files. For example:

```python
from servestatic import ServeStaticASGI

from my_project import MyASGIApp

application = MyASGIApp()
application = ServeStaticASGI(application, root="/path/to/static/files")
application.add_files("/path/to/more/static/files", prefix="more-files/")
```

If you would rather use ServeStatic as a standalone file server, you can simply not provide an ASGI app, such as via `#!python ServeStaticASGI(None, root="/path/to/static/files")`.

{% include-markdown "./wsgi.md" start="<!--shared-desc-start-->" end="<!--shared-desc-end-->" %}

After configuring ServeStatic, you can use your favourite ASGI server (such as [`uvicorn`](https://pypi.org/project/uvicorn/), [`hypercorn`](https://pypi.org/project/Hypercorn/), or [`nginx-unit`](https://unit.nginx.org/)) to run your application.

See the [API reference documentation](servestatic-asgi.md) for detailed usage and features.
