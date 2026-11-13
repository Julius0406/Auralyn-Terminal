#!/bin/bash
# Isolated completion worker. Entered text is DATA, never eval'd or executed.
# argv: COMP_LINE, COMP_POINT, COMP_CWORD, COMP_WORDS...
# Only trusted, installed Bash completion scripts are executed, as normal user.
set +m
shopt -s progcomp
__line=$1 __point=$2 __cword=$3
shift 3
__words=("$@")
(( ${#__words[@]} )) || exit 0
__cmd=${__words[0]}
[[ $__cmd && $__cmd != -* ]] || exit 0

if [[ -r /usr/share/bash-completion/bash_completion ]]; then
    source /usr/share/bash-completion/bash_completion >/dev/null 2>&1
fi

if ! complete -p -- "$__cmd" &>/dev/null; then
    if declare -F _completion_loader >/dev/null; then
        _completion_loader "$__cmd" >/dev/null 2>&1 || :
    elif declare -F _comp_load >/dev/null; then
        _comp_load "$__cmd" >/dev/null 2>&1 || :
    fi
fi

# Also discover regular third-party completion files, without guessing --help
# commands or sourcing .bashrc a second time. Never traverse outside a directory.
__base=${__cmd##*/}
if ! complete -p -- "$__cmd" &>/dev/null && [[ $__base != . && $__base != .. ]]; then
    for __dir in "${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions" \
                 /usr/local/share/bash-completion/completions /usr/share/bash-completion/completions; do
        for __file in "$__dir/$__base" "$__dir/$__base.bash"; do
            if [[ -f $__file && -r $__file ]]; then
                source "$__file" >/dev/null 2>&1
                break 2
            fi
        done
    done
fi

COMP_LINE=$__line
COMP_POINT=$__point
COMP_WORDS=("${__words[@]}")
COMP_CWORD=$__cword
COMP_TYPE=9
COMP_KEY=9
COMPREPLY=()
__cur=${COMP_WORDS[COMP_CWORD]-}
__prev=${COMP_WORDS[COMP_CWORD-1]-}
__spec=$(complete -p -- "$__cmd" 2>/dev/null) || exit 0
# complete -p returns SHELL-GENERATED, safely quoted declarations. This eval
# decodes that declaration only, NEVER COMP_LINE or anything entered by a user.
__spec=${__spec#complete }
eval "__args=( $__spec )"
__function= __wordlist= __prefix= __suffix= __filter=
__actions=()
__nospace=0
for ((__i=0; __i<${#__args[@]}; __i++)); do
    case ${__args[__i]} in
        -F) __function=${__args[++__i]} ;;
        -W) __wordlist=${__args[++__i]} ;;
        -P) __prefix=${__args[++__i]} ;;
        -S) __suffix=${__args[++__i]} ;;
        -X) __filter=${__args[++__i]} ;;
        -A) __actions+=(-A "${__args[++__i]}") ;;
        -o) [[ ${__args[++__i]} == nospace ]] && __nospace=1 ;;
        -[abcdefgjksuv]) __actions+=("${__args[__i]}") ;;
        -C) ((++__i)) ;; # Arbitrary -C command strings are intentionally unsupported.
    esac
done

# Completion functions may call compopt. Outside Readline, provide its useful
# no-space state without errors. Other choices use the safe GUI fallback.
compopt() {
    local __arg __want=
    for __arg in "$@"; do
        [[ $__arg == -o ]] && { __want=on; continue; }
        [[ $__arg == +o ]] && { __want=off; continue; }
        if [[ $__arg == nospace ]]; then
            [[ $__want == on ]] && __nospace=1 || __nospace=0
        fi
    done
    return 0
}

if [[ $__function ]] && declare -F -- "$__function" >/dev/null; then
    "$__function" "$__cmd" "$__cur" "$__prev" >/dev/null 2>&1 || :
elif [[ $__wordlist ]]; then
    mapfile -t COMPREPLY < <(compgen -W "$__wordlist" -- "$__cur")
elif (( ${#__actions[@]} )); then
    mapfile -t COMPREPLY < <(compgen "${__actions[@]}" -- "$__cur")
fi

# NUL output preserves spaces in package names / paths. Limit output volume.
printf '%s\0' "$__nospace"
__count=0
for __item in "${COMPREPLY[@]}"; do
    [[ -n $__item ]] || continue
    if [[ $__filter ]]; then
        __pat=${__filter//&/$__cur}
        if [[ $__pat == '!'* ]]; then
            [[ $__item == ${__pat:1} ]] || continue
        else
            [[ $__item == $__pat ]] && continue
        fi
    fi
    printf '%s\0' "$__prefix$__item$__suffix"
    ((++__count >= 10000)) && break
done
exit 0
