#!/usr/bin/env python3
"""UNPACKING: cloud acquisition of public datasets; public-safe output only.
GitHub Actions runs this script and commits docs/satellite-report.html and data manifests.
No user screenshots, private video, or unpublished files are uploaded.
"""
import base64, datetime as dt, html, io, json, os, time
from urllib.parse import urlencode
import requests

NOW=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
SITES=[
 {"id":"W01","name":"Wadas / Karawang","lat":-6.330215,"lon":107.275565,"precision":"administrative-area centre; not a parcel"},
 {"id":"B06","name":"Zara Kost – Kaliboson","lat":-6.977356,"lon":107.6246481,"precision":"user-provided map centre; not georeferenced parcel"},
 {"id":"B04N","name":"Dua rute BIG Bojongsoang","lat":-6.99097,"lon":107.652585,"precision":"sample route centroid; not entire Bojongsoang"},
 {"id":"B07","name":"IPAL Bojongsoang","query":"IPAL Bojongsoang Kabupaten Bandung Indonesia"},
 {"id":"B08","name":"Cisirung – Cangkuang Wetan","query":"Cisirung Dayeuhkolot Kabupaten Bandung Indonesia"},
 {"id":"B09","name":"Cikoneng – Cijeruk","query":"Cikoneng Bojongsoang Kabupaten Bandung Indonesia"},
 {"id":"B10","name":"Oxbow Bojongsoang","query":"Oxbow Bojongsoang Kabupaten Bandung Indonesia"},
 {"id":"B12","name":"Podomoro Park Buahbatu","query":"Podomoro Park Buahbatu Bandung Indonesia"},
 {"id":"B05","name":"Jalur panen Cikoneng","query":"Cikoneng Bojongsoang Kabupaten Bandung Indonesia"}
]
CATALOG=[
 {"lane":"S5","name":"Portal JDIH Kabupaten Karawang","url":"https://jdih.karawangkab.go.id/","kind":"historical/policy document index"},
 {"lane":"S5","name":"Portal pemerintah Kabupaten Karawang","url":"https://karawangkab.go.id/","kind":"historical events index"},
 {"lane":"S6","name":"BPS Kabupaten Karawang","url":"https://karawangkab.bps.go.id/","kind":"social statistics index"},
 {"lane":"S6","name":"BPS Kabupaten Bandung","url":"https://bandungkab.bps.go.id/","kind":"social statistics index"}
]
session=requests.Session()
session.headers.update({"User-Agent":"UNPACKING-LandscapeResearch/16.0 (public noncommercial research)","Accept":"application/json,*/*"})
results=[]
for site in SITES:
 results.append({"site":site,"sources":{k:{"status":"not_acquired","count":0} for k in ["S1","S2","S3","S4","S5","S6"]},"scenes":[],"errors":[]})

def get(url,**kwargs):
    for retry in range(2):
        try:
            r=session.get(url,timeout=(10,30),**kwargs)
            r.raise_for_status()
            return r
        except Exception:
            if retry: raise
            time.sleep(2)
def located(site):
    if "lat" in site:return True
    try:
        r=get("https://nominatim.openstreetmap.org/search",params={"q":site["query"],"format":"jsonv2","limit":3})
        for loc in r.json():
            lat=float(loc["lat"]);lon=float(loc["lon"])
            if -7.5<lat<-6.0 and 106.5<lon<109:
                site.update(lat=lat,lon=lon,precision="geocoding search estimate; NOT surveyed boundary")
                return True
    except Exception as exc:
        site["geocoding_error"]=str(exc)[:130]
    finally:time.sleep(1.2)
    return False
def extent(site):
    lon,lat=site["lon"],site["lat"]
    d=.007
    return [round(lon-d,6),round(lat-d,6),round(lon+d,6),round(lat+d,6)]
def stac(scene,year,bbox):
    start=f"{year}-05-01T00:00:00Z"
    end=f"{year}-11-14T23:59:59Z" if year==2026 else f"{year}-11-30T23:59:59Z"
    url="https://earth-search.aws.element84.com/v1/search"
    r=get(url,params={"collections":"sentinel-2-c1-l2a","bbox":",".join(map(str,bbox)),"datetime":start+"/"+end,"limit":100})
    items=r.json().get("features",[])
    items=[i for i in items if i.get("assets")]
    items.sort(key=lambda i:float(i.get("properties",{}).get("eo:cloud_cover",100)))
    return items[:4]
