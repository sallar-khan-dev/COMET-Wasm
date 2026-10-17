"""Approval-only common ingress prototype; requires aiohttp.
Routes are configured at admission, NOT chosen on every inference request.
Internal Docker bridge IPs/ports must be supplied explicitly; do not publish per-tenant ports.
"""
import argparse, asyncio, json
from aiohttp import web, ClientSession, ClientTimeout

class Gateway:
    def __init__(self, routes):
        self.routes=routes
        self.session=None
    async def startup(self,app):
        self.session=ClientSession(timeout=ClientTimeout(total=10))
    async def cleanup(self,app):
        await self.session.close()
    async def infer(self,request):
        try: body=await request.json()
        except Exception: return web.json_response({'error':'invalid_json'},status=400)
        tenant=str(body.get('tenant_id',''))
        route=self.routes.get(tenant)
        if route is None: return web.json_response({'error':'tenant_not_admitted'},status=404)
        if not isinstance(body.get('features'),list): return web.json_response({'error':'missing_features'},status=400)
        try:
            async with self.session.post(route['url'],json=body) as response:
                data=await response.read()
                return web.Response(body=data,status=response.status,content_type=response.content_type or 'application/json')
        except (asyncio.TimeoutError,Exception) as exc:
            return web.json_response({'error':'backend_unavailable','type':type(exc).__name__},status=502)
    async def noop(self,request): return web.json_response({'ok':True})

def make_app(routes):
    gateway=Gateway(routes)
    app=web.Application()
    app.on_startup.append(gateway.startup); app.on_cleanup.append(gateway.cleanup)
    app.router.add_post('/infer',gateway.infer)
    app.router.add_get('/health',lambda req:web.json_response({'ok':True}))
    app.router.add_get('/noop',gateway.noop)
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--routes',required=True);parser.add_argument('--port',type=int,default=8200)
    args=parser.parse_args(); routes=json.load(open(args.routes))
    for tenant,route in routes.items():
        if route.get('backend') not in ('wasmtime','docker','native') or not route.get('url','').startswith('http://'):
            raise ValueError('invalid route for '+tenant)
    web.run_app(make_app(routes),host='127.0.0.1',port=args.port)
