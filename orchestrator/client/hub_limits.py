"""Returns:
    DIFF_LIMIT: bytes of JSON-encoded patch text one review diff carries, in
        the client that builds it and the hub that takes it.
    DIFF_BODY_LIMIT: bytes of request body the hub reads for an ask or a
        review request; the client sends a larger one without its diff.
    FILE_CAP: files one review diff lists; the client builds no diff of more.
    PATH_LIMIT: characters of a path the hub takes, a diff path included;
        the client builds no diff with a longer one.
    NOTES_LIMIT: characters of review notes the hub takes; the client refuses
        longer notes instead of cutting them.
    WITHHELD: the note of a diff entry that ships without its patch because
        no secret rule loads to mask it.
    MASKED: the note of a diff entry whose patch reads MASK for every secret
        rule match and every armour block line.
    MASK: what stands for a masked span in a patch.
    SEALED_LIMIT: bytes of JSON-encoded clear patch text of the masked and
        withheld files one request carries apart from its diff, for a
        signed reveal.
"""

DIFF_LIMIT = 2 << 20
DIFF_BODY_LIMIT = 4 << 20
SEALED_LIMIT = 1 << 20
FILE_CAP = 5000
PATH_LIMIT = 4096
NOTES_LIMIT = 100_000
WITHHELD = "content withheld"
MASKED = "masked"
MASK = "••••"
