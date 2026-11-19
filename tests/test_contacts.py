import pytest

from app.parsing.contacts import extract_emails, extract_phones, validate_email


class TestEmails:
    def test_simple(self):
        assert extract_emails("Send CV to Jobs@Acme.io today") == ["jobs@acme.io"]

    def test_multiple_dedup_and_order(self):
        text = "a@x.com, b@y.org; A@X.com and c@z.co.in."
        assert extract_emails(text) == ["a@x.com", "b@y.org", "c@z.co.in"]

    def test_trailing_punctuation(self):
        assert extract_emails("mail hr.team@acme-corp.co.in.") == ["hr.team@acme-corp.co.in"]

    def test_bracket_obfuscation(self):
        assert extract_emails("write to jane [at] corp (dot) com") == ["jane@corp.com"]

    def test_zero_width_and_fullwidth(self):
        assert extract_emails("hr\u200b@acme.io") == ["hr@acme.io"]

    @pytest.mark.parametrize(
        "text",
        ["logo@2x.png", "name@example.com", "no-reply@acme.io", "a@b", "user@@acme.io", "x..y@acme.io", "plain text"],
    )
    def test_rejects_invalid(self, text):
        assert extract_emails(text) == []

    def test_validate_email_length(self):
        assert validate_email("a" * 65 + "@acme.io") is None

    def test_no_inference_from_names(self):
        assert extract_emails("Contact Jane Doe at Acme") == []


class TestPhones:
    def test_indian_with_country_code(self):
        assert extract_phones("Call +91 98765 43210 for details") == ["+919876543210"]

    def test_indian_local_with_context(self):
        assert extract_phones("WhatsApp: 98765-43210") == ["+919876543210"]

    def test_requires_context_or_plus(self):
        assert extract_phones("Reference ID 9876543210 is internal") == []

    def test_international_plus_prefix(self):
        assert extract_phones("US office +1 650-253-0000") == ["+16502530000"]

    def test_dedup_across_formats(self):
        assert extract_phones("Call 9876543210 or +91-98765-43210") == ["+919876543210"]

    def test_ignores_urls_and_emails(self):
        text = "see https://x.com/p/9876543210 mail hr9876543210@acme.io"
        assert extract_phones(text) == []

    def test_invalid_numbers(self):
        assert extract_phones("Call 12345") == []
