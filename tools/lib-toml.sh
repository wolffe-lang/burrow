# Adapted from wolffe-lang/scent eb888dfc tools/lib-toml.sh (aspen 476edee3's); own code.
# lib-toml.sh — sourced; reads one value from wolf-toolchain.toml.
# toml_value <section> <key>: prints the unquoted value, or nothing.
# (boreutils' reader, as lope has it.)
toml_value() {
    awk -v s="[$1]" -v k="$2" '
        $0 == s { in_s = 1; next }
        /^\[/ { in_s = 0 }
        in_s && $1 == k {
            sub(/^[^=]*= */, "")
            gsub(/"/, "")
            print
            exit
        }
    ' "${BURROW_ROOT:-.}/wolf-toolchain.toml"
}

# host_target: the release-archive target triple for this machine.
host_target() {
    case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) echo aarch64-apple-darwin ;;
    Linux-x86_64) echo x86_64-unknown-linux-gnu ;;
    Linux-aarch64 | Linux-arm64) echo aarch64-unknown-linux-gnu ;;
    *) return 1 ;;
    esac
}
