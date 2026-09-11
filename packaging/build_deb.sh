#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "${project_dir}/pyproject.toml")"
package_root="$(mktemp -d)"
trap 'rm -rf -- "${package_root}"' EXIT
chmod 0755 "${package_root}"

install -d "${package_root}/DEBIAN" \
  "${package_root}/usr/lib/python3/dist-packages/cursor_usage_supervisor" \
  "${package_root}/usr/bin" \
  "${package_root}/usr/lib/systemd/user" \
  "${package_root}/usr/share/applications" \
  "${package_root}/usr/share/dbus-1/services" \
  "${package_root}/usr/share/gnome-shell/extensions/cursor-usage-supervisor@owen.local" \
  "${package_root}/usr/share/icons/hicolor/scalable/apps" \
  "${package_root}/usr/share/doc/cursor-usage-supervisor/docs"

install -m 0644 "${project_dir}"/src/cursor_usage_supervisor/*.py \
  "${package_root}/usr/lib/python3/dist-packages/cursor_usage_supervisor/"
install -m 0644 "${project_dir}"/extension/* \
  "${package_root}/usr/share/gnome-shell/extensions/cursor-usage-supervisor@owen.local/"
install -m 0644 "${project_dir}/packaging/cursor-usage-supervisor.desktop" \
  "${package_root}/usr/share/applications/"
install -m 0644 "${project_dir}/packaging/cursor-usage-supervisor.svg" \
  "${package_root}/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 "${project_dir}/packaging/io.github.owen.CursorUsageSupervisor.service" \
  "${package_root}/usr/share/dbus-1/services/"
install -m 0644 "${project_dir}/packaging/cursor-usage-supervisor.service" \
  "${package_root}/usr/lib/systemd/user/"
install -m 0644 "${project_dir}/README.md" "${project_dir}/SECURITY.md" \
  "${project_dir}/CHANGELOG.md" \
  "${package_root}/usr/share/doc/cursor-usage-supervisor/"
install -m 0644 "${project_dir}"/docs/*.md \
  "${package_root}/usr/share/doc/cursor-usage-supervisor/docs/"

cat > "${package_root}/usr/bin/cursor-usage-supervisor" <<'EOF'
#!/usr/bin/env bash
exec python3 -m cursor_usage_supervisor.preferences "$@"
EOF
cat > "${package_root}/usr/bin/cursor-usage-supervisor-service" <<'EOF'
#!/usr/bin/env bash
exec python3 -m cursor_usage_supervisor.service "$@"
EOF
cat > "${package_root}/usr/bin/cursor-usage-supervisor-preferences" <<'EOF'
#!/usr/bin/env bash
exec python3 -m cursor_usage_supervisor.preferences "$@"
EOF
chmod 0755 "${package_root}"/usr/bin/*

cat > "${package_root}/DEBIAN/control" <<EOF
Package: cursor-usage-supervisor
Version: ${version}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gnome-shell (>= 42)
Maintainer: Owen
Description: GNOME top-panel monitor for Cursor account usage
 Displays Cursor billing-cycle allowance, usage pools, bonus usage, and
 on-demand spend using the signed-in Cursor Desktop session.
EOF

mkdir -p "${project_dir}/dist"
dpkg-deb --root-owner-group --build "${package_root}" \
  "${project_dir}/dist/cursor-usage-supervisor_${version}_all.deb"
