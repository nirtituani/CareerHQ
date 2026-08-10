import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "careerhq_session";
const PROTECTED = ["/dashboard", "/applications", "/profile", "/resumes"];

/**
 * Redirect unauthenticated visitors away from protected pages (FR-014).
 *
 * This checks only that a session cookie is *present*. Middleware has no
 * access to the signing secret, so it cannot verify the signature or the
 * expiry — an expired or forged cookie passes here, the page renders, and the
 * API then refuses the request with a 401.
 *
 * That is by design: authorization lives at the API boundary, where the secret
 * is. This guard exists to save an unauthenticated visitor a pointless page
 * load, not to protect data. Treating it as a security control would be a
 * mistake.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (!PROTECTED.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    return NextResponse.next();
  }

  if (request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/dashboard/:path*", "/applications/:path*", "/profile/:path*", "/resumes/:path*"],
};
