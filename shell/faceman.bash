# Auralyn-only playful Bash functions. Nothing is added to the user's ~/.bashrc.
# Keep output rate limited, so the terminal stays usable and Ctrl+C responds.
face() {
    while :; do
        builtin printf '%s\n' 'Faceman is here' || return $?
        command sleep 0.15 || return $?
    done
}

gondelface() { face; }
luiswiththegondelface() { face; }
