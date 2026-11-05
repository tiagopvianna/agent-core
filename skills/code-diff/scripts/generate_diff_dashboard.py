#!/usr/bin/env python3
"""Render a git diff as a standalone, annotated, side-by-side HTML dashboard.

Usage:
    python3 generate_diff_dashboard.py --diff <diff_file> --spec <spec.json> --out <out.html>

The diff file is the raw output of `git diff <base>...<head>` (unified format).
The spec JSON describes titles, an optional call-flow diagram, and per-file / per-change
annotations. See SKILL.md for the full spec shape. Any file or hunk without a matching
annotation still renders; its annotation column shows a muted "(context / imports)" note.
"""
import argparse, html, json, re, datetime

# ---- language-aware syntax highlighting -------------------------------------
# Only "go" is implemented today. Other values fall back to no keyword/function
# coloring (strings / numbers / line-comments are still colored generically).
LANGS = {
    "go": {
        "keywords": {"func","return","if","else","for","range","switch","case","default",
            "var","const","type","struct","interface","map","package","import","go","defer",
            "chan","select","break","continue","fallthrough","goto"},
        "types": {"string","int","int64","int32","bool","byte","rune","error","any",
            "float64","uint","uint64","true","false","nil"},
        "line_comment": "//",
        "raw_string": True,   # backtick raw strings
    },
}

def make_tokenizer(line_comment):
    lc = re.escape(line_comment)
    return re.compile(r"""
      (?P<raw>`[^`]*`) |
      (?P<str>"(?:\\.|[^"\\])*") |
      (?P<chr>'(?:\\.|[^'\\])*') |
      (?P<cmt>""" + lc + r"""[^\n]*) |
      (?P<num>\b\d[\d_.eExXa-fA-F]*\b) |
      (?P<id>[A-Za-z_][A-Za-z0-9_]*) |
      (?P<ws>\s+) |
      (?P<other>.)
    """, re.VERBOSE)

def highlight(code, lang):
    cfg = LANGS.get(lang)
    if not cfg:
        return html.escape(code)
    tok_re = make_tokenizer(cfg["line_comment"])
    out = []
    for m in tok_re.finditer(code):
        kind, t = m.lastgroup, m.group()
        if kind in ("raw", "str", "chr"):
            out.append(f'<span class="s">{html.escape(t)}</span>')
        elif kind == "cmt":
            out.append(f'<span class="c">{html.escape(t)}</span>')
        elif kind == "num":
            out.append(f'<span class="n">{html.escape(t)}</span>')
        elif kind == "id":
            if t in cfg["keywords"]:
                out.append(f'<span class="k">{html.escape(t)}</span>')
            elif t in cfg["types"]:
                out.append(f'<span class="t">{html.escape(t)}</span>')
            elif code[m.end():].lstrip().startswith("("):
                out.append(f'<span class="fn">{html.escape(t)}</span>')
            else:
                out.append(html.escape(t))
        else:
            out.append(html.escape(t))
    return "".join(out)

# ---- diff parsing / rendering ----------------------------------------------
def line_class(l):
    if l.startswith('+++') or l.startswith('---'): return 'meta'
    if l.startswith('@@'): return 'hunk'
    if l.startswith('+'): return 'add'
    if l.startswith('-'): return 'del'
    if l.startswith('diff --git') or l.startswith('index '): return 'meta'
    return 'ctx'

def render_line(l, lang):
    cls = line_class(l)
    if cls in ("add", "del", "ctx"):
        marker = l[:1] if l[:1] in "+- " else ""
        rest = l[len(marker):]
        body = f'<span class="mk">{html.escape(marker)}</span>{highlight(rest, lang)}' if (marker or rest) else "&nbsp;"
        return f'<span class="dl {cls}">{body}</span>'
    return f'<span class="dl {cls}">{html.escape(l) or "&nbsp;"}</span>'

def pre_for(hunk, lang):
    return '<pre class="diff">' + "".join(render_line(l, lang) for l in hunk) + '</pre>'

def parse_files(diff):
    files = []
    for b in re.split(r'(?m)^diff --git ', diff):
        if not b.strip():
            continue
        b = "diff --git " + b
        m = re.search(r'a/(\S+) b/(\S+)', b)
        path = m.group(2) if m else "unknown"
        lines = b.splitlines()
        adds = sum(1 for l in lines if l.startswith('+') and not l.startswith('+++'))
        dels = sum(1 for l in lines if l.startswith('-') and not l.startswith('---'))
        hunks, cur = [], None
        for l in lines:
            if l.startswith('@@'):
                if cur is not None: hunks.append(cur)
                cur = [l]
            elif cur is not None:
                cur.append(l)
        if cur is not None: hunks.append(cur)
        files.append({"path": path, "hunks": hunks, "adds": adds, "dels": dels})
    return files

