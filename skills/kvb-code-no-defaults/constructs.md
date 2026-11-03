# Banned constructs, by language

Each `Never` below means the default is a substantive value. The same
construct with `false`, `null` or `""` is permitted, and with any other value
only when justified in a comment.

| Language | Never | Instead |
| --- | --- | --- |
| Bash | `${VAR:-x}`, `${VAR:=x}`, `: "${VAR:=x}"` | `: "${VAR:?set VAR in <file>}"` |
| Python | `def f(a=1)`, `d.get(k, x)`, `getattr(o, n, x)`, `os.environ.get(k, x)`, `argparse(default=)` | required args, `d[k]`, `os.environ[k]`, `add_argument(required=True)` |
| Jinja / Ansible | `\| default(x)`, `lookup('env', k) \| default('')` | `\| mandatory`, `assert` on the var |
| JS / TS | `function f(a = 1)`, `const {a = 1} = o`, `a \|\| x`, `a ?? x` | required params, explicit `if (a === undefined) throw` |
| Go | relying on zero values | constructor that validates every field |
| Rust | `unwrap_or`, `unwrap_or_default`, `#[serde(default)]` | `ok_or(Error::MissingX)?`, `#[serde(deny_unknown_fields)]` |
| Java / C# | optional parameters, `??`, `getOrDefault` | required constructor args, explicit null check that throws |
| SQL | `DEFAULT` on a column | `NOT NULL` and supply it in every insert |
| Make | `VAR ?= x` | `VAR := $(or $(VAR),$(error VAR is required))` |
| Docker / Compose | `${VAR:-x}`, `ENV` placeholders standing in for config | `${VAR:?VAR is required}` |
| Terraform / Helm | `variable { default = }`, `default` in `values.yaml` | no default; fail on the missing input |
