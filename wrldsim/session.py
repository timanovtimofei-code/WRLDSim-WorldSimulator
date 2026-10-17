from dataclasses import dataclass


@dataclass
class GameSession:
    mode_id: str
    difficulty_id: str | None
    country_id: str | None = None
    hero: dict | None = None
    game: object = None
    era_id: str = "modern"
    polity_id: str | None = None
    start_idx: int = 0

    def fresh(self):
        return GameSession(self.mode_id, self.difficulty_id, era_id=self.era_id)
