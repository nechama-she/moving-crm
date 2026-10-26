"""Initial move card and safely encoded bootstrap data for verified visitors."""
import html
import json


def render(template, bootstrap=None):
    if not bootstrap:
        return template
    move = bootstrap['move']
    esc = lambda value: html.escape(str(value or ''), quote=True)
    company = move.get('company_details') or {}
    payload = json.dumps(bootstrap).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    stops = ''.join(f'<dt>Stop</dt><dd>{esc(stop.get("address"))}</dd>' for stop in move.get('stops', []))
    shell = f'''<style id="move-first-style">
    #root{{display:none}}body{{margin:0;background:#f5f3ec}}
    #move-first{{max-width:1060px;margin:auto;padding:40px 24px;font-family:Arial,sans-serif;color:#30231f}}
    #move-first header{{padding:20px 0;border-bottom:1px solid #ddd;font-size:24px;font-weight:bold}}
    #move-first main{{display:flex;align-items:center;gap:60px;padding:56px 0}}
    #move-first h1{{font-size:36px;line-height:1.2}}#move-first article{{background:white;border:1px solid #ddd;border-radius:18px;padding:30px;flex:1;min-width:0}}
    #move-first dt{{font-size:12px;text-transform:uppercase;margin-top:20px;color:#735b50}}#move-first dd{{margin:8px 0;overflow-wrap:anywhere}}
    @media(max-width:650px){{#move-first main{{display:block;padding:24px 0}}#move-first h1{{font-size:28px}}}}
    </style><div id="move-first"><header>{esc(company.get('name') or move.get('company'))}</header>
    <main><div><h1>Hi {esc(move.get('name'))},<br>you're in the right place.</h1><p>Share a little more about your home.</p></div>
    <article><small>YOUR MOVE</small><h2>{esc(move.get('move_date') or 'Date to be confirmed')}</h2><dl>
    <dt>Pickup</dt><dd>{esc(move.get('pickup'))}</dd>{stops}<dt>Delivery</dt><dd>{esc(move.get('delivery'))}</dd>
    </dl><hr><p>{esc(move.get('name'))}</p><p>{esc(move.get('phone'))}</p><p>{esc(move.get('email'))}</p></article></main></div>
    <script id="move-bootstrap" type="application/json">{payload}</script>'''
    return template.replace('<div id="root"></div>', shell + '<div id="root"></div>')
