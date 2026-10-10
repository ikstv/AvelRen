#!/usr/bin/env python3
"""Підготувати локального кандидата об'єднання; ніколи не виконувати push/deploy.

Вхід: три повні локальні mirror-копії Git. Джерела не змінюються.
Вихід: окремий bare-репозиторій, bundles, manifest та гілка codex/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Callable

PINNED = {
    "AvelRen": "4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27",
    "AvelRen-ops": "5be9da8b433813a664b4d4e21a0a92bae91c56a0",
}
BRANCH = "codex/consolidate-legacy-sources"
ARCHIVE = "legacy-repositories"
MAX_BUNDLE_BYTES = 80 * 1024 * 1024


class MigrationError(RuntimeError):
    """Помилка з безпечним для журналу повідомленням."""


def environment() -> dict[str, str]:
    # Не успадковувати сторонній index, replace refs або конфігурацію сканера.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "GITLEAKS_"))}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="AvelRen migration",
               GIT_AUTHOR_EMAIL="179980296+ikstv@users.noreply.github.com",
               GIT_COMMITTER_NAME="AvelRen migration",
               GIT_COMMITTER_EMAIL="179980296+ikstv@users.noreply.github.com")
    return env


def git(repo: Path | None, *args: str, data: bytes | None = None,
        extra_env: dict[str, str] | None = None) -> bytes:
    command = ["git", "-c", f"core.hooksPath={os.devnull}",
               "-c", "protocol.file.allow=always"]
    if repo is not None:
        command += ["-C", str(repo)]
    env = environment()
    env.update(extra_env or {})
    result = subprocess.run(command + list(args), input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, check=False)
    if result.returncode:
        # Git stderr може містити приватні шляхи або дані; не друкувати його.
        raise MigrationError(f"Git {args[0]} завершився кодом {result.returncode}.")
    return result.stdout


def refs(repo: Path) -> dict[str, str]:
    lines = git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    return dict(line.split(" ", 1) for line in lines.decode().splitlines())


def protect_output(path: Path) -> None:
    """chmod не встановлює Windows DACL; явно обмежити доступ власником."""
    if os.name != "nt":
        os.chmod(path, 0o700)
        return
    env = environment()
    def run(*args: str) -> bytes:
        result = subprocess.run(args, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
        if result.returncode:
            raise MigrationError("Не вдалося встановити й перевірити приватну Windows DACL.")
        return result.stdout
    identity = run("whoami.exe", "/user", "/fo", "csv", "/nh")
    match = re.search(rb"S-1-5-[0-9-]+", identity)
    if match is None:
        raise MigrationError("Не визначено SID поточного Windows-користувача.")
    sid = match.group().decode("ascii")
    run("icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F")
    proof = path / ".acl-verification"
    run("icacls.exe", str(path), "/save", str(proof), "/q")
    sddl = proof.read_bytes().decode("utf-16-le").lstrip("\ufeff")
    proof.unlink()
    entries = re.findall(r"\(([^()]*)\)", sddl)
    if "D:P" not in sddl or len(entries) != 1 or entries[0].split(";")[-1] != sid:
        raise MigrationError("Windows DACL містить сторонній доступ; вихід не прийнято.")


def sha(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", ref).decode().strip()


def validate_mirror(repo: Path) -> None:
    if not repo.is_dir() or git(repo, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise MigrationError("Потрібна окрема повна bare/mirror-копія, не робочий checkout.")
    if git(repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise MigrationError("Shallow-копія не зберігає повну історію.")
    if (repo / "objects/info/alternates").exists() or (repo / "info/grafts").exists():
        raise MigrationError("Alternates/grafts не підтримуються; створіть незалежний mirror.")
    if any(ref.startswith("refs/replace/") for ref in refs(repo)):
        raise MigrationError("Replace refs потребують окремого розбору.")
    if list((repo / "objects/pack").glob("*.promisor")):
        raise MigrationError("Partial clone не підтримується.")
    git(repo, "fsck", "--full", "--no-reflogs")
    sha(repo, "refs/heads/main^{commit}")


def scan_secrets(repo: Path, work: Path) -> None:
    if shutil.which("gitleaks") is None:
        raise MigrationError("Потрібен gitleaks; перевірку секретів пропускати заборонено.")
    config = work / "migration-gitleaks.toml"
    config.write_text('[extend]\nuseDefault = true\n', encoding="utf-8")
    ignore = work / "empty.gitleaksignore"
    ignore.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["gitleaks", "git", str(repo), "--log-opts=--all", "--redact=100",
         "--no-banner", "--ignore-gitleaks-allow", "--config", str(config),
         "--gitleaks-ignore-path", str(ignore)],
        cwd=work, env=environment(), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise MigrationError("Secret scan не пройшов. Кандидат не прийнятий; вміст не виводиться.")


def reject_external_objects(repo: Path) -> None:
    # Залежні репозиторії та LFS-об'єкти не містяться у звичайному Git bundle.
    raw = git(repo, "log", "--all", "--raw", "--format=", "--no-renames")
    if re.search(rb"(?m)^:(?:160000 [0-9]{6}|[0-9]{6} 160000) ", raw):
        raise MigrationError("Історія містить submodule; потрібне окреме перенесення його об'єктів.")
    listing = git(repo, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype) %(objectsize)")
    for line in listing.splitlines():
        oid, kind, size = line.split()
        if kind == b"blob" and int(size) <= 4096:
            content = git(repo, "cat-file", "blob", oid.decode())
            if content.splitlines()[:1] == [b"version https://git-lfs.github.com/spec/v1"]:
                raise MigrationError("Знайдено Git LFS pointer; LFS-дані ще не перенесені.")


def add_blob(repo: Path, env: dict[str, str], path: str, data: bytes) -> str:
    oid = git(repo, "hash-object", "-w", "--stdin", data=data).decode().strip()
    git(repo, "update-index", "--add", "--cacheinfo", "100644", oid, path, extra_env=env)
    return oid


def prepare(target: Path, sources: dict[str, Path], output: Path,
            expected: dict[str, str], expected_target: str,
            *, scanner: Callable[[Path, Path], None] = scan_secrets) -> dict:
    """Лише локальна підготовка. scanner ін'єктується тільки синтетичними тестами."""
    if set(sources) != set(PINNED):
        raise MigrationError("Потрібні рівно AvelRen та AvelRen-ops.")
    all_paths = [target.resolve(), *(p.resolve() for p in sources.values())]
    if len(set(all_paths)) != 3:
        raise MigrationError("Джерела та ціль повинні бути різними репозиторіями.")
    for repo in all_paths:
        validate_mirror(repo)
    base = sha(target, "refs/heads/main^{commit}")
    if base != expected_target:
        raise MigrationError("main цілі змінився; потрібна нова звірка, не примусовий запис.")
    if git(target, "ls-tree", "--name-only", base, "--", ARCHIVE).strip():
        raise MigrationError("Архівний каталог уже існує; автоматичне перезаписування заборонене.")
    initial_refs = {name: refs(path) for name, path in sources.items()}
    target_refs = refs(target)
    for name, path in sources.items():
        if sha(path, "refs/heads/main^{commit}") != expected[name]:
            raise MigrationError(f"main {name} не збігається з погодженим SHA.")
    if output.exists() or output.is_symlink():
        raise MigrationError("Вихідний каталог уже існує; виберіть новий, нічого не видаляється.")
    output = output.resolve()
    if any(output == p or p in output.parents for p in all_paths):
        raise MigrationError("Вихід має бути поза всіма вхідними репозиторіями.")
    # Python на Windows для mode=0700 додає explicit SYSTEM/Administrators ACE.
    # Створюємо звичайну теку, потім до запису даних встановлюємо owner-only DACL.
    output.mkdir(mode=0o777 if os.name == "nt" else 0o700, parents=False)
    protect_output(output)
    candidate = output / "candidate.git"
    for path in [target, *sources.values()]:
        scanner(path, output)
        reject_external_objects(path)
    git(None, "clone", "--mirror", "--no-hardlinks", str(target.resolve()), str(candidate))
    if sha(candidate, "refs/heads/main^{commit}") != base:
        raise MigrationError("main цілі змінився під час клонування.")
    # Вихідний mirror не повинен успадковувати push --mirror чи upstream credentials.
    git(candidate, "remote", "remove", "origin")
    if f"refs/heads/{BRANCH}" in refs(candidate):
        raise MigrationError("Гілка-кандидат уже існує; її не перезаписано.")
    index_env = {"GIT_INDEX_FILE": str(output / "candidate.index")}
    git(candidate, "read-tree", base, extra_env=index_env)
    manifest: dict = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": "ikstv/AvelRen-ORIGINAL",
        "target_base": base,
        "mode": "archive-only; active ORIGINAL tree is preserved",
        "sources": {},
        "not_transferred": ["GitHub issues/PR discussions and native numbering",
                            "release assets and secret backups", "settings, secrets, environments",
                            "local uncommitted files", "production and Google Play state"],
    }
    parents = [base]
    for name, path in sources.items():
        bundle = output / f"{name}.bundle"
        git(path, "bundle", "create", str(bundle), "--all")
        verified = output / f"{name}-verified.git"
        git(None, "clone", "--mirror", "--no-hardlinks", str(bundle), str(verified))
        git(verified, "fsck", "--full")
        if refs(verified) != initial_refs[name]:
            raise MigrationError("Відновлений bundle не відтворив усі refs.")
        if bundle.stat().st_size > MAX_BUNDLE_BYTES:
            raise MigrationError("Bundle перевищує локальний ліміт 80 MiB; потрібне інше сховище.")
        bundle_refs = dict((ref, oid) for oid, ref in
                           (line.split(" ", 1) for line in
                            git(path, "bundle", "list-heads", str(bundle)).decode().splitlines()))
        if any(bundle_refs.get(ref) != oid for ref, oid in initial_refs[name].items()):
            raise MigrationError("Bundle не містить усіх очікуваних refs.")
        git(candidate, "fetch", "--no-tags", str(bundle),
            f"refs/heads/main:refs/migration/{name}/main")
        head = expected[name]
        source_tree = sha(candidate, f"{head}^{{tree}}")
        prefix = f"{ARCHIVE}/snapshots/{name}"
        git(candidate, "read-tree", "-i", f"--prefix={prefix}/", source_tree, extra_env=index_env)
        data = bundle.read_bytes()
        bundle_path = f"{ARCHIVE}/git/{name}.bundle"
        bundle_blob = add_blob(candidate, index_env, bundle_path, data)
        manifest["sources"][name] = {
            "repository": f"ikstv/{name}", "main": head, "tree": source_tree,
            "refs": initial_refs[name], "snapshot": prefix,
            "bundle": bundle_path, "bundle_blob": bundle_blob,
            "bundle_sha256": hashlib.sha256(data).hexdigest(),
            "bundle_bytes": len(data),
        }
        if head not in parents:
            parents.append(head)
    note = (
        "# Архіви вихідних репозиторіїв\n\n"
        "Чинний код — у корені AvelRen-ORIGINAL. snapshots/ — незмінні старі\n"
        "дерева, не другий deployment root і не готові production-інструкції.\n"
        "Не запускати старі workflow/скрипти та не застосовувати старі міграції.\n"
        "git/*.bundle зберігають усі refs, доступні у вхідних mirror-копіях.\n"
        "Історії main також приєднані батьками архівного merge-коміту.\n"
        "Інші гілки та теги відновлюються з bundle без втрати їхніх SHA.\n"
        "GitHub-метадані, secrets, releases та production не перенесені цим кроком.\n"
        "Повний перелік — MANIFEST.json. Архівування не є функціональним прийманням.\n"
    )
    add_blob(candidate, index_env, f"{ARCHIVE}/README.md", note.encode())
    add_blob(candidate, index_env, f"{ARCHIVE}/MANIFEST.json",
             (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
    tree = git(candidate, "write-tree", extra_env=index_env).decode().strip()
    # Довести, що жодний старий файл ORIGINAL не змінений і не видалений.
    changes = git(candidate, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", base, tree)
    if any(not path.startswith((ARCHIVE + "/").encode()) for path in changes.split(b"\0") if path):
        raise MigrationError("Зміна вийшла за межі архівного каталогу.")
    for source in manifest["sources"].values():
        if sha(candidate, f"{tree}:{source['snapshot']}") != source["tree"]:
            raise MigrationError("Дерево джерела не збігається зі збереженим знімком.")
    for name, path in sources.items():
        if refs(path) != initial_refs[name]:
            raise MigrationError("Джерело змінилося під час підготовки; кандидат не прийнятий.")
    if refs(target) != target_refs:
        raise MigrationError("Refs цілі змінилися під час підготовки.")
    parent_args = [arg for parent in parents for arg in ("-p", parent)]
    commit = git(candidate, "commit-tree", tree, *parent_args,
                 data="Архівно об'єднати AvelRen та AvelRen-ops без зміни чинного коду\n".encode()).decode().strip()
    git(candidate, "update-ref", f"refs/heads/{BRANCH}", commit, "0" * len(commit))
    git(candidate, "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}")
    git(candidate, "fsck", "--full")
    scanner(candidate, output)
    receipt = {"status": "local_candidate_only", "commit": commit,
               "branch": BRANCH, "tree": tree, "manifest": manifest,
               "github_push_performed": False, "production_changed": False}
    (output / "RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("target", "avelren", "ops", "output"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--expected-target", required=True)
    args = parser.parse_args()
    try:
        receipt = prepare(args.target, {"AvelRen": args.avelren, "AvelRen-ops": args.ops},
                          args.output, PINNED, args.expected_target)
    except (MigrationError, OSError, ValueError) as exc:
        print(f"Підготовку зупинено: {exc}", file=sys.stderr)
        return 1
    print(f"Локальний кандидат: {receipt['commit']}; GitHub/main та production не змінені.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
