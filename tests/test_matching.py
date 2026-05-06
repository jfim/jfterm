from jfterm.matching import is_inside, matching_projects
from jfterm.models import Project


def _proj(name: str, directory: str) -> Project:
    return Project(name=name, directory=directory)


def test_is_inside_exact_match():
    assert is_inside("/code/a", "/code/a")


def test_is_inside_descendant():
    assert is_inside("/code/a/sub/file", "/code/a")


def test_is_inside_sibling_is_false():
    assert not is_inside("/code/b", "/code/a")


def test_is_inside_prefix_but_not_descendant_is_false():
    # /code/abc is NOT inside /code/ab
    assert not is_inside("/code/abc", "/code/ab")


def test_is_inside_handles_trailing_slashes():
    assert is_inside("/code/a/", "/code/a")
    assert is_inside("/code/a", "/code/a/")


def test_is_inside_none_cwd_is_false():
    assert not is_inside(None, "/code/a")


def test_matching_projects_deepest_first():
    monorepo = _proj("monorepo", "/code/monorepo")
    webapp = _proj("webapp", "/code/monorepo/webapp")
    other = _proj("other", "/code/other")
    cwd = "/code/monorepo/webapp/src"
    assert matching_projects(cwd, [monorepo, webapp, other]) == [webapp, monorepo]


def test_matching_projects_no_match():
    a = _proj("a", "/code/a")
    assert matching_projects("/tmp/somewhere", [a]) == []


def test_matching_projects_unknown_cwd():
    a = _proj("a", "/code/a")
    assert matching_projects(None, [a]) == []
