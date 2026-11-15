"""Build the pitch with the standard library and existing Pillow; no network or serving imports."""
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED
from datetime import datetime, timezone
import json
import textwrap
from PIL import ImageFont

HERE = Path(__file__).resolve().parent
W, H, EMU = 1600, 900, 7620
C = dict(bg="101A29", card="192638", white="F5F7FA", muted="A6B5C8",
         green="61E4B1", orange="FFAC86", line="304154")
slides = []

def slide(kicker, title, seconds, notes, source):
    s = dict(kicker=kicker, title=title, seconds=seconds, notes=notes, source=source, shapes=[])
    slides.append(s)
    rect(s, 0, 0, W, H, C["bg"])
    rect(s, 70, 70, 36, 6, C["green"])
    text(s, 122, 57, kicker.upper(), 20, C["green"], bold=True)
    text(s, 70, 842, "TEAM 26  /  RAWTREE × DATATHON FME 2026", 17, C["muted"])
    text(s, 1450, 840, f"{len(slides):02d} / 06", 18, C["muted"])
    return s

def rect(s, x, y, w, h, color, radius=0):
    s["shapes"].append(dict(kind="rect", x=x, y=y, w=w, h=h, color=color, radius=radius))

def text(s, x, y, value, size=30, color=None, bold=False, width=None):
    color = color or C["white"]
    lines = []
    font_path = Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf")
    font = ImageFont.truetype(str(font_path), size)
    for para in value.split("\n"):
        if width is None:
            lines.append(para)
            continue
        words, line = para.split(), ""
        for word in words:
            nxt = (line + " " + word).strip()
            if line and font.getlength(nxt) > width:
                lines.append(line)
                line = word
            else:
                line = nxt
        lines.append(line)
    s["shapes"].append(dict(kind="text", x=x, y=y, w=width or W-x-65,
                            h=max(1, len(lines))*size*1.19+12, lines=lines,
                            size=size, color=color, bold=bold))

def card(s, x, y, w, h, eyebrow, headline, body=None, accent=None):
    rect(s, x, y, w, h, C["card"], 22)
    text(s, x+28, y+24, eyebrow.upper(), 18, accent or C["green"], True, w-56)
    text(s, x+28, y+67, headline, 34, bold=True, width=w-56)
    if body:
        text(s, x+28, y+133, body, 25, C["muted"], width=w-56)

s = slide("The decision behind the system", "Ten products. Three seconds. One shopper.", 15,
    "Ten products. Three seconds. One shopper. "
    "We are Team 26. The difficult part was choosing what to trust: old data, live behavior, or a more complicated model. "
    "Our answer was to make every extra layer earn its place.",
    "Official challenge contract; team final handoff, message (4).txt.")
