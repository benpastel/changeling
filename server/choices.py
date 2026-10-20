from typing import cast
from contextlib import asynccontextmanager

from server.constants import (
    Tile,
    Action,
    OtherAction,
    Square,
    Response,
    OutEventType,
    ActionAndTarget,
)
from server.actions import Impact
from server.seat import Seat

# Generally incoming messages are invalid unless we've prompted for them.
# The seat keeps incoming messages in a FIFO queue, but generally all messages
# are invalid unless we've prompted for something specific.
#
# For each seat, we use an incrementing count as an ID
# All messages with other choice ids are ignored, so we can ignore messages from
# before our prompt.


async def send_prompt(prompt: str, seat: Seat, choice_id: int = 0) -> None:
    """
    Update the player's prompt.

    If we need them to make a choice, choice_id should be set to an incrementing ID
    so that we can ignore old clicks from before this prompt.

    If we don't need them to make a choice, we keep choice_id = 0.
    """
    event = {"type": OutEventType.PROMPT, "choiceId": choice_id, "prompt": prompt}
    await seat.send(event)


async def send_waiting(activity: str, seat: Seat) -> None:
    """
    Tell the player what their opponent is doing while they wait, e.g. "Choosing an
    action…"; it's shown in the opponent's strip, under their name.
    """
    event = {
        "type": OutEventType.PROMPT,
        "choiceId": 0,
        "prompt": activity,
        "waiting": True,
    }
    await seat.send(event)


async def acknowledge(event: dict, seat: Seat) -> dict:
    """
    Show the player something, e.g. how the game went, and wait for them to answer it;
    returns their answer.  `event` is sent with a choice id added.
    """
    # nothing else is asked of either player meanwhile
    await send_prompt("", seat)
    expected_choice_id = seat.next_choice_id
    seat.next_choice_id += 1
    await seat.send({**event, "choiceId": expected_choice_id})
    while True:
        answer = await seat.recv()
        if answer.get("choiceId") == expected_choice_id:
            break
    # gone, also for a reconnecting player
    await seat.send({"type": event["type"], "result": None, "choiceId": 0})
    data = answer.get("data")
    return data if isinstance(data, dict) else {}


async def _get_choice(prompt: str, seat: Seat) -> dict:
    """
    Prompts the player for a choice
    and returns the data from their response
    ignoring all other messages
    """

    # increment choice id
    # we use this to ignore old messages
    expected_choice_id = seat.next_choice_id
    seat.next_choice_id += 1
    await send_prompt(prompt, seat, expected_choice_id)

    # the queue may have accumulated stale messages since we last recieved
    # wait in a loop to throw away any stale messages
    while True:
        event = await seat.recv()
        try:
            choice_id = int(event["choiceId"])
            data = event["data"]
            assert isinstance(data, dict)
        except Exception:
            print(f"Ignored {event=}")
            continue

        if expected_choice_id == choice_id:
            return data
        else:
            print(f"Ignored {choice_id=}; {expected_choice_id=}")


async def _send_highlights(
    seat: Seat,
    squares: list[Square],
    actions: list[Action | Response],
    hand_tiles: list[Tile],
    board_tiles: list[Tile],
    targets: dict[Action, list[Square]] | None = None,
    impacts: dict[Action, dict[Square, Impact]] | None = None,
):
    event = {
        "type": OutEventType.HIGHLIGHT_CHANGE,
        "squares": squares,
        "actions": actions,
        "handTiles": hand_tiles,
        "boardTiles": board_tiles,
        # every square each action could target, for drawing the options on the board
        "targets": {
            action.value: squares for action, squares in (targets or {}).items()
        },
        # what each option would do, for drawing it while the option is hovered
        "impacts": {
            action.value: [
                {
                    "target": target,
                    "area": impact.area,
                    "killed": impact.killed,
                    "moved": impact.moved,
                }
                for target, impact in by_target.items()
            ]
            for action, by_target in (impacts or {}).items()
        },
    }
    await seat.send(event)


