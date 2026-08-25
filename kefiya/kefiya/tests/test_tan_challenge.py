# Copyright (c) 2026, Phamos GmbH and contributors
# For license information, please see license.txt

"""A challenge nobody can see is a question nobody can answer.

comdirect does not ask for a TAN in words. It sends a photoTAN: a coloured
mosaic that the photoTAN app reads off the screen, and only then does it show
the six digits to type. Sparkassen do the same with chipTAN-QR.

The prompt used to carry the TAN method and the account and nothing else. The
challenge sat in ask_for_tan() and was never passed on, so on a comdirect
access the box asked for a TAN and showed nothing to scan.
"""

import base64
import os
import re
import unittest

from kefiya.utils import tan_challenge


def _matrix(mime=b"image/png", image=b"\x89PNG\r\n\x1a\nDATA"):
    """A challenge as the banks send it: MIME type and image, each with its
    length in front, big endian."""
    return (len(mime).to_bytes(2, "big") + mime
            + len(image).to_bytes(2, "big") + image)


class Response(object):
    def __init__(self, **kwargs):
        self.challenge = kwargs.get("challenge")
        self.challenge_html = kwargs.get("challenge_html")
        self.challenge_hhduc = kwargs.get("challenge_hhduc")


class TestThePictureIsFoundInTheChallenge(unittest.TestCase):

    def test_a_phototan_image_is_read_out(self):
        mime, image = tan_challenge.matrix_code(_matrix())
        self.assertEqual(mime, "image/png")
        self.assertEqual(image, b"\x89PNG\r\n\x1a\nDATA")

    def test_a_gif_challenge_is_read_the_same_way(self):
        mime, _ = tan_challenge.matrix_code(_matrix(mime=b"image/gif"))
        self.assertEqual(mime, "image/gif")


class TestFlickerDataIsNotAnImage(unittest.TestCase):
    """The same field carries the flicker code for chipTAN optisch. Handing
    that to the browser as an image shows a broken frame and nothing to scan --
    which method it is has to be decided by reading the data, because banks
    name their TAN methods freely."""

    def test_flicker_data_is_refused(self):
        self.assertIsNone(tan_challenge.matrix_code(
            b"0F04871104373832303002"))

    def test_a_truncated_image_is_refused(self):
        """Half a picture is worse than none: a broken frame, and no reason
        given for it."""
        broken = _matrix()[:-4]
        self.assertIsNone(tan_challenge.matrix_code(broken))

    def test_an_empty_image_is_refused(self):
        self.assertIsNone(tan_challenge.matrix_code(_matrix(image=b"")))

    def test_a_mime_type_that_is_not_an_image_is_refused(self):
        self.assertIsNone(tan_challenge.matrix_code(_matrix(mime=b"text/html")))

    def test_nothing_at_all_is_refused(self):
        for value in (None, b"", b"\x00", "a string", 42):
            self.assertIsNone(tan_challenge.matrix_code(value), value)


class TestBankMarkupDoesNotReachThePage(unittest.TestCase):
    """The challenge text comes from the bank and is shown on a desk page. It
    is not ours to render."""

    def test_tags_are_stripped(self):
        self.assertEqual(
            tan_challenge.as_text("Bitte <b>scannen</b> Sie<br>die Grafik"),
            "Bitte scannen Sie die Grafik")

    def test_a_script_does_not_survive_as_markup(self):
        text = tan_challenge.as_text("<script>alert(1)</script>Freigabe")
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)

    def test_entities_come_out_readable(self):
        self.assertEqual(tan_challenge.as_text("Betrag&nbsp;70,40&amp;mehr"),
                         "Betrag 70,40&mehr")

    def test_nothing_is_an_empty_string(self):
        self.assertEqual(tan_challenge.as_text(None), "")


class TestTheChallengeReachesThePrompt(unittest.TestCase):

    def test_image_and_text_travel_together(self):
        got = tan_challenge.challenge_of(Response(
            challenge="Bitte Grafik scannen", challenge_hhduc=_matrix()))
        self.assertEqual(got["text"], "Bitte Grafik scannen")
        self.assertEqual(got["image"]["mime"], "image/png")
        self.assertEqual(base64.b64decode(got["image"]["data"]),
                         b"\x89PNG\r\n\x1a\nDATA")

    def test_the_html_challenge_is_used_when_there_is_no_plain_one(self):
        got = tan_challenge.challenge_of(
            Response(challenge_html="<p>Auftrag freigeben</p>"))
        self.assertEqual(got["text"], "Auftrag freigeben")

    def test_a_bank_that_sends_nothing_yields_nothing(self):
        self.assertEqual(tan_challenge.challenge_of(Response()), {})
        self.assertEqual(tan_challenge.challenge_of(None), {})

    def test_a_text_only_challenge_carries_no_image_key(self):
        got = tan_challenge.challenge_of(Response(challenge="TAN eingeben"))
        self.assertNotIn("image", got)


def _source(name):
    base = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    with open(os.path.join(base, name), encoding="utf-8") as handle:
        return handle.read()


class TestNothingSwallowsTheChallengeOnTheWay(unittest.TestCase):
    """It was already there once and never passed on -- the object sat in
    ask_for_tan() while the prompt showed a bare input field."""

    def test_the_controller_passes_it_to_both_kinds_of_prompt(self):
        source = _source(os.path.join("utils", "fints_controller.py"))
        body = source.split("def ask_for_tan(")[1].split("\n    def ")[0]
        self.assertIn("tan_challenge.challenge_of(response)", body)
        self.assertEqual(body.count("challenge=challenge"), 2,
                         "A TAN prompt and a decoupled confirmation both have "
                         "to show what the bank asked.")

    def test_the_prompt_publishes_it(self):
        source = _source(os.path.join("utils", "fints_interactive.py"))
        self.assertIn('params["challenge"] = challenge', source)

    def test_the_dialog_renders_the_picture(self):
        js = _source(os.path.join("public", "js", "controllers",
                                  "bank_refresh.js"))
        self.assertIn("function tanChallengeField(data)", js)
        self.assertIn("data:", js)
        self.assertIn("fields.unshift(challenge)", js,
                      "The picture is the question and belongs at the top.")

    def test_the_picture_is_sized_so_an_app_can_read_it(self):
        """A photoTAN app reads the mosaic off the screen. Given in pixels it
        comes out too small to focus on at high resolution."""
        js = _source(os.path.join("public", "js", "controllers",
                                  "bank_refresh.js"))
        self.assertTrue(re.search(r"width:\d+mm;height:\d+mm", js), js[:0])
