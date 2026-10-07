#!/usr/bin/env python3
"""Usage : bandit-garde.py <bandit> <cible> <base.json> <config.ini>
SAST avec base de référence, par comptage : échoue si un couple (fichier, test) compte plus de constats
de sévérité moyenne ou élevée que dans la base. `bandit -b` seul ne voit pas un nouveau constat d'un
test déjà présent dans le même fichier. Les « # nosec » sont ignorés (--ignore-nosec : un agent ne
s'exempte pas lui-même), comme toute configuration « .bandit » posée dans la cible (refusée) : seule
compte <config.ini>, fichier protégé. Un fichier que bandit ne sait pas lire, ou une cible vide, échoue.
Base : bandit -r <cible> -f json --ignore-nosec --ini <config.ini> -o <base.json>. Limite : remplacer un constat par un
autre du même test dans le même fichier passe. Codes : 0 OK · 2 nouveaux constats ou erreur."""
import collections, json, os, subprocess, sys

def compte(resultats):
    return collections.Counter((r["filename"], r["test_id"]) for r in resultats
                               if r["issue_severity"] in ("MEDIUM", "HIGH"))

try:
    bandit, cible, base, ini = sys.argv[1:5]
    open(ini).close()
    caches = [os.path.join(d, ".bandit") for d, _, fs in os.walk(cible) if ".bandit" in fs]
    if caches:
        print(f"FAIL : configuration bandit dans la cible, refusée : {', '.join(caches)}", file=sys.stderr); sys.exit(2)
    p = subprocess.run([bandit, "-r", cible, "-f", "json", "--ignore-nosec", "--ini", ini],
                       capture_output=True, text=True)
    sortie = json.loads(p.stdout)
    actuel, ref = compte(sortie["results"]), compte(json.load(open(base))["results"])
    erreurs, lignes = sortie.get("errors", []), sortie["metrics"]["_totals"]["loc"]
except (ValueError, KeyError, TypeError, OSError) as e:
    print(f"FAIL : usage, bandit ou base de référence en erreur ({e})", file=sys.stderr); sys.exit(2)
for err in erreurs:
    print(f"FAIL : bandit n'a pas pu analyser {err.get('filename')} ({err.get('reason')})", file=sys.stderr)
if lignes == 0:
    print(f"FAIL : aucune ligne analysée dans {cible} (cible absente ou renommée ?)", file=sys.stderr)
nouveaux = {k: n - ref.get(k, 0) for k, n in actuel.items() if n > ref.get(k, 0)}
for (fichier, test), n in sorted(nouveaux.items()):
    print(f"NOUVEAU : {test} ×{n} dans {fichier}")
print(f"{sum(actuel.values())} constat(s) moyens ou élevés ; {sum(ref.values())} dans la base de référence")
sys.exit(2 if nouveaux or erreurs or lignes == 0 else 0)
