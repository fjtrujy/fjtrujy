"""Dynamically rendered GitHub activity graphic."""
from http.server import BaseHTTPRequestHandler

from scripts.live_profile_http import serve_svg
from scripts.live_profile_stats import render_activity


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        serve_svg(self, render_activity)

    def do_HEAD(self):
        serve_svg(self, render_activity, send_body=False)
