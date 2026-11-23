import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD = (ROOT / 'buildspec.yml').read_text(encoding='utf-8')

# Each Lambda package (buildspec.yml) and the handlers that run from it (infra/template.yaml).
HANDLERS = {
    'API backend': ['lambda_handler', 'public_move_sync_handler', 'realtime_handler'],
    'message stream': ['message_stream_handler'],
    'lead-followup': ['handler'],
    'lead-duplicate': ['handler'],
}


def package_files(name):
    """The files buildspec.yml copies into a package, as paths in the repository keyed by their path in the package."""
    section = BUILD.split(f'echo "Packaging {name} Lambda"')[1].split('echo "Packaging')[0]
    folder = ROOT / re.search(r'cd \$CODEBUILD_SRC_DIR/(\S+)', section).group(1)
    files = {}
    for line in section.splitlines():
        match = re.search(r'- cp (-r )?(.+?) \./[\w-]*package/?(\S*)$', line.strip())
        if not match:
            continue
        recursive, sources, target = match.groups()
        for source in sources.split():
            source = source.replace('$CODEBUILD_SRC_DIR', str(ROOT))
            paths = sorted(folder.glob(source)) if '*' in source else [folder / source if not Path(source).is_absolute() else Path(source)]
            for path in paths:
                base = Path(target) if target and recursive else Path(path.name)
                for file in ([path] if path.is_file() else path.rglob('*.py')):
                    files[(base / file.relative_to(path)).as_posix() if path.is_dir() else base.as_posix()] = file
    return folder, files


def missing_modules(name):
    """Our own modules a package's handlers import, directly or through other modules, that the package does not ship."""
    folder, files = package_files(name)
    shipped = {Path(path).with_suffix('').as_posix().replace('/', '.').removesuffix('.__init__') for path in files if path.endswith('.py')}
    ours = {path.stem for path in folder.glob('*.py')} | {path.name for path in folder.iterdir() if path.is_dir()} | {'libs'}
    missing, seen, queue = set(), set(), list(HANDLERS[name])
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        path = next((files[key] for key in (module.replace('.', '/') + '.py', module.replace('.', '/') + '/__init__.py') if key in files), None)
        if path is None:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            for imported in names:
                if imported.split('.')[0] not in ours:
                    continue  # Installed from the package's requirements, not our code.
                if imported not in shipped and not any(item.startswith(imported + '.') for item in shipped):
                    missing.add(f'{imported} (imported by {module})')
                queue.append(imported)
    return missing


# Imports inside functions the message Lambda never runs; checked by hand. Anything else missing fails the test.
NEVER_RUN = {'message stream': {
    # Pricing plan helpers on models.PricingPlan; the message Lambda does not read pricing plans.
    *(f'{module} (imported by models)' for module in ('bulky_items', 'delivery_fees', 'elevator_pricing', 'extra_stops', 'long_carry_pricing',
                                                       'long_distance_packing', 'pickup_areas', 'shuttle', 'stairs_pricing', 'storage_pricing')),
    # followup_tasks.history and first_contact_state.add_created_lead run when a lead is created, in the API.
    'db (imported by followup_tasks)', 'libs.common.phone (imported by followup_tasks)',
    'routes.unanswered_messages (imported by first_contact_state)',
}}


@pytest.mark.parametrize('name', HANDLERS)
def test_every_lambda_ships_every_module_its_handlers_import(name):
    """A module a Lambda imports but its package leaves out fails it at startup or when that code runs, as when
    the message Lambda stopped saving messages and calls."""
    assert missing_modules(name) - NEVER_RUN.get(name, set()) == set()


def test_message_stream_lambda_starts_with_only_its_packaged_files(tmp_path):
    _, files = package_files('message stream')
    for path, source in files.items():
        shutil.copy(source, tmp_path / path)
    result = subprocess.run([sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, "."); import message_stream_handler'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]


def module_level_imports(tree):
    """The modules a file imports when it loads: its imports outside functions."""
    found, nodes = [], list(tree.body)
    while nodes:
        node = nodes.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # Runs only when called.
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found += [node.module] + [f'{node.module}.{alias.name}' for alias in node.names]
        nodes.extend(ast.iter_child_nodes(node))
    return found


@pytest.mark.parametrize('name', ['API backend'])
def test_no_packaged_module_loads_a_dialect_the_package_removes(name):
    """The API package deletes SQLAlchemy's mssql, mysql, oracle and sqlite dialects (buildspec.yml): a module that
    imports one when it loads fails on the Lambda, and every request failed with it. Inside a function (run only on
    that database) is fine."""
    removed = re.search(r'rm -rf \./package/boto3\*.*', BUILD).group(0)
    dialects = {f'sqlalchemy.dialects.{dialect}' for dialect in re.findall(r'\./package/sqlalchemy/dialects/(\w+)', removed)}
    assert 'sqlalchemy.dialects.sqlite' in dialects
    _, files = package_files(name)
    loading = {f'{path} imports {module}'
               for path, source in files.items() if path.endswith('.py')
               for module in module_level_imports(ast.parse(source.read_text(encoding='utf-8-sig')))
               if any(module == dialect or module.startswith(dialect + '.') for dialect in dialects)}
    assert loading == set()
