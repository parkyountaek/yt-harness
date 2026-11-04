"""Command checks for yt-guard. Standard library only, no state.

check(tool_name, tool_input, allow) -> None, or (category, reason) to block.

Categories (the human can lift one for a session with YT_GUARD_ALLOW=<a,b> set
before the session starts; a value set inside a command is never honoured):
  infra    writes through kubectl, terraform/tofu, helm, aws, gcloud/gsutil, az,
           and database migration tools; reads stay allowed. Parse failure: allow.
  db       interactive database clients (psql, mysql, mongosh, redis-cli, ...)
  secrets  reading or printing secret files (.env, keys, credentials). Parse
           failure: block.
  git      irreversible remote git: force push, deleting remote branches, mirror push

This is a best-effort command guard, not a shell interpreter or a sandbox. It can
inspect visible commands and literal inline Python, not arbitrary programs,
inherited shell functions/aliases, computed filenames, or unhooked runtime tools.
"""
import os
import re
import shlex
import ast
import glob
import subprocess

CATEGORIES = ("infra", "db", "secrets", "git")

# ---------- secrets ----------

SECRET_NAME = re.compile(
    r"(?:^|/)(?:"
    r"\.env(?:\.(?!example\b|sample\b|template\b)[\w.-]+)?"
    r"|\.envrc|\.netrc|_netrc|\.npmrc|\.pypirc|\.pgpass|\.git-credentials|\.htpasswd"
    r"|id_(?:rsa|dsa|ecdsa|ed25519)(?!\.pub\b)|[\w.-]+\.(?:pem|key|p12|pfx|jks|keystore|ppk|kdbx|asc)"
    r"|credentials\.(?:json|ya?ml)|(?<=/)credentials|service[-_]?account[\w-]*\.json|secrets?\.(?:json|ya?ml|toml|env)"
    r"|\.aws/credentials|\.kube/config|\.docker/config\.json|\.config/gcloud/[\w./-]*"
    r")$")
READ_TOOLS = {"Read", "NotebookRead", "View"}


def secret_path(token, cwd=None):
    token = token.strip("'\"").rstrip("/")
    if not token:
        return False
    path = os.path.normpath(os.path.expanduser(token))
    absolute = os.path.join(cwd or os.getcwd(), path)
    candidates = [path]
    if token != "credentials" or os.path.lexists(absolute):
        candidates.append(os.path.realpath(absolute))
    if glob.has_magic(absolute):
        candidates.extend(os.path.realpath(p) for p in glob.iglob(absolute))
        # Also recognize literal shell character classes when no file exists yet.
        candidates.append(re.sub(r"\[([^]!])\]", r"\1", path))
    return any(SECRET_NAME.search(p) for p in candidates)


# ---------- command parsing ----------

SEPARATORS = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")"}
WRAPPERS = {"sudo", "command", "time", "nohup", "exec", "builtin", "nice", "doas"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}


