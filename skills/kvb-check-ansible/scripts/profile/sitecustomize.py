"""Profile ansible-playbook and every worker it forks with cProfile, once on PYTHONPATH.

Args:
    ANSIBLE_PROFILE_DIR: directory for main-<pid>.prof and worker-<pid>.prof;
        <TMPDIR>/ansible-profile when unset.

Output:
    Only a process whose argv[0] is named ansible-playbook is profiled. The controller
    writes its file at exit, each forked worker when it leaves through os._exit.
"""

import atexit
import cProfile
import os
import sys
import tempfile

PROGRAM = "ansible-playbook"


def profile_dir() -> str:
    # Trip-wire: TMPDIR is the one scratch directory every sandbox lets the run write to.
    return os.environ.get("ANSIBLE_PROFILE_DIR") or os.path.join(tempfile.gettempdir(), "ansible-profile")


def start(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    controller = cProfile.Profile()

    def dump_controller() -> None:
        controller.disable()
        controller.dump_stats(os.path.join(out, f"main-{os.getpid()}.prof"))

    def after_fork() -> None:
        # Trip-wire: the fork inherits the enabled controller profiler; no second one starts beside it.
        controller.disable()
        worker = cProfile.Profile()
        real_exit = os._exit

        def exit_dumping(code: int) -> None:
            worker.disable()
            worker.dump_stats(os.path.join(out, f"worker-{os.getpid()}.prof"))
            real_exit(code)

        # Trip-wire: multiprocessing workers leave through os._exit, which skips atexit.
        os._exit = exit_dumping
        worker.enable()

    atexit.register(dump_controller)
    os.register_at_fork(after_in_child=after_fork)
    controller.enable()


if os.path.basename(sys.argv[0] if sys.argv else "") == PROGRAM:
    start(profile_dir())
