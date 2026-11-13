"""Shared helpers for the project's tests. Standard library only."""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path(*parts):
    return os.path.join(ROOT, *parts)


def read_text(*parts):
    with open(path(*parts), encoding="utf-8") as f:
        return f.read()


def parse(*parts):
    return ast.parse(read_text(*parts))


def constants(tree):
    """Module-level NAME = <literal> assignments of a parsed Python file."""
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return values


def pipeline_tables(tree):
    """The @dp.table decorators of a pipeline file, as {table name: {keyword: value node}}."""
    tables = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "table"):
                kwargs = {k.arg: k.value for k in dec.keywords}
                name = ast.literal_eval(kwargs["name"]) if "name" in kwargs else node.name
                tables[name] = kwargs
    return tables
