/* exported init */

'use strict';

const { Clutter, Gio, GObject, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;

const BUS_NAME = 'io.github.owen.CursorUsageSupervisor';
const OBJECT_PATH = '/io/github/owen/CursorUsageSupervisor';
const DBUS_XML = `
<node>
  <interface name="${BUS_NAME}">
    <method name="GetSummary"><arg name="summary" type="s" direction="out"/></method>
    <method name="Refresh"><arg name="summary" type="s" direction="out"/></method>
    <signal name="UsageChanged"><arg name="summary" type="s"/></signal>
  </interface>
</node>`;
const UsageProxy = Gio.DBusProxy.makeProxyWrapper(DBUS_XML);

function hasNumber(value) {
    return typeof value === 'number' && Number.isFinite(value);
}

function formatMoney(cents) {
    return hasNumber(cents) ? `$${(cents / 100).toFixed(2)}` : '—';
}

function formatPercent(value) {
    return hasNumber(value) ? `${Math.round(value)}%` : '—';
}

function resetText(value) {
    if (!value)
        return 'Reset date unavailable';
    const target = new Date(value);
    if (Number.isNaN(target.getTime()))
        return 'Reset date unavailable';
    const minutes = Math.max(0, Math.ceil((target.getTime() - Date.now()) / 60000));
    if (minutes < 60)
        return `Resets in ${minutes} min`;
    if (minutes < 1440)
        return `Resets in ${Math.floor(minutes / 60)}h ${minutes % 60}m`;
    return `Resets in ${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h`;
}

class ProgressLine {
    constructor(accentClass) {
        this.actor = new St.Widget({ style_class: 'cursor-progress-track' });
        this._fill = new St.Widget({ style_class: `cursor-progress-fill ${accentClass}` });
        this.actor.add_child(this._fill);
        this.setPercent(null);
    }

    setPercent(value) {
        const fraction = hasNumber(value) ? Math.min(1, Math.max(0, value / 100)) : 0;
        this._fill.set_width(Math.round(320 * fraction));
    }
}

const CursorIndicator = GObject.registerClass(
class CursorIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Cursor Usage Supervisor', false);
        const panelBox = new St.BoxLayout({ style_class: 'cursor-panel-box' });
        this._panelIcon = new St.Icon({
            icon_name: 'applications-development-symbolic',
            style_class: 'system-status-icon cursor-panel-icon',
        });
        this._panelLabel = new St.Label({ text: 'Cursor —', y_align: Clutter.ActorAlign.CENTER });
        panelBox.add_child(this._panelIcon);
        panelBox.add_child(this._panelLabel);
        this.add_child(panelBox);
        this._buildPopover();
        this._connectService();
    }

    _buildPopover() {
        const item = new PopupMenu.PopupBaseMenuItem({ reactive: false, can_focus: false });
        const body = new St.BoxLayout({ vertical: true, style_class: 'cursor-popover' });
        item.add_child(body);

        const header = new St.BoxLayout({ style_class: 'cursor-header' });
        header.add_child(new St.Label({ text: 'CURSOR', style_class: 'cursor-wordmark', x_expand: true }));
        this._liveLabel = new St.Label({ text: '● CONNECTING', style_class: 'cursor-live' });
        header.add_child(this._liveLabel);
        body.add_child(header);

        this._primaryValue = new St.Label({ text: '—', style_class: 'cursor-hero-value' });
        body.add_child(this._primaryValue);
        this._primaryCaption = new St.Label({ text: 'Waiting for Cursor usage data', style_class: 'cursor-caption' });
        body.add_child(this._primaryCaption);
        this._primaryBar = new ProgressLine('cursor-progress-primary');
        body.add_child(this._primaryBar.actor);
        this._resetLabel = new St.Label({ text: '', style_class: 'cursor-reset' });
        body.add_child(this._resetLabel);

        body.add_child(new St.Widget({ style_class: 'cursor-divider' }));
        body.add_child(new St.Label({ text: 'PLAN STATUS', style_class: 'cursor-section-label' }));
        this._allowance = this._addPool(body, 'Team included allowance', 'cursor-progress-allowance');
        this._contractLabel = new St.Label({
            text: 'Single shared allowance', style_class: 'cursor-contract',
        });
        body.add_child(this._contractLabel);

        body.add_child(new St.Widget({ style_class: 'cursor-divider' }));
        body.add_child(new St.Label({ text: 'THIS BILLING CYCLE', style_class: 'cursor-section-label' }));
        const stats = new St.BoxLayout({ style_class: 'cursor-stats' });
        this._includedValue = this._addStat(stats, 'INCLUDED');
        this._bonusValue = this._addStat(stats, 'BONUS');
        this._onDemandValue = this._addStat(stats, 'ON-DEMAND');
        body.add_child(stats);

        this._accountLabel = new St.Label({ text: '', style_class: 'cursor-account' });
        body.add_child(this._accountLabel);
        this._errorLabel = new St.Label({ text: '', style_class: 'cursor-error-detail' });
        body.add_child(this._errorLabel);

        this.menu.addMenuItem(item);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const refresh = new PopupMenu.PopupMenuItem('Refresh now');
        refresh.connect('activate', () => this._requestRefresh());
        this.menu.addMenuItem(refresh);
        const dashboard = new PopupMenu.PopupMenuItem('Open Cursor dashboard');
        dashboard.connect('activate', () => Gio.AppInfo.launch_default_for_uri('https://cursor.com/dashboard', null));
        this.menu.addMenuItem(dashboard);
        const preferences = new PopupMenu.PopupMenuItem('Preferences');
        preferences.connect('activate', () => this._openPreferences());
        this.menu.addMenuItem(preferences);
    }

    _addPool(body, label, accentClass) {
        const row = new St.BoxLayout({ style_class: 'cursor-pool-row' });
        row.add_child(new St.Label({ text: label, x_expand: true }));
        const value = new St.Label({ text: '—', style_class: 'cursor-pool-value' });
        row.add_child(value);
        body.add_child(row);
        const bar = new ProgressLine(accentClass);
        body.add_child(bar.actor);
        return { value, bar };
    }

    _addStat(parent, label) {
        const column = new St.BoxLayout({ vertical: true, style_class: 'cursor-stat', x_expand: true });
        const value = new St.Label({ text: '—', style_class: 'cursor-stat-value' });
        column.add_child(value);
        column.add_child(new St.Label({ text: label, style_class: 'cursor-stat-label' }));
        parent.add_child(column);
        return value;
    }

    _connectService() {
        this._proxy = new UsageProxy(Gio.DBus.session, BUS_NAME, OBJECT_PATH, (proxy, error) => {
            if (error) {
                this._showError('Backend service unavailable');
                return;
            }
            this._signalId = proxy.connectSignal('UsageChanged', (_proxy, _sender, [summary]) => this._applySummary(summary));
            proxy.GetSummaryRemote((result, callError) => {
                if (callError)
                    this._showError('Could not read Cursor usage');
                else
                    this._applySummary(result[0]);
            });
        });
    }

    _applySummary(serialized) {
        let summary;
        try {
            summary = JSON.parse(serialized);
        } catch (_error) {
            this._showError('Invalid backend response');
            return;
        }
        if (summary.error) {
            this._showError(summary.error);
            return;
        }
        this._errorLabel.text = summary.refresh_error || '';
        this._liveLabel.text = summary.stale ? '● STALE' : '● LIVE';
        this._liveLabel.remove_style_class_name('cursor-offline');
        if (summary.stale)
            this._liveLabel.add_style_class_name('cursor-stale');
        else
            this._liveLabel.remove_style_class_name('cursor-stale');

        const cycle = summary.billing_cycle || {};
        this._resetLabel.text = resetText(cycle.end);
        const membership = (summary.membership_type || 'Cursor').toUpperCase();
        this._accountLabel.text = `${summary.team_name || 'Personal account'}  ·  ${membership}`;

        if (summary.billing_model === 'legacy_request_count') {
            this._renderLegacy(summary.requests || {});
            return;
        }
        const plan = summary.plan || {};
        const percent = plan.total_percent;
        const onDemand = summary.on_demand || {};
        const billableUsage = summary.billable_usage_cents;
        this._panelLabel.text = hasNumber(billableUsage) ? `Cursor ${formatMoney(billableUsage)}` : 'Cursor —';
        this._primaryValue.text = hasNumber(billableUsage) ? formatMoney(billableUsage) : 'Usage available';
        this._primaryCaption.text = `${formatMoney(plan.used_cents)} included + ${formatMoney(onDemand.used_cents)} on-demand`;
        this._primaryBar.setPercent(percent);
        this._setUrgency(percent);
        this._renderPool(this._allowance, percent, true);
        this._contractLabel.text = summary.limit_type === 'team'
            ? 'Team contract · one included balance'
            : 'Personal plan · included balance';
        const breakdown = plan.breakdown || {};
        this._includedValue.text = formatMoney(breakdown.included_cents);
        this._bonusValue.text = formatMoney(breakdown.bonus_cents);
        this._onDemandValue.text = formatMoney(onDemand.used_cents);
    }

    _renderLegacy(requests) {
        const used = requests.used;
        const limit = requests.limit;
        const percent = hasNumber(used) && hasNumber(limit) && limit > 0 ? 100 * used / limit : null;
        this._panelLabel.text = hasNumber(percent) ? `Cursor ${Math.round(percent)}%` : 'Cursor —';
        this._primaryValue.text = hasNumber(percent) ? `${Math.round(percent)}% used` : 'Legacy plan';
        this._primaryCaption.text = hasNumber(used) && hasNumber(limit) ? `${used} of ${limit} premium requests` : 'Request allowance unavailable';
        this._primaryBar.setPercent(percent);
        this._renderPool(this._allowance, percent, true);
        this._contractLabel.text = 'Legacy request-count allowance';
        this._includedValue.text = hasNumber(used) ? `${used} req` : '—';
        this._bonusValue.text = '—';
        this._onDemandValue.text = '—';
        this._setUrgency(percent);
    }

    _renderPool(pool, percent, showUsed = false) {
        pool.value.text = hasNumber(percent) && showUsed ? `${formatPercent(percent)} used` : formatPercent(percent);
        pool.bar.setPercent(percent);
    }

    _setUrgency(percent) {
        this._panelLabel.remove_style_class_name('cursor-warning');
        this._panelLabel.remove_style_class_name('cursor-critical');
        if (hasNumber(percent) && percent >= 95)
            this._panelLabel.add_style_class_name('cursor-critical');
        else if (hasNumber(percent) && percent >= 80)
            this._panelLabel.add_style_class_name('cursor-warning');
    }

    _requestRefresh() {
        if (!this._proxy)
            return;
        this._liveLabel.text = '● REFRESHING';
        this._proxy.RefreshRemote((result, error) => {
            if (error)
                this._showError('Refresh failed');
            else
                this._applySummary(result[0]);
        });
    }

    _openPreferences() {
        try {
            Gio.Subprocess.new(['cursor-usage-supervisor-preferences'], Gio.SubprocessFlags.NONE);
        } catch (error) {
            Main.notifyError('Cursor Usage Supervisor', `Could not open preferences: ${error.message}`);
        }
    }

    _showError(message) {
        this._panelLabel.text = 'Cursor !';
        this._liveLabel.text = '● OFFLINE';
        this._liveLabel.add_style_class_name('cursor-offline');
        this._primaryValue.text = 'Unavailable';
        this._primaryCaption.text = message;
        this._primaryBar.setPercent(null);
    }

    destroy() {
        if (this._proxy && this._signalId)
            this._proxy.disconnectSignal(this._signalId);
        this._proxy = null;
        super.destroy();
    }
});

class Extension {
    enable() {
        this._indicator = new CursorIndicator();
        Main.panel.addToStatusArea('cursor-usage-supervisor', this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}

function init() {
    return new Extension();
}
