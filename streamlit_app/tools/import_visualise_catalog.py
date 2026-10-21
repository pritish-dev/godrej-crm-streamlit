"""
import_visualise_catalog.py

Builds the Product Catalogue page's local data from an **InterioFinder** HTML
export (e.g. ``InterioFinderQ3.26.html``) — specifically its *Visualise*
section. The page no longer reads products / images / features from the
Google Drive catalogue PDFs; everything comes from the files written here.

What it reads from the HTML
---------------------------
* ``<script id="visualData">``  — one entry per Visualise card: room,
  sub-category, name, catalogue page, sizes (``sz``), F-A-B key points and the
  product photo (embedded base64 JPEG).
* ``<script id="data">``        — the price list rows (item code, name, price).
* ``const VPMAP = {...}``       — links each Visualise card to its price rows.

What it writes (under ``streamlit_app/data/visualise_catalog/``)
--------------------------------------------------------------
* ``images/NNN_<slug>.jpg``     — one photo per product.
* ``catalog.json``              — product list; each product carries its
  price groups with item codes, used by the page to flag discontinued items.

RUN IT (whenever a new InterioFinder file is released)
------------------------------------------------------
    python streamlit_app/tools/import_visualise_catalog.py path/to/InterioFinderQx.yy.html
"""

import base64
import json
import os
import re
import shutil
import sys

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "visualise_catalog",
)


def _script_json(html: str, script_id: str):
    m = re.search(
        r'<script id="%s" type="application/json">(.*?)</script>' % re.escape(script_id),
        html, re.S,
    )
    if not m:
        raise ValueError(f'<script id="{script_id}"> not found in the HTML file')
    return json.loads(m.group(1))


def _vpmap(html: str) -> dict:
    m = re.search(r"const VPMAP=(\{.*?\});\s*$", html, re.M)
    return json.loads(m.group(1)) if m else {}


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "").strip())
    return s.strip("_")[:60] or "Product"


def _price_row(rec: dict) -> dict:
    return {
        "code": rec.get("code") or "",
        "ln_code": rec.get("ln_code") or "",
        "name": rec.get("name") or "",
        "category": rec.get("category") or "",
        "price": rec.get("price"),
        "status": rec.get("status") or "",
    }


def _auraline_groups(x: dict, data: list) -> list:
    """Mirror of the HTML's vpGroups() special-casing for the Auraline family."""
    def cat(r):
        return str(r.get("category") or "").upper()

    def digital(n):
        return bool(re.search(r"dgprint|dgp\b", n or "", re.I))

    def label(n):
        m = re.match(
            r"^auraline\s*(ele|enov|women|wmn|wm|men)\s*(basic|premium|b(?![a-z])|p(?![a-z]))?",
            re.sub(r"\s+", " ", str(n or "").lower()),
        )
        if not m:
            return None
        if m.group(1) == "ele":
            return "Ele"
        if m.group(1) == "enov":
            return "Enov"
        g = "Men's" if m.group(1) == "men" else "Women's"
        t = m.group(2)
        if not t:
            return None
        return f"{g} {'Basic' if t[0] == 'b' else 'Premium'}"

    name = x["name"]
    if name == "Auraline":
        recs = [r for r in data if cat(r) == "HOME STORAGE > AURALINE"
                and not digital(r["name"]) and not re.match(r"^auraline\s*ele", r["name"], re.I)]
    elif name == "Digital Printed Range - Auraline":
        recs = [r for r in data if cat(r) == "HOME STORAGE > AURALINE" and digital(r["name"])]
    elif name == "Auraline Enov":
        recs = [r for r in data if cat(r) == "HOME STORAGE > AURALINE ENOV"]
    elif name == "Auraline Ele":
        recs = [r for r in data if cat(r) == "HOME STORAGE > AURALINE ELE"
                or (cat(r) == "HOME STORAGE > AURALINE" and not digital(r["name"])
                    and re.match(r"^auraline\s*ele", r["name"], re.I))]
    else:
        return []

    groups = {}
    for r in recs:
        lbl = label(r["name"])
        if not lbl:
            if name == "Auraline Enov":
                lbl = "Enov"
            elif name == "Auraline Ele":
                lbl = "Ele"
            else:
                continue
        groups.setdefault(lbl, []).append(r)
    order = ["Men's Basic", "Men's Premium", "Women's Basic", "Women's Premium", "Ele", "Enov"]
    return [(lbl, groups[lbl]) for lbl in order if lbl in groups]


def build(html_path: str) -> str:
    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()

    visual = _script_json(html, "visualData")
    data = _script_json(html, "data")
    by_id = {r["id"]: r for r in data}
    vpmap = _vpmap(html)

    img_dir = os.path.join(OUT_DIR, "images")
    if os.path.isdir(img_dir):
        shutil.rmtree(img_dir)
    os.makedirs(img_dir, exist_ok=True)

    products = []
    for i, x in enumerate(visual):
        image_file = ""
        m = re.match(r"data:image/(\w+);base64,(.*)", x.get("image") or "", re.S)
        if m:
            ext = "jpg" if m.group(1) in ("jpeg", "jpg") else m.group(1)
            image_file = f"{i:03d}_{_slug(x['name'])}.{ext}"
            with open(os.path.join(img_dir, image_file), "wb") as out:
                out.write(base64.b64decode(m.group(2)))

        mapped = vpmap.get(f"{x.get('subcategory', '')}|{x['name']}")
        if mapped and x.get("subcategory") != "Auraline":
            raw_groups = [(lbl, [by_id[i] for i in ids if i in by_id]) for lbl, ids in mapped]
        else:
            raw_groups = _auraline_groups(x, data)
        prices = [
            {"label": lbl, "items": [_price_row(r) for r in
                                     sorted(recs, key=lambda r: r.get("price") or 0)]}
            for lbl, recs in raw_groups if recs
        ]

        products.append({
            "room": x.get("room") or "",
            "subcategory": x.get("subcategory") or "",
            "name": x["name"],
            "page": x.get("page") or "",
            "image": image_file,
            "sizes": x.get("sz") or [],
            "fab": x.get("fab") or [],
            "prices": prices,
        })

    payload = {"source": os.path.basename(html_path), "products": products}
    with open(os.path.join(OUT_DIR, "catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    linked = sum(1 for p in products if p["prices"])
    return (f"✅ {len(products)} products written to {OUT_DIR} "
            f"({linked} linked to price list / item codes).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(build(sys.argv[1]))
