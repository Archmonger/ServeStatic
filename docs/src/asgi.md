# Using ServeStatic with ASGI apps

!!! tip

    `ServeStaticASGI` inherits its interface and features from the [WSGI variant](wsgi.md).

To enable ServeStatic on an existing ASGI asgi_app, wrap it in a `ServeStaticASGI` instance and tell it where to find your static files. For example:

=== "`my_project.py`"

    ```python
    from servestatic import ServeStaticASGI

    from example_framework import ExampleApp

    asgi_app = ExampleApp()
    asgi_app = ServeStaticASGI(asgi_app, root="/path/to/static/files")
    asgi_app.add_files("/path/to/more/static/files", prefix="more-files/")
    ```

Alternatively, you can use ServeStatic as a standalone file server by not providing a WSGI app. For example:

```python linenums="0"
asgi_app = ServeStaticASGI(application=None, root="/path/to/static/files")
```

{% include-markdown "./wsgi.md" start="<!--shared-desc-start-->" end="<!--shared-desc-end-->" %}

After configuring ServeStatic, you can use your favourite ASGI server (such as [`uvicorn`](https://pypi.org/project/uvicorn/) or [`hypercorn`](https://pypi.org/project/Hypercorn/)) to run your application.

```bash linenums="0"
uvicorn my_project:asgi_app
```

See the [API reference documentation](servestatic-asgi.md) for detailed usage and features.
