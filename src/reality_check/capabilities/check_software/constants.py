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

# $named_files in prompt.md
NAMED_FILES = Template("\nThe request names these files:\n\n$files\n")

# $previous_checks in prompt.md and resume-prompt.md
PREVIOUS_CHECKS = Template("\nEarlier checks are in these directories:\n\n$directories\n")

# $target in prompt.md, when no target is given
TARGET_FROM_REQUEST = "where the request says"
