#!/usr/bin/env python3
"""Usage : deps-nouvelles.py <base>
Dépendances directes AJOUTÉES depuis <base> (commit ou arbre) : chacune doit exister sur son registre et
avoir au moins DEPS_AGE_MIN_JOURS jours (anti-slopsquatting, §3.4). Gérés : package.json (npm),
pyproject.toml (PEP 621, Poetry, uv) et requirements*.txt (PyPI), pubspec.yaml (pub.dev), Cargo.toml (crates.io).
Échec fermé : un autre manifeste modifié (go.mod, Gemfile, pom.xml…) ou un registre privé => UNVERIFIED,
sauf si le dev a approuvé ce contenu exact : DEPS_APPROUVEES="go.mod=<12 premiers caractères du sha256>".
Codes : 0 OK · 2 FAIL · 4 UNVERIFIED. Python >= 3.11, bibliothèque standard seule."""
import hashlib, json, os, re, subprocess, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
try:
    import tomllib
except ImportError:
    print("UNVERIFIED : Python >= 3.11 requis (tomllib)", file=sys.stderr); sys.exit(4)

NON_GERES = {"go.mod", "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts", "Package.swift",
             "Podfile", "Pipfile", "setup.py", "setup.cfg", "environment.yml", "packages.config", "mix.exs", "deno.json"}

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, errors="replace")

def lire(rev, chemin):
    """Contenu de chemin à la révision rev, ou dans l'arbre de travail si rev est None."""
    if rev is None:
        return open(chemin, encoding="utf-8", errors="replace").read() if os.path.exists(chemin) else None
    r = git("show", f"{rev}:{chemin}")
    return r.stdout if r.returncode == 0 else None

def npm_deps(txt):
    if not txt: return set()
    d = json.loads(txt)
    return {n for k in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
            for n in d.get(k, {}) if not str(d[k][n]).startswith(("workspace:", "file:", "link:"))}

def nom_pep508(req):
    return re.split(r"[\s\[<>=!~;@(]", req.strip(), maxsplit=1)[0].lower().replace("_", "-").replace(".", "-")

def py_deps(txt):
    if not txt: return set()
    d = tomllib.loads(txt); p = d.get("project", {})
    reqs = list(p.get("dependencies", []))
    for v in p.get("optional-dependencies", {}).values(): reqs += v
    for v in d.get("dependency-groups", {}).values(): reqs += [x for x in v if isinstance(x, str)]
    outil = d.get("tool", {})
    reqs += [x for x in outil.get("uv", {}).get("dev-dependencies", []) if isinstance(x, str)]
    noms = {nom_pep508(r) for r in reqs if r.strip()}
    poetry = outil.get("poetry", {})                                    # Poetry : tables nom = contrainte
    tables = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
    tables += [g.get("dependencies", {}) for g in poetry.get("group", {}).values()]
    for t in tables:
        for n, v in t.items():
            if n.lower() == "python": continue
            if isinstance(v, dict):
                if "path" in v or "git" in v or "url" in v: continue
                if "source" in v: noms.add("?" + nom_pep508(n)); continue
            noms.add(nom_pep508(n))
    return noms

def req_deps(txt):
    """requirements*.txt : une exigence PEP 508 par ligne ; options (-r, -e…), chemins et URL ignorés."""
    if not txt: return set()
    lignes = (l.split(" #")[0].strip() for l in txt.splitlines())
    return {nom_pep508(l) for l in lignes if l and not l.startswith(("#", "-", ".", "/")) and "://" not in l}

def pub_deps(txt):
    """pubspec.yaml : dependencies et dev_dependencies ; entrées sdk:, path:, git: ignorées, hosted: => '?'."""
    if not txt: return set()
    res, bloc, ind_dep, nom, hors = set(), False, None, None, ""
    for l in txt.splitlines() + ["fin:"]:
        if not l.strip() or l.lstrip().startswith("#"): continue
        ind = len(l) - len(l.lstrip(" ")); cle = l.strip().split(":")[0].strip()
        if ind == 0 or (ind_dep is not None and ind <= ind_dep):
            if nom and hors != "x": res.add(hors + nom)
            nom, hors = None, ""
        if ind == 0:
            bloc, ind_dep = cle in ("dependencies", "dev_dependencies"), None; continue
        if not bloc: continue
        if ind_dep is None: ind_dep = ind
        if ind == ind_dep: nom = cle
        elif cle in ("sdk", "path", "git"): hors = "x"
        elif cle == "hosted" and hors != "x": hors = "?"
    return res

def cargo_deps(txt):
    """Cargo.toml : [dependencies], [dev-…], [build-…], [workspace.dependencies], [target.*.…]."""
    if not txt: return set()
    d = tomllib.loads(txt); cles = ("dependencies", "dev-dependencies", "build-dependencies")
    tables = [d.get(k, {}) for k in cles] + [d.get("workspace", {}).get("dependencies", {})]
    tables += [t.get(k, {}) for t in d.get("target", {}).values() for k in cles]
    res = set()
    for t in tables:
        for n, v in t.items():
            if isinstance(v, dict):
                if "path" in v or "git" in v or v.get("workspace"): continue
                if "registry" in v: res.add("?" + n); continue
                n = v.get("package", n)
            res.add(n)
    return res

