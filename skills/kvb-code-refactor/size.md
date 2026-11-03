# Refactor: a file over 250 lines

No file containing program code exceeds 250 lines. Split the overflow along
the SRP seam: the size is the symptom, not the cause. Exempt are description
and markup languages (Markdown, YAML, JSON, HTML, translation and data files)
and the rare file the language or framework genuinely forbids splitting:
name that reason in the report; "it was easier" does not qualify.
