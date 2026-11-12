"""Slack notifier safety checks."""

from __future__ import annotations

import pytest

import slack_notify


def test_slack_post_rejects_non_slack_webhook() -> None:
    with pytest.raises(ValueError, match="hooks.slack.com"):
        slack_notify.slack_post("hello", webhook_url="https://example.com/hook")


def test_slack_post_skips_when_missing(capsys) -> None:
    slack_notify.slack_post("hello", webhook_url="")
    err = capsys.readouterr().err
    assert "skipping" in err.lower()