def interroger(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agent-factory deps-nouvelles"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise

def age_npm(nom):
    d = interroger("https://registry.npmjs.org/" + urllib.parse.quote(nom, safe="@"))
    return None if d is None else d.get("time", {}).get("created")

def age_pypi(nom):
    d = interroger(f"https://pypi.org/pypi/{nom}/json")
    if d is None: return None
    dates = [f["upload_time_iso_8601"] for fs in d.get("releases", {}).values() for f in fs]
    return min(dates) if dates else None

def age_pub(nom):
    d = interroger(f"https://pub.dev/api/packages/{urllib.parse.quote(nom)}")
    if d is None: return None
    dates = [v["published"] for v in d.get("versions", []) if v.get("published")]
    if not dates: raise ValueError("champ « published » absent de la réponse")   # => UNVERIFIED
    return min(dates)

def age_crates(nom):
    d = interroger(f"https://crates.io/api/v1/crates/{urllib.parse.quote(nom)}")
    return None if d is None else d.get("crate", {}).get("created_at")

ANALYSEURS = {"package.json": ("npm", npm_deps, age_npm), "pyproject.toml": ("pypi", py_deps, age_pypi),
              "pubspec.yaml": ("pub", pub_deps, age_pub), "Cargo.toml": ("crates", cargo_deps, age_crates)}

def approuve(f, txt):
    empreinte = hashlib.sha256((txt or "").encode()).hexdigest()[:12]
    return f"{f}={empreinte}" in os.environ.get("DEPS_APPROUVEES", "").split(), empreinte

def main():
    if len(sys.argv) != 2: print(__doc__, file=sys.stderr); return 2
    base = sys.argv[1]
    if git("rev-parse", "--verify", "--quiet", base + "^{tree}").returncode:
        print(f"FAIL : base introuvable : {base}", file=sys.stderr); return 2
    os.chdir(git("rev-parse", "--show-toplevel").stdout.strip())
    suivis = git("ls-files", "--cached", "--others", "--exclude-standard").stdout.splitlines()
    nouvelles, rc = [], 0
    for f in suivis:
        nomf = os.path.basename(f)
        if not (nomf in ANALYSEURS or nomf in NON_GERES or nomf.endswith(".csproj")
                or re.fullmatch(r"requirements.*\.txt", nomf)): continue
        avant, apres = lire(base, f), lire(None, f)
        if avant == apres: continue
        if re.fullmatch(r"requirements.*\.txt", nomf): reg, analyser, age = "pypi", req_deps, age_pypi
        elif nomf in ANALYSEURS: reg, analyser, age = ANALYSEURS[nomf]
        else:
            ok, emp = approuve(f, apres)
            if ok: print(f"APPROUVÉ par le dev : {f} ({emp})"); continue
            print(f"UNVERIFIED : {f} modifié, écosystème non vérifié automatiquement : vérifier à la main les "
                  f"dépendances ajoutées (existence, âge), puis DEPS_APPROUVEES=\"{f}={emp}\" (dev)", file=sys.stderr)
            rc = rc or 4; continue
        try:
            ajout = sorted(analyser(apres) - analyser(avant))
        except Exception as e:
            print(f"FAIL : {f} illisible ({e})", file=sys.stderr); rc = 2; continue
        for n in ajout:
            if n.startswith("?"):
                ok, emp = approuve(f, apres)
                if not ok:
                    print(f"UNVERIFIED : {n[1:]} ({f}) vient d'un registre privé : DEPS_APPROUVEES=\"{f}={emp}\" après "
                          "vérification (dev)", file=sys.stderr); rc = rc or 4
                continue
            nouvelles.append((reg, n, f, age))
    mini = int(os.environ.get("DEPS_AGE_MIN_JOURS", "7"))
    for reg, nom, f, age in nouvelles:
        try:
            cree = age(nom)
        except Exception as e:
            print(f"UNVERIFIED : {reg}/{nom} ({f}) : registre injoignable ({e})", file=sys.stderr); rc = rc or 4; continue
        if cree is None:
            print(f"FAIL : {reg}/{nom} ({f}) n'existe pas sur le registre (paquet halluciné ?)", file=sys.stderr); rc = 2; continue
        jours = (datetime.now(timezone.utc) - datetime.fromisoformat(cree.replace("Z", "+00:00"))).days
        if jours < mini:
            print(f"FAIL : {reg}/{nom} ({f}) publié il y a {jours} j (< {mini} j)", file=sys.stderr); rc = 2
        else:
            print(f"NOUVELLE : {reg}/{nom} ({f}), {jours} j — à justifier dans la revue")
    if rc == 0 and not nouvelles: print(f"Aucune dépendance directe ajoutée depuis {base[:12]}")
    return rc

if __name__ == "__main__":
    sys.exit(main())
