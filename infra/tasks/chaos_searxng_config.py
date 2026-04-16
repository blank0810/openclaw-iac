"""
Upload docker/chaos/searxng/settings.yml to /opt/openclaw/chaos/searxng/settings.yml.

Per memory note searxng_json_format_gotcha.md, this file must have
formats: [html, json] or web_search tool returns 403.
"""

from pyinfra.operations import files

files.put(
    name="Upload SearXNG settings.yml",
    src="docker/chaos/searxng/settings.yml",
    dest="/opt/openclaw/chaos/searxng/settings.yml",
    user="root",
    group="root",
    mode="644",
)
