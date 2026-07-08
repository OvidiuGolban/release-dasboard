# -*- coding: utf-8 -*-
"""
Build an interactive HTML release dashboard aggregating GitHub Releases across
several Flutter-Global repositories, grouped by component and filterable by
status (Released / Unreleased / Draft) and component.

Data source: the GitHub REST API, accessed through the `gh` CLI (`gh api`),
which uses the GH_TOKEN environment variable for authentication.

Status mapping (derived from each release object):
    draft        == true  -> "Draft"
    prerelease   == true  -> "Unreleased"   (temporary release from the Initial job)
    otherwise             -> "Released"     (promoted release from the Final job)

Output: dashboard.html in the current working directory.

The list of repositories can be provided in three ways (first match wins):
    1. DASHBOARD_REPOS env var: comma-separated repo names, e.g. "hlp,ccc,crp".
    2. A configs folder (DASHBOARD_CONFIG_FOLDER, default ./configs): every
       <tla>-config.json with "generateGithubReleaseNotes": true contributes its
       "gitProject" value (deduplicated).
    3. The DEFAULT_REPOS constant below.
"""

import os
import json
import glob
import subprocess
import datetime


OWNER = os.environ.get("DASHBOARD_OWNER", "Flutter-Global")
DEFAULT_REPOS = ["hlp", "ccc", "crp"]


def discover_repos():
    """Resolve the list of repositories to scan."""
    env_repos = os.environ.get("DASHBOARD_REPOS")
    if env_repos:
        repos = [r.strip() for r in env_repos.split(",") if r.strip()]
        if repos:
            return sorted(set(repos))

    config_folder = os.environ.get("DASHBOARD_CONFIG_FOLDER", "./configs")
    repos = set()
    for path in glob.glob(os.path.join(config_folder, "*-config.json")):
        try:
            with open(path) as fh:
                cfg = json.load(fh)
        except Exception:
            continue
        if cfg.get("generateGithubReleaseNotes") and cfg.get("gitProject"):
            repos.add(cfg["gitProject"])
    if repos:
        return sorted(repos)

    return list(DEFAULT_REPOS)


def gh_json(path):
    """Call `gh api --paginate <path>` and return the parsed JSON (list)."""
    try:
        out = subprocess.check_output(["gh", "api", "--paginate", path])
    except subprocess.CalledProcessError as exc:
        print("WARN: gh api failed for %s: %s" % (path, exc))
        return []
    out = out.strip()
    return json.loads(out) if out else []


def component_of(tag):
    """"hlpbf-1773" -> "hlpbf"; strip the trailing -<build> segment."""
    return tag.rsplit("-", 1)[0] if "-" in tag else tag


def status_of(rel):
    if rel.get("draft"):
        return "Draft"
    if rel.get("prerelease"):
        return "Unreleased"
    return "Released"


def html_escape(value):
    if value is None:
        return ""
    return (str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def collect_rows(repos):
    rows = []
    for repo in repos:
        releases = gh_json("repos/%s/%s/releases" % (OWNER, repo))
        for rel in releases:
            tag = rel.get("tag_name", "") or ""
            rows.append({
                "repo": repo,
                "component": component_of(tag),
                "tag": tag,
                "name": rel.get("name") or tag,
                "status": status_of(rel),
                "date": (rel.get("published_at") or rel.get("created_at") or "")[:10],
                "url": rel.get("html_url", ""),
            })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def render_html(rows):
    tr = []
    for r in rows:
        tr.append(
            '<tr data-status="%s" data-component="%s">'
            '<td>%s</td><td>%s</td>'
            '<td><span class="badge %s">%s</span></td>'
            '<td>%s</td><td><a href="%s" target="_blank" rel="noopener">open</a></td></tr>' % (
                html_escape(r["status"]), html_escape(r["component"]),
                html_escape(r["component"]), html_escape(r["tag"]),
                html_escape(r["status"].lower()), html_escape(r["status"]),
                html_escape(r["date"]), html_escape(r["url"])))

    components = sorted({r["component"] for r in rows})
    comp_opts = "".join(
        '<option value="%s">%s</option>' % (html_escape(c), html_escape(c)) for c in components)
    updated = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Release Dashboard</title>
<style>
 body{font-family:Arial,Helvetica,sans-serif;margin:24px;color:#24292f}
 h1{margin-bottom:4px}
 .meta{color:#57606a;margin-top:0}
 .controls{margin:16px 0}
 label{margin-right:16px;font-size:14px}
 select,input{padding:6px;font-size:14px}
 table{border-collapse:collapse;width:100%%;margin-top:12px}
 th,td{border:1px solid #d0d7de;padding:8px;text-align:left;font-size:14px}
 th{background:#f6f8fa;cursor:default}
 tbody tr:nth-child(even){background:#fafbfc}
 .badge{padding:2px 10px;border-radius:12px;color:#fff;font-size:12px;white-space:nowrap}
 .badge.released{background:#2da44e}
 .badge.unreleased{background:#bf8700}
 .badge.draft{background:#6e7781}
 .count{color:#57606a;font-size:13px;margin-left:8px}
</style>
</head>
<body>
<h1>Release Dashboard</h1>
<p class="meta">Updated: %s UTC &middot; %d releases</p>

<div class="controls">
 <label>Status:
  <select id="statusFilter">
   <option value="all">All</option>
   <option value="Released">Released</option>
   <option value="Unreleased">Unreleased</option>
   <option value="Draft">Draft</option>
  </select>
 </label>
 <label>Component:
  <select id="componentFilter"><option value="all">All</option>%s</select>
 </label>
 <label>Search:
  <input type="text" id="searchBox" placeholder="tag contains...">
 </label>
 <span class="count" id="count"></span>
</div>

<table>
 <thead><tr><th>Component</th><th>Tag</th><th>Status</th><th>Date</th><th>Link</th></tr></thead>
 <tbody id="rows">%s</tbody>
</table>

<script>
 var statusSel = document.getElementById('statusFilter');
 var compSel   = document.getElementById('componentFilter');
 var search    = document.getElementById('searchBox');
 var countEl   = document.getElementById('count');

 function applyFilters(){
   var s = statusSel.value;
   var c = compSel.value;
   var q = (search.value || '').toLowerCase();
   var shown = 0;
   document.querySelectorAll('#rows tr').forEach(function(row){
     var okS = (s === 'all' || row.dataset.status === s);
     var okC = (c === 'all' || row.dataset.component === c);
     var okQ = (q === '' || row.textContent.toLowerCase().indexOf(q) !== -1);
     var visible = okS && okC && okQ;
     row.style.display = visible ? '' : 'none';
     if (visible) shown++;
   });
   countEl.textContent = shown + ' shown';
 }

 statusSel.addEventListener('change', applyFilters);
 compSel.addEventListener('change', applyFilters);
 search.addEventListener('input', applyFilters);
 applyFilters();
</script>
</body>
</html>""" % (updated, len(rows), comp_opts, "".join(tr))


def main():
    repos = discover_repos()
    print("Scanning %d repositories under %s: %s" % (len(repos), OWNER, ", ".join(repos)))
    rows = collect_rows(repos)
    html = render_html(rows)
    with open("dashboard.html", "w") as fh:
        fh.write(html)
    print("Wrote dashboard.html with %d releases across %d repositories" % (len(rows), len(repos)))


if __name__ == "__main__":
    main()