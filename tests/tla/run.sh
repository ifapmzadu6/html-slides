#!/bin/sh
# Model-check the player's playback logic (Player.tla) with TLC.
#
#   tests/tla/run.sh            check the model of the current code in three environments
#   tests/tla/run.sh before     check the model of the code before the fix (reproduces the defect that was found)
#
# Requires Java and tla2tools.jar:
#   JAVA=/path/to/java TLA_JAR=/path/to/tla2tools.jar tests/tla/run.sh
# Get tla2tools.jar from https://github.com/tlaplus/tlaplus/releases . MAXUSER sets the number of user actions explored (default 3).
set -u
CALLER_PWD="$PWD"
cd "$(dirname "$0")" || exit 1
JAVA="${JAVA:-java}"
JAR="${TLA_JAR:-tla2tools.jar}"
FIXED=TRUE
[ "${1:-}" = "before" ] && FIXED=FALSE
case "$JAR" in
  /*) ;;
  *) if [ -f "$CALLER_PWD/$JAR" ]; then JAR="$CALLER_PWD/$JAR"; else JAR="$PWD/$JAR"; fi ;;
esac
[ -f "$JAR" ] || { echo "tla2tools.jar was not found. Set TLA_JAR to its path."; exit 2; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM
status=0
# environments: with or without embedded audio / with or without an on-device voice
for env in "FALSE TRUE device-voice" "TRUE TRUE embedded-audio" "FALSE FALSE no-on-device-voice"; do
  set -- $env
  cat > "$WORK/Player.cfg" <<EOF
SPECIFICATION Spec
CONSTANTS
  Parts <- SmallDeck
  MaxUser = ${MAXUSER:-3}
  HasClips = $1
  LocalVoice = $2
  Fixed = $FIXED
INVARIANTS Consistent OneContinuation NeverStuck SpeakingTheRightSentence NoError
PROPERTIES PausedIsStable EventuallyStops
EOF
  cp Player.tla "$WORK/"
  echo "=== $3 (Fixed = $FIXED) ==="
  (cd "$WORK" && "$JAVA" -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers auto -nowarning -deadlock -difftrace Player 2>&1) > "$WORK/out.txt"
  if grep -q "Model checking completed. No error has been found" "$WORK/out.txt"; then
    grep -E "states generated|No error" "$WORK/out.txt" | tail -2
  else
    status=1
    # show the counterexample as changed variables only; skip the first state (all variables)
    awk '/^Error:/ {p=1} /^State 1:/ {skip=1} /^State 2:/ {skip=0} p && !skip' "$WORK/out.txt" | grep -vE "^(Linting|[0-9]+ states|The depth|Finished|The number|$)" | head -${LINES_MAX:-120}
  fi
done
exit $status
