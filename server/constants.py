"""Application constants."""

# Bot behavior
RESPONSE_DELAY_SEC = 2.0
BOT_NAME = "Recall"

# Wake words (common STT variations of "recall")
WAKE_WORDS = (
    "recall", "recal", "rico", "regal", "re call", "recall,",
    "hey recall", "ok recall", "okay recall",
)

# Leave command keywords
LEAVE_KEYWORDS = ("leave", "go away", "exit", "bye", "goodbye", "go now", "depart")

# Chat commands that trigger bot removal
CHAT_REMOVE_COMMANDS = frozenset({"remove", "leave", "exit", "bye"})

# Default message sent when bot joins meeting
DEFAULT_JOIN_MESSAGE = (
    f"Hi! I'm {BOT_NAME}, your project bot. I can recall information from "
    f"previous meetings in this series. Say '{BOT_NAME}' to get my attention! "
    f"Type 'remove' in chat or say '{BOT_NAME}, please leave' if you'd like me to go."
)