def read_rgb(scene,bbox):
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds, Window
    from rasterio.enums import Resampling
    from PIL import Image
    assets=scene.get("assets",{})
    visual=assets.get("visual",{}).get("href")
    if not visual or not visual.startswith("https://"):
        raise ValueError("Public visual COG not provided by this STAC scene")
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES",GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                       CPL_VSIL_CURL_USE_HEAD="NO",GDAL_HTTP_TIMEOUT="25",GDAL_HTTP_MAX_RETRY="1"):
        with rasterio.open(visual) as ds:
            bounds=transform_bounds("EPSG:4326",ds.crs,*bbox,densify_pts=6)
            win=from_bounds(*bounds,transform=ds.transform).round_offsets().round_lengths()
            win=win.intersection(Window(0,0,ds.width,ds.height))
            if win.width<2 or win.height<2:raise ValueError("AOI outside COG scene")
            w,h= min(int(win.width),520),min(int(win.height),520)
            if ds.count<3:raise ValueError("RGB visual has less than 3 channels")
            rgb=ds.read([1,2,3],window=win,out_shape=(3,h,w),resampling=Resampling.bilinear)
    if rgb.dtype!=np.uint8:
        bands=[]
        for band in rgb:
            valid=band[np.isfinite(band)&(band>0)]
            if valid.size==0:raise ValueError("No valid raster pixels")
            lo,hi=np.percentile(valid,[2,98])
            bands.append(np.clip((band-lo)/(max(hi-lo,1))*255,0,255).astype("uint8"))
        rgb=np.stack(bands)
    if not np.any(rgb):raise ValueError("RGB appears empty")
    image=Image.fromarray(np.moveaxis(rgb,0,2),"RGB")
    f=io.BytesIO();image.save(f,format="WEBP",quality=77)
    return "data:image/webp;base64,"+base64.b64encode(f.getvalue()).decode(),[w,h]
def acquire(result):
    site=result["site"]; sid=site["id"]
    if not located(site):
        result["errors"].append("Location not resolved; no AOI generated")
        return
    bbox=extent(site)
    result["bbox"]=bbox
    # S1 OSM: public Overpass, with fallback host
    q=f'[out:json][timeout:32];(way["highway"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});way["waterway"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}););out tags geom;'
    for endpoint in ["https://overpass.kumi.systems/api/interpreter","https://overpass-api.de/api/interpreter"]:
        try:
            data=get(endpoint,params={"data":q}).json()
            objects=data.get("elements",[])
            if not objects:raise ValueError("empty Overpass response")
            # Store simplified geometry with source attribution, not raw gigantic API output.
            result["osm"]=[{"id":x.get("id"),"tags":x.get("tags",{}),"geometry":x.get("geometry",[])} for x in objects[:600]]
            result["sources"]["S1"]={"status":"downloaded","count":len(result["osm"]),"provider":"OpenStreetMap / Overpass","url":endpoint}
            break
        except Exception as exc:result["errors"].append("S1 "+str(exc)[:80])
    # S2: catalog success is distinct from actual successful COG pixel read
    for year in [2021,2026]:
        try:
            scenes=stac(site,year,bbox)
            result["sources"]["S2"]["catalogued"]=result["sources"]["S2"].get("catalogued",0)+len(scenes)
            for scene in scenes:
                try:
                    data,wh=read_rgb(scene,bbox)
                    result["scenes"].append({"year":year,"datetime":scene["properties"].get("datetime"),"scene_id":scene["id"],
                        "cloud_cover_scene_pct":scene["properties"].get("eo:cloud_cover"),"rgb":data,"dimensions":wh,
                        "source_url":scene.get("assets",{}).get("visual",{}).get("href"),
                        "type":"RGB visual from public Sentinel-2 COG","status":"pixels_downloaded"})
                    break
                except Exception as exc: result["errors"].append(f"S2 COG {year}: "+str(exc)[:100])
        except Exception as exc:result["errors"].append(f"S2 STAC {year}: "+str(exc)[:100])
    result["sources"]["S2"]["count"]=len(result["scenes"])
    result["sources"]["S2"]["status"]="pixels_downloaded" if result["scenes"] else ("catalog_only" if result["sources"]["S2"].get("catalogued") else "not_acquired")
    # S3 public Panoramax search; not Mapillary
    try:
        r=get("https://api.panoramax.xyz/api/search",params={"bbox":",".join(map(str,bbox)),"limit":20})
        features=r.json().get("features",[])
        result["street_catalog"]=features
        result["sources"]["S3"]={"status":"catalogued","count":len(features),"provider":"Panoramax, not Mapillary"}
    except Exception as exc:result["errors"].append("S3 "+str(exc)[:100])
    # S4 monthly climate context: not local flooding measurement
    try:
        r=get("https://power.larc.nasa.gov/api/temporal/monthly/point",params={
            "parameters":"PRECTOTCORR","community":"AG","longitude":site["lon"],"latitude":site["lat"],
            "start":"2020","end":"2025","format":"JSON"})
        series=r.json().get("properties",{}).get("parameter",{}).get("PRECTOTCORR",{})
        if not series:raise ValueError("NASA POWER series empty")
        result["monthly_rainfall"]=series
        result["sources"]["S4"]={"status":"downloaded","count":len(series),"provider":"NASA POWER grid (regional context)"}
    except Exception as exc:result["errors"].append("S4 "+str(exc)[:100])
    # S5–S6 link registry only: no fabricated document harvest or per-site social statistics
    result["sources"]["S5"]={"status":"indexed_only","count":0,"provider":"Official archival portals"}
    result["sources"]["S6"]={"status":"indexed_only","count":0,"provider":"BPS portals"}
    print(sid,"S1",result["sources"]["S1"]["count"],"S2 RGB",len(result["scenes"]),
          "S3",result["sources"]["S3"]["count"],"S4",result["sources"]["S4"]["count"],flush=True)

