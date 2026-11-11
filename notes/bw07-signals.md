# bw07 — a session's program starts with the default signal dispositions

burrow#25: a program in a burrowd session inherits the signals burrowd was started with ignored. A shell
without job control starts a background command (`burrowd … &`) with SIGINT and SIGQUIT ignored (POSIX, the
shell command language's asynchronous lists), and an ignored disposition survives `fork` and `exec`. So
Ctrl-C and Ctrl-\ in an `ssh -t` session reach the foreground program and do nothing, and a command over ssh
cannot be ended by `kill -INT`. `src/ssession` sets SIGPIPE back to its default in both of the program's child
paths, and nothing else.

## Prediction

Written 2026-11-11 before any change, at trunk `ab34042`, from `signal(7)`'s and POSIX's rules for a
disposition across `fork` and `exec` (an ignored signal stays ignored; a caught one returns to the default),
POSIX's shell command language (an asynchronous list in a shell without job control has SIGINT and SIGQUIT
ignored), `sshd(8)`, wolf-std's `std/signal` (`reset`, `reset_one`, the twenty listenable meanings), and
burrow#25's reproducer. The pinned `sshd` is a black box; its answers below are predictions.

- **The change:** in both child paths, before the exec, every signal burrowd does not own goes back to its
  default: the twenty listenable meanings in one `signal.reset` (SIGHUP, SIGINT, SIGQUIT, SIGTERM, the
  terminal's stop signals, SIGPIPE and the rest), and SIGSEGV, SIGBUS, SIGFPE, SIGILL, SIGTRAP and SIGSYS
  one by one. SIGKILL and SIGSTOP cannot be ignored. burrowd itself keeps what it has.
- **The row**, `tools/check-server`'s `session-signals-default`, red at the rows tip and green after: both
  servers started with SIGINT and SIGQUIT ignored (a shell's `trap '' INT QUIT` and `exec`), which the row
  reads from each listener's `/proc` status first. Then, through each:
  - at a terminal of the row's own, the login shell runs `sleep 31`; Ctrl-C ends it and `$?` reads 130; it
    runs `sleep 32`; Ctrl-\ ends it and `$?` reads 131; byte for byte alike through both;
  - with no pty, a command (`exec sleep 33`) is found by its process (live, started during the turn) and sent
    SIGINT from outside; it ends, the session's status is the signal (`exit-signal INT`, the client's 255),
    alike through both, and burrowd's log line names `signal INT`.
  - Red at the rows tip through burrowd alone: the sleep ignores Ctrl-C and SIGINT, and the row's deadline
    ends the client. `sshd` gives its programs the defaults (predicted).
  - The hosted container runs with no init: the row counts only the live processes each turn started, and
    reaps what it ends where it is their parent, as `session-tty-gone` does.
- **The plant** (`bw07-plant-pipe`): the child paths reset SIGPIPE alone, as before; the row red by name.
- **Unchanged:** every other row; burrowd's own dispositions.

## Evidence

Development takes on the Linux build host's light slot (two CPUs, the pinned container), not records; their
rows and steps are `notes/bw07/takes.log` (raw logs sha256 `d723359f…` and `78895cdf…`).

- **The row's first form was wrong, and is corrected before the code** (`30f7cfb`): it asked that each
  listener hold both SIGINT and SIGQUIT ignored, and the pinned `sshd` keeps SIGINT ignored but catches
  SIGQUIT itself (its ignored mask read `0x1002`: SIGINT and SIGPIPE; burrowd's `0x1006`). The row now reads
  each server's start by what it ignores or catches. The take at the first form (`d35f6d6`, `a1abe57`)
  stopped there on both heads; it is kept in the log.
- **Red at the rows tip `30f7cfb`**, with no init in the container as on the hosted runner, by name:
  `exit -9 through burrowd, 0 through sshd; burrowd stderr '[row: timed out]'`: the sleep at the terminal
  ignored Ctrl-C through burrowd, and the row's deadline ended the client. Through `sshd`, started the same
  way, Ctrl-C and Ctrl-\ ended the sleeps ($? 130 and 131): it gives its programs the defaults, as
  predicted. The row stops at its first case, so the no-pty case was not reached at the tip.
- **Green at the head `7191002`**, with no init and with it: `ignored 0x1006 by burrowd, 0x1002 by sshd; …
  $? 130 then 131; kill -INT: exit 255`, byte for byte alike through both; the neighbouring rows
  (`session-tty-interrupt`, `-gone`, `session-sigterm`, `session-terminal-stop`, `session-own-session`)
  green.
- **Scored:** as predicted, but for the row's own first form above.
