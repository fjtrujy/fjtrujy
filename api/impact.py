"""Dynamically rendered open-source impact graphic."""
from http.server import BaseHTTPRequestHandler

from scripts.live_profile_http import serve_svg
from scripts.live_profile_stats import render_impact


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        serve_svg(self, render_impact)

    def do_HEAD(self):
        serve_svg(self, render_impact, send_body=False)
