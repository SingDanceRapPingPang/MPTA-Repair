#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/mnt/d/study/graduation_project/project/MPTA-Repair/TarTar-master}"
UPPAAL_ZIP="${2:-}"

cd "$ROOT"

sudo apt-get update
sudo apt-get install -y \
  openjdk-11-jdk \
  maven \
  z3 \
  libz3-dev \
  libz3-java \
  bc \
  g++ \
  libboost-all-dev \
  swig \
  graphviz \
  graphviz-dev \
  unzip \
  python3-ply \
  python3-pygraphviz

chmod +x opaal/createTS.sh opaal/bin/opaal_ltsmin || true

if [[ -n "$UPPAAL_ZIP" ]]; then
  rm -rf uppaal-4.1.23
  mkdir -p uppaal-4.1.23
  unzip -q "$UPPAAL_ZIP" -d uppaal-4.1.23
  inner="$(find uppaal-4.1.23 -type f -path '*/bin-Linux/verifyta' -printf '%h\n' | head -n 1 || true)"
  expected="$ROOT/uppaal-4.1.23/bin-Linux"
  if [[ -n "$inner" && "$(realpath "$inner")" != "$(realpath -m "$expected")" ]]; then
    parent="$(dirname "$inner")"
    tmp="uppaal-4.1.23.__tmp__"
    rm -rf "$tmp"
    mv "$parent"/* "$tmp"
    rm -rf uppaal-4.1.23
    mv "$tmp" uppaal-4.1.23
  fi
  chmod +x uppaal-4.1.23/bin-Linux/verifyta
fi

export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH="$JAVA_HOME/bin:$ROOT/ltsmin-3.0.2/src/pins2lts-mc:$ROOT/opaal/bin:$PATH"
export PYTHONPATH="$ROOT/opaal:$ROOT/pyuppaal:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/lib:/usr/lib:/usr/local/lib:${LD_LIBRARY_PATH:-}"

echo "Java:"
java -version 2>&1 | head -n 3
echo "Maven:"
mvn -version | head -n 4
echo "Z3:"
z3 -version

if [[ -x "$ROOT/uppaal-4.1.23/bin-Linux/verifyta" ]]; then
  echo "UPPAAL:"
  "$ROOT/uppaal-4.1.23/bin-Linux/verifyta" -v | head -n 3
else
  echo "UPPAAL 4.1.x verifyta is still missing."
  echo "Expected: $ROOT/uppaal-4.1.23/bin-Linux/verifyta"
  echo "Pass a downloaded UPPAAL 4.1.x Linux zip as the second argument to install it."
  exit 2
fi

echo "Original TarTar WSL dependencies look ready."
