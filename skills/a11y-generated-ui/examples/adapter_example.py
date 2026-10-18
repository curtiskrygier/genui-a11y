#!/usr/bin/env python3
"""The adapter is the only part you write: turn your generator's output into {name: html fragment}.

Here, a stand-in "renderer" for a payload schema. Replace render() with a call into yours (a Python function, a Node script that
prints HTML, an HTTP call). Give the real host stylesheet to ratchet.py with --shell so theme tokens resolve as they do in production.

    python3 adapter_example.py > items.json && python3 ../scripts/ratchet.py --items items.json --report
"""
import json


def render(payload):
    kind = payload["type"]
    if kind == "button":
        return f'<button type="button">{payload["label"]}</button>'
    if kind == "field":
        return f'<label for="{payload["id"]}">{payload["label"]}</label> <input id="{payload["id"]}" type="text">'
    raise ValueError(kind)


PAYLOADS = {
    "button_example": {"type": "button", "label": "Save"},
    "field_example": {"type": "field", "id": "name", "label": "Name"},
}

print(json.dumps({name: render(p) for name, p in PAYLOADS.items()}, indent=1))
