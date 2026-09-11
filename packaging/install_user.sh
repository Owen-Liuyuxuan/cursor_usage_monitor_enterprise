#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_root="${XDG_DATA_HOME:-${HOME}/.local/share}"
config_root="${XDG_CONFIG_HOME:-${HOME}/.config}"
local_bin="${HOME}/.local/bin"
python_site="$(python3 -m site --user-site)"
extension_dir="${data_root}/gnome-shell/extensions/cursor-usage-supervisor@owen.local"

install -d "${python_site}/cursor_usage_supervisor" "${local_bin}" \
  "${config_root}/systemd/user" "${data_root}/dbus-1/services" "${extension_dir}"
install -m 0644 "${project_dir}"/src/cursor_usage_supervisor/*.py \
  "${python_site}/cursor_usage_supervisor/"
install -m 0644 "${project_dir}"/extension/* "${extension_dir}/"

cat > "${local_bin}/cursor-usage-supervisor" <<'EOF'
#!/usr/bin/env bash
exec python3 -m cursor_usage_supervisor.preferences "$@"
EOF
cat > "${local_bin}/cursor-usage-supervisor-service" <<'EOF'
#!/usr/bin/env bash
exec python3 -m cursor_usage_supervisor.service "$@"
EOF
cat > "${local_bin}/cursor-usage-supervisor-preferences" <<'EOF'
#!/usr/bin/env bash
exec python3 -m cursor_usage_supervisor.preferences "$@"
EOF
chmod 0755 "${local_bin}"/cursor-usage-supervisor*

install -m 0644 "${project_dir}/packaging/cursor-usage-supervisor.service" \
  "${config_root}/systemd/user/cursor-usage-supervisor.service"
sed -i "s|ExecStart=/usr/bin/cursor-usage-supervisor-service|ExecStart=%h/.local/bin/cursor-usage-supervisor-service|" \
  "${config_root}/systemd/user/cursor-usage-supervisor.service"
cat > "${data_root}/dbus-1/services/io.github.owen.CursorUsageSupervisor.service" <<EOF
[D-BUS Service]
Name=io.github.owen.CursorUsageSupervisor
Exec=${local_bin}/cursor-usage-supervisor-service
SystemdService=cursor-usage-supervisor.service
EOF

systemctl --user daemon-reload
systemctl --user restart cursor-usage-supervisor.service

echo "Installed Cursor Usage Supervisor for ${USER}."
echo "Reload GNOME Shell, then enable cursor-usage-supervisor@owen.local."
