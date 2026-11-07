from __future__ import annotations

import pytest

from rsi_cross_swing_bot.cli import build_parser, main


def test_parser_has_commands() -> None:
    p = build_parser()
    assert p.parse_args(["check"]).command == "check"
    assert p.parse_args(["replay", "--last", "10"]).last == 10


def test_main_unknown_exits() -> None:
    with pytest.raises(SystemExit):
        main(["nope"])
