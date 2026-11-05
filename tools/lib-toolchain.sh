# Adapted from wolffe-lang/scent eb888dfc tools/lib-toolchain.sh (aspen 476edee3's); own code.
# lib-toolchain.sh — sourced by every tool; not executable on its own.
#
# Resolves the pinned toolchain ($WOLF_BIN / $LUPIN_BIN, then .wolf-bin/)
# and verifies identity against wolf-toolchain.toml before anything
# runs. PATH is deliberately not consulted: a wolf on PATH is whatever
# the machine last installed, and the pin is the point.
# Callers get $WOLF, $LUPIN and an exported $WOLF_STD.
: "${BURROW_ROOT:?lib-toolchain.sh needs BURROW_ROOT}"
. "$BURROW_ROOT/tools/lib-toml.sh"

fail_pin() {
    echo "toolchain: REFUSED — $1" >&2
    echo "toolchain: run tools/fetch-toolchain to stage the pin into .wolf-bin/" >&2
    exit 1
}

WOLF=${WOLF_BIN:-$BURROW_ROOT/.wolf-bin/wolf}
LUPIN=${LUPIN_BIN:-$BURROW_ROOT/.wolf-bin/lupin}
[ -x "$WOLF" ] || fail_pin "no wolf at $WOLF"
[ -x "$LUPIN" ] || fail_pin "no lupin at $LUPIN"

want=$(toml_value wolf version_line)
have=$("$WOLF" --version 2>/dev/null | head -1)
[ "$have" = "$want" ] || fail_pin "wolf identity: have \"$have\", pin wants \"$want\""
want=$(toml_value lupin version_line)
have=$("$LUPIN" --version 2>/dev/null | head -1)
[ "$have" = "$want" ] || fail_pin "lupin identity: have \"$have\", pin wants \"$want\""
[ -f "$(dirname "$WOLF")/libwolf_rt.a" ] || fail_pin "libwolf_rt.a is not beside $WOLF"

WOLF_STD=${WOLF_STD:-$BURROW_ROOT/.wolf-bin/std}
want=$(toml_value std rev)
[ -f "$WOLF_STD/STD-REV" ] || fail_pin "no std tree at $WOLF_STD"
have=$(cat "$WOLF_STD/STD-REV")
[ "$have" = "$want" ] || fail_pin "std identity: have $have, pin wants $want"
export WOLF LUPIN WOLF_STD
