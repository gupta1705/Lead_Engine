"""Links in an email: [words](https://address) is sent clickable; an email without one does not change."""
import email
import unittest
from email import policy

import mail_links as ml
import outreach

BODY = ("Hi Nicole,\n\nEvery episode holds a story.\n\n"
        "[ReelForge](https://reel--forge.vercel.app/#1), from LCX, puts editors on your long-form.\n\n"
        "Regards,\nUpagnya Purigilla\nLCX | lightscameraexperiment.com")


def parts(msg):
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    return {p.get_content_type(): p.get_content() for p in parsed.walk() if not p.is_multipart()}, parsed


class Forms(unittest.TestCase):
    def test_the_form_the_team_writes_becomes_a_link(self):
        html = ml.to_html(BODY)
        self.assertIn('<a href="https://reel--forge.vercel.app/#1">ReelForge</a>, from LCX', html)
        self.assertNotIn("](", html)
        self.assertEqual(html.count("<br>"), BODY.count("\n"))

    def test_plain_part_keeps_the_address_without_the_brackets(self):
        plain = ml.to_plain(BODY)
        self.assertIn("ReelForge (https://reel--forge.vercel.app/#1), from LCX", plain)
        self.assertNotIn("](", plain)
        self.assertEqual(ml.to_plain("[https://a.example](https://a.example)"), "https://a.example")

    def test_accepted_addresses(self):
        self.assertIn('href="https://example.com/page"', ml.to_html("[a](example.com/page)"))
        self.assertIn('href="http://example.com"', ml.to_html("[a](http://example.com)"))
        self.assertIn('href="mailto:me@example.com"', ml.to_html("[write](mailto:me@example.com)"))
        self.assertIn('href="https://en.wikipedia.org/wiki/A_(b)"', ml.to_html("[a](https://en.wikipedia.org/wiki/A_(b))"))
        self.assertEqual(ml.to_plain("[write](mailto:me@example.com)"), "write (me@example.com)")

    def test_anything_else_is_left_as_text_and_cannot_inject(self):
        for text in ("[a](javascript:alert(1))", "[a](data:text/html,x)", "[a]( )", "[a](not an address)", "[a] (https://b.example)"):
            self.assertFalse(ml.has_links(text), text)
        self.assertNotIn("<a", ml.to_html("[a](javascript:alert(1))"))
        html = ml.to_html('<script>x</script> [<b>w</b>](https://a.example/"onclick=x) & more')
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>", html)
        self.assertNotIn('"onclick', html)
        self.assertIn("&amp; more", html)

    def test_written_out_addresses_stay_clickable_without_their_punctuation(self):
        html = ml.to_html("[a](https://a.example) and see https://b.example/x.")
        self.assertIn('<a href="https://b.example/x">https://b.example/x</a>.', html)


class Sent(unittest.TestCase):
    def test_an_email_with_a_link_has_both_parts(self):
        got, parsed = parts(outreach._message(BODY))
        self.assertEqual(parsed.get_content_type(), "multipart/alternative")
        self.assertIn('<a href="https://reel--forge.vercel.app/#1">ReelForge</a>', got["text/html"])
        self.assertIn("ReelForge (https://reel--forge.vercel.app/#1)", got["text/plain"])

    def test_non_ascii_words_survive(self):
        got, _ = parts(outreach._message("India’s biggest [रील](https://a.example)"))
        self.assertIn("India’s biggest", got["text/plain"])
        self.assertIn("रील</a>", got["text/html"])

    def test_an_email_without_a_link_is_exactly_what_it_was(self):
        from email.mime.text import MIMEText
        for text in ("Hi Kay,\n\nSee https://a.example for more.", "India’s biggest", "[Name] is not a link"):
            msg = outreach._message(text)
            self.assertEqual(msg.get_content_type(), "text/plain")
            self.assertEqual(msg.as_bytes(), MIMEText(text).as_bytes())

    def test_headers_can_be_set_on_the_message_the_sender_builds(self):
        msg = outreach._message(BODY)
        msg["to"], msg["from"], msg["subject"] = "a@example.com", "b@example.com", "Show | Clipping + Distribution"
        msg["Message-ID"] = "<tvf-1@example.com>"
        parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
        self.assertEqual(parsed["subject"], "Show | Clipping + Distribution")
        self.assertEqual(parsed["to"], "a@example.com")


if __name__ == "__main__":
    unittest.main()
