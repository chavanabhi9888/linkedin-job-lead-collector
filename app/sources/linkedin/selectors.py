"""Every LinkedIn-specific selector/URL lives here."""
from __future__ import annotations

BASE_URL = "https://www.linkedin.com"
LOGIN_URL = f"{BASE_URL}/login"
FEED_URL = f"{BASE_URL}/feed/"
SEARCH_URL = f"{BASE_URL}/search/results/content/"

LOGGED_IN_MARKER = "#global-nav, nav.global-nav"
LOGIN_USERNAME = "#username"
LOGIN_PASSWORD = "#password"
LOGIN_SUBMIT = "button[type='submit']"
LOGIN_ERRORS = "#error-for-username, #error-for-password"

# Matches post cards on modern SDUI, group posts, and legacy layouts
POST_CARD = (
    "div[id*='FeedType'], "
    "div[id^='expanded'], "
    "[data-testid='lazy-column'] > div > div, "
    "div:has(button:has-text('Comment')), "
    "div.feed-shared-update-v2, "
    "li.reusable-search__result-container"
)

NO_RESULTS = ".search-no-results__container, .artdeco-empty-state, .search-reusable-search-no-results"

NOT_LOGGED_IN_URL_PARTS = ("/login", "/authwall", "/uas/", "/signup")
CHALLENGE_URL_PARTS = ("/checkpoint/", "/challenge", "captcha")
CHALLENGE_SELECTORS = (
    "iframe[src*='captcha'], iframe[title*='captcha' i], #captcha-internal, "
    "input[name='pin'], #input__phone_verification_pin, #input__email_verification_pin"
)
CHALLENGE_TEXT = (
    "quick security check",
    "security verification",
    "verify you're not a robot",
    "two-step verification",
    "let's do a quick security check",
)

EXTRACT_POSTS_JS = """
(els) => {
  return els.map((el) => {
    const txt = (n) => (n ? (n.innerText || n.textContent || '').trim() : '');
    const allLinks = Array.from(el.querySelectorAll('a'));

    // 1. Author Name and Profile URL
    const profileLink = allLinks.find(a => a.href && (a.href.includes('/in/') || a.href.includes('/company/')));
    let author = '';
    let profile = '';
    if (profileLink) {
      profile = profileLink.href.split('?')[0];
      author = txt(profileLink).split('\\n')[0].trim();
    }

    // 2. Post URL and URN
    let postUrl = '';
    let urn = el.getAttribute('data-urn') || el.getAttribute('data-chameleon-result-urn') || '';

    const updateLink = allLinks.find(a => 
      a.href && (a.href.includes('/feed/update/') || a.href.includes('/posts/') || a.href.includes('activity-'))
    );
    if (updateLink) {
      postUrl = updateLink.href.split('?')[0];
      const match = postUrl.match(/urn:li:(?:activity|ugcPost|share):\\d+/) || postUrl.match(/-(activity|ugcPost)-(\\d+)/);
      if (match) {
        urn = match[0].startsWith('urn:') ? match[0] : `urn:li:${match[1]}:${match[2]}`;
      }
    }

    if (!postUrl && urn && urn.startsWith('urn:li:')) {
      postUrl = `https://www.linkedin.com/feed/update/${urn}/`;
    }
    if (!postUrl && el.id) {
      postUrl = `https://www.linkedin.com/feed/update/${encodeURIComponent(el.id)}/`;
    }

    // 3. Post Text: Extract full text so contacts inside '... more' are not lost
    let bodyText = '';
    const specificContainer = el.querySelector(
      '.feed-shared-update-v2__description-wrapper, ' +
      '.feed-shared-text, ' +
      '.update-components-text, ' +
      '.feed-shared-inline-show-more-text'
    );
    if (specificContainer) {
      bodyText = txt(specificContainer);
    }
    if (!bodyText || bodyText.length < 30) {
      bodyText = txt(el);
    }

    // 4. Timestamp / relative label (e.g. '29m', '42m', '2h')
    const fullText = txt(el);
    const labelMatch = fullText.match(/\\b(\\d+\\s*(?:m|h|d|w|mo|yr|s|min|hour|day|week)s?)\\s*•/i);
    const label = labelMatch ? labelMatch[1] : '';

    return {
      urn: urn || postUrl,
      post_url: postUrl,
      text: bodyText,
      author: author,
      profile: profile,
      label: label
    };
  });
}
"""