text(s, 70, 180, "Ten products.\nThree seconds.\nOne shopper.", 100, bold=True)
text(s, 75, 595, "A changing store.\nA different decision for every shopper.", 31, C["muted"])
rect(s, 1020, 166, 480, 556, C["card"], 32)
text(s, 1070, 200, "THE DECISION WINDOW", 21, C["green"], True)
text(s, 1062, 274, "3", 230, C["green"], True)
text(s, 1240, 402, "seconds", 35, C["muted"])
for j in range(10):
    x, y = 1070+(j%5)*76, 580+(j//5)*54
    rect(s, x, y, 61, 39, C["green"] if j < 3 else C["line"], 8)
    text(s, x+19, y+7, str(j+1), 20, C["bg"] if j<3 else C["white"], True)

s = slide("Why this model / how we trained it", "A small model. A deliberate choice.", 40,
    "We kept a linear ranker because gradient boosting did not improve our held-out results. "
    "For baseline training, each shown product becomes an example; unshown products are not labeled failures. "
    "Clicks provide more examples, while purchases receive three times the weight. We model slot position because exposure changes behavior. "
    "We reconstruct earlier shopper state and test on later requests. "
    "The final policy then combines cohort-specific refits and overrides, rather than blindly deploying the default training output.",
    "recsys/lfm_build.py: impressions(), fit(), BUY_W=3, log-slot and regularized LogisticRegression. "
    "Purchase calibration supports reports, not a guarantee for overridden final scores. R-24/E-260 documents the "
    "held-out gradient-boosting comparison. As-of metadata limitations remain in the replay reports.")
text(s, 70, 143, "A small model.\nA deliberate choice.", 78, bold=True)
card(s, 70, 390, 460, 245, "01 / examples", "Learn from exposure",
     "Shown products + feedback.\nPurchases weighted ×3.")
card(s, 550, 390, 460, 245, "02 / fitting", "Control position",
     "Regularized logistic model.\nSeparate known/new weights.")
card(s, 1030, 390, 500, 245, "03 / validation", "Test later requests",
     "Earlier training → later test.\nComplexity needs evidence.")
rect(s, 70, 690, 1460, 87, C["line"], 16)
text(s, 98, 714, "Why linear? Fast to serve, easy to inspect, retained after held-out comparisons.", 28)

s = slide("Why this adaptation / how it stays stable", "Frozen weights. Live intelligence.", 35,
    "We separated changing evidence from stable model weights. "
    "Shopper memory updates as people return, including new shoppers without historical profiles. "
    "Product quality uses organic views and purchases; recommendation purchases update user memory, not the organic rate. "
    "That separation prevents a feedback loop. Trends come from recent events versus a baseline, not yesterday's clock. "
    "This lets us adapt during the final without refitting on a handful of noisy purchases. Previous purchases still stay excluded.",
    "Final handoff and organizer same-world clarification. Fast trend detector is active; "
    "exact detection delay is not claimed. Home launch cap has exceptions for the shopper's own items.")
text(s, 70, 145, "Frozen weights.\nLive intelligence.", 79, bold=True)
card(s, 70, 395, 460, 240, "01 / shopper memory", "Use earlier visits",
     "Session evidence accumulates.\nKnown purchases stay out.")
card(s, 550, 395, 460, 240, "02 / product quality", "Keep sources separate",
     "Organic counts → quality.\nPrivate buys → user memory.")
card(s, 1030, 395, 500, 240, "03 / trends", "Compare event windows",
     "Recent activity vs baseline.\nNo timetable assumptions.")
text(s, 75, 704, "Why: adapt from live evidence; keep the final policy stable.", 31, C["green"], True)

s = slide("Method / evidence", "Measure before believing.", 40,
    "Offline screening was not enough, because logged impressions reflect what earlier policies chose to show. "
    "For live checks, we compared against the reference in the same windows, so a better hour would not look like a better model. "
    "Across eight practice blocks, refitted weights showed a zero-point-seventeen percentage-point improvement, with ten thousand eight hundred requests per policy. "
    "These were time blocks, not randomized A/B. "
    "We also rejected ideas and wrote counterexamples when passing tests missed real query behavior.",
    "presentation/cifras.md from javi/jury-final, section 5: 15 Nov 02:20–04:20 UTC; "
    "8 × 2,700 requests, 4 blocks/policy. Mean team-minus-reference: +0.212 vs +0.044 pp; delta +0.167 pp. "
    "Deployment log assigns policies. Handoff z≈3.0 and alternate documented z=3.5 are not repeated on-slide.")
text(s, 70, 145, "Measure before\nbelieving.", 79, bold=True)
text(s, 870, 155, "+0.17", 140, C["green"], True)
text(s, 880, 327, "percentage points", 34)
text(s, 880, 382, "Observed after refitting the weights", 24, C["muted"])
for j, (title, body) in enumerate([
    ("Temporal offline", "Screen hypotheses without future information."),
    ("Matched windows", "Compare against the reference at the same time."),
    ("Counterexamples", "A green test is only as good as its assumptions.")]):
    text(s, 78, 430+j*91, f"0{j+1}", 25, C["green"], True)
    text(s, 140, 425+j*91, title, 29, bold=True)
    text(s, 140, 463+j*91, body, 22, C["muted"])
for j, control in enumerate([True, False, True, False, False, True, False, True]):
    rect(s, 880+j*74, 493, 58, 92, C["orange"] if control else C["green"], 10)
    text(s, 898+j*74, 523, "A" if control else "B", 26, C["bg"], True)
text(s, 880, 616, "8 blocks · 10,800 requests per policy", 26, bold=True)
text(s, 75, 762, "PRACTICE / 15 NOV 03:20–05:20 CET · TIME BLOCKS, NOT RANDOMIZED A/B", 19, C["muted"])

s = slide("Why it is fast / how RawTree supports it", "Precompute. Validate. Batch.", 25,
    "To protect the deadline, SQL aggregation runs in the background and local scoring stays small. "
    "We validate products before batched writes, with one writer and durable request claims. "
    "That design served ninety-nine-point-nine-six percent on time across forty-three thousand two hundred practice requests. "
    "RawTree snapshots and feedback let us trace a decision from input to outcome.",
    "presentation/cifras.md, sections 3 and 10: 15 Nov 03:00–07:00 UTC / 04:00–08:00 CET, "
    "43,182/43,200 on time; p50 1.22 s, p95 1.91 s, p99 2.35 s. "
    "144 scratch snapshots recorded. Handoff's p99≈2.0 s has no comparable window; use documented 2.35 s.")
text(s, 70, 145, "Precompute.\nValidate. Batch.", 79, bold=True)
text(s, 75, 397, "99.96%", 126, C["green"], True)
text(s, 82, 550, "valid and on time · 43,200 requests", 29)
text(s, 83, 602, "p99  2.35 s     /     deadline  3 s", 28, C["muted"])
rect(s, 890, 164, 640, 533, C["card"], 24)
text(s, 925, 196, "RAWTREE → ONE SERVING LOOP", 23, C["green"], True)
for j, label in enumerate(["Requests + events + catalogue", "SQL → feature snapshots", "Rank → validate → batch write", "Private feedback → evaluation"]):
    text(s, 931, 278+j*80, label, 30, bold=j==2)
    if j<3:
        rect(s, 934, 328+j*80, 3, 22, C["green"])
text(s, 925, 626, "144 stored metric snapshots", 22, C["muted"])
text(s, 75, 762, "PRACTICE / 15 NOV 04:00–08:00 CET · 43,182 OF 43,200 SERVED ON TIME", 19, C["muted"])

s = slide("How we worked / AI-assisted development", "Agents accelerated. Evidence decided.", 25,
    "We used Claude and Codex to implement experiments, audit code and find failure cases in isolated branches. "
    "People controlled integration, measurements and the single live deployment. "
    "The four of us covered modeling, independent challengers, cold-start research and reliability. "
    "The lesson was to use agents to move faster, while making every claimed improvement explainable and testable. "
    "Build fast. Verify carefully.",
    "Team roster supplied by the user. Claude/Codex use is confirmed at team level; no unconfirmed per-person "
    "tool or workstream assignment is asserted. Examples of agent work are in tasks and branch histories. "
    "Practice conversion 2.159% remains in EVIDENCE.md, not presented as a final result.")
text(s, 70, 149, "Agents accelerated.\nEvidence decided.", 79, bold=True)
card(s, 70, 395, 710, 235, "Development tool", "Claude",
     "Implementation, integrations\nand experiments.")
card(s, 800, 395, 730, 235, "Development tool", "Codex",
     "Audits, evaluation\nand failure cases.")
text(s, 75, 690, "Hypothesis → isolated code → tests → measured decision", 33, C["green"], True)
text(s, 75, 754, "Salvador Coll · Héctor Verdeal · Daniel Nieto · Javier Andrés García", 24)
text(s, 75, 796, "Build fast. Verify carefully.", 27, bold=True)

def svg(s):
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(s["title"])}">']
    for sh in s["shapes"]:
        x,y,w,h = [sh[k] for k in ("x","y","w","h")]
        color="#"+sh["color"]
        if sh["kind"]=="rect":
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{sh["radius"]}" fill="{color}"/>')
        else:
            size=sh["size"]
            out.append(f'<text fill="{color}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{700 if sh["bold"] else 400}">')
            for j,line in enumerate(sh["lines"]):
                out.append(f'<tspan x="{x}" y="{y+size*.94+j*size*1.19}">{escape(line)}</tspan>')
            out.append("</text>")
    return "".join(out)+"</svg>"

