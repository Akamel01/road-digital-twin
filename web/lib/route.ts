// URL state: ?f=<facility id>&e=<element id>. Plain query params, so a static export needs no server.

export interface Route {
  f?: string;
  e?: string;
}

export function parseRoute(search: string): Route {
  const p = new URLSearchParams(search);
  const route: Route = {};
  const f = p.get("f");
  const e = p.get("e");
  if (f) route.f = f;
  if (e) route.e = e;
  return route;
}

export function routeUrl(route: Route): string {
  const p = new URLSearchParams();
  if (route.f) p.set("f", route.f);
  if (route.e) p.set("e", route.e);
  const qs = p.toString();
  return qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
}
