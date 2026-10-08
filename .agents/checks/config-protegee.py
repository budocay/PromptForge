#!/usr/bin/env python3
"""Usage : config-protegee.py <avant> <apres> <fichier> [<avant2> <base>]
Configuration des contrôles logée dans un fichier mixte, donc partagé (pyproject.toml [tool.ruff],
package.json scripts.test…) : échoue si une clé protégée de <fichier> diffère entre les révisions <avant>
et <apres> (« : » = contenu indexé). Merge (<avant2> : second parent, <base> : base(s) de fusion, séparées par des virgules) : la valeur
est celle qu'une fusion à trois points donnerait (le côté qui a changé l'emporte) ; si les deux côtés l'ont
changée différemment, seul le dev fusionne. Clés : variable CONFIG_PROTEGEE, « nom_de_fichier:clé.pointée »
séparés par des espaces (.cfg, .ini : nom de section) ; « scripts.X » protège aussi « scripts.preX » et
« scripts.postX ». Codes : 0 · 2 (clé modifiée, fichier illisible ou usage). Python >= 3.11."""
import configparser, json, os, subprocess, sys
try:
    import tomllib
except ImportError:
    print("FAIL : config-protegee.py demande Python >= 3.11 (tomllib)", file=sys.stderr); sys.exit(2)

VIDE = object()

def lire(rev, chemin):
    spec = f":{chemin}" if rev == ":" else f"{rev}:{chemin}"
    r = subprocess.run(["git", "show", spec], capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else None

def analyser(txt, chemin):
    if txt is None: return {}
    if chemin.endswith(".toml"): return tomllib.loads(txt)
    if chemin.endswith(".json"): return json.loads(txt)
    c = configparser.ConfigParser(interpolation=None); c.read_string(txt)
    return {s: dict(c[s]) for s in c.sections()}

def valeur(d, cle, ini):
    if ini: return d.get(cle, VIDE)
    for morceau in cle.split("."):
        if not isinstance(d, dict) or morceau not in d: return VIDE
        d = d[morceau]
    return d

def main():
    if len(sys.argv) not in (4, 6): print(__doc__, file=sys.stderr); return 2
    avant, apres, chemin = sys.argv[1:4]; avant2, base = (sys.argv[4:6] if len(sys.argv) == 6 else (None, None))
    nom = os.path.basename(chemin); ini = nom.endswith((".cfg", ".ini"))
    cles = [s.split(":", 1)[1] for s in os.environ.get("CONFIG_PROTEGEE", "").split()
            if ":" in s and s.split(":", 1)[0] == nom]
    for c in list(cles):                                   # npm lance aussi pretest et posttest
        if c.startswith("scripts.") and "." not in c[8:]: cles += ["scripts.pre" + c[8:], "scripts.post" + c[8:]]
    if not cles: return 0
    try:
        nouveau = analyser(lire(apres, chemin), chemin)
    except Exception as e:
        print(f"PROTEGE : {chemin} illisible ({e}) : configuration protégée invérifiable", file=sys.stderr); return 2
    def version(rev):
        try: return analyser(lire(rev, chemin), chemin)
        except Exception: return {}
    p1 = version(avant); p2 = version(avant2) if avant2 else None
    bases = [version(x) for x in base.split(",")] if avant2 else []
    rc = 0
    for cle in cles:
        v, v1 = valeur(nouveau, cle, ini), valeur(p1, cle, ini)
        if p2 is None: attendu = v1
        else:
            v2 = valeur(p2, cle, ini); vbs = [valeur(x, cle, ini) for x in bases]
            vb = vbs[0] if all(x == vbs[0] for x in vbs) else None   # bases en désaccord : au dev
            if vb is None: attendu = None
            elif v1 == vb: attendu = v2
            elif v2 == vb or v1 == v2: attendu = v1
            else: attendu = None                       # changée des deux côtés : au dev de trancher
        if attendu is None or v != attendu:
            print(f"PROTEGE : {chemin} : « {cle} » modifiée (configuration d'un contrôle : Agent: dev seulement)",
                  file=sys.stderr); rc = 2
    return rc

if __name__ == "__main__":
    sys.exit(main())
