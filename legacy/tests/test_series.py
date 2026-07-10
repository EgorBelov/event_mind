"""Тесты распознавания серии события (compute_series_slug)."""
import pytest

from app.recommender.series import compute_series_slug


@pytest.mark.parametrize(
    "title,city,expected",
    [
        # выпуски одной серии должны получать одинаковый slug
        ("Python MeetUp #14", None, "python-meetup"),
        ("Python MeetUp #15", None, "python-meetup"),
        ("Python MeetUp № 16", None, "python-meetup"),
        # vol / volume / Часть IV — снимаются
        ("ML Meetup vol.2", "msk", "ml-meetup--msk"),
        ("ML Meetup volume 3", "msk", "ml-meetup--msk"),
        ("Часть IV: Postgres внутри", None, "postgres-vnutri"),
        # годы и даты должны вычищаться
        ("DevOps Days 2026", "moscow", "devops-days--moscow"),
        ("IT Conf 1 июня 2026", None, "it-conf"),
        # «голые» римские/латинские слова НЕ должны отрезаться (ML, VI)
        ("MLOps Meetup", None, "mlops-meetup"),
        # crap-case
        ("#15", None, None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_compute_series_slug(title, city, expected):
    assert compute_series_slug(title, city) == expected


def test_city_suffix_only_when_not_in_title():
    """Если город уже встроен в title (DevOps Days Moscow + city=moscow), не дублируем."""
    assert compute_series_slug("DevOps Days Moscow", "moscow") == "devops-days-moscow"
