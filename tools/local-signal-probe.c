/* A row-owned foreground program, not installed. POSIX APIs only.
 * It never catches or sends a signal. The terminal's interrupt must end it.
 */
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <termios.h>
#include <unistd.h>

int main(int argc, char **argv) {
    struct sigaction disposition;
    sigset_t blocked;
    struct termios modes;
    if (argc != 2 || sigaction(SIGINT, NULL, &disposition) != 0 ||
        sigprocmask(SIG_BLOCK, NULL, &blocked) != 0 ||
        disposition.sa_handler != SIG_DFL || sigismember(&blocked, SIGINT) != 0 ||
        !isatty(STDIN_FILENO) || tcgetpgrp(STDIN_FILENO) != getpgrp() ||
        tcgetattr(STDIN_FILENO, &modes) != 0 || !(modes.c_lflag & ISIG) ||
        modes.c_cc[VINTR] != 3) {
        fputs("PROBE_BAD_START\n", stderr);
        return 90;
    }
    printf("PROBE_READY %s pid=%ld default=1 unblocked=1 foreground=1 intr=3\n",
           argv[1], (long)getpid());
    fflush(stdout);
    /* Harmless/missing input must terminate normally and fail the row, never
     * wait indefinitely for its rescue to manufacture a signal verdict. */
    struct pollfd fd = {STDIN_FILENO, POLLIN, 0};
    if (poll(&fd, 1, 3000) > 0) {
        char data[32];
        (void)read(STDIN_FILENO, data, sizeof data);
    }
    printf("PROBE_DEADLINE %s\n", argv[1]);
    return 91;
}
