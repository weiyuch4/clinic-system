"""Clinic separation audit: finds calls that leave out clinic_id and silently fall back to clinic 1.
Most data functions take `clinic_id: int = 1`, so a call that forgets it shows clinic 1's patients
to whoever made the request. Run before pushing anything that adds or changes queries:
    python tools/clinic_scope_audit.py
Exits 1 when it finds a call that isn't in ALLOWED. Static check only — no server or database needed."""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ["auth", "contacts", "directory", "inventory", "lab_report", "line_service", "broadcast_service",
           "ai_agent_service", "review_service", "settings", "database", "lab_results", "main", "scheduler"]
ALIASES = {"_settings": "settings"}

# First-run setup creates clinic 1 on an empty database; these calls mean clinic 1 on purpose.
ALLOWED = {("main", "auth.has_any_users"), ("main", "contacts.get_nurses"), ("main", "contacts.add_nurse")}


def main() -> int:
    funcs = {}  # (module, name) -> position of clinic_id among positional params (None = keyword-only)
    trees = {}
    for m in MODULES:
        path = os.path.join(REPO, m + ".py")
        if not os.path.exists(path):
            continue
        trees[m] = tree = ast.parse(open(path, encoding="utf-8").read())
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = [a.arg for a in node.args.args]
            if "clinic_id" in names:
                idx = names.index("clinic_id")
                if idx >= len(names) - len(node.args.defaults):  # only defaulted params can be left out
                    funcs[(m, node.name)] = idx
            elif "clinic_id" in [a.arg for a in node.args.kwonlyargs]:
                funcs[(m, node.name)] = None

    found = []
    for m, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                key = (ALIASES.get(f.value.id, f.value.id), f.attr)
            elif isinstance(f, ast.Name):
                key = (m, f.id)
            else:
                continue
            if key not in funcs:
                continue
            idx = funcs[key]
            if any(k.arg in ("clinic_id", None) for k in node.keywords):
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            if idx is not None and len(node.args) > idx:
                continue
            name = f"{key[0]}.{key[1]}"
            if (m, name) not in ALLOWED:
                found.append(f"{m}.py:{node.lineno}  {name}() called without clinic_id")

    for line in found:
        print(line)
    print(f"{len(funcs)} functions take clinic_id; {len(found)} call(s) fall back to clinic 1")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
