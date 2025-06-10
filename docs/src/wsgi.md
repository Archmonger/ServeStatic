# Using ServeStatic with WSGI apps

To enable ServeStatic you need to wrap your existing WSGI application in a `ServeStatic` instance and tell it where to find your static files. For example:

```python
from servestatic import ServeStatic

from my_project import MyWSGIApp

application = MyWSGIApp()
application = ServeStatic(application, root="/path/to/static/files")
application.add_files("/path/to/more/static/files", prefix="more-files/")
```

If you would rather use ServeStatic as a standalone file server, you can simply not provide a WSGI app, such as `#!python ServeStatic(None, root="/path/to/static/files")`.

<!--shared-desc-start-->

On initialization, ServeStatic walks over all the files in the directories that have been added (descending into sub-directories) and builds a list of available static files. Any requests which match a static file get served by ServeStatic, all others are passed through to the original application.

<!--shared-desc-end-->

After configuring ServeStatic, you can use your favourite WSGI server (such as [`gunicorn`](https://gunicorn.org/), [`waitress`](https://pypi.org/project/waitress/), or [`nginx-unit`](https://unit.nginx.org/)) to run your application.

See the [API reference documentation](servestatic.md) for detailed usage and features.
