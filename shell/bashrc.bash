# Auralyn Bash integration. Only loaded by Auralyn, never written to ~/.bashrc.
# The user's normal interactive environment is loaded first.
# Ubuntu/Debian Bash already loads /etc/bash.bashrc for interactive shells.
[[ -r ~/.bashrc ]] && source ~/.bashrc

[[ $- == *i* && -p ${AURALYN_EVENT_FIFO-} && -d ${AURALYN_SESSION_DIR-} ]] || return 0
exec {__auralyn_fd}>"$AURALYN_EVENT_FIFO" || return 0
# Do not export the IPC paths to programs launched from this shell.
__auralyn_dir=$AURALYN_SESSION_DIR
unset AURALYN_EVENT_FIFO AURALYN_SESSION_DIR

source "${BASH_SOURCE[0]%/*}/programs.bash"
source "${BASH_SOURCE[0]%/*}/faceman.bash"

__auralyn_prompt() {
    local __status=$?
    local __names
    __names=$(compgen -A builtin -A alias -A function)
    printf 'P\0%s\0%s\0%s\0%s\0%s\0' \
        "$$" "$PWD" "$PATH" "$__names" "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}" >&"$__auralyn_fd" 2>/dev/null || :
    return "$__status"
}

# Readline exposes character positions in the active locale. The IPC protocol
# uses UTF-8 byte offsets. Helpers use dynamically scoped result variables and
# restore LC_ALL on return; no process is spawned per keystroke.
__auralyn_byte_count() {
    local LC_ALL=C
    __auralyn_byte_length=${#1}
}
__auralyn_byte_prefix() {
    local LC_ALL=C
    __auralyn_prefix_result=${1:0:$2}
}

__auralyn_snapshot() {
    local __status=$?
    local __auralyn_byte_length
    __auralyn_byte_count "${READLINE_LINE:0:READLINE_POINT}"
    if (( ${#READLINE_LINE} <= 32768 )); then
        printf 'S\0%s\0%s\0%s\0%s\0' \
            "$__auralyn_byte_length" "$PWD" "$PATH" "$READLINE_LINE" >&"$__auralyn_fd" 2>/dev/null || :
    fi
    return "$__status"
}

__auralyn_apply() {
    local __status=$?
    local __old __point __new __newpoint __file
    local __auralyn_byte_length __auralyn_prefix_result
    __file=$__auralyn_dir/replacement
    [[ -f $__file && ! -L $__file && -O $__file ]] || return "$__status"
    {
        IFS= read -r -d '' __old &&
        IFS= read -r -d '' __point &&
        IFS= read -r -d '' __new &&
        IFS= read -r -d '' __newpoint
    } < "$__file" || return "$__status"
    # Stale suggestions must never overwrite newly typed text.
    __auralyn_byte_count "${READLINE_LINE:0:READLINE_POINT}"
    if [[ $READLINE_LINE == "$__old" && $__auralyn_byte_length == "$__point" && $__newpoint =~ ^[0-9]+$ ]]; then
        __auralyn_byte_prefix "$__new" "$__newpoint"
        READLINE_LINE=$__new
        READLINE_POINT=${#__auralyn_prefix_result}
    fi
    command rm -f -- "$__file"
    __auralyn_snapshot
    return "$__status"
}

# Reserve two otherwise unused Readline sequences. Normal keys and .inputrc
# are not remapped. Bindings only execute in Readline, never inside sudo/nano.
for __auralyn_map in emacs-standard vi-insert vi-command; do
    bind -m "$__auralyn_map" -x '"\e[989;1~":__auralyn_snapshot' 2>/dev/null
    bind -m "$__auralyn_map" -x '"\e[989;2~":__auralyn_apply' 2>/dev/null
done
unset __auralyn_map

# Preserve string AND array PROMPT_COMMAND configurations and their status.
if [[ $(declare -p PROMPT_COMMAND 2>/dev/null) == 'declare -a '* ]]; then
    PROMPT_COMMAND=(__auralyn_prompt "${PROMPT_COMMAND[@]}")
else
    PROMPT_COMMAND=(__auralyn_prompt "${PROMPT_COMMAND-}")
fi
# PS0 is expanded immediately before executing a command. This invalidates
# suggestions even when a Readline macro, instead of Enter, executes a line.
PS0='$(printf "B\0" >&"$__auralyn_fd" 2>/dev/null)'"${PS0-}"