@asynccontextmanager
async def _highlighted(
    seat: Seat,
    squares: list[Square] = [],
    actions: list[Action | Response] = [],
    hand_tiles: list[Tile] = [],
    board_tiles: list[Tile] = [],
    targets: dict[Action, list[Square]] | None = None,
    impacts: dict[Action, dict[Square, Impact]] | None = None,
):
    """Sends a list of highlighted options to the player.  Clears highlights when done."""
    await _send_highlights(
        seat, squares, actions, hand_tiles, board_tiles, targets, impacts
    )
    try:
        yield
    finally:
        # clear highlights in UI by highlighting empty lists, also when the clock
        # runs out mid-choice
        await _send_highlights(seat, [], [], [], [])


def _parse_action(data: dict) -> Action | None:
    """The action named by a clicked button, if any."""
    for kind in (Tile, OtherAction):
        try:
            return cast(Action, kind(data["button"]))
        except (KeyError, ValueError):
            pass
    return None


async def choose_action_or_square(
    possible_actions: list[Action],
    possible_squares: list[Square],
    prompt: str,
    seat: Seat,
    targets: dict[Action, list[Square]] | None = None,
    impacts: dict[Action, dict[Square, Impact]] | None = None,
) -> Action | Square | ActionAndTarget:
    """
    If `targets` is given, the player may also pick an action and its target in one
    click, which returns them together.
    """
    async with _highlighted(
        seat,
        actions=cast(list[Action | Response], possible_actions),
        squares=possible_squares,
        targets=targets,
        impacts=impacts,
    ):
        # loop until we get a valid action or square
        while True:
            data = await _get_choice(
                prompt,
                seat,
            )
            # try parsing as an action and its target together
            if targets and "row" in data:
                action = _parse_action(data)
                square = Square(row=data.get("row", -1), col=data.get("column", -1))
                if action in targets and square in targets[action]:
                    return ActionAndTarget(action, square)

            # try parsing as a square
            square = Square(row=data.get("row", -1), col=data.get("column", -1))
            if square in possible_squares:
                return square

            # try parsing as a Tile Action
            try:
                tile = Tile(data["button"])
                if tile in possible_actions:
                    return cast(Action, tile)
            except:
                pass

            # try parsing as an Other Action
            try:
                action = OtherAction(data["button"])
                if action in possible_actions:
                    return action
            except:
                pass

            # it's not valid; get a new choice
            print(
                f"Ignoring invalid choice {data=}, {possible_actions=}, {possible_squares=}"
            )


async def choose_square_or_hand(
    possible_squares: list[Square],
    possible_hand_tiles: list[Tile],
    prompt: str,
    seat: Seat,
) -> Square | Tile:
    async with _highlighted(
        seat, squares=possible_squares, hand_tiles=possible_hand_tiles
    ):
        # loop until we get a valid square or hand tile
        while True:
            data = await _get_choice(
                prompt,
                seat,
            )
            # try parsing as a square
            square = Square(row=data.get("row", -1), col=data.get("column", -1))
            if square in possible_squares:
                return square

            # try parsing as a Tile
            try:
                tile = Tile(data["handTile"])
                if tile in possible_hand_tiles:
                    return tile
            except:
                pass

            # it's not valid; get a new choice
            print(
                f"Ignoring invalid choice {data=}, {possible_squares=}, {possible_hand_tiles=}"
            )


async def choose_response(
    possible_responses: list[Response | Tile],
    prompt: str,
    seat: Seat,
) -> Response | Tile:
    async with _highlighted(
        seat, actions=cast(list[Action | Response], possible_responses)
    ):
        # loop until we get a valid response
        while True:
            data = await _get_choice(
                prompt,
                seat,
            )
            # try parsing as a Response
            try:
                response = Response(data["button"])
                if response in possible_responses:
                    return response
            except:
                pass

            # try parsing as a Tile
            try:
                tile = Tile(data["button"])
                if tile in possible_responses:
                    return tile
            except:
                pass

            # it's not valid; get a new choice
            print(f"Ignoring invalid choice {data=}, {possible_responses=}")


async def choose_exchange(
    choices: list[Tile],
    prompt: str,
    seat: Seat,
) -> Tile:
    async with _highlighted(seat, board_tiles=choices):
        # loop until we get a valid response
        while True:
            data = await _get_choice(
                prompt,
                seat,
            )
            # try parsing as a Tile
            try:
                tile = Tile(data["boardTile"])
                if tile in choices:
                    return tile
            except:
                pass

            # it's not valid; get a new choice
            print(f"Ignoring invalid choice {data=}, {choices=}")
