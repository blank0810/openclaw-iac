from __future__ import annotations

from pyinfra.operations import apt, files, systemd


def install_probes(agents) -> None:
    apt.packages(
        name="Install jq for Slack probes",
        packages=["jq"],
        present=True,
        _sudo=True,
    )
    files.directory(
        name="Ensure /opt/zeroclaw/bin exists",
        path="/opt/zeroclaw/bin",
        present=True,
        user="overlord101",
        group="overlord101",
        mode="750",
        _sudo=True,
    )
    files.directory(
        name="Ensure /var/lib/zeroclaw-probe exists",
        path="/var/lib/zeroclaw-probe",
        present=True,
        user="root",
        group="root",
        mode="750",
        _sudo=True,
    )
    files.template(
        name="Render shared zeroclaw-slack-probe.sh",
        src="templates/systemd/zeroclaw-slack-probe.sh.j2",
        dest="/opt/zeroclaw/bin/zeroclaw-slack-probe.sh",
        user="overlord101",
        group="overlord101",
        mode="750",
        _sudo=True,
    )

    for agent in agents:
        if not agent.get("enabled", True):
            continue
        service_name = f"zeroclaw-slack-probe-{agent['name']}"
        files.file(
            name=f"Ensure probe log exists for {agent['name']}",
            path=f"/var/log/{service_name}.log",
            present=True,
            user="root",
            group="root",
            mode="640",
            _sudo=True,
        )
        files.template(
            name=f"Render {service_name}.service",
            src="templates/systemd/zeroclaw-slack-probe.service.j2",
            dest=f"/etc/systemd/system/{service_name}.service",
            user="root",
            group="root",
            mode="644",
            agent=agent,
            _sudo=True,
        )
        files.template(
            name=f"Render {service_name}.timer",
            src="templates/systemd/zeroclaw-slack-probe.timer.j2",
            dest=f"/etc/systemd/system/{service_name}.timer",
            user="root",
            group="root",
            mode="644",
            agent=agent,
            _sudo=True,
        )
        systemd.daemon_reload(name=f"systemctl daemon-reload ({service_name})", _sudo=True)
        systemd.service(
            name=f"Enable + start {service_name}.timer",
            service=f"{service_name}.timer",
            running=True,
            enabled=True,
            _sudo=True,
        )
