"""Regression: git_create_tag's commit=None path.

repo.create_tag(tag_name, ref=commit) with commit=None stringifies to the
literal "None" instead of defaulting to HEAD, since GitPython/git treat a
positional ref argument as a raw string, not a Python None. Fixed by
defaulting to 'HEAD' before the call: ref = commit or 'HEAD'.
"""
import pytest

git = pytest.importorskip("git")

from src.tools.git_tools import git_create_tag


@pytest.fixture
def repo_path(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value('user', 'name', 'Test User')
        cw.set_value('user', 'email', 'test@example.com')
    (tmp_path / 'file.txt').write_text('hello')
    repo.index.add(['file.txt'])
    repo.index.commit('initial commit')
    return str(tmp_path)


def test_create_tag_with_no_commit_defaults_to_head(repo_path):
    result = git_create_tag(repo_path=repo_path, tag_name='v1')
    assert result['success'] is True
    repo = git.Repo(repo_path)
    tag = repo.tags['v1']
    assert tag.commit == repo.head.commit


def test_create_annotated_tag_with_no_commit_defaults_to_head(repo_path):
    result = git_create_tag(repo_path=repo_path, tag_name='v2', message='release')
    assert result['success'] is True
    assert result['annotated'] is True
    repo = git.Repo(repo_path)
    tag = repo.tags['v2']
    assert tag.commit == repo.head.commit


def test_create_tag_with_explicit_commit(repo_path):
    repo = git.Repo(repo_path)
    head_sha = repo.head.commit.hexsha
    result = git_create_tag(repo_path=repo_path, tag_name='v3', commit=head_sha)
    assert result['success'] is True
    tag = repo.tags['v3']
    assert tag.commit.hexsha == head_sha
