Use this as the agent’s implementation plan.

This migration should do three things in one pass: rebrand Superloop to Autoloop, move to a standard src/ layout, and make the project directly publishable to PyPI with pyproject.toml. That layout is a good fit here because it keeps importable code out of the repo root and reduces accidental imports from the working tree. Current PyPA guidance is to declare metadata in pyproject.toml, expose the CLI with [project.scripts], keep runtime data inside the package, and declare runtime files with setuptools package-data.

Your current code should target Python 3.10+, not 3.7+. It uses argparse.BooleanOptionalAction, which was added in Python 3.9, and X | Y union syntax, which arrived with PEP 604 in Python 3.10. For packaging, stay with a regular package and add __init__.py; PyPA still recommends that as the normal starting point.

1. Freeze the public naming

The agent should treat these names as final:
- PyPI distribution name: autoloop
- Import package: autoloop
- Console command: autoloop
- Runtime state directory: .autoloop
- Primary config names: autoloop.yaml, autoloop.config

For the first Autoloop release, I recommend read-only backward compatibility for old state and config names:
- legacy state dir: .superloop
- legacy config names: superloop.yaml, superloop.config

That means: new runs write to .autoloop, but --resume can still detect and read an existing .superloop workspace.

2. Target directory layout

The final tree should be:
.
├── pyproject.toml
├── README.md
├── LICENSE
├── install_autoloop.sh
├── requirements-dev.txt
├── src/
│   └── autoloop/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── loop_control.py
│       ├── templates/
│       └── skill/
│           └── SKILL.md
└── tests/

3. Move and rename files

The agent should perform these moves first:

mkdir -p src/autoloop/templates
mkdir -p src/autoloop/skill

git mv superloop.py src/autoloop/cli.py
git mv loop_control.py src/autoloop/loop_control.py
git mv install_superloop.sh install_autoloop.sh
git mv Readme.md README.md
git mv templates/* src/autoloop/templates/
git mv skills/superloop/SKILL.md src/autoloop/skill/SKILL.md

Then remove now-empty legacy directories if they are empty.

4. Add the package scaffold

Create src/autoloop/__init__.py:

"""Autoloop package."""

Create src/autoloop/__main__.py:

from .cli import main

raise SystemExit(main())

Do not create main.py.

5. Update Python imports and packaging-sensitive logic

Required code edit
In src/autoloop/cli.py, change the top-level import to a package-relative import.

Rebranding replacements
The agent should do a repo-wide replacement of these categories:
- Superloop → Autoloop
- superloop → autoloop
- .superloop → .autoloop
- SUPERLOOP_ → AUTOLOOP_
- superloop: commit prefixes → autoloop:
- superloop-installer log prefix → autoloop-installer

Important correctness fix
Replace repo-root config lookup with:
- user config directory: ~/.config/autoloop/ or $XDG_CONFIG_HOME/autoloop/
- workspace config directory: selected --workspace root
Search these for autoloop.yaml/autoloop.config and optional legacy names.

State-directory selection
Add constants:
- STATE_DIRNAME = ".autoloop"
- LEGACY_STATE_DIRNAME = ".superloop"

Centralize state-root resolution:
- new runs prefer .autoloop
- resume/list tasks fallback to .superloop with warning if needed

6. Update all runtime paths in prompts and docs

All templates under src/autoloop/templates/ should use .autoloop paths.
Also update command examples to autoloop --help and related path references.

Skill file correction:
- replace stale run_log.md reference with raw_phase_log.md and events.jsonl

7. Rewrite installer

install_autoloop.sh should:
1) require Python 3.10+
2) create venv
3) run pip install "$REPO_ROOT" in venv
4) create launcher exec "$VENV_DIR/bin/autoloop" "$@"
5) install skill from src/autoloop/skill/SKILL.md
6) rename env vars:
   SUPERLOOP_INSTALL_ROOT -> AUTOLOOP_INSTALL_ROOT
   SUPERLOOP_BIN_DIR -> AUTOLOOP_BIN_DIR
   SUPERLOOP_SKIP_PIP_UPGRADE -> AUTOLOOP_SKIP_PIP_UPGRADE
   SUPERLOOP_SKIP_DEP_INSTALL -> AUTOLOOP_SKIP_DEP_INSTALL

8. Create pyproject.toml

Use the provided pyproject content with setuptools build backend, project metadata, project.scripts autoloop = autoloop.cli:main, src package discovery, and package-data for templates/*.md and skill/SKILL.md.

9. Add/update ancillary files

README.md updates:
- # Autoloop
- pip install autoloop
- autoloop --help
- Python 3.10+
- codex required, git optional with --no-git

LICENSE:
- add MIT text if MIT

requirements-dev.txt:
-e .
build
twine
pytest

.gitignore include:
build/
dist/
*.egg-info/
.venv/

10. Add minimal tests
- tests/test_imports.py imports autoloop.cli and autoloop.loop_control
- tests/test_module_entrypoint.py runs python -m autoloop --help and exit 0
- tests/test_resources.py verifies plan_producer.md present in installed package

11. Verification checklist
Run:
rg -n "superloop|Superloop|\.superloop|SUPERLOOP_|install_superloop|skills/superloop" .
python -m pip install --upgrade pip
python -m pip install -e .
autoloop --help
python -m autoloop --help
pytest

12. Build and inspect artifacts
python -m pip install --upgrade build
python -m build
python -m zipfile -l dist/*.whl | grep -E "templates|skill"
tar -tf dist/*.tar.gz | grep -E "templates|skill|README|LICENSE"

13. Publish flow
Use twine upload commands for TestPyPI then real PyPI.

14. Final acceptance criteria
- editable install works
- autoloop CLI/module help work
- no non-legacy branding remains
- runtime writes under .autoloop
- templates + skill in wheel
- README + LICENSE present
- TestPyPI upload succeeds
- fresh install works

Be strict about config lookup fix when moving to src/autoloop/cli.py.
