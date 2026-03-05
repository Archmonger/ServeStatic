# Using ServeStatic with WSGI apps

To enable ServeStatic you need to wrap your existing WSGI application in a `ServeStatic` instance and tell it where to find your static files. For example:

```python
from servestatic import ServeStatic

from my_project import MyWSGIApp

application = MyWSGIApp()
application = ServeStatic(application, root="/path/to/static/files")
application.add_files("/path/to/more/static/files", prefix="more-files/")
```

Alternatively, you can use ServeStatic as a standalone file server by not providing a WSGI app. For example:

```python
from servestatic import ServeStatic

application = ServeStatic(None, root="/path/to/static/files")
```

<!--shared-desc-start-->

On initialization, ServeStatic walks over all the files in the directories that have been added (descending into sub-directories) and builds a list of available static files. Any requests which match a static file get served by ServeStatic, all others are passed through to the original application.

<!--shared-desc-end-->

After configuring ServeStatic, you can use your favorite WSGI server (such as [`gunicorn`](https://gunicorn.org/) or [`waitress`](https://pypi.org/project/waitress/)) to run your application.

```bash linenums="0"
gunicorn my_project:application
```

See the [API reference documentation](servestatic.md) for detailed usage and features.
