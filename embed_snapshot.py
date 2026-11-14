import json,re
from pathlib import Path
p=Path("docs/index.html")
d=Path("docs/public-data.json")
if d.exists():
    payload=json.dumps(json.loads(d.read_text()),ensure_ascii=False).replace("<","\\u003c")
    page=re.sub(r'(<script id="initial" type="application/json">).*?(</script>)',lambda m:m[1]+payload+m[2],p.read_text(),flags=re.S)
    p.write_text(page)
