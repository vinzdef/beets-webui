import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from beets.library import Library
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .imports import ImportManager
from .routes import imports, library

STATIC_DIR = Path(__file__).parent / "static"

# Older Pythons don't know this type, and browsers want it for the PWA manifest.
mimetypes.add_type("application/manifest+json", ".webmanifest")


def create_app(lib: Library) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Release an import blocked on a question, or its pipeline threads keep the process alive.
        app.state.imports.shutdown()

    app = FastAPI(title="beets web UI", lifespan=lifespan)
    app.state.lib = lib
    app.state.imports = ImportManager(lib)

    app.include_router(library.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Serve the compiled SvelteKit SPA, falling back to index.html for client routes.
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR.resolve()):
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(404, "Frontend not built. Run `pnpm build` in frontend/.")
        return FileResponse(index)

    return app
