from types import SimpleNamespace

from app.sources.linkedin.guards import is_logged_in


def _page(url, cookies, marker_count=0):
    return SimpleNamespace(
        url=url,
        context=SimpleNamespace(cookies=lambda _u: cookies),
        locator=lambda _sel: SimpleNamespace(count=lambda: marker_count),
    )


def test_logged_in_via_cookie_even_if_markup_changed():
    assert is_logged_in(_page("https://www.linkedin.com/feed/", [{"name": "li_at", "value": "x"}]))


def test_not_logged_in_on_login_or_checkpoint_urls():
    cookie = [{"name": "li_at", "value": "x"}]
    assert not is_logged_in(_page("https://www.linkedin.com/login", cookie))
    assert not is_logged_in(_page("https://www.linkedin.com/checkpoint/challenge/abc", cookie))


def test_not_logged_in_without_cookie_or_marker():
    assert not is_logged_in(_page("https://www.linkedin.com/feed/", []))
