from __future__ import annotations

import base64
import json
import stat
import unittest

from hub_case import HubCase
from kvb_orchestrator import accounts, accounts_io
from kvb_orchestrator.errors import ToolError

ONE = {
    "id": "a" * 16, "created": "2026-11-27T08:00:00+00:00", "provider": "Anthropic", "email": "a@example.org",
    "renewal": {"day": 1, "time": "09:00"}, "reset": {"day": 3, "time": "18:30"}, "resubscribe": "", "autorenew": True, "limit": None,
    "note": '=HYPERLINK("x")',
}
TWO = {**ONE, "id": "b" * 16, "email": "b@example.org", "autorenew": False, "limit": 5000, "note": "team seat"}
MINIMAL = "provider,email,renewal,reset\n"


def encoded(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode()


def body(text: str, mapping: dict | None, separator: str, choices: dict) -> dict:
    return {"file": encoded(text), "separator": separator, "mapping": mapping, "choices": choices}


def previewed(text: str, stored: list[dict]) -> dict:
    return accounts_io.preview(body(text, None, "", {}), stored)


class TestExport(unittest.TestCase):
    def test_csv_and_tsv_hold_the_header_one_line_per_account_and_guard_formulas(self):
        for fmt, separator in (("csv", ","), ("tsv", "\t")):
            with self.subTest(fmt=fmt):
                kind, data = accounts_io.export([ONE, TWO], fmt)
                lines = data.decode("utf-8").split("\r\n")
                self.assertEqual(kind, accounts_io.FORMATS[fmt][1])
                self.assertEqual(lines[0], separator.join(accounts_io.HEADER))
                self.assertEqual(len([line for line in lines if line]), 3)
                self.assertIn("Mon", lines[1])
                self.assertIn("'=HYPERLINK", lines[1])
        with self.assertRaises(ToolError):
            accounts_io.export([ONE], "xlsx")

    def test_an_exported_file_previews_every_row_unchanged_and_the_formula_comes_back_bare(self):
        for fmt in accounts_io.FORMATS:
            with self.subTest(fmt=fmt):
                result = previewed(accounts_io.export([ONE, TWO], fmt)[1].decode(), [ONE, TWO])
                self.assertEqual([row["status"] for row in result["rows"]], ["unchanged", "unchanged"])
                self.assertEqual(result["rows"][0]["account"]["note"], '=HYPERLINK("x")')


class TestMapping(unittest.TestCase):
    def test_the_table_labels_map_without_a_choice_and_unknown_headers_name_every_required_field(self):
        mapping = accounts_io.proposed(["Provider", "Email", "Renewal", "Next reset"])
        self.assertEqual([mapping[name] for name in ("provider", "email", "renewal", "reset")], [0, 1, 2, 3])
        result = previewed("foo,bar\n1,2\n", [])
        self.assertEqual((result["missing"], result["rows"]), (["provider", "email", "renewal", "reset"], []))

    def test_each_separator_is_detected_and_a_requested_one_wins(self):
        for separator in accounts_io.SEPARATORS:
            with self.subTest(separator=repr(separator)):
                self.assertEqual(previewed(f"a{separator}b\n", [])["separator"], separator)
        self.assertEqual(accounts_io.preview(body("a,b;c\n", None, ";", {}), [])["separator"], ";")
        with self.assertRaises(ToolError):
            accounts_io.preview(body("a,b\n", None, "|", {}), [])

    def test_weekday_spellings_one_or_two_columns_and_bad_days_name_their_column(self):
        self.assertEqual({accounts_io.weekday(word, "c") for word in ("0", "Sun", "Sunday", "So", "Sonntag")}, {0})
        one = previewed(f"{MINIMAL}X,c@example.org,Mon 09:00,Mon 10:00\n", [])["rows"][0]["account"]
        two = previewed("provider,email,renewal_day,renewal_time,reset\nX,c@example.org,Mon,9:00,Mon 10:00\n", [])["rows"][0]["account"]
        self.assertEqual(one["renewal"], two["renewal"])
        for bad in ("7 09:00", "Funday 09:00"):
            with self.subTest(bad=bad):
                row = previewed(f"{MINIMAL}X,c@example.org,{bad},Mon 10:00\n", [])["rows"][0]
                self.assertEqual(row["status"], "error")
                self.assertIn("column renewal", row["error"])

    def test_absent_optional_columns_take_their_empty_values(self):
        account = previewed(f"{MINIMAL}X,c@example.org,Mon 09:00,Mon 10:00\n", [])["rows"][0]["account"]
        self.assertEqual((account["resubscribe"], account["autorenew"], account["limit"], account["note"]), ("", False, None, ""))
        self.assertTrue(accounts_io.autorenew_of("ja", "c"))
        with self.assertRaises(ToolError):
            accounts_io.autorenew_of("maybe", "c")

    def test_an_oversized_long_or_non_utf8_file_parses_nothing(self):
        big = MINIMAL + "x" * (accounts_io.FILE_LIMIT + 1)
        long = MINIMAL + "X,c@example.org,Mon 09:00,Mon 10:00\n" * (accounts_io.ROW_LIMIT + 1)
        for raw in (encoded(big), encoded(long), base64.b64encode(b"provider\n\xff\xfe\n").decode(), "not base64!"):
            with self.subTest(raw=raw[:20]), self.assertRaises(ToolError):
                accounts_io.preview({"file": raw, "separator": "", "mapping": None, "choices": {}}, [])
        self.assertEqual(accounts_io.file_text(encoded(chr(0xFEFF) + "a,b")), "a,b")


class TestConflicts(unittest.TestCase):
    def test_a_changed_known_email_is_an_update_with_its_fields_and_a_new_one_is_new(self):
        text = f"{MINIMAL}Anthropic,a@example.org,Tue 09:00,Wed 18:30\nX,b@example.org,Mon 09:00,Mon 10:00\n"
        rows = previewed(text, [ONE])["rows"]
        self.assertEqual((rows[0]["status"], rows[0]["choice"], rows[0]["id"]), ("update", "overwrite", ONE["id"]))
        self.assertIn("renewal", rows[0]["changed"])
        self.assertEqual(rows[1]["status"], "new")

    def test_two_rows_with_one_email_are_both_errors(self):
        result = previewed(f"{MINIMAL}X,c@example.org,Mon 09:00,Mon 10:00\nY,C@example.org,Mon 09:00,Mon 10:00\n", [])
        self.assertEqual(([row["status"] for row in result["rows"]], result["errors"]), (["error", "error"], 2))

    def test_the_digest_follows_every_stored_field_and_id(self):
        self.assertEqual(accounts_io.digest([ONE]), accounts_io.digest([dict(ONE)]))
        self.assertNotEqual(accounts_io.digest([ONE]), accounts_io.digest([{**ONE, "note": "x"}]))
        self.assertNotEqual(accounts_io.digest([ONE]), accounts_io.digest([{**ONE, "id": "c" * 16}]))


class TestTransferApi(HubCase):
    def post(self, path: str, payload: object) -> tuple[int, bytes]:
        status, _, answer = self.post_json(path, payload, self.guard(self.host))
        return status, answer

    def stored(self) -> list[dict]:
        status, answer = self.post("/api/accounts", {"id": "", "account": {key: ONE[key] for key in accounts.KEYS}})
        self.assertEqual(status, 200, answer)
        return [json.loads(answer)]

    def test_export_answers_an_attachment_without_writing_a_file(self):
        self.stored()
        before = sorted(path.name for path in self.state.iterdir())
        status, headers, data = self.get("/api/accounts/export?format=csv")
        self.assertEqual(status, 200, data)
        self.assertEqual(headers["content-type"], "text/csv; charset=utf-8")
        self.assertRegex(headers["content-disposition"], r'attachment; filename="accounts-[0-9]{4}-[0-9]{2}-[0-9]{2}\.csv"')
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(self.get("/api/accounts/export?format=tsv")[1]["content-type"], "text/tab-separated-values; charset=utf-8")
        self.assertEqual(self.get("/api/accounts/export?format=xls")[0], 400)
        self.assertEqual(sorted(path.name for path in self.state.iterdir()), before)

    def test_keep_and_overwrite_apply_in_one_write_and_unlisted_accounts_stay(self):
        account = self.stored()[0]
        self.post("/api/accounts", {"id": "", "account": {**{key: TWO[key] for key in accounts.KEYS}, "email": "z@example.org"}})
        text = f"{MINIMAL}Changed,a@example.org,Tue 09:00,Wed 18:30\nNew,b@example.org,Mon 09:00,Mon 10:00\n"
        for choice, provider in (("keep", "Anthropic"), ("overwrite", "Changed")):
            with self.subTest(choice=choice):
                status, answer = self.post("/api/accounts/import/preview", body(text, None, "", {"a@example.org": choice}))
                self.assertEqual(status, 200, answer)
                status, answer = self.post("/api/accounts/import/apply", {**body(text, None, "", {"a@example.org": choice}), "digest": json.loads(answer)["digest"]})
                self.assertEqual(status, 200, answer)
                listed = {row["email"]: row for row in json.loads(self.get("/api/accounts")[2])["accounts"]}
                self.assertEqual((listed["a@example.org"]["provider"], listed["a@example.org"]["id"]), (provider, account["id"]))
                self.assertIn("z@example.org", listed)
                self.assertEqual(stat.S_IMODE((self.state / accounts.ACCOUNTS).stat().st_mode), 0o600)

    def test_an_error_row_or_a_stale_digest_leaves_the_file_byte_identical(self):
        self.stored()
        file = self.state / accounts.ACCOUNTS
        before = file.read_bytes()
        bad = body(f"{MINIMAL}X,c@example.org,Funday 09:00,Mon 10:00\n", None, "", {})
        self.assertEqual(self.post("/api/accounts/import/apply", {**bad, "digest": ""})[0], 400)
        good = body(f"{MINIMAL}X,c@example.org,Mon 09:00,Mon 10:00\n", None, "", {})
        status, answer = self.post("/api/accounts/import/apply", {**good, "digest": "0" * accounts_io.DIGEST_LENGTH})
        self.assertEqual((status, json.loads(answer)["reason"]), (409, "the accounts changed since the preview"))
        self.assertEqual(file.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
