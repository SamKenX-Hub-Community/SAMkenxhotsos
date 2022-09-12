from hotsos.core.plugintools import summary_entry_offset as idx
from hotsos.core.host_helpers import NetworkPort
from hotsos.core.plugins.openvswitch import OpenvSwitchChecksBase


class OpenvSwitchSummary(OpenvSwitchChecksBase):

    @idx(0)
    def __summary_services(self):
        """Get string info for running daemons."""
        if self.systemd.services:
            return self.systemd.summary

    @idx(1)
    def __summary_dpkg(self):
        return self.apt.all_formatted

    @idx(2)
    def __summary_config(self):
        _config = {}
        if self.offload_enabled:
            _config['offload'] = 'enabled'

        if self.ovsdb.other_config:
            _config['other-config'] = self.ovsdb.other_config

        if self.ovsdb.external_ids:
            _config['external-ids'] = self.ovsdb.external_ids

        if _config:
            return _config

    @idx(3)
    def __summary_bridges(self):
        bridges = {}
        for bridge in self.bridges:
            # filter patch/phy ports since they are not generally interesting
            ports = []
            for port in bridge.ports:
                if type(port) != NetworkPort:
                    name = port
                else:
                    name = port.name

                if (name.startswith('patch-') or name.startswith('phy-') or
                        name.startswith('int-')):
                    continue

                if type(port) != NetworkPort:
                    # ovs port so will be just a name
                    ports.append(port)
                    continue

                ports.append(port.to_dict())

            # exlude br-int port since it will have too many
            if bridge.name == 'br-int' and ports:
                ports = ["({} ports)".format(len(ports))]

            bridges[bridge.name] = ports

        if bridges:
            return bridges
