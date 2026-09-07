from backend.news.sentiment import analyze_sentiment, classify_category, score_news_impact


def test_contrast_conjunction_flips_to_bearish():
    """The exact example from the spec: positive-sounding word before
    'but', negative clause after it — must net out bearish."""
    result = analyze_sentiment("Company revenue increased but guidance was reduced")
    assert result["score"] < 0
    assert result["label"] in ("moderate_negative", "strong_negative")


def test_unambiguous_positive_headline():
    result = analyze_sentiment("Company beats earnings estimates, raises full-year guidance")
    assert result["score"] > 0
    assert result["label"] in ("moderate_positive", "strong_positive")


def test_unambiguous_negative_headline():
    result = analyze_sentiment("Stock plunges after CEO resigns amid fraud investigation")
    assert result["score"] < 0
    assert result["label"] == "strong_negative"


def test_double_negative_is_not_strongly_negative():
    result = analyze_sentiment("Regulators are not investigating the company")
    assert result["score"] >= 0


def test_neutral_headline_has_small_magnitude():
    result = analyze_sentiment("Company to present at investor conference next week")
    assert abs(result["score"]) < 20


def test_category_classification():
    assert classify_category("Company beats Q2 earnings estimates") == "earnings"
    assert classify_category("Analyst downgrades stock to underweight") == "analyst_rating"
    assert classify_category("Company to acquire smaller rival in $2B deal") == "acquisition"
    assert classify_category("Fed raises interest rates by 25bps") == "macro"


def test_impact_score_bounded():
    for headline in [
        "Company beats earnings estimates, raises full-year guidance",
        "Stock plunges after CEO resigns amid fraud investigation",
        "Company to present at investor conference next week",
    ]:
        impact = score_news_impact(headline)
        assert -100 <= impact["impact_score"] <= 100
        assert impact["horizon"] in ("short_term", "medium_term", "long_term")
        assert isinstance(impact["explanation"], str) and len(impact["explanation"]) > 10