def segments(command, depth=0, variables=None):
    """Simple commands as token lists, following `sh -c '...'` and stripping wrappers.

    Raises ValueError when the text cannot be tokenised.
    """
    if depth > 16:
        raise ValueError("nested command limit")
    variables = dict(variables or {})
    aliases = {}
    out = []
    # Inspect substitutions even inside double quotes. Never execute expansions.
    for nested in substitutions(command):
        out.extend(segments(nested, depth + 1, variables))
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    parts, current = [], []
    for tok in lexer:   # raises ValueError on unbalanced quotes
        if tok in SEPARATORS or (tok and all(c in ";&|()" for c in tok)):
            parts.append(current)
            current = []
        else:
            current.append(tok)
    parts.append(current)
    for tokens in parts:
        tokens = [re.sub(r"\$(?:\{(\w+)\}|(\w+))",
                         lambda m: variables.get(m[1] or m[2], m[0]), t) for t in tokens]
        if tokens and tokens[0] == "alias":
            for definition in tokens[1:]:
                key, sep, value = definition.partition("=")
                if sep:
                    aliases[key] = value
            continue
        if tokens and tokens[0] in aliases:
            out.extend(segments(aliases[tokens[0]] + " " + shlex.join(tokens[1:]), depth + 1, variables))
            continue
        while tokens:
            head = os.path.basename(tokens[0])
            if head in WRAPPERS:
                tokens = tokens[1:]
                while tokens and tokens[0].startswith("-"):
                    option = tokens.pop(0)
                    value_options = {"nice": {"-n", "--adjustment"},
                                     "sudo": {"-u", "-g", "-h", "-p", "-C", "--user", "--group", "--host"},
                                     "doas": {"-u"}, "time": {"-o", "--output", "-f", "--format"}}
                    if option in value_options.get(head, set()) and tokens:
                        tokens.pop(0)
            elif head == "env":
                tokens = tokens[1:]
                while tokens and (tokens[0].startswith("-") or "=" in tokens[0]):
                    option = tokens[0]
                    tokens = tokens[1:]
                    if option in {"-S", "--split-string"} or option.startswith("--split-string="):
                        text = " ".join(tokens)
                        if "=" in option:
                            text = option.split("=", 1)[1] + " " + text
                        out.extend(segments(text, depth + 1, variables))
                        tokens = []
                        break
                    if option in {"-u", "--unset", "-C", "--chdir"} and tokens:
                        tokens = tokens[1:]
            elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
                key, value = tokens[0].split("=", 1)
                variables[key] = value
                tokens = tokens[1:]
            else:
                break
        if not tokens:
            continue
        head = os.path.basename(tokens[0])
        if head in SHELLS and any(re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", t) for t in tokens[1:-1]):
            index = next(i for i, t in enumerate(tokens[1:-1], 1)
                         if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", t))
            out.extend(segments(tokens[index + 1], depth + 1, variables))
            continue
        if head in SHELLS and "<<<" in tokens:
            index = tokens.index("<<<")
            if index + 1 < len(tokens):
                out.extend(segments(tokens[index + 1], depth + 1, variables))
                continue
        if head == "find":
            for i, token in enumerate(tokens):
                if token in {"-exec", "-execdir", "-ok", "-okdir"}:
                    end = next((j for j in range(i + 1, len(tokens)) if tokens[j] in {";", "+"}), len(tokens))
                    out.extend(segments(shlex.join(tokens[i + 1:end]), depth + 1, variables))
        if head in {"xargs", "npx", "pnpx", "uv", "pipx"}:
            rest = tokens[1:]
            while rest and (rest[0].startswith("-") or rest[0] in {"run", "exec"}):
                option = rest.pop(0)
                if option in {"-I", "-n", "-P", "-L", "-a", "--replace", "--max-args", "--max-procs", "--arg-file", "-p", "--package"} and rest:
                    rest.pop(0)
            if rest:
                out.extend(segments(shlex.join(rest), depth + 1, variables))
        if re.fullmatch(r"python[\d.]*", head) and "-c" in tokens[1:-1]:
            code = tokens[tokens.index("-c") + 1]
            try:
                tree = ast.parse(code)
                literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                for literal in literals:
                    out.append(["__inline_read__", literal])
                    try:
                        out.extend(segments(literal, depth + 1, variables))
                    except ValueError:
                        pass  # A Python string is not necessarily shell syntax.
                for node in ast.walk(tree):
                    if isinstance(node, (ast.List, ast.Tuple)):
                        values = [n.value for n in node.elts if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                        if len(values) == len(node.elts) and values:
                            out.extend(segments(shlex.join(values), depth + 1, variables))
            except SyntaxError:
                pass
        out.append([head] + tokens[1:])
    return out


def substitutions(command):
    """Extract balanced $() and backticks without evaluating shell code."""
    i, quote = 0, None
    while i < len(command):
        c = command[i]
        if c == "\\":
            i += 2
            continue
        if c in "'\"" and (quote is None or quote == c):
            quote = None if quote else c
        if quote != "'" and command.startswith("$(", i):
            start, level, j = i + 2, 1, i + 2
            while j < len(command) and level:
                if command[j] == "\\":
                    j += 2
                    continue
                level += (command[j] == "(") - (command[j] == ")")
                j += 1
            if level:
                raise ValueError("unclosed substitution")
            yield command[start:j - 1]
            i = j
            continue
        if quote != "'" and c == "`":
            end = command.find("`", i + 1)
            if end < 0:
                raise ValueError("unclosed backtick")
            yield command[i + 1:end]
            i = end + 1
            continue
        i += 1


# Options that take a separate value ("-n prod"), per tool, so the value is not read as a verb.
VALUE_FLAGS = {
    "kubectl": {"-n", "--namespace", "--context", "--cluster", "--kubeconfig", "--user", "-s", "--server",
                "-c", "--container", "-l", "--selector", "-o", "--output", "--as", "--token",
                "--request-timeout", "--as-group", "--as-uid", "--cache-dir", "--certificate-authority",
                "--client-certificate", "--client-key"},
    "helm": {"-n", "--namespace", "--kube-context", "--kubeconfig", "-f", "--values", "--version"},
    "terraform": {"-chdir", "-var", "-var-file", "-target"},
    "git": {"-C", "-c", "--git-dir", "--work-tree"},
    "aws": {"--profile", "--region", "--endpoint-url", "--output", "--query", "--ca-bundle",
            "--cli-read-timeout", "--cli-connect-timeout"},
    "gcloud": {"--project", "--account", "--configuration", "--format", "--filter", "--impersonate-service-account"},
    "az": {"--subscription", "--resource-group", "-g", "--output", "-o", "--query"},
}
VALUE_FLAGS["oc"] = VALUE_FLAGS["kubectl"]
VALUE_FLAGS["tofu"] = VALUE_FLAGS["terragrunt"] = VALUE_FLAGS["terraform"]


def words(tokens):
    """Arguments that are not options or the values of options."""
    takes_value = VALUE_FLAGS.get(tokens[0], set())
    out, skip = [], False
    for t in tokens[1:]:
        if skip:
            skip = False
        elif t.startswith("-"):
            skip = t in takes_value
        else:
            out.append(t)
    return out


# ---------- infra ----------

KUBECTL_WRITE = {"apply", "create", "delete", "edit", "patch", "replace", "scale", "rollout", "set",
                 "label", "annotate", "drain", "cordon", "uncordon", "taint", "exec", "cp", "run",
                 "expose", "autoscale"}
TERRAFORM_WRITE = {"apply", "destroy", "import", "taint", "untaint", "force-unlock", "refresh"}
TERRAFORM_STATE_WRITE = {"rm", "mv", "push", "replace-provider"}
HELM_WRITE = {"install", "upgrade", "uninstall", "delete", "rollback"}
CLOUD_WRITE = re.compile(r"^(?:create|delete|put|update|modify|terminate|run|start|stop|reboot|attach|detach"
                         r"|associate|disassociate|remove|add|set|deploy|resize|reset|restart|import|rm|mv|cp"
                         r"|sync|rsync|enable|disable|apply|invoke|publish|purge|restore|upload|complete|abort)(?:-|$)")
MIGRATION = {
    "flyway": {"migrate", "clean", "repair", "undo", "baseline"},
    "liquibase": {"update", "rollback", "drop-all", "update-sql"},
    "alembic": {"upgrade", "downgrade", "stamp"},
    "prisma": {"migrate", "db"},
    "knex": {"migrate:latest", "migrate:rollback", "migrate:up", "migrate:down", "seed:run"},
    "sequelize": {"db:migrate", "db:migrate:undo", "db:seed:all"},
    "rails": {"db:migrate", "db:rollback", "db:drop", "db:reset", "db:schema:load", "db:seed"},
    "rake": {"db:migrate", "db:rollback", "db:drop", "db:reset", "db:schema:load", "db:seed"},
}


def infra_write(tokens):
    head, w = tokens[0], words(tokens)
    if head in ("kubectl", "oc") and w:
        dry_run = None
        for i, token in enumerate(tokens):
            if token.startswith("--dry-run="):
                dry_run = token.split("=", 1)[1]
            elif token == "--dry-run" and i + 1 < len(tokens):
                dry_run = tokens[i + 1]
        if dry_run == "client":
            return None
        if w[0] == "rollout" and len(w) > 1 and w[1] in {"status", "history"}:
            return None
        if w[0] in KUBECTL_WRITE:
            return f"{head} {w[0]}"
        if w[0] == "config" and len(w) > 1 and w[1].startswith(("set", "use", "delete", "rename")):
            return f"{head} config {w[1]}"
    if head in ("terraform", "tofu", "terragrunt") and w:
        if w[0] in TERRAFORM_WRITE or (w[0] == "state" and len(w) > 1 and w[1] in TERRAFORM_STATE_WRITE):
            return f"{head} {' '.join(w[:2])}"
    if head == "helm" and w and w[0] in HELM_WRITE:
        return f"helm {w[0]}"
    if head in ("aws", "gcloud", "gsutil", "az"):
        # Options after the command path contain resource names, not verbs.
        command_words = []
        i = 1
        while i < len(tokens):
            token = tokens[i]
            if token.startswith("-"):
                if not command_words or (len(command_words) == 1 and token.split("=")[0] in VALUE_FLAGS.get(head, set())):
                    i += 2 if token in VALUE_FLAGS.get(head, set()) else 1
                    continue
                break
            command_words.append(token)
            i += 1
        # `run` is a gcloud service group; only its subcommands perform writes.
        if head == "gcloud" and command_words[:1] == ["run"]:
            command_words = command_words[1:]
        for word in command_words:
            if CLOUD_WRITE.match(word):
                return f"{head} ... {word}"
    if head == "prisma" and w[:2] in (["migrate", "status"], ["migrate", "diff"], ["db", "pull"]):
        return None
    if head in MIGRATION and w and w[0] in MIGRATION[head]:
        return f"{head} {' '.join(w[:2])}"
    return None


# ---------- db, git ----------

DB_CLIENTS = {"psql", "mysql", "mariadb", "mongosh", "mongo", "redis-cli", "sqlcmd", "sqlplus", "cqlsh",
              "clickhouse-client", "pgcli", "mycli", "usql"}


def git_irreversible(tokens, cwd=None, depth=0):
    if tokens[0] != "git":
        return None
    if depth > 8:
        return "recursive git alias"
    args, options, settings = tokens[1:], [], {}
    while args and args[0].startswith("-"):
        option = args.pop(0)
        options.append(option)
        if option in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}:
            if not args:
                return None
            value = args.pop(0)
            options.append(value)
            if option == "-c" and "=" in value:
                key, value = value.split("=", 1)
                settings[key.lower()] = value
        elif option.startswith("-c") and "=" in option[2:]:
            key, value = option[2:].split("=", 1)
            settings[key.lower()] = value
    # Read configuration only; git config does not run aliases or repository hooks.
    try:
        result = subprocess.run(["git", *options, "config", "--null", "--get-regexp", r"^(alias\.|remote\..*\.(mirror|push)$)"],
                                cwd=cwd, capture_output=True, text=True, timeout=2)
        for entry in result.stdout.split("\0"):
            key, sep, value = entry.partition("\n")
            if sep:
                settings.setdefault(key.lower(), value)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if args and "alias." + args[0].lower() in settings:
        alias = settings["alias." + args[0].lower()]
        if alias.startswith("!"):
            for nested in segments(alias[1:]):
                hit = git_irreversible(nested, cwd, depth + 1)
                if hit:
                    return hit
        else:
            return git_irreversible(["git", *options, *shlex.split(alias), *args[1:]], cwd, depth + 1)
    if not args or args[0] != "push":
        return None
    rest = args[1:]
    positional, short_flags, skip = [], set(), False
    for arg in rest:
        if skip:
            skip = False
            continue
        if arg in {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}:
            skip = True
        elif arg.startswith("-") and not arg.startswith("--"):
            for flag in arg[1:]:
                if flag == "o":
                    break  # The remaining characters are a push-option value.
                short_flags.add(flag)
        elif not arg.startswith("-"):
            positional.append(arg)
    remote = positional[0] if positional else None
    if any((key.endswith(".mirror") and value.lower() in {"true", "yes", "on", "1"}) or
           (key.endswith(".push") and value.startswith(("+", ":"))) for key, value in settings.items()
           if key.startswith("remote.") and (remote is None or key.rsplit(".", 1)[0] == "remote." + remote)):
        return "git push with irreversible remote configuration"
    flags = {a.split("=")[0] for a in rest if a.startswith("-")}
    if short_flags & {"f", "d"}:
        return "git push with force/delete short options"
    if flags & {"--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d", "--prune"}:
        return "git push " + " ".join(sorted(flags & {"--force", "-f", "--force-with-lease", "--force-if-includes",
                                                     "--mirror", "--delete", "-d", "--prune"}))
    if any(a.startswith(":") or a.startswith("+") for a in positional):
        return "git push with a deleting (:ref) or forced (+ref) refspec"
    return None


# ---------- entry point ----------

def check(tool_name, tool_input, allow=(), cwd=None):
    allow = set(allow)
    tool_input = tool_input or {}
    if not isinstance(tool_input, dict):
        raise ValueError("invalid tool input")
    if tool_name in READ_TOOLS or re.search(r"(?:^|[_.])(?:read_file|read_text_file|read_multiple_files)$", tool_name):
        path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        paths = tool_input.get("paths", [path])
        if isinstance(paths, str):
            paths = [paths]
        if "secrets" not in allow and any(secret_path(p, cwd) for p in paths):
            return "secrets", f"reading {os.path.basename(path)}"
        return None
    command = tool_input.get("command", tool_input.get("cmd"))
    if tool_name.endswith("write_stdin"):
        command = tool_input.get("chars")
    if isinstance(command, list):
        command = shlex.join(str(c) for c in command)
    if command is not None and not isinstance(command, str):
        raise ValueError("invalid command")
    if not isinstance(command, str) or not command.strip():
        return None
    try:
        segs = segments(command)
    except ValueError:
        # Unparseable: secrets fail closed, everything else fails open.
        if "secrets" not in allow and any(secret_path(t, cwd) for t in re.split(r"[\s'\"=<>;|&()]+", command)):
            return "secrets", "a command naming a secret file (could not be parsed)"
        return None
    for tokens in segs:
        # An open shell permits unhooked follow-up stdin on some runtimes.
        interpreter = tokens[0] in SHELLS or re.fullmatch(r"python[\d.]*", tokens[0])
        interactive = len(tokens) == 1 or all(
            re.fullmatch(r"-[ilsmrvx]+", t) or t in {"--login", "--noprofile", "--norc"}
            for t in tokens[1:])
        if interpreter and interactive:
            category = next((c for c in CATEGORIES if c not in allow), None)
            if category:
                return category, "an interactive shell permits unchecked follow-up commands"
        if "secrets" not in allow:
            metadata_only = tokens[0] in {"test", "[", "[[", "touch", "echo", "printf"} and not any("<" in t for t in tokens)
            certificate = tokens[:2] == ["openssl", "x509"] and not any(t in {"-signkey", "-CAkey", "-key"} for t in tokens)
            hit = None if metadata_only else next((t for t in tokens[1:] if
                secret_path(t.split("=", 1)[-1], cwd) and not (certificate and t.endswith(".pem"))), None)
            if hit:
                return "secrets", f"{tokens[0]} on {os.path.basename(hit.strip(chr(39) + chr(34)))}"
        if "db" not in allow and tokens[0] in DB_CLIENTS and not any(t in {"--help", "--version", "-V"} for t in tokens[1:]):
            return "db", f"interactive database client {tokens[0]}"
        if "infra" not in allow:
            hit = infra_write(tokens)
            if hit:
                return "infra", hit
        if "git" not in allow:
            hit = git_irreversible(tokens, cwd)
            if hit:
                return "git", hit
    return None
