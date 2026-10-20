from string import Template

from reality_check.schemas import AskFirst

# $ask_first in prompt.md and resume-prompt.md
ASK_FIRST: dict[AskFirst, str] = {
    "when-off": (
        "When that investigation shows something seems off, such as computer use not enabled, a tester for the "
        "software's platform not installed, a browser that cannot be reached, or no realistic data, stop before the "
        "work: end your turn with a final message that says what is off and what you need. When nothing is off, do "
        "not ask; start the work."
    ),
    "always": (
        "Then stop before the work, whatever you find: end your turn with a short message of what you will check and "
        "how you will reach and see the software, with the points that need the caller's attention first."
    ),
    "never": (
        "Do not stop to ask. Note in the report anything that seems off, and go on as far as you can without it."
    ),
}

# $computer_use in prompt.md and resume-prompt.md. Each states a fact; $ask_first decides what the agent does about it.
COMPUTER_USE_ENABLED = Template("Computer use is enabled through the CLI `$command`; see the using-computer-use skill.")
NO_ACCESSIBILITY_TREE = Template(
    "This desktop gives no accessibility tree, so work from screenshots; `$command doctor` says why."
)
COMPUTER_USE_NOT_INSTALLED = Template(
    "Computer use is not installed yet. When the software needs its desktop UI driven, install it with `$install`: "
    "it asks nothing and changes nothing outside reality-check's own folder. Within a few seconds of it succeeding, "
    "computer use is enabled through the CLI `$command` (`$command status` says when it runs); see the "
    "using-computer-use skill. If the install fails, computer use is not enabled, and the install's error says why."
)
COMPUTER_USE_OFF = Template(
    "Computer use is not enabled: $reason To enable it: $remedy This matters only for software that needs its "
    "desktop UI driven."
)
COMPUTER_USE_UNSUPPORTED = Template(
    "Computer use is not enabled: $reason It cannot be enabled on this machine. This matters only for software that "
    "needs its desktop UI driven."
)

# $keep_running in prompt.md and resume-prompt.md
KEEP_RUNNING: dict[bool, str] = {
    False: (
        "Before you finish, destroy every universe you launched and stop every process you started for this check."
    ),
    True: (
        "Leave running what you start, such as universes and servers, so later checks can use it; the report lists "
        "each one with the command that stops it."
    ),
}

# $evidence in prompt.md and resume-prompt.md
EVIDENCE_DIRECTORY = Template(
    "Put every piece of evidence in `$evidence`. Your final message is saved as `$report`, so in it refer to each "
    "file by its path relative to that, such as `evidence/01-open-home.png`."
)

# $earlier_evidence in resume-prompt.md
EARLIER_EVIDENCE = Template(
    "What you recorded before this request is in `$evidence`; refer to those files relative to the new report too, "
    "such as `${relative}01-open-home.png`."
)

# $named_files in prompt.md
NAMED_FILES = Template("\nThe request names these files:\n\n$files\n")

# $previous_checks in prompt.md and resume-prompt.md
PREVIOUS_CHECKS = Template("\nEarlier checks are in these directories:\n\n$directories\n")

# $target in prompt.md, when no target is given
TARGET_FROM_REQUEST = "where the request says"

# The steering message a check sends its agent when most of its time is used.
WRAP_UP = Template(
    "This check has $left left before it is stopped. Stop testing now. Clean up as the request says, then end your "
    "turn with your report: what you checked, the verdict for each, and what you did not get to."
)
