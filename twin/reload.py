"""Code reload: detect when the repo's HEAD moves (new code pulled/checked out)."""

from twin import runner


class CodeWatch:
    """Records an initial HEAD; changed() reports (old, new) on a move."""

    def __init__(self) -> None:
        self._head = runner.repo_head()

    def start(self) -> None:
        self._head = runner.repo_head()

    def initial(self) -> str | None:
        return self._head

    def changed(self) -> tuple[str, str] | None:
        new = runner.repo_head()
        if self._head and new and new != self._head:
            return self._head, new
        return None
