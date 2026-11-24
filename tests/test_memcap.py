import os
import subprocess
from pathlib import Path

from twin import memcap


def test_cap_gb_defaults_per_kind():
    assert memcap.cap_gb("area-merge") == 20.0
    for k in ("stage", "run", "rerun", "eval", "publish", "prgate"):
        assert memcap.cap_gb(k) == 8.0
    assert memcap.cap_gb("unknown-kind") == 8.0


def test_cap_gb_job_override_wins(monkeypatch):
    monkeypatch.delenv("TWIN_MEM_CAP_RUN_GB", raising=False)
    assert memcap.cap_gb("run", {"mem_cap_gb": 5}) == 5.0


def test_cap_gb_rejects_bool_and_nan(monkeypatch):
    monkeypatch.delenv("TWIN_MEM_CAP_RUN_GB", raising=False)
    for bad in ("x", 0, -1, True, False, float("nan")):
        if bad == "x":
            job = {"mem_cap_gb": bad}
        else:
            job = {"mem_cap_gb": bad}
        # capture stderr not required; just falls through
        val = memcap.cap_gb("run", job)
        assert val == 8.0


def test_cap_gb_env_overrides_kind_and_stage(monkeypatch):
    monkeypatch.setenv("TWIN_MEM_CAP_AREA_MERGE_GB", "32")
    monkeypatch.setenv("TWIN_MEM_CAP_STAGE_GB", "6")
    monkeypatch.setenv("TWIN_MEM_CAP_STAGE_LOAD_GB", "3")
    assert memcap.cap_gb("area-merge") == 32.0
    assert memcap.cap_gb("stage") == 6.0
    assert memcap.cap_gb("stage", stage="load") == 3.0
    # stage var wins over kind var for load stage
    assert memcap.cap_gb("stage", stage="load") == 3.0


def _fake_root(tmp_path):
    root = tmp_path / "cgroup"
    # two levels: root (no memory) -> child (memory in subtree_control)
    child = root / "user.slice"
    child.mkdir(parents=True)
    (root / "cgroup.subtree_control").write_text("")
    (child / "cgroup.subtree_control").write_text("cpu memory")
    # worker cgroup under child
    worker = child / "app.slice"
    worker.mkdir()
    (worker / "cgroup.subtree_control").write_text("")
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text(f"0::/{worker.relative_to(root)}\n")
    return root, worker, proc


def test_cap_root_walks_up_to_the_memory_delegated_ancestor(tmp_path):
    root, _worker, proc = _fake_root(tmp_path)
    res = memcap._cap_root(root=root, proc_cgroup=proc)
    assert res == root / "user.slice"


def test_probe_creates_and_removes_a_capped_probe_child(tmp_path):
    root, _worker, _proc = _fake_root(tmp_path)
    caproot = root / "user.slice"
    res = memcap._probe_cgroup(caproot)
    assert res == caproot
    # probe dir gone
    probes = list(caproot.glob("twin-cap-probe-*"))
    assert probes == []


