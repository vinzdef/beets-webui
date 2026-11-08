"""Beets plugin that serves a web UI for browsing, editing and importing music.

Enable it by adding ``webui`` to the ``plugins`` list in your beets config, then
run ``beet webui``.
"""

from beets.plugins import BeetsPlugin
from beets.ui import Subcommand


class WebUIPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add(
            {
                "host": "127.0.0.1",
                "port": 8338,
            }
        )

    def commands(self):
        cmd = Subcommand("webui", help="start the beets web UI")

        def func(lib, opts, args):
            import uvicorn

            from .app import create_app

            host = args.pop(0) if args else self.config["host"].as_str()
            port = int(args.pop(0)) if args else self.config["port"].get(int)

            self._log.info("serving on http://{}:{}", host, port)
            uvicorn.run(create_app(lib), host=host, port=port, log_level="info")

        cmd.func = func
        return [cmd]
