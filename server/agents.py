from server.bots import Bot
from server.constants import (
    Action,
    ActionAndTarget,
    Claim,
    Square,
    Tile,
    Response,
)
from server.seat import Seat
from server.choices import (
    choose_action_or_square,
    choose_square_or_hand,
    choose_response,
    choose_exchange,
)


class Human:
    """
    Makes all choices by prompting a player through their seat, and waiting for their response.
    """

    def __init__(self, seat: Seat):
        self.seat = seat

    async def choose_action_or_square(
        self,
        possible_actions: list[Action],
        possible_squares: list[Square],
        prompt: str,
        true_action_hint: Action | None,
        targets: dict[Action, list[Square]] | None = None,
    ) -> Action | Square | ActionAndTarget:
        return await choose_action_or_square(
            possible_actions,
            possible_squares,
            prompt,
            self.seat,
            targets,
        )

    async def choose_square_or_hand(
        self,
        possible_squares: list[Square],
        possible_hand_tiles: list[Tile],
        prompt: str,
    ) -> Square | Tile:
        return await choose_square_or_hand(
            possible_squares,
            possible_hand_tiles,
            prompt,
            self.seat,
        )

    async def choose_response(
        self,
        possible_responses: list[Response | Tile],
        prompt: str,
        claim: Claim,
    ) -> Response | Tile:
        return await choose_response(
            possible_responses,
            prompt,
            self.seat,
        )

    async def choose_exchange(
        self,
        choices: list[Tile],
        prompt: str,
    ) -> Tile:
        return await choose_exchange(
            choices,
            prompt,
            self.seat,
        )


# An agent is a human player or bot that makes choices
Agent = Human | Bot
