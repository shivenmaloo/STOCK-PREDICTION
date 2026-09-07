from backend.forecasting.summary import build_plain_summary


def _base_args(**overrides):
    args = {
        "ticker": "TESTCO",
        "horizon_days": 5,
        "signal": {"signal": "NEUTRAL", "reason": "No clear directional edge from the models."},
        "ensemble": {"direction": "neutral", "confidence": 0.3, "expected_return_pct": 0.1,
                     "model_agreement": "2/4", "low_confidence_disagreement": False},
        "news_context": {"available": False},
        "position_sizing": {"suggested_position_pct": None},
        "relaxed_mode": False,
        "out_of_distribution": {"is_out_of_distribution": False},
    }
    args.update(overrides)
    return args


def test_summary_mentions_ticker_and_horizon():
    summary = build_plain_summary(**_base_args(ticker="NVDA", horizon_days=5))
    assert "NVDA" in summary
    assert "5 trading day" in summary


def test_summary_reflects_disagreement_honestly():
    args = _base_args(ensemble={"direction": "neutral", "confidence": 0.1, "expected_return_pct": 0.0,
                                 "model_agreement": "1/4", "low_confidence_disagreement": True})
    summary = build_plain_summary(**args)
    assert "disagree" in summary.lower()


def test_summary_includes_news_agreement():
    args = _base_args(
        signal={"signal": "STRONG_BULLISH_SETUP", "reason": "everything agrees"},
        ensemble={"direction": "bullish", "confidence": 0.8, "expected_return_pct": 3.0,
                  "model_agreement": "4/4", "low_confidence_disagreement": False},
        news_context={"available": True, "agrees_with_model": True, "summary": "reads bullish — agrees"},
    )
    summary = build_plain_summary(**args)
    assert "supports this" in summary.lower()


def test_summary_never_silently_drops_news_on_neutral_direction():
    """Real gap found via manual testing: when the model's own
    direction lands on neutral, agrees_with_model is None (no
    meaningful comparison to make) — but the news sentence was being
    dropped ENTIRELY in that case, even though real news data existed
    and was fetched. It must still be mentioned, just without a forced
    agree/disagree framing."""
    args = _base_args(
        ensemble={"direction": "neutral", "confidence": 0.2, "expected_return_pct": 0.1,
                  "model_agreement": "2/4", "low_confidence_disagreement": False},
        news_context={"available": True, "agrees_with_model": None,
                      "summary": "5 recent article(s) average +2 impact — reads neutral."},
    )
    summary = build_plain_summary(**args)
    assert "impact" in summary.lower() or "context" in summary.lower()


def test_summary_mentions_when_no_news_available_at_all():
    args = _base_args(news_context={"available": False})
    summary = build_plain_summary(**args)
    assert "no recent news" in summary.lower()


def test_summary_flags_news_disagreement():
    args = _base_args(
        ensemble={"direction": "bullish", "confidence": 0.6, "expected_return_pct": 1.5,
                  "model_agreement": "3/4", "low_confidence_disagreement": False},
        news_context={"available": True, "agrees_with_model": False, "summary": "reads bearish — counter"},
    )
    summary = build_plain_summary(**args)
    assert "points the other way" in summary.lower() or "worth noting" in summary.lower()


def test_summary_mentions_position_size_when_available():
    args = _base_args(position_sizing={"suggested_position_pct": 7.5})
    summary = build_plain_summary(**args)
    assert "7.5%" in summary


def test_summary_mentions_relaxed_mode_caveat():
    args = _base_args(relaxed_mode=True)
    summary = build_plain_summary(**args)
    assert "less trading history" in summary.lower()


def test_summary_mentions_ood_caveat():
    args = _base_args(out_of_distribution={"is_out_of_distribution": True})
    summary = build_plain_summary(**args)
    assert "unusual" in summary.lower()


def test_summary_always_ends_with_disclaimer():
    summary = build_plain_summary(**_base_args())
    assert "not a guarantee" in summary.lower()


def test_summary_contains_no_raw_jargon_placeholders():
    """Sanity check: the summary should never leak an unformatted
    template artifact or raw internal signal constant."""
    args = _base_args(signal={"signal": "STRONG_BULLISH_SETUP", "reason": "x"})
    summary = build_plain_summary(**args)
    assert "STRONG_BULLISH_SETUP" not in summary  # should be translated to plain language
    assert "{" not in summary and "}" not in summary


def test_summary_never_contradicts_itself_on_weak_lean_neutral():
    """Real bug found via testing: a weak bullish lean that doesn't
    escalate past NEUTRAL was producing a self-contradictory summary
    ('reads as no clear direction... more likely to rise'). The
    opening sentence must stay consistent with the actual final call."""
    args = _base_args(
        signal={"signal": "NEUTRAL", "reason": "Bullish lean, but confidence or expected return too weak to escalate."},
        ensemble={"direction": "bullish", "confidence": 0.28, "expected_return_pct": 1.8,
                  "model_agreement": "3/4", "low_confidence_disagreement": False},
    )
    summary = build_plain_summary(**args)
    assert "no clear direction" not in summary.lower() or "rise" not in summary.lower(), (
        "Summary must not simultaneously claim 'no clear direction' and 'more likely to rise' "
        "in the same opening statement"
    )
    assert "not strongly enough" in summary.lower() or "lean" in summary.lower()