def render_flow(flow):
    if not flow:
        return ""
    cols = []
    for col in flow.get("columns", []):
        nodes = []
        for i, n in enumerate(col.get("nodes", [])):
            variant = n.get("variant", "plain")
            cls = {"new": " new", "gate": " gate"}.get(variant, "")
            w = f'<span class="w">{html.escape(n["w"])}</span>' if n.get("w") else ""
            nodes.append(f'<div class="fnode{cls}"><span class="m">{html.escape(n["m"])}</span>{w}</div>')
            if i < len(col["nodes"]) - 1:
                nodes.append('<div class="farrow">&darr;</div>')
        cols.append(f'<div class="flowcol"><h3>{html.escape(col.get("title",""))}</h3>{"".join(nodes)}</div>')
    legend = f'<p class="legend">{flow["legend_html"]}</p>' if flow.get("legend_html") else ""
    return f'<h2>{html.escape(flow.get("title","Call flow"))}</h2><div class="flowwrap"><div class="flows">{"".join(cols)}</div>{legend}</div>'

STYLE = """
 :root{--ink:#1f2933;--muted:#616e7c;--line:#e4e7eb;--bg:#f4f7fb;--blue:#1f5c99;
   --addbg:#e8f6ee;--addln:#9fd4b3;--delbg:#fdecea;--delln:#f0b8b1;
   --hunk:#eef2f7;--codebg:#fbfcfe;--green:#1f7a4d;--amber:#9a6700;
   --k:#9333a8;--fn:#1f5c99;--s:#9a5b00;--c:#6b7a86;--n:#0f766e;--t:#0f766e;}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.5;}
 .wrap{max-width:1180px;margin:0 auto;padding:40px 24px 80px;}
 h1{font-size:25px;margin:0 0 4px;} h2{font-size:18px;color:var(--blue);margin:34px 0 12px;}
 .sub{color:var(--muted);font-size:14px;margin:0 0 20px;} .sub a{color:var(--blue);}
 code{background:#eef1f5;padding:1px 5px;border-radius:4px;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:.92em;}
 .summary{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin:0 0 10px;} .summary p{margin:8px 0;}
 .stat{display:inline-block;font-weight:600;font-size:13px;padding:2px 10px;border-radius:999px;margin-right:8px;}
 .stat.add{background:var(--addbg);color:var(--green);} .stat.del{background:var(--delbg);color:#9b2c2c;}
 .flowwrap{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 22px 24px;margin:0 0 28px;}
 .flows{display:flex;gap:26px;flex-wrap:wrap;} .flowcol{flex:1;min-width:300px;}
 .flowcol h3{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:14px 0 10px;}
 .fnode{border:1px solid #cdd9e5;background:#f7fafd;border-radius:9px;padding:9px 13px;font-size:13px;}
 .fnode .m{font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12px;font-weight:600;}
 .fnode .w{display:block;color:var(--muted);font-size:11.5px;margin-top:2px;}
 .fnode.new{background:var(--addbg);border-color:var(--addln);} .fnode.new .m{color:var(--green);}
 .fnode.gate{background:#fff7e6;border-color:#f0dca8;}
 .farrow{text-align:center;color:#9aa5b1;font-size:15px;margin:3px 0;}
 .legend{font-size:12px;color:var(--muted);margin-top:14px;} .legend b{color:var(--green);}
 .file{background:#fff;border:1px solid var(--line);border-radius:12px;margin:0 0 26px;overflow:hidden;}
 .fhead{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
 .fpath{font-family:"SF Mono",Menlo,Consolas,monospace;font-size:13px;font-weight:600;}
 .ftag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;padding:2px 8px;border-radius:6px;background:#e8f0f9;color:var(--blue);}
 .ftag.test{background:#fff3df;color:var(--amber);}
 .fcount{margin-left:auto;font-family:monospace;font-size:12px;} .fcount .a{color:var(--green);} .fcount .d{color:#9b2c2c;}
 .fpurpose{padding:11px 18px 4px;color:var(--muted);font-size:14px;}
 .hrow{display:flex;gap:16px;align-items:flex-start;padding:10px 18px 4px;border-top:1px solid #f0f2f5;}
 .hrow:first-of-type{border-top:none;}
 .hcode{flex:1 1 58%;min-width:0;} .hann{flex:0 0 38%;display:flex;flex-direction:column;gap:8px;padding-top:2px;}
 .hann .spacer{color:#b7c0cb;font-size:12px;font-style:italic;}
 .note{border-left:3px solid var(--line);padding:8px 12px;border-radius:0 8px 8px 0;background:var(--codebg);font-size:13px;}
 .note.added{border-left-color:#2f9e5e;} .note.changed{border-left-color:#d39a2a;} .note.removed{border-left-color:#c0392b;}
 .note b{font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12px;display:block;margin-top:3px;}
 .badge{font-size:10px;font-weight:700;text-transform:uppercase;padding:1px 6px;border-radius:5px;}
 .badge.added{background:var(--addbg);color:var(--green);} .badge.changed{background:#fff3df;color:var(--amber);} .badge.removed{background:var(--delbg);color:#c0392b;}
 pre.diff{margin:0;overflow-x:auto;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12px;line-height:1.5;border:1px solid var(--line);border-radius:8px;}
 .dl{display:block;padding:1px 12px;white-space:pre;}
 .dl.add{background:var(--addbg);border-left:3px solid var(--addln);}
 .dl.del{background:var(--delbg);border-left:3px solid var(--delln);}
 .dl.ctx{border-left:3px solid transparent;}
 .dl.hunk{background:var(--hunk);color:#5a6b7b;border-left:3px solid #cdd6e0;}
 .dl.meta{color:#9aa5b1;border-left:3px solid transparent;}
 .mk{color:#8a97a3;}
 .k{color:var(--k);} .fn{color:var(--fn);} .s{color:var(--s);} .c{color:var(--c);font-style:italic;} .n{color:var(--n);} .t{color:var(--t);}
 @media(max-width:820px){.hrow{flex-direction:column;} .hann{flex-basis:auto;}}
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    diff = open(args.diff).read()
    spec = json.load(open(args.spec))
    lang = spec.get("lang", "go")
    files = parse_files(diff)
    fspec = spec.get("files", {})
    total_add = sum(f["adds"] for f in files)
    total_del = sum(f["dels"] for f in files)

    p = [f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(spec.get("title","Annotated diff"))}</title>
<style>{STYLE}</style></head><body><div class="wrap">
 <h1>{spec.get("title_html") or html.escape(spec.get("title","Annotated diff"))}</h1>
 <p class="sub">{spec.get("subtitle_html","")}</p>
 <div class="summary">
   <p><span class="stat add">+{total_add}</span><span class="stat del">&minus;{total_del}</span> across {len(files)} files</p>
   <p>{spec.get("summary_html","")}</p>
 </div>
 {render_flow(spec.get("flow"))}
 <h2>Annotated diffs <span style="font-weight:400;font-size:13px;color:#616e7c">— each hunk beside the change it makes</span></h2>
"""]

    for f in files:
        meta = fspec.get(f["path"], {})
        tag = meta.get("tag", "")
        tagcls = "test" if tag == "test" else ""
        notes = meta.get("notes", [])
        p.append('<div class="file">')
        p.append(f'<div class="fhead"><span class="ftag {tagcls}">{html.escape(tag)}</span>'
                 f'<span class="fpath">{html.escape(f["path"])}</span>'
                 f'<span class="fcount"><span class="a">+{f["adds"]}</span> <span class="d">&minus;{f["dels"]}</span></span></div>')
        if meta.get("purpose"):
            p.append(f'<div class="fpurpose">{html.escape(meta["purpose"])}</div>')
        for hunk in f["hunks"]:
            htext = "\n".join(hunk)
            matched = [n for n in notes if n.get("anchor") and n["anchor"] in htext]
            matched.sort(key=lambda n: htext.index(n["anchor"]))  # follow code order
            if matched:
                ann = "".join(
                    f'<div class="note {n["kind"]}"><span class="badge {n["kind"]}">{html.escape(n["kind"])}</span>'
                    f'<b>{html.escape(n["name"])}</b>{html.escape(n["desc"])}</div>'
                    for n in matched)
            else:
                ann = '<div class="spacer">(context / imports)</div>'
            p.append(f'<div class="hrow"><div class="hcode">{pre_for(hunk, lang)}</div><div class="hann">{ann}</div></div>')
        p.append('</div>')

    p.append('</div></body></html>')
    open(args.out, "w").write("\n".join(p))
    print(args.out)

if __name__ == "__main__":
    main()
