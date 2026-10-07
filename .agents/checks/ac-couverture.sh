#!/bin/bash
# Usage : ac-couverture.sh <F-id>
# Chaque critère d'acceptation « <F-id>-ACn » de specs/<F-id>.md doit être cité par au moins un test.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname "$0")/lib.sh"
fid="${1:?usage : ac-couverture.sh <F-id>}"; spec="specs/$fid.md"
[ -f "$spec" ] || echec "spec absente : $spec"
ids="$(grep -oE "$fid-AC[0-9]+" "$spec" | sort -u)"
[ -n "$ids" ] || echec "$spec ne contient aucun critère '$fid-ACn'"
pathspecs=(); set -f                                # les motifs ne doivent pas s'étendre sur le disque
for g in ${TESTS_GLOB:-**/*.test.* **/*.spec.* **/test_*.py **/*_test.py **/*_test.go **/*_test.dart **/integration_test/**}; do pathspecs+=(":(glob)$g"); done
set +f
manquants=""
for id in $ids; do
  alt="$(printf '%s' "$id" | tr '-' '_')"                  # F-012-AC1 ou F_012_AC1 (identifiants)
  git grep --untracked -q -E "($id|$alt)([^0-9]|\$)" -- "${pathspecs[@]}" || manquants="$manquants $id"
done
[ -z "$manquants" ] || echec "critères sans test :$manquants (citer l'id dans le nom du test, sous la forme F_012_AC1 si besoin, ou dans un commentaire)"
exit 0
