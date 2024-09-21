from __future__ import annotations

from wsgiref.util import FileWrapper

from servestatic.base import ServeStaticBase
from servestatic.utils import decode_path_info


class ServeStatic(ServeStaticBase):
    def __call__(self, environ, start_response):
        path = decode_path_info(environ.get("PATH_INFO", ""))
        static_file = self.find_file(path) if self.autorefresh else self.files.get(path)
        if static_file is None:
            return self.application(environ, start_response)

        return self.serve(static_file, environ, start_response)

    @staticmethod
    def serve(static_file, environ, start_response):
        response = static_file.get_response(environ["REQUEST_METHOD"], environ)
        status_line = f"{response.status} {response.status.phrase}"
        start_response(status_line, list(response.headers))
        if response.file is not None:
            file_wrapper = environ.get("wsgi.file_wrapper", FileWrapper)
            return file_wrapper(response.file)
        return []