for item in results:
    acquire(item)

public_data={"schema":"unpacking.public-acquisition.v16","generated_at":NOW,"site_count":len(SITES),
             "notes":["Source results are location- and date-specific.","RGB is visualization; not NDVI or land-use change.","Geocoded points are search estimates, not AOI polygons.","S5/S6 are document indexes until records are harvested."],
             "source_registry":CATALOG,"results":results}
os.makedirs("docs",exist_ok=True)
with open("docs/public-data.json","w",encoding="utf8") as f:json.dump(public_data,f,ensure_ascii=False,separators=(",",":"))
status={"generated_at":NOW,"site_count":len(results),"sites_with_real_rgb":sum(bool(r["scenes"]) for r in results),
        "real_rgb_scene_count":sum(len(r["scenes"]) for r in results),
        "sites_with_osm":sum(r["sources"]["S1"]["status"]=="downloaded" for r in results),
        "sites_with_climate":sum(r["sources"]["S4"]["status"]=="downloaded" for r in results),
        "errors_by_site":{r["site"]["id"]:r["errors"] for r in results if r["errors"]}}
with open("docs/data-status.json","w",encoding="utf8") as f:json.dump(status,f,ensure_ascii=False,indent=2)

# The viewer is self-contained, retains downloaded public rasters and metadata.
cards=[]
for r in results:
    s=r["site"]; rows=[]
    for code in ["S1","S2","S3","S4","S5","S6"]:
        q=r["sources"][code]
        rows.append(f'<span class="pill">{code}: {html.escape(q["status"])} · {q["count"]}</span>')
    images="".join(f'<figure><img loading="lazy" src="{x["rgb"]}" alt="Real Sentinel-2 scene for {html.escape(s["name"])}">'
                   f'<figcaption>{x["year"]} · {html.escape(x["scene_id"])} · awan scene {x["cloud_cover_scene_pct"]}%</figcaption></figure>' for x in r["scenes"])
    if not images:images='<p class="empty">Belum ada raster Sentinel yang berhasil diunduh untuk lokasi ini.</p>'
    cards.append(f'<article class="site" data-id="{s["id"]}"><div class="head"><strong>{s["id"]} · {html.escape(s["name"])}</strong><small>{html.escape(s.get("precision","lokasi tidak terverifikasi"))}</small></div>'
                 f'<div class="pills">{"".join(rows)}</div><div class="images">{images}</div>'
                 f'<details><summary>Metadata dan sumber</summary><pre>{html.escape(json.dumps({"site":s,"sources":r["sources"],"errors":r["errors"]},ensure_ascii=False,indent=2))}</pre></details></article>')
page='''<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>UNPACKING / Landscape Acquisition Atlas</title>
<style>body{margin:0;background:#f7faf8;color:#1d3935;font:14px/1.55 system-ui,Arial}
header{padding:27px clamp(18px,4vw,50px);background:#fff;border-bottom:1px solid #dae5df}
header h1{margin:0;font-size:28px}header p{color:#56736d;margin:5px 0}
main{max-width:1300px;margin:auto;padding:22px}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin:0 0 22px}.stats b{padding:10px 15px;border:1px solid #cee0d6;border-radius:10px;background:#fff}
.site{border:1px solid #d4e4dc;background:#fff;border-radius:14px;padding:20px;margin-bottom:15px}
.head{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
.head strong{font-size:19px}.head small{color:#78908a}.pills{display:flex;gap:7px;flex-wrap:wrap;margin:13px 0}
.pill{padding:5px 9px;background:#e8f3ef;border-radius:15px;font-size:11px}
.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
figure{margin:0}figure img{width:100%;border-radius:9px;display:block}figcaption{font-size:11px;color:#60766f;margin:4px 0}
.empty{background:#f3f6f4;padding:30px;border-radius:9px;color:#708781}
details{margin-top:12px}summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;background:#f5f7f5;padding:12px;border-radius:9px}
</style><header><h1>UNPACKING / Landscape Acquisition</h1><p>Data publik · 9 lokasi · Satelit, jaringan, iklim, dan arsip sumber · Pattern Lab belum diproses</p></header>
<main><div class="stats">'''
page+=f'<b>{len(results)} lokasi</b><b>{status["sites_with_real_rgb"]} lokasi dengan raster</b><b>{status["real_rgb_scene_count"]} scene RGB</b><b>{status["sites_with_osm"]} lokasi OSM</b></div>'
page+="".join(cards)
page+=f'<p>Pengambilan terakhir: {NOW}. Tidak ada raster atau nilai ekologis sintetis.</p></main></html>'
with open("docs/satellite-report.html","w",encoding="utf8") as f:f.write(page)
print("FINISHED",json.dumps(status,ensure_ascii=False),flush=True)
