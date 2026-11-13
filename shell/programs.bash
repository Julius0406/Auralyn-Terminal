# Auralyn-only convenience commands. Never written into the user's ~/.bashrc.
__auralyn_program_root=$(builtin cd -- "${BASH_SOURCE[0]%/*}/.." && builtin pwd -P)
__auralyn_program_helper() (
    # Do not let launched programs inherit the Readline IPC descriptor.
    if [[ ${__auralyn_fd-} =~ ^[0-9]+$ ]]; then
        exec {__auralyn_fd}>&-
    fi
    exec /usr/bin/python3 -I "$__auralyn_program_root/program_launcher.py" "$@"
)
function auralyn-run { __auralyn_program_helper run "$@"; }
function auralyn-kill { __auralyn_program_helper kill "$@"; }

# Preserve user-defined aliases/functions. The explicit auralyn-* alternatives
# remain available, and completion only activates when our marker is present.
if ! alias run &>/dev/null && ! declare -F run &>/dev/null; then
    function run { __auralyn_program_helper run "$@"; }
    function __auralyn_run_enabled { :; }
fi
if ! alias kill &>/dev/null && ! declare -F kill &>/dev/null; then
    function kill {
        case ${1-} in
            --app|--help|--list) __auralyn_program_helper kill "$@" ;;
            '' ) __auralyn_program_helper kill --help ;;
            -*|%*) builtin kill "$@" ;;
            *) if [[ $1 =~ ^[0-9]+$ ]]; then builtin kill "$@"; else __auralyn_program_helper kill "$@"; fi ;;
        esac
    }
    function __auralyn_kill_enabled { :; }
fi

# Native Readline fallback when the graphical suggestion box is switched off.
__auralyn_program_complete() {
    local action=${COMP_WORDS[0]#auralyn-} current=${COMP_WORDS[COMP_CWORD]-} first=1
    case ${COMP_WORDS[1]-} in
        --foreground|-f|--app|--) first=2 ;;
    esac
    COMPREPLY=()
    if [[ ${COMP_WORDS[0]} == kill && ${COMP_WORDS[1]-} == -- ]]; then
        return 0  # `kill --` belongs to the ordinary numeric Bash syntax.
    fi
    if (( COMP_CWORD == 1 )) && [[ $current == -* ]]; then
        if [[ $action == run ]]; then
            mapfile -t COMPREPLY < <(compgen -W '--foreground --list --help' -- "$current")
        else
            mapfile -t COMPREPLY < <(compgen -W '--app --list --help -9 -l -s' -- "$current")
        fi
    elif (( COMP_CWORD == first )); then
        mapfile -d '' -t COMPREPLY < <(__auralyn_program_helper complete "$action" "$current")
    elif [[ $action == run ]]; then
        compopt -o filenames 2>/dev/null || :
        mapfile -t COMPREPLY < <(compgen -f -- "$current")
    fi
}
complete -F __auralyn_program_complete auralyn-run auralyn-kill
if declare -F __auralyn_run_enabled >/dev/null; then complete -F __auralyn_program_complete run; fi
if declare -F __auralyn_kill_enabled >/dev/null; then complete -F __auralyn_program_complete kill; fi
