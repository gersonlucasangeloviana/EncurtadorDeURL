import secrets
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from .application.catalog import create_path, create_project, delete_entry
from .application.errors import ApplicationError, Conflict, InvalidInput, NotFound, Unavailable
from .application.links import create_link, delete_link
from .application.resolution import Outcome, resolve
from .core import csv_values

_ERROR_STATUS = {InvalidInput: 422, Conflict: 409, NotFound: 404, Unavailable: 503}
_REDIRECT_STATUS = {Outcome.REDIRECT: 302, Outcome.NOT_FOUND: 404, Outcome.GONE: 410}
_NO_STORE = {'Cache-Control': 'no-store'}


class Named(BaseModel):
    name: str


class LinkInput(BaseModel):
    destination_url: str
    short_code: str | None = None
    project_name: str | None = None
    public_path: str | None = None
    expires_at: datetime | None = None


def _link_response(link, base_url):
    prefix = f'{link.public_path}/' if link.public_path else ''
    return {
        'short_code': link.short_code,
        'destination_url': link.destination_url,
        'public_path': link.public_path,
        'project_name': link.project_name,
        'active': link.active,
        'expires_at': link.expires_at,
        'url': f'{base_url.rstrip("/")}/{prefix}{link.short_code}',
    }


def create_app(cfg, links, projects, paths, cache, record_event, *, lifespan=None):
    app = FastAPI(lifespan=lifespan)
    api_key = cfg.api_key.encode()
    admin_password = cfg.admin_password.encode()

    @app.middleware('http')
    async def protect_api(request: Request, call_next):
        path = request.scope['path']
        if path == '/api' or path.startswith('/api/'):
            supplied = request.headers.get('x-api-key', '').encode()
            if not secrets.compare_digest(supplied, api_key):
                return JSONResponse(status_code=401, content={'detail': 'API key inválida'})
            if request.method == 'DELETE':
                password = request.headers.get('x-admin-password', '').encode()
                if not secrets.compare_digest(password, admin_password):
                    return JSONResponse(status_code=403, content={'detail': 'Senha de administrador inválida'})
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(csv_values(cfg.allowed_hosts)))

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, error: ApplicationError):
        detail = {'code': error.code, 'message': str(error)} if error.code else str(error)
        return JSONResponse(status_code=_ERROR_STATUS[type(error)], content={'detail': detail})

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/links')
    def list_links():
        with links() as store:
            return [_link_response(link, cfg.short_base_url) for link in store.list()]

    @app.post('/api/links', status_code=201)
    def add_link(data: LinkInput):
        with links() as store:
            link = create_link(store, cfg, **data.model_dump())
        return _link_response(link, cfg.short_base_url)

    @app.delete('/api/links/{code}')
    def remove_link(code: str):
        with links() as store:
            delete_link(store, cache, code)
        return {'ok': True}

    @app.get('/api/projects')
    def list_projects():
        with projects() as store:
            return store.list()

    @app.post('/api/projects', status_code=201)
    def add_project(data: Named):
        with projects() as store:
            return {'name': create_project(store, data.name)}

    @app.delete('/api/projects')
    @app.delete('/api/projects/{name}')
    def remove_project(name: str):
        with projects() as store:
            delete_entry(store, name, 'Pasta')
        return {'ok': True}

    @app.get('/api/paths')
    def list_paths():
        with paths() as store:
            return store.list()

    @app.post('/api/paths', status_code=201)
    def add_path(data: Named):
        with paths() as store:
            return {'name': create_path(store, data.name, cfg)}

    @app.delete('/api/paths/{path}')
    def remove_path(path: str):
        with paths() as store:
            delete_entry(store, path, 'Path')
        return {'ok': True}

    @app.get('/{code}')
    @app.head('/{code}')
    @app.get('/{path}/{code}')
    @app.head('/{path}/{code}')
    def redirect(request: Request, code: str, path: str | None = None):
        with links() as store:
            result = resolve(code, path, store, cache)
        status = _REDIRECT_STATUS[result.outcome]
        record_event(code, path, request.method, status, result.found, request.scope['headers'])
        if result.outcome is not Outcome.REDIRECT:
            raise HTTPException(status, headers=_NO_STORE)
        return RedirectResponse(result.destination, status_code=status, headers=_NO_STORE)

    return app
