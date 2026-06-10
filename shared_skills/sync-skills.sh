#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TOP_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)

SRC_DIR="${TOP_DIR}/shared_skills/skills"
DST_DIR="${TOP_DIR}/workspace/_shared/skills"

if [ ! -d "${SRC_DIR}" ]; then
  echo "ERROR: skills folder not found: ${SRC_DIR}" >&2
  exit 1
fi

missing=0
for d in "${SRC_DIR}"/*; do
  [ -d "${d}" ] || continue
  if [ ! -f "${d}/skill.json" ]; then
    echo "ERROR: missing skill.json: ${d}" >&2
    missing=1
  fi
done

if [ "${missing}" -ne 0 ]; then
  exit 1
fi

mkdir -p "${DST_DIR}"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${SRC_DIR}/" "${DST_DIR}/"
else
  rm -rf "${DST_DIR}"
  mkdir -p "${DST_DIR}"
  cp -a "${SRC_DIR}/." "${DST_DIR}/"
fi

echo "OK: synced skills to ${DST_DIR}"
