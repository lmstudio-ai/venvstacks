"""Render information specifically for terminal/console display."""

from typing import Iterable

from rich.tree import Tree

from ..stacks import StackStatus, LayerStatus, _format_json, format_env_status


def _add_envs_to_ui_tree(
    tree: Tree,
    category_label: str,
    env_statuses: Iterable[LayerStatus],
) -> None:
    category_branch = tree.add(category_label)
    for env_status in env_statuses:
        env_branch = category_branch.add(format_env_status(env_status))
        dep_statuses = env_status.get("dependencies", None)
        if dep_statuses:
            for dep_status in dep_statuses:
                env_branch.add(format_env_status(dep_status))


def format_stack_status(stack_status: StackStatus, *, json: bool) -> str | Tree:
    if json:
        return _format_json(stack_status)
    stack_tree = Tree(stack_status["spec_name"])
    category_branches = (
        ("Runtimes", stack_status["runtimes"]),
        ("Frameworks", stack_status["frameworks"]),
        ("Applications", stack_status["applications"]),
    )
    for category, envs in category_branches:
        _add_envs_to_ui_tree(stack_tree, category, envs)
    return stack_tree