def test_enter_scope_zero_cap_is_a_noop(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    assert l.enter(0.0, "k") is False
    assert not (root / "twin-cap-k").exists()


def test_enter_scope_writes_memory_max_and_swap_into_child_cgroup(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    assert l.enter(8.0, "k") is True
    scope = root / "twin-cap-k"
    assert (scope / "memory.max").read_text() == "8589934592"
    assert (scope / "memory.swap.max").read_text() == "0"
    assert (scope / "cgroup.procs").read_text().strip() == str(os.getpid())


def test_enter_scope_reuses_an_existing_scope_directory(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    scope = root / "twin-cap-k"
    scope.mkdir()
    (scope / "memory.max").write_text("1")
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    # empty procs -> reuses/overwrites
    assert l.enter(8.0, "k") is True
    assert (scope / "memory.max").read_text() == "8589934592"


def test_enter_scope_removes_a_stale_same_key_directory(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    scope = root / "twin-cap-k"
    scope.mkdir()
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    assert l.enter(8.0, "k") is True
    assert scope.exists()


def test_enter_refuses_a_scope_with_live_procs(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    scope = root / "twin-cap-k"
    scope.mkdir()
    (scope / "cgroup.procs").write_text("12345\n")
    (scope / "memory.max").write_text("ORIGINAL")
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    assert l.enter(8.0, "k") is False
    assert (scope / "memory.max").read_text() == "ORIGINAL"


def test_oom_killed_reads_memory_events(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    scope = root / "twin-cap-k"
    scope.mkdir()
    (scope / "memory.events").write_text("oom_kill 1\n")
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    assert l.oom_killed("k") is True


def test_oom_killed_without_cgroup_is_false():
    l = memcap.Launcher(None, None)
    memcap.set_launcher(l)
    assert l.oom_killed("k") is False
    assert memcap.oom_killed("k") is False


def test_cleanup_without_cgroup_is_a_noop():
    l = memcap.Launcher(None, None)
    memcap.set_launcher(l)
    l.cleanup("k")  # no exception
    memcap.cleanup_scope("k")


def test_oom_killed_ignores_a_stale_scope(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    other = root / "twin-cap-other"
    other.mkdir()
    (other / "memory.events").write_text("oom_kill 1\n")
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    assert l.oom_killed("k") is False


def test_cleanup_scope_removes_an_empty_scope(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    scope = root / "twin-cap-k"
    scope.mkdir()
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    memcap.cleanup_scope("k")
    assert not scope.exists()


def test_cleanup_scope_leaves_nonempty_dir(tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    scope = root / "twin-cap-k"
    scope.mkdir()
    (scope / "cgroup.procs").write_text("999\n")
    l = memcap.Launcher(None, root)
    memcap.set_launcher(l)
    l.cleanup("k")  # rmdir fails, ignored
    assert scope.exists()


def test_launcher_probe_runs_the_capped_argv(monkeypatch):
    calls = {}

    def fake_which(name):
        return "/usr/bin/systemd-run"

    def fake_run(argv, **kw):
        calls["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(memcap.shutil, "which", fake_which)
    monkeypatch.setattr(memcap.subprocess, "run", fake_run)
    monkeypatch.setattr(memcap, "_cap_root", lambda *a, **k: None)
    monkeypatch.setattr(memcap, "_probe_cgroup", lambda *a, **k: None)
    memcap.set_launcher(None)
    l = memcap.launcher()
    assert l.systemd == "/usr/bin/systemd-run"
    assert calls["argv"] == [
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "-p",
        "MemoryMax=1073741824",
        "-p",
        "MemorySwapMax=0",
        "--",
        "true",
    ]


def test_launcher_present_but_unusable_is_uncapped(monkeypatch):
    def fake_which(name):
        return "/usr/bin/systemd-run"

    def fake_run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(memcap.shutil, "which", fake_which)
    monkeypatch.setattr(memcap.subprocess, "run", fake_run)
    monkeypatch.setattr(memcap, "_cap_root", lambda *a, **k: None)
    monkeypatch.setattr(memcap, "_probe_cgroup", lambda *a, **k: None)
    memcap.set_launcher(None)
    l = memcap.launcher()
    assert l.systemd is None


def test_launcher_absent_warns_once_and_runs_uncapped(monkeypatch, capsys):
    monkeypatch.setattr(memcap.shutil, "which", lambda name: None)
    monkeypatch.setattr(memcap, "_cap_root", lambda *a, **k: None)
    monkeypatch.setattr(memcap, "_probe_cgroup", lambda *a, **k: None)
    memcap.set_launcher(None)
    memcap.launcher()
    memcap.scope_argv(["echo", "hi"], 1.0)
    err = capsys.readouterr().err
    assert err.count("WARNING") == 1
    assert "caps NOT enforced (headroom check still applies)" in err


def test_launcher_systemd_only_reports_child_cgroups_none(monkeypatch, capsys):
    monkeypatch.setattr(memcap.shutil, "which", lambda name: "/usr/bin/systemd-run")

    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(memcap.subprocess, "run", fake_run)
    monkeypatch.setattr(memcap, "_cap_root", lambda *a, **k: None)
    monkeypatch.setattr(memcap, "_probe_cgroup", lambda *a, **k: None)
    memcap.set_launcher(None)
    l = memcap.launcher()
    assert l.systemd == "/usr/bin/systemd-run"
    assert l.cgroup is None
    err = capsys.readouterr().err
    assert "shell=systemd-run" in err
    assert "child-cgroups=none" in err


def test_launcher_cgroup_only_reports_shell_uncapped(monkeypatch, capsys, tmp_path):
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cgroup.subtree_control").write_text("memory")
    monkeypatch.setattr(memcap.shutil, "which", lambda name: None)
    monkeypatch.setattr(memcap, "_cap_root", lambda *a, **k: root)
    monkeypatch.setattr(memcap, "_probe_cgroup", lambda r: r)
    memcap.set_launcher(None)
    l = memcap.launcher()
    assert l.systemd is None
    assert l.cgroup == root
    err = capsys.readouterr().err
    assert "shell=UNCAPPED" in err
    assert f"child-cgroups={root}" in err


def test_scope_argv_carries_memory_max_and_swap_off(monkeypatch):
    l = memcap.Launcher("/usr/bin/systemd-run", None)
    memcap.set_launcher(l)
    out = memcap.scope_argv(["echo", "hi"], 20.0)
    assert out == [
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "-p",
        "MemoryMax=21474836480",
        "-p",
        "MemorySwapMax=0",
        "--",
        "echo",
        "hi",
    ]


def test_headroom_reason_holds_under_ten_gb(monkeypatch):
    reader = lambda: (44.0, 64.0)  # used, total -> available 20.0
    r = memcap.headroom_reason("area-merge", reader=reader)
    assert r == "area-merge needs 20.0 GB cap + 10.0 GB headroom; 20.0 GB available"


def test_headroom_reason_passes_at_ten_gb_or_more():
    assert memcap.headroom_reason("area-merge", reader=lambda: (34.0, 64.0)) is None
    assert memcap.headroom_reason("area-merge", reader=lambda: (10.0, 64.0)) is None


def test_headroom_reason_reader_error_does_not_block(capsys):
    def bad():
        raise OSError("nope")

    r = memcap.headroom_reason("area-merge", reader=bad)
    assert r is None
    err = capsys.readouterr().err
    assert "WARNING" in err


def test_cap_killed_requires_cgroup_or_text():
    assert memcap.cap_killed(137) is False
    assert memcap.cap_killed(137, cgroup_oom=True) is True
    assert memcap.cap_killed(0, text="oom-kill here") is True


def test_oom_in_text_markers():
    assert memcap.oom_in_text("oom-kill") is True
    assert memcap.oom_in_text("Memory cgroup out of memory") is True
    assert memcap.oom_in_text("Killed process 123") is True
    assert memcap.oom_in_text("normal exit") is False


def test_launcher_available_property():
    assert memcap.Launcher("/x", None).available is True
    assert memcap.Launcher(None, Path("/tmp")).available is True
    assert memcap.Launcher(None, None).available is False
