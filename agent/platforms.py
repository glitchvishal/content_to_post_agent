"""Per-platform rules. Adding a platform = adding one entry here (plus its Literal in schemas.py)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    name: str
    max_chars: int
    style: str

    @property
    def target_chars(self) -> int:
        """Ask the writer for ~90% of the hard limit so small overshoots still fit."""
        return int(self.max_chars * 0.9)


PLATFORMS: dict[str, PlatformSpec] = {
    "linkedin": PlatformSpec(
        key="linkedin",
        name="LinkedIn",
        max_chars=1300,
        style=(
            "- Professional but human; write like a practitioner sharing a lesson, not a press release.\n"
            "- The first 1-2 lines are the hook and must work on their own before the 'see more' cut (~200 chars).\n"
            "- Short paragraphs separated by blank lines; 3-5 bullet points are fine for lists.\n"
            "- End with a clear takeaway or a genuine question to the reader.\n"
            "- At most 3 relevant hashtags, only at the very end."
        ),
    ),
    "x": PlatformSpec(
        key="x",
        name="X (Twitter)",
        max_chars=280,
        style=(
            "- One punchy, standalone post (not a thread, no '1/').\n"
            "- Lead with the single most surprising or useful point.\n"
            "- Conversational and direct; cut every filler word.\n"
            "- At most 1 hashtag, ideally none."
        ),
    ),
}

SUPPORTED_PLATFORMS: tuple[str, ...] = tuple(PLATFORMS)
