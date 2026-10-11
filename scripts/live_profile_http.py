"""HTTP response helpers for the two public Vercel SVG endpoints."""
import logging


def serve_svg(request, renderer, send_body=True):
    try:
        svg = renderer().encode("utf-8") if send_body else b""
    except Exception:
        # Do not return GitHub credentials, API errors, or tracebacks to the
        # public image URL. A failed refresh must not be cached.
        logging.exception("Could not generate a live profile graphic")
        request.send_response(503)
        request.send_header("Content-Type", "text/plain; charset=utf-8")
        request.send_header("Cache-Control", "no-store")
        request.end_headers()
        if send_body:
            request.wfile.write(b"Profile statistics temporarily unavailable")
        return

    request.send_response(200)
    request.send_header("Content-Type", "image/svg+xml; charset=utf-8")
    request.send_header("X-Content-Type-Options", "nosniff")
    request.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
    # Recalculate at the origin on CDN revalidation rather than committing
    # static SVG snapshots. GitHub's separate Camo cache is outside our control.
    request.send_header("Cache-Control", "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400")
    if send_body:
        request.send_header("Content-Length", str(len(svg)))
    request.end_headers()
    if send_body:
        request.wfile.write(svg)