A="http://schemas.openxmlformats.org/drawingml/2006/main"
P="http://schemas.openxmlformats.org/presentationml/2006/main"
R="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG="http://schemas.openxmlformats.org/package/2006/relationships"
DECL='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
GROUP='<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
CLR='<p:clrMap accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2" folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/>'

def rels(items):
    return DECL+f'<Relationships xmlns="{PKG}">'+''.join(f'<Relationship Id="{i}" Type="{R}/{typ}" Target="{target}"/>' for i,typ,target in items)+'</Relationships>'

def paragraphs(lines,size=24,color="F5F7FA",bold=False):
    return "".join(f'<a:p><a:pPr marL="0" indent="0"/><a:r><a:rPr lang="en-US" sz="{int(size*60)}" b="{int(bold)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="Arial"/></a:rPr><a:t xml:space="preserve">{escape(line)}</a:t></a:r><a:endParaRPr lang="en-US" sz="{int(size*60)}"/></a:p>' for line in lines)

def shape_xml(sh,i):
    x,y,w,h=[int(sh[k]*EMU) for k in ("x","y","w","h")]
    text_kind=sh["kind"]=="text"
    geom="roundRect" if sh.get("radius") else "rect"
    fill='<a:noFill/>' if text_kind else f'<a:solidFill><a:srgbClr val="{sh["color"]}"/></a:solidFill>'
    geomval='<a:avLst><a:gd name="adj" fmla="val 7000"/></a:avLst>' if sh.get("radius") else '<a:avLst/>'
    result=f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Shape {i}"/><p:cNvSpPr'+(' txBox="1"' if text_kind else '')+'/>'+'<p:nvPr/></p:nvSpPr>'
    result+=f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="{geom}">{geomval}</a:prstGeom>{fill}<a:ln><a:noFill/></a:ln></p:spPr>'
    if text_kind:
        result+='<p:txBody><a:bodyPr wrap="none" lIns="0" rIns="0" tIns="0" bIns="0" anchor="t"/><a:lstStyle/>'+paragraphs(sh["lines"],sh["size"],sh["color"],sh["bold"])+'</p:txBody>'
    return result+'</p:sp>'

