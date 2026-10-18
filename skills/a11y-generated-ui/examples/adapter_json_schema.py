#!/usr/bin/env python3
"""A second, deliberately small adapter: a JSON component list in, {name: html} out, ready for `ratchet.py --items`.

This is a worked example of the adapter step for a different kind of generator than the catalogue the harness was built on (a declarative
description of components, rendered by a small renderer). It is a toy: a real system replaces `render` with its own renderer and keeps the rest.

    python3 adapter_json_schema.py components.json > items.json
    python3 ../scripts/ratchet.py --items items.json --score

components.json:  {"save": {"type": "button", "label": "Save"}, "photo": {"type": "image", "src": "a.png", "alt": ""}, ...}
"""
import html, json, sys


def render(c):
    t = c.get('type')
    if t == 'button':
        return f'<button type="button">{html.escape(c.get("label", ""))}</button>'
    if t == 'link':
        return f'<a href="{html.escape(c.get("href", "#"))}">{html.escape(c.get("label", ""))}</a>'
    if t == 'image':
        alt = c.get('alt')
        return f'<img src="{html.escape(c.get("src", ""))}"' + (f' alt="{html.escape(alt)}"' if alt is not None else '') + '>'
    if t == 'input':
        label = c.get('label')
        field = f'<input id="f" type="text" name="{html.escape(c.get("name", "x"))}">'
        return (f'<label for="f">{html.escape(label)}</label>' if label else '') + field
    if t == 'heading':
        return f'<h2>{html.escape(c.get("text", ""))}</h2>'
    raise ValueError(f'no renderer for type {t!r}')


if __name__ == '__main__':
    components = json.load(open(sys.argv[1]))
    print(json.dumps({'html': {name: render(c) for name, c in components.items()}}, indent=1))
