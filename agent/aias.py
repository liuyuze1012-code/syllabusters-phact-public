"""The AI Assessment Scale (AIAS). Level names from the revised paper; the AIAS site shortens 2 and 3 to
"AI Planning" and "AI Collaboration".: Perkins, Furze, Roe & MacVaugh (2024, revised Dec 2024, arXiv 2412.09029).

Five levels per TASK (not per course). PHACT uses it as the backbone of every assessment suggestion:
each suggestion names the level it sets, and code checks the level fits the course stance and school policy.
The revised scale shows levels as different, not better/worse, so the UI uses no traffic-light colours.
"""

LEVELS = {
    1: ("No AI", "The task is done without AI, in a setting where that can be relied on (e.g. in class, oral)."),
    2: ("AI-assisted planning", "AI may be used for brainstorming, outlining or early research; the submitted work is the student's own."),
    3: ("AI-assisted task completion", "AI may help draft and refine; students critically evaluate and modify what it produces."),
    4: ("Full AI", "AI may be used throughout; students direct it and are assessed on how well they use and judge it."),
    5: ("AI exploration", "Students use AI creatively to solve the problem or co-design new approaches."),
}

# Highest level each course stance allows. ban = AI is not used; restricted = brainstorm/edit with disclosure.
STANCE_MAX = {"ban": 1, "restricted": 3, "open": 5}


def max_level(stance: str | None) -> int:
    return STANCE_MAX.get(stance or "restricted", 3)


def label(level: int | None) -> str:
    return f"AIAS {level}: {LEVELS[level][0]}" if level in LEVELS else "AIAS level not set"
