# Deleting block comments

Block-comment languages are not line-oriented: in Jinja (`{# … #}`), C-like
(`/* … */`), HTML (`<!-- … -->`) and kin, a closer alone on its line looks
like a comment line; deleted with the rest, the opener swallows every live
statement down to the next closer. Delete such a block by hand, count the
delimiters (`grep -c '{#'` against `grep -c '#}'`), re-parse the file and
diff it against `git show HEAD:<path>`: only comment lines may leave. A green
lint proves nothing here.