def build_pptx():
    parts={}
    def put(name,txt):parts[name]=txt
    put("_rels/.rels",rels([("rId1","officeDocument","ppt/presentation.xml")]))
    p_rel=[("rId1","slideMaster","slideMasters/slideMaster1.xml")]
    for i in range(1,len(slides)+1):p_rel.append((f"rId{i+1}","slide",f"slides/slide{i}.xml"))
    p_rel.append(("rId100","notesMaster","notesMasters/notesMaster1.xml"))
    put("ppt/_rels/presentation.xml.rels",rels(p_rel))
    put("ppt/presentation.xml",DECL+f'<p:presentation xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:notesMasterIdLst><p:notesMasterId r:id="rId100"/></p:notesMasterIdLst><p:sldIdLst>'+''.join(f'<p:sldId id="{255+i}" r:id="rId{i+1}"/>' for i in range(1,len(slides)+1))+f'</p:sldIdLst><p:sldSz cx="{W*EMU}" cy="{H*EMU}" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle/></p:presentation>')
    put("ppt/slideMasters/slideMaster1.xml",DECL+f'<p:sldMaster xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>{GROUP}</p:spTree></p:cSld>{CLR}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
    put("ppt/slideMasters/_rels/slideMaster1.xml.rels",rels([("rId1","slideLayout","../slideLayouts/slideLayout1.xml"),("rId2","theme","../theme/theme1.xml")]))
    put("ppt/slideLayouts/slideLayout1.xml",DECL+f'<p:sldLayout xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{GROUP}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    put("ppt/slideLayouts/_rels/slideLayout1.xml.rels",rels([("rId1","slideMaster","../slideMasters/slideMaster1.xml")]))
    colors={"dk1":"101A29","lt1":"F5F7FA","dk2":"192638","lt2":"A6B5C8","accent1":"61E4B1","accent2":"FFAC86","accent3":"A6B5C8","accent4":"304154","accent5":"5088A8","accent6":"D6DDF5","hlink":"61E4B1","folHlink":"FFAC86"}
    scheme=''.join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k,v in colors.items())
    fill='<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    put("ppt/theme/theme1.xml",DECL+f'<a:theme xmlns:a="{A}" name="Team 26"><a:themeElements><a:clrScheme name="Team 26">{scheme}</a:clrScheme><a:fontScheme name="Arial"><a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Team 26"><a:fillStyleLst>{fill*3}</a:fillStyleLst><a:lnStyleLst>'+''.join(f'<a:ln w="{w}">{fill}<a:prstDash val="solid"/></a:ln>' for w in [9525,19050,28575])+f'</a:lnStyleLst><a:effectStyleLst>{("<a:effectStyle><a:effectLst/></a:effectStyle>")*3}</a:effectStyleLst><a:bgFillStyleLst>{fill*3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
    put("ppt/notesMasters/notesMaster1.xml",DECL+f'<p:notesMaster xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>{GROUP}</p:spTree></p:cSld>{CLR}<p:notesStyle/></p:notesMaster>')
    put("ppt/notesMasters/_rels/notesMaster1.xml.rels",rels([("rId1","theme","../theme/theme1.xml")]))
    for i,s in enumerate(slides,1):
        shapes=''.join(shape_xml(sh,k+2) for k,sh in enumerate(s["shapes"]))
        put(f"ppt/slides/slide{i}.xml",DECL+f'<p:sld xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld name="{escape(s["title"])}"><p:spTree>{GROUP}{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
        put(f"ppt/slides/_rels/slide{i}.xml.rels",rels([("rId1","slideLayout","../slideLayouts/slideLayout1.xml"),("rId2","notesSlide",f"../notesSlides/notesSlide{i}.xml")]))
        ntext=f'{s["seconds"]} seconds. '+s["notes"]+"\nSOURCE / LIMIT: "+s["source"]
        note=f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr txBox="1"/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paragraphs(ntext.splitlines(),18)}</p:txBody></p:sp>'
        put(f"ppt/notesSlides/notesSlide{i}.xml",DECL+f'<p:notes xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>{GROUP}{note}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')
        put(f"ppt/notesSlides/_rels/notesSlide{i}.xml.rels",rels([("rId1","notesMaster","../notesMasters/notesMaster1.xml"),("rId2","slide",f"../slides/slide{i}.xml")]))
    overrides=[]
    for path in parts:
        if path.endswith(".rels"):continue
        if path=="ppt/presentation.xml":typ="presentation.main"
        elif "/slideMasters/" in path:typ="slideMaster"
        elif "/slideLayouts/" in path:typ="slideLayout"
        elif "/notesMasters/" in path:typ="notesMaster"
        elif "/notesSlides/" in path:typ="notesSlide"
        elif "/theme/" in path:
            overrides.append(f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>');continue
        else:typ="slide"
        overrides.append(f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.presentationml.{typ}+xml"/>')
    parts["[Content_Types].xml"]=DECL+'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'+''.join(overrides)+'</Types>'
    with ZipFile(HERE/"Team26_3min.pptx","w",ZIP_DEFLATED) as z:
        for p,t in parts.items():z.writestr(p,t.encode("utf8"))

def build_html():
    sections=''.join(f'<section class="slide" aria-label="Slide {i+1}">{svg(s)}</section>' for i,s in enumerate(slides))
    data=json.dumps([dict(notes=s["notes"],seconds=s["seconds"]) for s in slides]).replace("</","<\\/")
    html="""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Team 26 — Three-minute pitch</title><style>
*{box-sizing:border-box}body{margin:0;background:#101a29;color:#f5f7fa;font-family:Arial,sans-serif}
#stage{height:100vh;display:grid;place-items:center}.slide{display:none;width:min(100vw,177.7778vh);height:min(56.25vw,100vh)}.slide.active{display:block}svg{display:block;width:100%;height:100%}
nav{position:fixed;bottom:14px;right:22px;display:flex;gap:7px;align-items:center;background:#101a29d9;padding:8px;border-radius:12px}
button{background:#26374a;border:0;border-radius:7px;color:white;padding:8px 12px;cursor:pointer}button:hover{background:#38516c}
#clock{min-width:125px;font-variant-numeric:tabular-nums;font-size:13px;color:#a6b5c8}
aside{display:none;position:fixed;right:24px;top:24px;max-width:420px;padding:24px;background:#101a29f5;border:1px solid #61e4b1;border-radius:14px;font-size:18px;line-height:1.55}aside.open{display:block}
@page{size:13.333333in 7.5in;margin:0}@media print{html,body,#stage{width:13.333333in;height:auto}#stage{display:block}.slide,.slide.active{display:block;width:13.333333in;height:7.5in;break-after:page;page-break-after:always}.slide:last-child{break-after:auto;page-break-after:auto}nav,aside{display:none!important}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style><main id="stage">__PITCH_SECTIONS__</main><aside id="notes"></aside>
<nav><span id="clock">00:00 / 03:00</span><button id="prev" title="Left arrow">←</button><button id="next" title="Right arrow / space">→</button><button id="nt" title="N">Notes</button><button id="fs" title="F">Fullscreen</button><button id="rs" title="R">Reset timer</button></nav>
<script>const data=__PITCH_DATA__;let idx=+(new URLSearchParams(location.search).get('s')||0),start=null;const pages=[...document.querySelectorAll('.slide')],note=document.getElementById('notes');
function show(i){idx=Math.max(0,Math.min(pages.length-1,i));pages.forEach((p,k)=>p.classList.toggle('active',k===idx));note.textContent=data[idx].seconds+' sec — '+data[idx].notes;document.title='Team 26 — '+(idx+1)+'/6';}
function next(){if(start===null)start=performance.now();show(idx+1)}function toggleNotes(){note.classList.toggle('open')}function full(){if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen()}
document.getElementById('prev').onclick=()=>show(idx-1);document.getElementById('next').onclick=next;document.getElementById('nt').onclick=toggleNotes;document.getElementById('fs').onclick=full;document.getElementById('rs').onclick=()=>start=performance.now();
document.addEventListener('keydown',e=>{if(['ArrowRight',' ','PageDown'].includes(e.key)){e.preventDefault();next()}if(['ArrowLeft','PageUp'].includes(e.key))show(idx-1);if(e.key.toLowerCase()==='n')toggleNotes();if(e.key.toLowerCase()==='f')full();if(e.key.toLowerCase()==='r')start=performance.now();if(e.key==='Home')show(0);if(e.key==='End')show(pages.length-1)});
if(new URLSearchParams(location.search).has('clean'))document.querySelector('nav').style.display='none';
setInterval(()=>{const n=start===null?0:Math.floor((performance.now()-start)/1000);document.getElementById('clock').textContent=String(Math.floor(n/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0')+' / 03:00';},250);show(idx);
</script></html>""".replace("__PITCH_SECTIONS__",sections).replace("__PITCH_DATA__",data)
    (HERE/"pitch.html").write_text(html,encoding="utf8")

def build_notes():
    out=["# Team 26 — three-minute pitch", "",
         "English. Six slides. Timings are rehearsal targets, not a promise of reading speed.",
         "Aim for roughly 130–140 words per minute and rehearse with pauses. Slide sources are in the PowerPoint notes and EVIDENCE.md.", ""]
    elapsed=0
    for i,s in enumerate(slides,1):
        end=elapsed+s["seconds"]
        fmt=lambda n:f"{n//60}:{n%60:02d}"
        out += [f'## {i}. {s["title"]} — {fmt(elapsed)}–{fmt(end)}', "", s["notes"], ""]
        elapsed=end
    words=sum(len(s["notes"].split()) for s in slides)
    out += ["## Delivery", "", f"Script: {words} words. Total slide budget: {elapsed} seconds.",
            "Start the browser timer with R before speaking. Right arrow/space advances; N toggles notes; F enters fullscreen.",
            "The initial pitch explains HOW and WHY. Team names are credited briefly; no unconfirmed individual roles are assigned.",
            "For questions, HOW_AND_WHY.md provides a code walkthrough. The 2.159% practice aggregate in EVIDENCE.md is not a final result.",
            "Keep the caveat that the +0.17 pp comparison used time blocks, not randomized contemporaneous A/B.", ""]
    (HERE/"SCRIPT.md").write_text("\n".join(out),encoding="utf8")
    (HERE/"slides.json").write_text(json.dumps(slides,indent=2),encoding="utf8")
    for i,s in enumerate(slides,1):(HERE/f"slide_{i:02d}.svg").write_text(svg(s),encoding="utf8")
    print(json.dumps(dict(slides=len(slides),seconds=elapsed,script_words=words,pptx=str(HERE/"Team26_3min.pptx"))))

if __name__=="__main__":
    build_pptx();build_html();build_notes()
