from apps.orchestrator.jobs import JobStore
from apps.orchestrator.provisioner import GATEWAY_PORT, provision_agent
from lib.config import load_config
from tests.test_config import _write_agent, _write_env


class _FakeContainer:
    status = "running"


class _FakeContainers:
    def __init__(self):
        self.run_kwargs = None

    def run(self, **kw):
        self.run_kwargs = kw
        return _FakeContainer()


class _FakeNetworks:
    def __init__(self):
        self.created = []

    def list(self, names=None):
        return []

    def create(self, name, **kw):
        self.created.append(name)


class _FakeImages:
    def __init__(self):
        self.pulled = []

    def pull(self, image):
        self.pulled.append(image)


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()
        self.networks = _FakeNetworks()
        self.images = _FakeImages()


def _agent(tmp_path):
    _write_env(tmp_path)
    _write_agent(tmp_path, "acme")
    return load_config(tmp_path).agents[0]


def test_provision_success(tmp_path):
    agent = _agent(tmp_path)
    store = JobStore()
    job = store.create()
    client = _FakeClient()
    provision_agent(
        client,
        store,
        job.job_id,
        agent,
        image="img:1",
        states_base=tmp_path / "states",
        project_root=tmp_path,
        server_ip="1.2.3.4",
    )
    final = store.get(job.job_id)
    assert final.status == "succeeded"
    assert final.result.container_name == "zeroclaw-acme"
    assert final.result.server_ip == "1.2.3.4"
    assert final.result.host == "1.2.3.4"
    assert final.result.gateway_port == GATEWAY_PORT
    assert final.result.status == "running"
    assert client.networks.created == ["zc-acme"]
    assert client.images.pulled == ["img:1"]
    assert client.containers.run_kwargs["name"] == "zeroclaw-acme"
    # config rendered to the state dir
    assert (tmp_path / "states" / "acme" / ".zeroclaw" / "config.toml").exists()


def test_provision_tracks_all_steps(tmp_path):
    agent = _agent(tmp_path)
    store = JobStore()
    job = store.create()
    provision_agent(
        _FakeClient(),
        store,
        job.job_id,
        agent,
        image="img:1",
        states_base=tmp_path / "states",
        project_root=tmp_path,
        server_ip="1.2.3.4",
    )
    final = store.get(job.job_id)
    step_names = [s.name for s in final.steps]
    assert step_names == ["render_config", "ensure_network", "pull_image", "run_container"]
    assert all(s.status == "succeeded" for s in final.steps)


def test_provision_unexpected_error_marks_failed(tmp_path):
    agent = _agent(tmp_path)
    store = JobStore()
    job = store.create()
    client = _FakeClient()

    def boom(**kw):
        raise RuntimeError("daemon down")

    client.containers.run = boom
    provision_agent(
        client,
        store,
        job.job_id,
        agent,
        image="i",
        states_base=tmp_path / "states",
        project_root=tmp_path,
        server_ip="1.2.3.4",
    )
    final = store.get(job.job_id)
    assert final.status == "failed"
    assert "daemon down" in final.error


def test_provision_skips_existing_network(tmp_path):
    agent = _agent(tmp_path)
    store = JobStore()
    job = store.create()
    client = _FakeClient()
    client.networks.list = lambda names=None: [object()]  # already exists
    provision_agent(
        client,
        store,
        job.job_id,
        agent,
        image="i",
        states_base=tmp_path / "states",
        project_root=tmp_path,
        server_ip="1.2.3.4",
    )
    assert client.networks.created == []  # not re-created
